#!/usr/bin/env bash
# Daily PostgreSQL backup for ESBvaktin.
#
# Writes compressed pg_dump to ~/Documents/esbvaktin-backups/
# (synced to iCloud via Desktop & Documents sync).
# Retains the last 7 daily backups.
#
# Usage:
#   ./scripts/backup_db.sh          # Run backup
#   ./scripts/backup_db.sh --status # Show existing backups

set -euo pipefail

# pg_dump from Homebrew libpq (not on default PATH)
PG_DUMP="${PG_DUMP:-/opt/homebrew/Cellar/libpq/18.2/bin/pg_dump}"
if [[ ! -x "$PG_DUMP" ]]; then
    # Fallback: try PATH
    PG_DUMP="pg_dump"
fi

BACKUP_DIR="$HOME/Documents/esbvaktin-backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DUMP_FILE="$BACKUP_DIR/esbvaktin_${TIMESTAMP}.dump"
RETENTION_DAYS=7

mkdir -p "$BACKUP_DIR"

if [[ "${1:-}" == "--status" ]]; then
    echo "Backup directory: $BACKUP_DIR"
    echo ""
    if ls "$BACKUP_DIR"/esbvaktin_*.dump 1>/dev/null 2>&1; then
        echo "Existing backups:"
        ls -lh "$BACKUP_DIR"/esbvaktin_*.dump | awk '{print "  " $NF " (" $5 ")"}'
        echo ""
        OLDEST=$(ls -t "$BACKUP_DIR"/esbvaktin_*.dump | tail -1)
        NEWEST=$(ls -t "$BACKUP_DIR"/esbvaktin_*.dump | head -1)
        echo "Newest: $(basename "$NEWEST")"
        echo "Oldest: $(basename "$OLDEST")"
        echo "Count:  $(ls "$BACKUP_DIR"/esbvaktin_*.dump | wc -l | tr -d ' ')"
    else
        echo "No backups found."
    fi
    exit 0
fi

echo "Backing up esbvaktin database..."

# pg_dump with custom format (compressed, supports selective restore)
"$PG_DUMP" -Fc -h localhost -U esb -d esbvaktin -f "$DUMP_FILE"

SIZE=$(ls -lh "$DUMP_FILE" | awk '{print $5}')
echo "Backup written: $DUMP_FILE ($SIZE)"

# Prune old backups (keep last RETENTION_DAYS days)
PRUNED=$(find "$BACKUP_DIR" -name "esbvaktin_*.dump" -mtime +${RETENTION_DAYS} -print -delete | wc -l | tr -d ' ')
if [[ "$PRUNED" -gt 0 ]]; then
    echo "Pruned $PRUNED backup(s) older than $RETENTION_DAYS days"
fi

echo "Done. Backup will sync to iCloud via ~/Documents."
