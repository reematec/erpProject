#!/bin/bash
# =============================================================================
# Odoo Dev Session — PostgreSQL Backup Script
# Runs automatically at Ubuntu boot via systemd (odoo-db-backup.service)
# Stores rotating backups in /home/amir/erpProject/backups/
# =============================================================================
#
# RESTORE a backup:
#   pg_restore -U amir -d odoo18_sgo_football_dev --clean \
#     /home/amir/erpProject/backups/session_YYYYMMDD_HHMMSS.dump
#
# VIEW backup log:
#   cat /home/amir/erpProject/backups/backup.log
#
# VIEW service log:
#   journalctl -u odoo-db-backup
# =============================================================================

set -euo pipefail

DB_NAME="odoo18_sgo_football_dev"
DB_USER="amir"
DB_PASSWORD="admin"
BACKUP_DIR="/home/amir/erpProject/backups"
LOG_FILE="$BACKUP_DIR/backup.log"
MAX_BACKUPS=10

# Ensure backup directory exists
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/session_${TIMESTAMP}.dump"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting backup of '$DB_NAME'..." | tee -a "$LOG_FILE"

# Run pg_dump — custom compressed format (-F c)
# Supports pg_restore with --table/--schema flags for selective restore
export PGPASSWORD="$DB_PASSWORD"
pg_dump \
  -U "$DB_USER" \
  -F c \
  -f "$BACKUP_FILE" \
  "$DB_NAME"

SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓  Backup saved: session_${TIMESTAMP}.dump  ($SIZE)" | tee -a "$LOG_FILE"

# --- Rotation: keep only the last MAX_BACKUPS, remove older ones ---
OVERFLOW=$(ls -t "$BACKUP_DIR"/session_*.dump 2>/dev/null | tail -n +$((MAX_BACKUPS + 1)))
if [ -n "$OVERFLOW" ]; then
    echo "$OVERFLOW" | xargs -r rm -f
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Rotated old backups (limit=$MAX_BACKUPS)" | tee -a "$LOG_FILE"
fi

COUNT=$(ls "$BACKUP_DIR"/session_*.dump 2>/dev/null | wc -l)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Active backups: $COUNT / $MAX_BACKUPS" | tee -a "$LOG_FILE"
echo "---" >> "$LOG_FILE"
