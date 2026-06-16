FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libgomp1 && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir uvicorn[standard] aiosqlite

# Copy source
COPY . .

ENV PYTHONPATH=/app:/app/decision-api
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8081

WORKDIR /app/decision-api
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8081"]
