# syntax=docker/dockerfile:1
#
# AI metadata checker service.
# Pillow ships manylinux wheels for CPython 3.14, so no compiler is needed and
# a single-stage slim image stays small.

FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Requirements first so the dependency layer caches across code edits.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ai_metadata_check.py server.py ./

# Run unprivileged. The service only ever reads request bodies into memory --
# it never writes to disk -- so it needs no writable paths at all.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# No curl in slim, so probe with the interpreter that is already here.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# Scanning is CPU-bound and short; a couple of workers absorb concurrent
# uploads without the memory cost of a large pool. Override via WEB_CONCURRENCY.
ENV WEB_CONCURRENCY=2
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY}"]
