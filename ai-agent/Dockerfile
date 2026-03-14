FROM python:3.11-slim

WORKDIR /app

COPY ai-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ai-agent/src/ ./src/
COPY ai-agent/config/ ./config/

ENV PYTHONPATH=/app/src

EXPOSE 8082

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8082", "--workers", "1"]
