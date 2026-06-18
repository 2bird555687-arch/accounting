#!/bin/bash
# restore.sh — Restore SQLite databases from a backup archive
# Usage:
#   ./scripts/restore.sh                        — list available backups
#   ./scripts/restore.sh 2026-06-18             — restore latest backup from that date
#   ./scripts/restore.sh 2026-06-18/acccloud_*.tar.gz  — restore specific archive

set -euo pipefail

BACKUPS_DIR="${BACKUPS_DIR:-./backups}"
DATA_DIR="${DATA_DIR:-./data}"

# ── List mode ─────────────────────────────────────────────────────────────────
if [ $# -eq 0 ]; then
    echo "Available backups:"
    echo ""
    if [ -d "$BACKUPS_DIR" ]; then
        find "$BACKUPS_DIR" -name "*.tar.gz" | sort -r | while IFS= read -r f; do
            SIZE=$(du -sh "$f" | cut -f1)
            echo "  ${SIZE}  $f"
        done
    else
        echo "  (no backups directory found at $BACKUPS_DIR)"
    fi
    echo ""
    echo "Usage: $0 <date>                e.g. $0 2026-06-18"
    echo "       $0 <path/to/file.tar.gz>  restore specific archive"
    exit 0
fi

ARG="$1"

# ── Resolve archive path ──────────────────────────────────────────────────────
if echo "$ARG" | grep -q "\.tar\.gz$"; then
    ARCHIVE="$ARG"
else
    # Treat as date — find latest archive for that date
    DATE_DIR="${BACKUPS_DIR}/${ARG}"
    if [ ! -d "$DATE_DIR" ]; then
        echo "ERROR: No backup directory for date: $ARG"
        exit 1
    fi
    ARCHIVE=$(find "$DATE_DIR" -name "*.tar.gz" | sort -r | head -1)
    if [ -z "$ARCHIVE" ]; then
        echo "ERROR: No archive found in $DATE_DIR"
        exit 1
    fi
fi

if [ ! -f "$ARCHIVE" ]; then
    echo "ERROR: Archive not found: $ARCHIVE"
    exit 1
fi

echo "============================================================"
echo "  AccCloud — Restore Procedure"
echo "============================================================"
echo "  Archive : $ARCHIVE"
echo "  Target  : $DATA_DIR"
echo ""
echo "  WARNING: This will OVERWRITE current database files!"
echo ""
read -p "  Type 'yes' to confirm: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 1
fi

# ── Stop app (if running via docker-compose) ──────────────────────────────────
echo ""
echo "[restore] Stopping app container..."
docker compose stop app 2>/dev/null || true

# ── Backup current data before restore ───────────────────────────────────────
PRE_BACKUP="${DATA_DIR}/../backups/pre_restore_$(date +%Y%m%d_%H%M%S)"
if [ -d "$DATA_DIR" ]; then
    echo "[restore] Saving current data to $PRE_BACKUP ..."
    mkdir -p "$PRE_BACKUP"
    cp -r "$DATA_DIR" "$PRE_BACKUP/"
fi

# ── Extract ────────────────────────────────────────────────────────────────────
echo "[restore] Extracting $ARCHIVE ..."
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

tar -xzf "$ARCHIVE" -C "$TMPDIR"

# Find the data directory inside the archive
EXTRACTED_DATA=$(find "$TMPDIR" -name "*.db" -o -name "*.sqlite" | head -1 | xargs dirname 2>/dev/null || echo "")

if [ -z "$EXTRACTED_DATA" ]; then
    echo "ERROR: No database files found in archive"
    exit 1
fi

# Copy restored files
echo "[restore] Copying files to $DATA_DIR ..."
mkdir -p "$DATA_DIR"
find "$TMPDIR" \( -name "*.db" -o -name "*.sqlite" \) | while IFS= read -r f; do
    REL="${f#$TMPDIR/}"
    DEST_FILE="${DATA_DIR}/${REL#app/data/}"
    mkdir -p "$(dirname "$DEST_FILE")"
    cp "$f" "$DEST_FILE"
    echo "  restored: $DEST_FILE"
done

echo ""
echo "[restore] Restore complete!"
echo "[restore] Pre-restore backup saved to: $PRE_BACKUP"
echo ""
echo "Start the app with: docker compose start app"
echo "         or:        make dev"
