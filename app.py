import json
import logging
import os
import secrets
import sys
import time
import uuid
from datetime import datetime, timezone

from flask import Flask, Response, g, jsonify, request
from gunicorn.glogging import Logger as GunicornLogger
from prometheus_client import (
    CONTENT_TYPE_LATEST, REGISTRY, CollectorRegistry, Counter, Histogram,
    generate_latest, multiprocess,
)
from werkzeug.exceptions import HTTPException


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": utc_now(), "level": record.levelname,
            "service": "compliment-generator", "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def stdout_handler():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    return handler


class JsonGunicornLogger(GunicornLogger):
    def setup(self, cfg):
        super().setup(cfg)
        for logger in (self.error_log, self.access_log):
            logger.handlers = [stdout_handler()]
            logger.propagate = False


app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
app.logger.handlers = [stdout_handler()]
app.logger.setLevel(logging.INFO)
app.logger.propagate = False

REQUEST_COUNT = Counter(
    "compliment_http_requests_total",
    "Completed HTTP requests, excluding probes and metric scrapes.",
    ["method", "route", "status"],
)
REQUEST_LATENCY = Histogram(
    "compliment_http_request_duration_seconds",
    "Server request handling duration, excluding probes and metric scrapes.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
COMPLIMENTS = (
    "You turn complex problems into clear, practical solutions.",
    "Your curiosity makes every project stronger.",
    "You bring calm and clarity when things get complicated.",
    "Your persistence turns small improvements into real progress.",
    "You make the people around you better at what they do.",
    "Your attention to detail builds trust.",
    "You have a talent for making difficult things understandable.",
    "Your next small step matters more than you think.",
)
EXCLUDED_ENDPOINTS = {"healthz", "readyz", "metrics"}
KNOWN_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


@app.before_request
def begin_request():
    g.started_at = time.perf_counter()
    g.trace_id = uuid.uuid4().hex


@app.after_request
def finish_request(response):
    duration = time.perf_counter() - g.started_at
    response.headers["X-Trace-ID"] = g.trace_id
    response.headers["Server-Timing"] = f"app;dur={duration * 1000:.3f}"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if request.endpoint not in EXCLUDED_ENDPOINTS:
        # Bound cardinality: route templates rather than raw URLs.
        route = request.url_rule.rule if request.url_rule else "unmatched"
        method = request.method if request.method in KNOWN_METHODS else "OTHER"
        REQUEST_COUNT.labels(method=method, route=route,
                             status=str(response.status_code)).inc()
        REQUEST_LATENCY.labels(method=method, route=route).observe(duration)
        app.logger.info("http_request", extra={"fields": {
            "trace_id": g.trace_id, "method": method, "route": route,
            "status": response.status_code,
            "duration_ms": round(duration * 1000, 3),
        }})
    return response


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/v1/compliments/random")
def random_compliment():
    return jsonify(compliment=secrets.choice(COMPLIMENTS),
                   trace_id=g.trace_id, timestamp=utc_now())


@app.get("/healthz")
def healthz():
    return Response("OK\n", status=200, mimetype="text/plain")


@app.get("/readyz")
def readyz():
    # No external dependencies.
    return Response("OK\n", status=200, mimetype="text/plain")


@app.get("/metrics")
def metrics():
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    else:
        registry = REGISTRY
    return Response(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)


@app.errorhandler(HTTPException)
def handle_http_error(error):
    response = error.get_response()
    response.data = app.json.dumps({"error": error.name,
                                    "trace_id": g.trace_id,
                                    "timestamp": utc_now()})
    response.content_type = "application/json"
    return response


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    app.logger.exception("unhandled_exception",
                         extra={"fields": {"trace_id": g.trace_id}})
    return jsonify(error="Internal server error", trace_id=g.trace_id,
                   timestamp=utc_now()), 500
