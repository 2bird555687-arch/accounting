#!/bin/bash
set -e

echo "=== AccCloud Startup ==="
echo "DATA_DIR=${DATA_DIR:-/app/data}"

# สร้าง data directory ถ้ายังไม่มี (Railway volume อาจยังไม่ mount)
mkdir -p "${DATA_DIR:-/app/data}"

echo "Running database migrations..."
alembic upgrade head

echo "Migrations complete."
echo "Starting server on port ${PORT:-8000}..."

exec python -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 2 \
  --log-level info \
  --access-log
