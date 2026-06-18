#!/bin/sh
# backup.sh — Daily SQLite backup
# Runs inside the 'backup' container (alpine).
# Mounted: /app/data (ro), /backups (rw)

set -e

DATE=$(date +%Y-%m-%d)
TIME=$(date +%H%M%S)
DEST="/backups/${DATE}"
ARCHIVE="${DEST}/acccloud_${DATE}_${TIME}.tar.gz"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

echo "[backup] Starting backup at $(date)"

# Create dated directory
mkdir -p "${DEST}"

# Find all SQLite files under /app/data and archive them
SQLITE_FILES=$(find /app/data -name "*.db" -o -name "*.sqlite" 2>/dev/null | sort)

if [ -z "$SQLITE_FILES" ]; then
    echo "[backup] No database files found in /app/data — skipping"
    exit 0
fi

echo "[backup] Files to backup:"
echo "$SQLITE_FILES" | while IFS= read -r f; do echo "  $f"; done

# Create compressed archive (preserve directory structure)
tar -czf "${ARCHIVE}" -C /app $SQLITE_FILES 2>/dev/null || \
tar -czf "${ARCHIVE}" -C / app/data 2>/dev/null

SIZE=$(du -sh "${ARCHIVE}" | cut -f1)
echo "[backup] Archive created: ${ARCHIVE} (${SIZE})"

# Verify the archive is readable
tar -tzf "${ARCHIVE}" > /dev/null
echo "[backup] Archive integrity OK"

# Write a manifest
echo "date=${DATE}" > "${DEST}/manifest.txt"
echo "time=${TIME}" >> "${DEST}/manifest.txt"
echo "archive=${ARCHIVE}" >> "${DEST}/manifest.txt"
echo "size=${SIZE}" >> "${DEST}/manifest.txt"
echo "files=$(echo "$SQLITE_FILES" | wc -l)" >> "${DEST}/manifest.txt"

# ── Retention: remove old backups ─────────────────────────────────────────────
echo "[backup] Removing backups older than ${RETENTION_DAYS} days..."
find /backups -maxdepth 1 -type d -name "20*" | sort | while IFS= read -r dir; do
    DIR_DATE=$(basename "$dir")
    CUTOFF=$(date -d "-${RETENTION_DAYS} days" +%Y-%m-%d 2>/dev/null || \
             date -v-${RETENTION_DAYS}d +%Y-%m-%d 2>/dev/null || echo "1970-01-01")
    if [ "$DIR_DATE" \< "$CUTOFF" ]; then
        echo "[backup] Removing old backup: $dir"
        rm -rf "$dir"
    fi
done

echo "[backup] Done at $(date)"
