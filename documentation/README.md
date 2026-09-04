# Metadata Validator documentation

This folder is the documentation hub for the metadata validator: a tool that
detects — and removes — the metadata markers that make platforms label an
upload as "Altered or synthetic content".

It ships in three shapes from the same code: a command-line checker
([ai_metadata_check.py](../ai_metadata_check.py)), an HTTP service around it
([server.py](../server.py)), and a container image published to GHCR.

If you are new, start with [GETTING-STARTED.md](GETTING-STARTED.md). If you
already know which area you need, use the indexes below.

## Choose your path

| You want to…                                  | Start here                                                                       |
| --------------------------------------------- | ---------------------------------------------------------------------------------- |
| Run the checker on your machine                | [Getting started](GETTING-STARTED.md) · [Installation](INSTALL.md)                 |
| Understand how a verdict is reached            | [Overview](architecture/OVERVIEW.md) · [Detection](architecture/DETECTION.md)      |
| Know why a file was flagged                    | [Signature reference](reference/SIGNATURES.md)                                     |
| Call the service over HTTP                     | [Endpoint reference](reference/ENDPOINTS.md)                                       |
| Use the CLI                                    | [CLI reference](reference/CLI.md)                                                  |
| Import it as a Python module                   | [Python API](reference/PYTHON-API.md)                                              |
| Add support for a new container format         | [Containers](architecture/CONTAINERS.md)                                           |
| Add a new AI tool signature                    | [Detection](architecture/DETECTION.md) · [Contributing](standards/CONTRIBUTING.md) |
| Understand why stripping never recompresses    | [Stripping](architecture/STRIPPING.md)                                             |
| Deploy to the VPS                              | [Deployment](deployment/README.md) · [Runbook](deployment/RUNBOOK.md)              |
| Configure an environment variable              | [Environment](deployment/ENVIRONMENT.md)                                           |
| Call it from Next.js                           | [Next.js integration](integrations/NEXTJS.md)                                      |
| Know what is still planned                     | [Roadmap](ROADMAP.md)                                                              |
| See what changed and when                      | [Changelog](CHANGELOG.md)                                                          |
| Report a vulnerability                         | [Security](architecture/SECURITY.md)                                               |

## How the pieces fit together

```text
CLI                       HTTP client (Next.js route handler, curl, worker)
 |                         |
 |                        Traefik  ->  TLS, rate limit, 25 MB body cap
 |                         |
 |                        server.py  ->  bearer auth, size cap, threadpool
 |                         |
 +-----------+-------------+
             |
      ai_metadata_check.py
             |
   extract_regions()   -> per-container metadata blocks only, never pixels
   scan_regions()      -> hard / soft signature match
   verdict_for()       -> CLEAN | SUSPICIOUS | AI METADATA DETECTED
   strip_bytes()       -> rebuild the container without its metadata
```

Every layer above `ai_metadata_check.py` is transport. All detection and
stripping logic lives in that one module, which is why the CLI, the service and
any Python caller cannot disagree about a verdict.

## Documentation index

### Architecture

- [Overview](architecture/OVERVIEW.md) — the pipeline, the two processes, and what each layer is responsible for.
- [Detection](architecture/DETECTION.md) — hard versus soft signatures, benign signals, and how the verdict is computed.
- [Containers](architecture/CONTAINERS.md) — how JPEG, PNG, WebP and ISO base media files are parsed into metadata regions.
- [Stripping](architecture/STRIPPING.md) — byte surgery per format, what is deliberately kept, and the verify-after-strip rule.
- [Security](architecture/SECURITY.md) — the threat model, authentication, resource limits, and vulnerability reporting.

### Reference

- [Endpoints](reference/ENDPOINTS.md) — every HTTP route, its form fields, response shape and status codes.
- [CLI](reference/CLI.md) — every flag, exit code, and the shape of the terminal report.
- [Python API](reference/PYTHON-API.md) — `analyze`, `clean`, `strip_bytes` and the dictionaries they return.
- [Signatures](reference/SIGNATURES.md) — the complete signature tables, with what each pattern means in practice.

### Deployment

- [Deployment index](deployment/README.md) — the three ways to run it, and how to choose.
- [Docker](deployment/DOCKER.md) — how the image is built and why it is a single stage.
- [CI](deployment/CI.md) — the publish workflow and its smoke test.
- [Environment](deployment/ENVIRONMENT.md) — every variable, its default, and what it protects.
- [Traefik](deployment/TRAEFIK.md) — routing, TLS, the dedicated rate limiter, and the body cap.
- [Runbook](deployment/RUNBOOK.md) — verification, rollback, diagnosis, and known pitfalls.

### Integrations

- [Integration index](integrations/README.md) — every caller and its failure mode.
- [Next.js](integrations/NEXTJS.md) — the reference route handler and why the service stays server-side.

### Standards

- [Contributing](standards/CONTRIBUTING.md) — branches, commits, and how to add a signature or a container.
- [Testing](standards/TESTING.md) — what is verified automatically, and what you must verify by hand.

### Product

- [Roadmap](ROADMAP.md) — planned and in-progress work.
- [Changelog](CHANGELOG.md) — released changes, grouped by release.

## Four assumptions that hold everything up

1. **A verdict is about metadata, never about pixels.** Nothing here looks at
   the image content. A hand-drawn thumbnail exported by Canva can be flagged;
   a genuine diffusion output with its metadata already stripped reads as clean.
   That is correct behaviour — it mirrors exactly what the platforms read.
2. **`hard` and `soft` findings are not the same claim.** A `hard` finding is a
   formal declaration that platforms act on. A `soft` finding is a fingerprint
   that an AI tool touched the file. Only `hard` sets `ai_detected`.
3. **A strip is never reported as successful until it is re-scanned.** `clean()`
   analyses the output and sets `verified`; `/clean` returns 500 rather than
   hand back a file it could not confirm.
4. **The service holds nothing.** No disk writes, no database, no state between
   requests. Every byte lives in memory for the length of one request, which is
   why the container runs unprivileged with no writable paths.

Each is documented where it is enforced. Violating one silently breaks a
guarantee the rest of the documentation assumes.

## References

- [Getting started](GETTING-STARTED.md)
- [Installation](INSTALL.md)
- [Technology map](TECHNOLOGIES.md)
- [Architecture](architecture/README.md)
- [Reference](reference/README.md)
- [Deployment](deployment/README.md)
- [Integrations](integrations/README.md)
- [Standards](standards/README.md)
