# Docker

**Applies to:** Anyone changing the Dockerfile or diagnosing a build failure
**Related documents:** [Deployment](README.md) · [CI](CI.md) · [Environment](ENVIRONMENT.md) · [Security](../architecture/SECURITY.md)

The service is packaged as one immutable image, published to the GitHub
Container Registry and pulled by Watchtower.

Source: [Dockerfile](../../Dockerfile).

## Why a single stage

Multi-stage builds exist to keep compilers and build tooling out of the runtime
image. There is nothing to keep out here.

Pillow ships manylinux wheels for CPython 3.14, so `pip install` never compiles
anything and no toolchain is ever installed. FastAPI and uvicorn are pure Python.
A build stage would add complexity and save nothing.

If a future dependency needs compiling, that is the moment to introduce a second
stage — not before.

## Structure

```dockerfile
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .                       # dependency layer, cached
RUN pip install --no-cache-dir -r requirements.txt
COPY ai_metadata_check.py server.py ./        # code layer, changes often

RUN useradd --create-home --uid 10001 appuser
USER appuser
EXPOSE 8000
```

Requirements are copied before the source so the dependency layer survives every
code edit. A change to `ai_metadata_check.py` rebuilds one small layer.

Only the two Python files are copied. The compose files, the Next.js example and
the documentation are excluded by [.dockerignore](../../.dockerignore) and never
enter the context.

## Runtime settings

| Setting                    | Value                | Why                                                                |
| -------------------------- | -------------------- | ------------------------------------------------------------------ |
| `PYTHONUNBUFFERED=1`       | —                    | Logs reach `docker logs` immediately instead of sitting in a buffer |
| `PYTHONDONTWRITEBYTECODE=1`| —                    | No `.pyc` files; the filesystem stays untouched                     |
| User                       | `appuser`, UID 10001 | Unprivileged. The service needs no writable path at all             |
| Port                       | `8000`               | `expose` only in both compose files, never published to the host    |
| `WEB_CONCURRENCY`          | `2`                  | Scanning is CPU-bound and short; two workers absorb concurrent uploads without a large pool's memory cost |

The service reads request bodies into memory and never writes to disk, which is
what makes the unprivileged, no-volume setup possible.

## The healthcheck

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
```

`python:3.14-slim` has no `curl` and no `wget`. Rather than install one just to
probe a local port, the check uses the interpreter that is already there.

`/health` is deliberately unauthenticated so this works regardless of `API_KEY`.

## The command

```dockerfile
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY}"]
```

The shell form is required because `${WEB_CONCURRENCY}` must be expanded at
runtime — exec form does no variable substitution. `exec` hands PID 1 to uvicorn
so it receives `SIGTERM` directly and shuts down cleanly instead of being killed
after the stop timeout.

`--host 0.0.0.0` binds inside the container. That is not a public bind: both
compose files use `expose`, so the port is reachable from the Docker network
only.

## Building

```bash
docker build -t metadata-validator .
docker run --rm -p 8000:8000 -e API_KEY=local-dev metadata-validator
curl -s localhost:8000/health
```

Pull the published image instead:

```bash
docker pull ghcr.io/sagabeats/metadata-validator:prod
docker pull ghcr.io/sagabeats/metadata-validator:<sha>   # for a rollback
```

Both tags are pushed by CI on every merge to `main`. See [CI.md](CI.md).

## Build requirements

- **Pin the base image.** `python:3.14-slim`, not `python:slim`.
- **No secret in any layer.** `API_KEY` is injected at runtime. There are no
  build arguments, and `.dockerignore` excludes `.env` and `.env.*` so a stray
  file cannot reach the context.
- **Stay unprivileged.** Any change requiring a writable path is a change to the
  security model — read [architecture/SECURITY.md](../architecture/SECURITY.md)
  first.
- **Keep the context minimal.** `.dockerignore` excludes `.venv/`,
  `__pycache__/`, `.git/`, `nextjs-example/`, `*.md`, and tool output such as
  `*.bak` and `*.clean.*`.

## References

- [Deployment](README.md)
- [CI](CI.md)
- [Environment](ENVIRONMENT.md)
- [Traefik](TRAEFIK.md)
- [Security](../architecture/SECURITY.md)
- [Docker healthcheck reference](https://docs.docker.com/reference/dockerfile/#healthcheck)
- [uvicorn deployment](https://www.uvicorn.org/deployment/)
