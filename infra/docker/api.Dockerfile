# ===========================================================================
# Academic Edge API / worker image.
#
# One image serves both processes (the command differs), which keeps the
# dependency set identical between the API and the ingestion worker. Credentials
# are supplied at runtime via environment variables only - never baked in, and
# no bookmaker credential is ever mounted.
# ===========================================================================
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# curl is used by the healthcheck; build-essential is only needed for wheels
# that lack manylinux builds (psycopg-binary and friends ship wheels, so the
# compiler is dropped again in the next stage).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- dependency layer (cached unless pyproject changes) --------------------
COPY pyproject.toml README.md ./
COPY packages ./packages
COPY apps ./apps
COPY config ./config
RUN python -m pip install --upgrade pip && python -m pip install -e ".[worker,s3]"

# ---- migrations + local scripts -------------------------------------------
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts

# Run as a non-root user: an ingester does not need root.
RUN useradd --create-home --shell /usr/sbin/nologin academic \
    && mkdir -p /app/.data \
    && chown -R academic:academic /app
USER academic

ENV ACADEMIC_EDGE_ENV=production \
    RAW_ARCHIVE_BACKEND=s3 \
    API_HOST=0.0.0.0 \
    API_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/v1/health || exit 1

CMD ["uvicorn", "academic_edge_api.main:app", "--host", "0.0.0.0", "--port", "8000"]