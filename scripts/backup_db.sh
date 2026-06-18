#!/usr/bin/env bash
# Daily PostgreSQL backup for ESBvaktin.
#
# Writes compressed pg_dump to ~/Documents/esbvaktin-backups/
# (synced to iCloud via Desktop & Documents sync).
# Also backs up the article inbox (gitignored but stateful).
# Retains the last 30 daily backups. Verifies dump restorability.
#
# Data-safety contract (hardened 2026-06-18 after a 23-day silent outage):
#   * The dump is written to a temp file and only renamed into its canonical
#     esbvaktin_*.dump name AFTER it is proven good — pg_dump exited 0, the file
#     is non-zero, and `pg_restore --list` reports a non-empty TOC. A failed,
#     empty, or corrupt dump NEVER reaches a canonical name, so --status can't
#     be fooled into reporting a 0-byte file as "the newest backup".
#   * Any failure deletes the temp file and exits non-zero, so launchd records
#     the failure and a durable status marker is written.
#   * --status reports the newest *good* (non-empty, restorable) dump and warns
#     loudly when it is older than the staleness threshold.
#
# Usage:
#   ./scripts/backup_db.sh          # Run backup
#   ./scripts/backup_db.sh --status # Show existing backups + health
#
# Test seams (overridable env, default to production values; used by
# tests/test_backup_db.sh): ESBVAKTIN_BACKUP_DIR, ESBVAKTIN_INBOX_DIR,
# ESBVAKTIN_STALE_DAYS, PG_DUMP, PG_RESTORE, PG_ISREADY.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# pg_dump/pg_restore/pg_isready from Homebrew libpq (not on default PATH).
# Use the version-agnostic symlink so brew upgrades don't break us.
LIBPQ_PREFIX="$(brew --prefix libpq 2>/dev/null || echo "/opt/homebrew/opt/libpq")"
PG_DUMP="${PG_DUMP:-$LIBPQ_PREFIX/bin/pg_dump}"
PG_RESTORE="${PG_RESTORE:-$LIBPQ_PREFIX/bin/pg_restore}"
PG_ISREADY="${PG_ISREADY:-$LIBPQ_PREFIX/bin/pg_isready}"

if [[ ! -x "$PG_DUMP" ]]; then
    if command -v pg_dump >/dev/null 2>&1; then
        PG_DUMP="pg_dump"
    else
        echo "ERROR: pg_dump not found. Install with: brew install libpq" >&2
        echo "Tried: $LIBPQ_PREFIX/bin/pg_dump and PATH=$PATH" >&2
        exit 1
    fi
fi
if [[ ! -x "$PG_RESTORE" ]]; then
    if command -v pg_restore >/dev/null 2>&1; then
        PG_RESTORE="pg_restore"
    else
        echo "ERROR: pg_restore not found. Install with: brew install libpq" >&2
        exit 1
    fi
fi
# pg_isready is optional — it only powers the "is the DB up?" pre-check.
# If it's missing the pre-check is skipped and pg_dump failure is still caught.
if [[ ! -x "$PG_ISREADY" ]]; then
    if command -v pg_isready >/dev/null 2>&1; then
        PG_ISREADY="pg_isready"
    else
        PG_ISREADY=""
    fi
fi

BACKUP_DIR="${ESBVAKTIN_BACKUP_DIR:-$HOME/Documents/esbvaktin-backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DUMP_FILE="$BACKUP_DIR/esbvaktin_${TIMESTAMP}.dump"
INBOX_FILE="$BACKUP_DIR/inbox_${TIMESTAMP}.tar.gz"
INBOX_DIR="${ESBVAKTIN_INBOX_DIR:-$PROJECT_DIR/data/inbox}"
RETENTION_DAYS=30
# Warn in --status when the newest valid dump is older than this many days.
# Daily cadence -> 2 days tolerates a single missed cycle plus a margin.
STALE_AFTER_DAYS="${ESBVAKTIN_STALE_DAYS:-2}"
STATUS_FILE="$BACKUP_DIR/last_backup_status.txt"

mkdir -p "$BACKUP_DIR"

MODE=""
TMP_DUMP=""

