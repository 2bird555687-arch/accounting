# ── Stage 1: Build dependencies ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools for compiled packages (bcrypt, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python deps into isolated prefix
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ── Stage 2: Production image ─────────────────────────────────────────────────
FROM python:3.11-slim AS production

LABEL org.opencontainers.image.title="AccCloud"
LABEL org.opencontainers.image.description="Accounting Web App — FastAPI + SQLite"

# Runtime system deps (WeasyPrint needs Pango/Cairo, pymupdf needs libmupdf)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libglib2.0-0 \
    libffi8 \
    libgdk-pixbuf2.0-0 \
    libxml2 \
    libxslt1.1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Create non-root user
RUN groupadd --gid 1001 appgroup \
 && useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy application code (explicit — no dev junk)
COPY --chown=appuser:appgroup app/              ./app/
COPY --chown=appuser:appgroup templates/        ./templates/
COPY --chown=appuser:appgroup migrations/       ./migrations/
COPY --chown=appuser:appgroup alembic.ini       ./alembic.ini
COPY --chown=appuser:appgroup requirements.txt  ./requirements.txt

# Static files directory (may be populated at runtime)
RUN mkdir -p app/static data backups logs \
 && chown -R appuser:appgroup /app

USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

EXPOSE 8000

# Use exec form — signals propagate to uvicorn
CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--log-level", "info", \
     "--access-log"]
