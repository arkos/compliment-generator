FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WEB_CONCURRENCY=2 \
    PORT=8080 \
    HOME=/tmp

WORKDIR /app
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY --chown=10001:10001 app.py .
COPY --chown=10001:10001 static/ ./static/
USER 10001:10001
EXPOSE 8080
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8080') + '/healthz', timeout=2)" || exit 1

# Fresh metrics directory for every startup; exec forwards termination signals.
CMD ["sh", "-c", "export PROMETHEUS_MULTIPROC_DIR=$(mktemp -d /tmp/compliment-metrics.XXXXXX) && exec gunicorn app:app --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY} --worker-class gthread --threads 4 --timeout 30 --graceful-timeout 30 --worker-tmp-dir /tmp --error-logfile - --logger-class app.JsonGunicornLogger"]