# Returns 0 iff $1 is a non-empty, restorable custom-format dump whose archive
# table-of-contents has at least one real entry. A 0-byte or header-only
# (data-less) dump returns non-zero — closing the hole where `pg_restore --list`
# treats an empty custom-format dump as "valid".
dump_is_valid() {
    local f="$1" toc
    [[ -s "$f" ]] || return 1
    toc="$("$PG_RESTORE" --list "$f" 2>/dev/null)" || return 1
    printf '%s\n' "$toc" | grep -qE '^[[:space:]]*[0-9]' || return 1
    return 0
}

# Single exit handler: always remove a lingering temp dump (never leave a
# partial artifact), and for backup runs record a durable OK/FAILED health
# signal so a failure can't stay silent the way the 23-day outage did.
on_exit() {
    local rc=$?
    if [[ -n "${TMP_DUMP:-}" && -e "${TMP_DUMP:-}" ]]; then
        rm -f "$TMP_DUMP"
    fi
    if [[ "${MODE:-}" == "backup" ]]; then
        if [[ $rc -eq 0 ]]; then
            printf '%s\tOK\tverified backup published\n' \
                "$(date '+%Y-%m-%d %H:%M:%S')" > "$STATUS_FILE" 2>/dev/null || true
        else
            printf '%s\tFAILED\texit %s\n' \
                "$(date '+%Y-%m-%d %H:%M:%S')" "$rc" > "$STATUS_FILE" 2>/dev/null || true
        fi
    fi
    return $rc
}
trap on_exit EXIT

