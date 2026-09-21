FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN groupadd --gid 10001 tatparya && useradd --uid 10001 --gid tatparya --create-home tatparya
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN mkdir -p /app/logs && chown -R tatparya:tatparya /app
USER tatparya
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + os.getenv('API_V1_PREFIX', '/api/v1') + '/health', timeout=4)"

# One worker: the analysis queue and rate limiter are process-local.
# Apply migrations before accepting requests; exec forwards container stop signals.
CMD ["sh", "-c", "alembic upgrade head && exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
