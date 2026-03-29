#!/usr/bin/env bash
# Daily PostgreSQL backup for ESBvaktin.
#
# Writes compressed pg_dump to ~/Documents/esbvaktin-backups/
# (synced to iCloud via Desktop & Documents sync).
# Also backs up the article inbox (gitignored but stateful).
# Retains the last 30 daily backups. Verifies dump restorability.
#
# Usage:
#   ./scripts/backup_db.sh          # Run backup
#   ./scripts/backup_db.sh --status # Show existing backups

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# pg_dump/pg_restore from Homebrew libpq (not on default PATH)
LIBPQ_PREFIX="$(brew --prefix libpq 2>/dev/null || echo "/opt/homebrew/Cellar/libpq/18.2")"
PG_DUMP="${PG_DUMP:-$LIBPQ_PREFIX/bin/pg_dump}"
PG_RESTORE="${PG_RESTORE:-$LIBPQ_PREFIX/bin/pg_restore}"

if [[ ! -x "$PG_DUMP" ]]; then
    PG_DUMP="pg_dump"
fi
if [[ ! -x "$PG_RESTORE" ]]; then
    PG_RESTORE="pg_restore"
fi

BACKUP_DIR="$HOME/Documents/esbvaktin-backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DUMP_FILE="$BACKUP_DIR/esbvaktin_${TIMESTAMP}.dump"
INBOX_FILE="$BACKUP_DIR/inbox_${TIMESTAMP}.tar.gz"
RETENTION_DAYS=30

mkdir -p "$BACKUP_DIR"

if [[ "${1:-}" == "--status" ]]; then
    echo "Backup directory: $BACKUP_DIR"
    echo "Retention: $RETENTION_DAYS days"
    echo ""
    if ls "$BACKUP_DIR"/esbvaktin_*.dump 1>/dev/null 2>&1; then
        echo "Database backups:"
        ls -lh "$BACKUP_DIR"/esbvaktin_*.dump | awk '{print "  " $NF " (" $5 ")"}'
        echo ""
        OLDEST=$(ls -t "$BACKUP_DIR"/esbvaktin_*.dump | tail -1)
        NEWEST=$(ls -t "$BACKUP_DIR"/esbvaktin_*.dump | head -1)
        echo "Newest: $(basename "$NEWEST")"
        echo "Oldest: $(basename "$OLDEST")"
        echo "Count:  $(ls "$BACKUP_DIR"/esbvaktin_*.dump | wc -l | tr -d ' ')"
    else
        echo "No database backups found."
    fi
    echo ""
    if ls "$BACKUP_DIR"/inbox_*.tar.gz 1>/dev/null 2>&1; then
        echo "Inbox backups:"
        NEWEST_INBOX=$(ls -t "$BACKUP_DIR"/inbox_*.tar.gz | head -1)
        echo "  Latest: $(basename "$NEWEST_INBOX") ($(ls -lh "$NEWEST_INBOX" | awk '{print $5}'))"
        echo "  Count:  $(ls "$BACKUP_DIR"/inbox_*.tar.gz | wc -l | tr -d ' ')"
    else
        echo "No inbox backups found."
    fi
    exit 0
fi

echo "Backing up esbvaktin database..."

# pg_dump with custom format (compressed, supports selective restore)
"$PG_DUMP" -Fc -h localhost -U esb -d esbvaktin -f "$DUMP_FILE"

SIZE=$(ls -lh "$DUMP_FILE" | awk '{print $5}')
echo "Database backup: $DUMP_FILE ($SIZE)"

# Verify the dump is restorable
if "$PG_RESTORE" --list "$DUMP_FILE" > /dev/null 2>&1; then
    echo "Verification: OK (dump is restorable)"
else
    echo "ERROR: Backup verification failed — dump may be corrupt" >&2
    rm -f "$DUMP_FILE"
    exit 1
fi

# Back up the article inbox (gitignored but stateful)
INBOX_DIR="$PROJECT_DIR/data/inbox"
if [[ -d "$INBOX_DIR" ]]; then
    tar -czf "$INBOX_FILE" -C "$PROJECT_DIR" data/inbox/
    INBOX_SIZE=$(ls -lh "$INBOX_FILE" | awk '{print $5}')
    echo "Inbox backup: $INBOX_FILE ($INBOX_SIZE)"
fi

# Prune old backups (keep last RETENTION_DAYS days)
PRUNED=0
for pattern in "esbvaktin_*.dump" "inbox_*.tar.gz"; do
    COUNT=$(find "$BACKUP_DIR" -name "$pattern" -mtime +${RETENTION_DAYS} -print -delete 2>/dev/null | wc -l | tr -d ' ')
    PRUNED=$((PRUNED + COUNT))
done
if [[ "$PRUNED" -gt 0 ]]; then
    echo "Pruned $PRUNED file(s) older than $RETENTION_DAYS days"
fi

echo "Done. Backups will sync to iCloud via ~/Documents."
