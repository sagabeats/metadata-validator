# Metadata Validator

Detects — and removes — the metadata markers that make platforms label an upload
as "Altered or synthetic content". One engine, shipped as a CLI, an HTTP service,
and a container image.

YouTube, Instagram, TikTok and LinkedIn apply that label by reading file
metadata, not by looking at the image. A thumbnail can be entirely hand-made and
still get labelled, because some tool in the chain — Photoshop Generative Fill,
Canva Magic Media, an AI upscaler, a background remover — stamped the file on
export. This answers "will this upload be labelled?" before the upload happens,
and removes the cause when the answer is yes.

All documentation is in [documentation/](documentation/). Start at
[documentation/README.md](documentation/README.md).

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # source .venv/bin/activate on macOS / Linux
pip install -r requirements.txt

python ai_metadata_check.py thumb.jpg           # check
python ai_metadata_check.py thumb.jpg --strip   # writes thumb.clean.jpg
```

As a service:

```bash
python server.py                                # http://127.0.0.1:8000
curl -s -X POST localhost:8000/check -F file=@thumb.jpg
```

Full setup is in
[documentation/GETTING-STARTED.md](documentation/GETTING-STARTED.md).

## Verdicts

| Verdict                | Exit | Meaning                                                                   |
| ---------------------- | ---- | ------------------------------------------------------------------------- |
| `CLEAN`                | `0`  | Nothing declares or fingerprints AI use                                    |
| `SUSPICIOUS`           | `2`  | An AI tool touched the file but declared nothing                           |
| `AI METADATA DETECTED` | `1`  | A formal declaration platforms read. **This upload will be labelled**      |

The split between the last two is the point of the tool. Collapsing them would
flag every Photoshop export and train users to ignore the warning — see
[documentation/architecture/DETECTION.md](documentation/architecture/DETECTION.md).

## Format support

| Format                          | Check | Strip                              |
| ------------------------------- | ----- | ---------------------------------- |
| JPEG, PNG, WebP                 | Yes   | Yes, pixels untouched              |
| MP4, MOV, M4A, HEIC, AVIF       | Yes   | No — check-only today              |
| Anything else                   | Yes, whole-file scan | CLI only, via a lossy re-save |

Stripping JPEG, PNG and WebP copies the compressed image data verbatim, so the
pixels are bit-identical and the file is never recompressed.

## Choose your path

| You want to…                                | Start here                                                                                |
| ------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Run the checker locally                      | [Getting started](documentation/GETTING-STARTED.md)                                         |
| Understand how a verdict is reached          | [Detection](documentation/architecture/DETECTION.md)                                        |
| Know why a file was flagged                  | [Signature reference](documentation/reference/SIGNATURES.md)                                |
| Call the service over HTTP                   | [Endpoint reference](documentation/reference/ENDPOINTS.md)                                  |
| Use every CLI flag                           | [CLI reference](documentation/reference/CLI.md)                                             |
| Import it as a Python module                 | [Python API](documentation/reference/PYTHON-API.md)                                         |
| Add a signature or a container format        | [Contributing](documentation/standards/CONTRIBUTING.md)                                     |
| Deploy to a VPS                              | [Deployment](documentation/deployment/README.md)                                            |
| Configure an environment variable            | [Environment](documentation/deployment/ENVIRONMENT.md)                                      |
| Wire it into a Next.js upload flow           | [Next.js integration](documentation/integrations/NEXTJS.md)                                 |
| Report a vulnerability                       | [Security](documentation/architecture/SECURITY.md)                                          |

## Components

| Component                                                     | Stack                    | Port    | Responsibility                                                     |
| ------------------------------------------------------------- | ------------------------ | ------- | -------------------------------------------------------------------- |
| [ai_metadata_check.py](ai_metadata_check.py)                   | Python 3.10+, stdlib     | —       | Signature tables, container parsers, verdicts, stripping, and the CLI |
| [server.py](server.py)                                        | FastAPI, uvicorn         | `:8000` | HTTP transport only: auth, size limits, threadpool dispatch          |
| [Dockerfile](Dockerfile)                                      | `python:3.14-slim`       | `:8000` | The published image, unprivileged, no writable paths                 |
| [nextjs-example/](nextjs-example/)                            | Next.js Route Handler    | —       | A reference caller to copy, not a shipped package                    |

`server.py` imports `ai_metadata_check` and calls three functions from it. It
holds no detection logic, so the CLI and the service cannot disagree about a
file.

## Documentation

| Area                                                              | Contents                                                            |
| ----------------------------------------------------------------- | --------------------------------------------------------------------- |
| [documentation/](documentation/README.md)                          | The documentation hub                                                 |
| [architecture/](documentation/architecture/README.md)              | Pipeline, detection model, container parsing, stripping, security     |
| [reference/](documentation/reference/README.md)                    | Endpoints, CLI flags, Python API, and the complete signature tables   |
| [deployment/](documentation/deployment/README.md)                  | Docker, CI, environment, Traefik, runbook                             |
| [integrations/](documentation/integrations/README.md)              | Callers, and the Next.js reference handler                            |
| [standards/](documentation/standards/README.md)                    | Contribution workflow and manual verification                         |
| [ROADMAP.md](documentation/ROADMAP.md)                             | Planned and in-progress work                                          |
| [CHANGELOG.md](documentation/CHANGELOG.md)                         | Released changes                                                      |

## Deployment

The image is published to `ghcr.io/sagabeats/metadata-validator:prod` on every
merge to `main`, and Watchtower rolling-restarts the container on the VPS within
about a minute. The service is stateless — no database, no volume, no cache — so
recovery is always either a restart or a pinned `:<sha>` tag.

Prefer keeping it off the public internet: a caller on the same VPS reaches it at
`http://metadata-validator:8000`, with nothing to expose, rate-limit or
certificate. See [documentation/deployment/README.md](documentation/deployment/README.md).

## Author

Yosua Hares — haresyosuaa[at]gmail.com — [wa.me/6281261414784](https://wa.me/6281261414784)
