#!/bin/bash
# =============================================================================
# Odoo Manual PostgreSQL Backup
# Usage:
#   ./scripts/backup-now.sh                        # plain timestamp
#   ./scripts/backup-now.sh "before-invoice-fix"   # with a label
# =============================================================================
#
# RESTORE:
#   pg_restore -U amir -d odoo18_sgo_football_dev --clean \
#     /home/amir/erpProject/backups/manual_LABEL_YYYYMMDD_HHMMSS.dump
#
# LIST backups:
#   ls -lh /home/amir/erpProject/backups/
# =============================================================================

set -euo pipefail

DB_NAME="odoo18_sgo_football_dev"
DB_USER="amir"
DB_PASSWORD="admin"
BACKUP_DIR="/home/amir/erpProject/backups"
LOG_FILE="$BACKUP_DIR/backup.log"

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Optional label — strips spaces/special chars for safe filenames
if [ -n "${1-}" ]; then
    LABEL=$(echo "$1" | tr ' ' '-' | tr -cd '[:alnum:]-_')
    FILENAME="manual_${LABEL}_${TIMESTAMP}.dump"
else
    FILENAME="manual_${TIMESTAMP}.dump"
fi

BACKUP_FILE="$BACKUP_DIR/$FILENAME"

echo ""
echo "📦  Backing up '$DB_NAME'..."
echo "    → $BACKUP_FILE"
echo ""

export PGPASSWORD="$DB_PASSWORD"
pg_dump \
  -U "$DB_USER" \
  -F c \
  -f "$BACKUP_FILE" \
  "$DB_NAME"

SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)

echo "✓  Done! ($SIZE)"
echo ""
echo "Restore later with:"
echo "  pg_restore -U amir -d $DB_NAME --clean $BACKUP_FILE"
echo ""

# Log it alongside auto-backups
echo "[$(date '+%Y-%m-%d %H:%M:%S')] [MANUAL] $FILENAME ($SIZE)" >> "$LOG_FILE"
