# syntax=docker/dockerfile:1
# ── Base ──────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ── Dependencies ─────────────────────────────────────────────────────────
COPY etl/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ─────────────────────────────────────────────────────
COPY etl/ ./etl/
COPY db/ ./db/

# ── Runtime ──────────────────────────────────────────────────────────────
# Runs the long-lived consumer loop (Cloud Run always-on service)
CMD ["python", "-m", "etl.pubsub_consumer"]
