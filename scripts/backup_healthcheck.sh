#!/usr/bin/env bash
# Daily watchdog for the ESBvaktin database backup.
#
# Why this exists: the launchd job `is.esbvaktin.backup-db` exited 1 for ~23
# days (2026 outage) with no one notified — its only sink was a log file nobody
# read. backup_db.sh was hardened to emit durable failure signals; this script
# is the *active surfacing* layer that polls those signals daily and fires a
# macOS notification when a backup is failing or stale, so a silent failure
# can't recur.
#
# It is deliberately decoupled from the backup job (a separate LaunchAgent, not
# a hook inside it) so it still alerts when the backup job never ran at all —
# was unloaded, throttled off, or died before reaching any notification code.
# It needs no database: it only reads two on-disk signals backup_db.sh writes.
#
#   1. The status marker  ~/Documents/esbvaktin-backups/last_backup_status.txt
#      one line: "<timestamp>\tOK|FAILED\t<detail>".  Field 2 == FAILED -> alert.
#   2. `backup_db.sh --status`, which prints a loud staleness/no-valid-backup
#      WARNING (to stderr) when the newest *valid* dump is older than
#      ESBVAKTIN_STALE_DAYS (default 2) or every dump on disk is empty/corrupt.
#
# Any of those -> one consolidated notification (terminal-notifier if present,
# else osascript). Healthy -> stay quiet and log an OK line.
#
# Usage:
#   ./scripts/backup_healthcheck.sh            # check + notify on problems
#   ./scripts/backup_healthcheck.sh --dry-run  # report the decision, notify nothing
#
# Test seams (overridable env, default to production values; used by
# tests/test_backup_healthcheck.sh): ESBVAKTIN_BACKUP_DIR, ESBVAKTIN_STALE_DAYS,
# ESBVAKTIN_BACKUP_SCRIPT, ESBVAKTIN_NOTIFY_FILE (capture instead of firing),
# plus the PG_DUMP/PG_RESTORE/PG_ISREADY seams it forwards to backup_db.sh.
#
# bash 3.2 compatible (launchd uses /bin/bash). No arrays expanded under set -u.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BACKUP_DIR="${ESBVAKTIN_BACKUP_DIR:-$HOME/Documents/esbvaktin-backups}"
STATUS_FILE="$BACKUP_DIR/last_backup_status.txt"
BACKUP_SCRIPT="${ESBVAKTIN_BACKUP_SCRIPT:-$SCRIPT_DIR/backup_db.sh}"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
fi

# --- Notification (with dry-run + test seams) --------------------------------
# Priority: --dry-run prints the decision; ESBVAKTIN_NOTIFY_FILE captures it for
# tests; otherwise fire a real macOS notification. terminal-notifier is richer
# (subtitle, sound) but optional — osascript ships with macOS, so fall back to
# it and a fresh machine still alerts.
notify() {
    local title="$1" msg="$2"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '[dry-run] would notify: %s — %s\n' "$title" "$msg"
        return 0
    fi
    if [[ -n "${ESBVAKTIN_NOTIFY_FILE:-}" ]]; then
        printf '%s\t%s\n' "$title" "$msg" >> "$ESBVAKTIN_NOTIFY_FILE"
        return 0
    fi

    # Strip quotes/backslashes — we build msg ourselves, but never hand
    # unescaped text to the AppleScript string literal below.
    local safe_title safe_msg
    safe_title="$(printf '%s' "$title" | tr -d '"\\')"
    safe_msg="$(printf '%s' "$msg" | tr -d '"\\')"

    if command -v terminal-notifier >/dev/null 2>&1; then
        terminal-notifier -title "$safe_title" -subtitle "backup watchdog" \
            -message "$safe_msg" -sound default >/dev/null 2>&1 || true
    else
        osascript -e "display notification \"$safe_msg\" with title \"$safe_title\"" \
            >/dev/null 2>&1 || true
    fi
}

# Accumulate problems into one "; "-joined string (bash 3.2: avoid arrays so an
# empty expansion can't trip set -u).
problems=""
add_problem() {
    if [[ -z "$problems" ]]; then
        problems="$1"
    else
        problems="$problems; $1"
    fi
}

# --- Guard: we must be able to run the status check at all -------------------
# If the backup script itself is gone, that is its own silent-failure class —
# surface it loudly rather than skipping the check.
if [[ ! -x "$BACKUP_SCRIPT" ]]; then
    notify "ESBvaktin backup" "PROBLEM: backup watchdog cannot run — $BACKUP_SCRIPT is missing or not executable."
    echo "Backup healthcheck: ERROR — backup script not found at $BACKUP_SCRIPT" >&2
    exit 1
fi

# --- Signal 1: the durable OK/FAILED status marker ---------------------------
# Field 2 of "<ts>\tOK|FAILED\t<detail>". The hardened backup_db.sh writes
# FAILED on any non-zero exit, so this catches "ran today and failed" even when
# an older good dump keeps the staleness check quiet.
if [[ -f "$STATUS_FILE" ]]; then
    marker_status="$(awk -F'\t' 'NR==1 {print $2}' "$STATUS_FILE" 2>/dev/null)"
    marker_detail="$(awk -F'\t' 'NR==1 {print $3}' "$STATUS_FILE" 2>/dev/null)"
    if [[ "$marker_status" == "FAILED" ]]; then
        if [[ -n "$marker_detail" ]]; then
            add_problem "last backup run FAILED ($marker_detail)"
        else
            add_problem "last backup run FAILED"
        fi
    fi
fi

# --- Signal 2: backup_db.sh --status staleness / no-valid-backup -------------
# --status prints its WARNING to stderr, so capture both streams. Run it without
# aborting on a non-zero exit; an inability to even produce a status report is
# itself a problem worth surfacing.
status_out="$("$BACKUP_SCRIPT" --status 2>&1)"
status_rc=$?

if [[ "$status_rc" -ne 0 ]]; then
    add_problem "backup --status check failed (exit $status_rc)"
elif printf '%s' "$status_out" | grep -q 'NO valid'; then
    add_problem "no valid backup on disk — every dump is empty or corrupt"
elif printf '%s' "$status_out" | grep -q 'WARNING'; then
    add_problem "newest valid backup is stale (older than ${ESBVAKTIN_STALE_DAYS:-2} day(s))"
fi

# --- Decide -----------------------------------------------------------------
if [[ -n "$problems" ]]; then
    notify "ESBvaktin backup" "PROBLEM: $problems. Inspect $BACKUP_DIR/backup.log or run scripts/backup_db.sh --status."
    echo "Backup healthcheck: ALERT — $problems"
    # Exit 0: the watchdog did its job (it detected and surfaced the problem).
    # A non-zero exit would only be noise in the watchdog's own log and could
    # invite launchd throttling.
    exit 0
fi

echo "Backup healthcheck: OK — newest backup is valid and within the staleness threshold."
exit 0