if [[ "${1:-}" == "--status" ]]; then
    MODE="status"
    echo "Backup directory: $BACKUP_DIR"
    echo "Retention: $RETENTION_DAYS days"
    echo "Staleness threshold: $STALE_AFTER_DAYS day(s)"
    if [[ -f "$STATUS_FILE" ]]; then
        echo "Last recorded run: $(cat "$STATUS_FILE")"
    fi
    echo ""
    if ls "$BACKUP_DIR"/esbvaktin_*.dump 1>/dev/null 2>&1; then
        # Names embed YYYYMMDD_HHMMSS, so a plain glob sorts oldest -> newest.
        dumps=( "$BACKUP_DIR"/esbvaktin_*.dump )
        total=${#dumps[@]}
        empty=0

        echo "Database backups (newest first):"
        i=$total
        while (( i > 0 )); do
            i=$((i - 1))
            f="${dumps[$i]}"
            sz=$(ls -lh "$f" | awk '{print $5}')
            if [[ -s "$f" ]]; then
                echo "  $(basename "$f") ($sz)"
            else
                echo "  $(basename "$f") ($sz)  [EMPTY — ignored]"
                empty=$((empty + 1))
            fi
        done
        echo ""
        echo "Count: $total total, $empty empty"

        # The "last good" backup is the newest non-empty, restorable dump.
        last_good=""
        i=$total
        while (( i > 0 )); do
            i=$((i - 1))
            if dump_is_valid "${dumps[$i]}"; then
                last_good="${dumps[$i]}"
                break
            fi
        done

        if [[ -n "$last_good" ]]; then
            ts="$(basename "$last_good" .dump)"; ts="${ts#esbvaktin_}"
            if backup_epoch=$(date -j -f "%Y%m%d_%H%M%S" "$ts" +%s 2>/dev/null); then
                age_days=$(( ( $(date +%s) - backup_epoch ) / 86400 ))
                echo "Last good backup: $(basename "$last_good") (${age_days} day(s) old)"
                if (( age_days > STALE_AFTER_DAYS )); then
                    {
                        echo ""
                        echo "  ⚠️  WARNING: newest VALID backup is ${age_days} day(s) old (threshold ${STALE_AFTER_DAYS} day(s))."
                        echo "      Daily backups may be failing silently — inspect $STATUS_FILE and the"
                        echo "      launchd job 'is.esbvaktin.backup-db' (it logs to $BACKUP_DIR/backup.log)."
                    } >&2
                fi
            else
                echo "Last good backup: $(basename "$last_good") (age unknown — unparseable timestamp)"
            fi
        else
            {
                echo "  ⚠️  WARNING: NO valid (non-empty, restorable) database backup found!"
                echo "      Every dump on disk is empty or corrupt. Restore capability is at risk."
            } >&2
        fi
    else
        echo "No database backups found."
    fi
    echo ""
    if ls "$BACKUP_DIR"/inbox_*.tar.gz 1>/dev/null 2>&1; then
        inboxes=( "$BACKUP_DIR"/inbox_*.tar.gz )
        newest_inbox="${inboxes[$(( ${#inboxes[@]} - 1 ))]}"
        echo "Inbox backups:"
        echo "  Latest: $(basename "$newest_inbox") ($(ls -lh "$newest_inbox" | awk '{print $5}'))"
        echo "  Count:  ${#inboxes[@]}"
    else
        echo "No inbox backups found."
    fi
    exit 0
fi

MODE="backup"
echo "Backing up esbvaktin database..."

# Pre-check: if Postgres is plainly down, fail loudly BEFORE writing anything,
# rather than emitting a silent empty backup.
if [[ -n "$PG_ISREADY" ]]; then
    if ! "$PG_ISREADY" -h localhost -U esb -d esbvaktin -q; then
        echo "ERROR: PostgreSQL is not accepting connections on localhost:5432." >&2
        echo "       The database container appears to be down. Start it with:" >&2
        echo "         cd ~/esbvaktin && docker compose up -d" >&2
        echo "       Aborting before writing any backup artifact." >&2
        exit 1
    fi
fi

# Dump to a temp file in the same directory (so the later mv is an atomic
# same-filesystem rename), then publish only after the dump is proven good.
TMP_DUMP="$(mktemp "${BACKUP_DIR}/.esbvaktin_${TIMESTAMP}.XXXXXX")"

# pg_dump with custom format (compressed, supports selective restore)
if ! "$PG_DUMP" -Fc -h localhost -U esb -d esbvaktin -f "$TMP_DUMP"; then
    echo "ERROR: pg_dump failed — database unreachable or dump error." >&2
    echo "       (Start the DB with: cd ~/esbvaktin && docker compose up -d)" >&2
    exit 1   # on_exit trap removes the temp file
fi

if [[ ! -s "$TMP_DUMP" ]]; then
    echo "ERROR: pg_dump exited 0 but produced an empty (0-byte) dump — refusing to publish." >&2
    exit 1
fi

if ! dump_is_valid "$TMP_DUMP"; then
    echo "ERROR: Backup verification failed — dump is unrestorable or contains no data." >&2
    exit 1
fi

# Verified good — publish atomically. After this point the temp no longer
# exists, so the trap has nothing to clean.
mv "$TMP_DUMP" "$DUMP_FILE"
TMP_DUMP=""

SIZE=$(ls -lh "$DUMP_FILE" | awk '{print $5}')
echo "Database backup: $DUMP_FILE ($SIZE)"
echo "Verification: OK (dump is restorable)"

# Back up the article inbox (gitignored but stateful)
if [[ -d "$INBOX_DIR" ]]; then
    tar -czf "$INBOX_FILE" -C "$PROJECT_DIR" data/inbox/
    INBOX_SIZE=$(ls -lh "$INBOX_FILE" | awk '{print $5}')
    echo "Inbox backup: $INBOX_FILE ($INBOX_SIZE)"
fi

# Prune old backups (keep last RETENTION_DAYS days).
# Note: under launchd, macOS TCC may block directory listing on Documents
# even though writes are permitted. Disable pipefail locally so a
# blocked find doesn't fail the whole run.
set +o pipefail
PRUNED=0
for pattern in "esbvaktin_*.dump" "inbox_*.tar.gz"; do
    COUNT=$(find "$BACKUP_DIR" -name "$pattern" -mtime +${RETENTION_DAYS} -print -delete 2>/dev/null | wc -l | tr -d ' \n')
    if [[ "$COUNT" =~ ^[0-9]+$ ]]; then
        PRUNED=$((PRUNED + COUNT))
    fi
done
set -o pipefail
if [[ "$PRUNED" -gt 0 ]]; then
    echo "Pruned $PRUNED file(s) older than $RETENTION_DAYS days"
fi

# Clean up any historical zero-byte dumps (artifacts of the pre-hardening bug).
# Safe here: we only reach this line after a fresh, verified backup was just
# published above, so deleting empty dumps can never remove our last good copy.
set +o pipefail
ZB=0
while IFS= read -r z; do
    [[ -n "$z" ]] || continue
    rm -f "$z" && ZB=$((ZB + 1))
done < <(find "$BACKUP_DIR" -name 'esbvaktin_*.dump' -size 0 2>/dev/null)
set -o pipefail
if [[ "$ZB" -gt 0 ]]; then
    echo "Cleaned up $ZB stale zero-byte dump(s)."
fi

echo "Done. Backups will sync to iCloud via ~/Documents."
