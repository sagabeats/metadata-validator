# Installation

**Applies to:** Anyone setting up the checker, the service, or the container
**Related documents:** [Getting started](GETTING-STARTED.md) · [Environment](deployment/ENVIRONMENT.md) · [Docker](deployment/DOCKER.md)

This is the complete environment reference. For the fastest path to a working
checker, use [GETTING-STARTED.md](GETTING-STARTED.md) instead.

## What you are installing

The repository is four things, and you may only need the first:

| Path                                              | What it is                       | Needs                                     |
| ------------------------------------------------- | -------------------------------- | ----------------------------------------- |
| [ai_metadata_check.py](../ai_metadata_check.py)   | The CLI and the whole engine     | Python. Pillow optional                   |
| [server.py](../server.py)                         | The HTTP service around it       | FastAPI, uvicorn, python-multipart        |
| [Dockerfile](../Dockerfile)                       | The published container image    | Docker                                    |
| [nextjs-example/](../nextjs-example/)             | A reference caller, not shipped  | Nothing — it is copied into your own app  |

## Python

| Requirement | Version       | Why                                                                       |
| ----------- | ------------- | ------------------------------------------------------------------------- |
| CPython     | 3.10 or later | PEP 604 unions (`str \| None`) in annotations, and `int.from_bytes` usage  |
| CPython     | 3.14          | What the container image runs, and therefore what production behaves like  |

There is no `pyproject.toml`, no package, and no entry point to install. Both
scripts are run directly.

## Dependencies

From [requirements.txt](../requirements.txt):

| Package             | Constraint | Needed by                    | What breaks without it                                       |
| ------------------- | ---------- | ---------------------------- | ------------------------------------------------------------ |
| `Pillow`            | `>=11.0`   | CLI and service (optional)   | The EXIF table is empty; the Pillow strip fallback is gone   |
| `fastapi`           | `>=0.115`  | `server.py`                  | The service will not import                                  |
| `uvicorn[standard]` | `>=0.32`   | `server.py`                  | The service has no ASGI server to run under                  |
| `python-multipart`  | `>=0.0.9`  | `server.py`                  | Every multipart upload fails; FastAPI raises on startup      |

If you only want the CLI, `pip install "Pillow>=11.0"` is sufficient — and even
that is optional. Container parsing, signature scanning and JPEG/PNG/WebP
stripping are pure standard library (`struct`, `zlib`, `re`, `io`).

## Local setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

Verify:

```bash
python ai_metadata_check.py --help
python server.py --help
```

## Configuration

The CLI takes no configuration at all — every option is a flag. The service is
configured entirely by environment variables, none of which are required for a
localhost run:

| Variable            | Default              | Purpose                                                   |
| ------------------- | -------------------- | --------------------------------------------------------- |
| `API_KEY`           | unset (open)         | Bearer token required on every route when set              |
| `MAX_UPLOAD_BYTES`  | `26214400` (25 MiB)  | Per-file ceiling, enforced after the body is read          |
| `MAX_BATCH_FILES`   | `20`                 | Ceiling on files in one `/check/batch` call                |
| `ALLOWED_ORIGINS`   | unset (no CORS)      | Comma-separated origins, only for direct browser callers   |
| `WEB_CONCURRENCY`   | `2` (image only)     | uvicorn worker count in the container                      |

The full reference, including what each one actually protects, is in
[deployment/ENVIRONMENT.md](deployment/ENVIRONMENT.md).

There is no `.env` loading in the code. Values come from the real environment,
which in practice means a compose file or your shell.

## Container setup

```bash
docker build -t metadata-validator .
docker run --rm -p 8000:8000 -e API_KEY=local-dev metadata-validator
```

Or pull the published image:

```bash
docker pull ghcr.io/sagabeats/metadata-validator:prod
```

The image is a single stage on `python:3.14-slim`, runs as UID 10001, and needs
no writable path — it never touches disk. See
[deployment/DOCKER.md](deployment/DOCKER.md).

## What is deliberately not here

- **No test suite.** The only automated verification is the CI smoke test. See
  [standards/TESTING.md](standards/TESTING.md) for what that covers and what it
  does not.
- **No linter or formatter config.** Match the surrounding style by hand.
- **No lock file.** Dependencies are floor-pinned, not exact-pinned. The image
  digest is the reproducibility boundary, not `requirements.txt`.
- **No sample images in the repository.** Detection changes are verified against
  files you supply; see [standards/TESTING.md](standards/TESTING.md).

## References

- [Getting started](GETTING-STARTED.md)
- [Technology map](TECHNOLOGIES.md)
- [Environment](deployment/ENVIRONMENT.md)
- [Docker](deployment/DOCKER.md)
- [Testing](standards/TESTING.md)
- [Pillow](https://pillow.readthedocs.io/en/stable/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [uvicorn](https://www.uvicorn.org/)
