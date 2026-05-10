FROM python:3.12-slim AS runtime
WORKDIR /app

# Install build deps for asyncpg / numpy then strip them
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gcc libpq-dev \
  && rm -rf /var/lib/apt/lists/*

COPY services/ai-service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Run as non-root
RUN groupadd -r app && useradd -r -g app -d /app appuser
COPY --chown=appuser:app services/ai-service/app ./app
USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD curl -fs http://localhost:8000/healthz || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
