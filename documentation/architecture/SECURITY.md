# Security

**Applies to:** Anyone exposing the service, or reviewing a change to it
**Related documents:** [Environment](../deployment/ENVIRONMENT.md) · [Traefik](../deployment/TRAEFIK.md) · [Docker](../deployment/DOCKER.md) · [Overview](OVERVIEW.md)

## Threat model

The service accepts arbitrary binary uploads from a caller and parses them with
hand-written byte parsers. That is the whole attack surface, and it produces
three realistic risks:

| Risk                        | Where it lands                                     | Mitigation                                                          |
| --------------------------- | -------------------------------------------------- | ------------------------------------------------------------------- |
| Resource exhaustion         | Large or many uploads held in memory                | `MAX_UPLOAD_BYTES`, `MAX_BATCH_FILES`, Traefik body cap, memory limit |
| Malformed-input crash       | The container parsers                               | Parsers stop rather than raise; `_safe_inflate` bounded and caught   |
| Unauthorised use            | An internet-reachable endpoint doing CPU work       | Bearer `API_KEY`, Traefik rate limit, CrowdSec                       |

What is **not** in the model: the uploaded content itself. Nothing is executed,
nothing is written to disk, and nothing is stored. A malicious image is parsed
and discarded.

## Authentication

`require_key()` is a FastAPI dependency applied to `/check`, `/check/batch`,
`/clean` and `/clean/json`. `/health` is deliberately open so that Docker,
Traefik and CI can probe it.

- Unset `API_KEY` disables the check entirely. That is intended for localhost
  and nothing else.
- The comparison is `secrets.compare_digest`, so the key cannot be recovered
  by timing the response.
- The header is declared as `Annotated[str | None, Header()]`. The `Header()`
  marker is load-bearing: without it FastAPI treats `authorization` as a *query*
  parameter and every request fails auth regardless of what it sent. Do not
  simplify that annotation.

Two guards exist against running open by accident:

- `server.py` prints a warning when `--host` is anything but `127.0.0.1` and no
  key is set.
- [docker-compose.yml](../../docker-compose.yml) declares
  `${API_KEY:?set API_KEY in .env before starting}`, so the stack refuses to
  start unauthenticated. That file publishes to the internet through Traefik;
  the `:?` is the thing standing between it and an open endpoint.

Generate a key with `openssl rand -hex 32`. There is no rotation mechanism —
change the value and restart.

## Resource limits

Defence is layered, and the outermost layer rejects first:

```text
Traefik buffering middleware     maxRequestBodyBytes = 26214400
        |                        memRequestBodyBytes = 2097152  (spill beyond this)
        v
Traefik rate limit               30/min average, burst 10, per source
        |
        v
server.py read_upload()          413 above MAX_UPLOAD_BYTES
        |                        400 on an empty body
        v
/check/batch                     413 above MAX_BATCH_FILES (default 20)
        |
        v
container memory limit           512M
```

Keep the Traefik cap and `MAX_UPLOAD_BYTES` in step. If the proxy cap is lower,
the application's error message is never seen and callers get an opaque proxy
error; if it is much higher, memory is committed before the application can
refuse.

Batch requests process files **sequentially**, so peak memory is about one file,
not twenty. That is why 512 MB is enough.

## Parser robustness

The container parsers are the code most exposed to hostile input, and they are
written to degrade rather than raise:

- `_iso_boxes()` returns on a malformed length instead of raising. Half a tree
  is still a usable report, and truncated uploads are normal.
- `_safe_inflate()` bounds zlib output at 4 MiB and returns the input unchanged
  on any exception — a decompression bomb in a `zTXt` chunk cannot expand
  without limit.
- `ISOBMFF_REGION_CAP` truncates any single box carried into a report at 4 MiB.
- The walk depth is capped at 8, so a deeply nested box tree cannot recurse
  without bound.
- `read_exif_summary()` wraps Pillow in a bare `except` — a malformed image must
  not turn a verdict into a 500.

If you add a parser, hold the same line: never raise on structure you did not
expect, and never allocate proportional to an attacker-controlled length field.

## Runtime hardening

From the [Dockerfile](../../Dockerfile) and the compose files:

- Runs as `appuser`, UID 10001, not root.
- No writable path is needed. The service reads request bodies into memory and
  never touches disk.
- `expose`, not `ports`, in both compose files — the container is reachable from
  Traefik on `project-network`, never from the host's public interface.
- A 512 MB memory limit, so a pathological request cannot starve the other
  services on the VPS.
- Pinned base image `python:3.14-slim`.

## CORS

`ALLOWED_ORIGINS` is unset by default and the CORS middleware is only installed
when it has a value. Leave it unset.

CORS is only relevant when a **browser** calls the service directly, which means
the API key would have to be in browser-reachable code. The supported pattern is
the opposite: a server-side caller — a Next.js route handler, a worker — holds
the key and the browser only ever talks to your own origin. See
[integrations/NEXTJS.md](../integrations/NEXTJS.md).

## Secrets

There are exactly two secrets in the system, and neither is in the repository:

| Secret               | Lives in                        | Notes                                                  |
| -------------------- | ------------------------------- | ------------------------------------------------------ |
| `API_KEY`            | `.env` beside the compose file  | Never in an image layer, never a build argument        |
| `GITHUB_TOKEN`       | Provided by GitHub Actions      | Scoped to `packages: write` for the publish job only   |

`.gitignore` excludes `.env` and `.env.*`; `.dockerignore` excludes them from the
build context so they cannot reach a layer even by accident.

## Reporting a vulnerability

Do not open a public issue. Contact the maintainer directly — see the author
line in the [root README](../../README.md) — and include a minimal sample file
where the problem is in the parsing path.

A false negative in the signature tables is a normal issue, not a vulnerability.
A crash, a hang, or unbounded memory growth on a crafted file is a vulnerability.

## References

- [Environment](../deployment/ENVIRONMENT.md)
- [Traefik](../deployment/TRAEFIK.md)
- [Docker](../deployment/DOCKER.md)
- [Runbook](../deployment/RUNBOOK.md)
- [Next.js integration](../integrations/NEXTJS.md)
- [FastAPI security](https://fastapi.tiangolo.com/tutorial/security/)
