# Environment

**Applies to:** Anyone configuring a deployment
**Related documents:** [Deployment](README.md) · [Security](../architecture/SECURITY.md) · [Traefik](TRAEFIK.md) · [Docker](DOCKER.md)

Every environment variable the service reads, where it is set, and what it
protects. The CLI reads none of these — it is configured entirely by flags.

There is no `.env` loading in the code. Values come from the real process
environment, which in practice means a compose file or your shell.

## Service variables

Read by [server.py](../../server.py) at import time. Changing one requires a
restart.

| Variable           | Default             | Read by                     | Purpose                                                        |
| ------------------ | ------------------- | --------------------------- | -------------------------------------------------------------- |
| `API_KEY`          | unset (**open**)    | `require_key()`             | Bearer token required on every route except `/health`          |
| `MAX_UPLOAD_BYTES` | `26214400` (25 MiB) | `read_upload()`             | Per-file ceiling. Returns `413` above it                       |
| `MAX_BATCH_FILES`  | `20`                | `check_batch()`             | Ceiling on files in one `/check/batch` call. Returns `413`     |
| `ALLOWED_ORIGINS`  | unset (no CORS)     | CORS middleware             | Comma-separated origins, only for direct browser callers       |
| `WEB_CONCURRENCY`  | `2` (image only)    | the container `CMD`         | uvicorn worker count                                           |

### API_KEY

The single security control on the service.

- **Unset means open.** Acceptable on localhost, nowhere else.
- Generate with `openssl rand -hex 32`.
- Compared with `secrets.compare_digest`, so it cannot be timed out.
- Rotation is: change the value, restart, update every caller. There is no
  overlap window and no second key.

[docker-compose.yml](../../docker-compose.yml) declares it as
`${API_KEY:?set API_KEY in .env before starting}`. That variant publishes through
Traefik, so the `:?` is what stands between the deployment and an open endpoint.
Do not soften it to a default.

### MAX_UPLOAD_BYTES

Enforced **after** the body has been read into memory, so it bounds what is
retained, not what is received. The Traefik `buffering` middleware is the layer
that stops a large body earlier.

**Keep the two in step.** If the Traefik cap is lower, callers get an opaque
proxy error instead of the service's message. If it is much higher, memory is
committed before the application can refuse. Both default to 25 MiB.

### MAX_BATCH_FILES

Batch entries are processed one at a time, so this bounds request duration and
threadpool pressure rather than peak memory — that stays at roughly one file.

### ALLOWED_ORIGINS

The CORS middleware is only installed when this has a value. Leave it unset.

CORS matters only when a **browser** calls the service directly, which means the
API key is in browser-reachable code. The supported pattern is the opposite: a
server-side caller holds the key. See
[integrations/NEXTJS.md](../integrations/NEXTJS.md).

If you must set it, list exact origins — `https://app.example.com` — never `*`.
Methods are restricted to `POST` and `GET` regardless.

### WEB_CONCURRENCY

Only the container reads this; it is substituted into the uvicorn command. Two
workers absorb concurrent uploads without a large pool's memory cost. Raising it
raises peak memory roughly linearly, and the 512 MB container limit is sized for
two.

## Compose variables

Read by the compose files, not by the application.

| Variable           | Used in                                                       | Purpose                                                       |
| ------------------ | ------------------------------------------------------------- | ------------------------------------------------------------- |
| `METADATA_DOMAIN`  | [docker-compose.yml](../../docker-compose.yml)                 | The Traefik router host rule                                   |
| `METADATA_API_KEY` | [docker-compose.traefik.yml](../../docker-compose.traefik.yml) | Maps to the container's `API_KEY` when pasted into a shared stack |

The two files name the key differently because the second is meant to be pasted
into a compose file that already has an `API_KEY` for something else.

## A .env for the standalone stack

```bash
# Required
API_KEY=<openssl rand -hex 32>

# Required when the Traefik router is enabled
METADATA_DOMAIN=metadata.example.com

# Optional, shown with their defaults
MAX_UPLOAD_BYTES=26214400
WEB_CONCURRENCY=2
ALLOWED_ORIGINS=
```

`.env` and `.env.*` are excluded by [.gitignore](../../.gitignore) and by
[.dockerignore](../../.dockerignore), so they can reach neither the repository
nor an image layer.

## Caller-side variables

Not read by this service — these belong to whatever calls it. From the
[Next.js example](../../nextjs-example/app/api/thumbnail-check/route.ts):

| Variable               | Example                                       | Notes                                                    |
| ---------------------- | --------------------------------------------- | -------------------------------------------------------- |
| `METADATA_SERVICE_URL` | `http://metadata-validator:8000`              | Internal Docker name when both run on the same VPS        |
| `METADATA_API_KEY`     | the same value as the service's `API_KEY`      | Server-side only. Never a `NEXT_PUBLIC_*` variable        |

Reaching the service internally is preferable to going out through Traefik and
back: no TLS handshake, no rate limiter, no public exposure.

## Values that must match

| These must be equal                                       | Symptom when they are not                                    |
| --------------------------------------------------------- | ------------------------------------------------------------- |
| Service `API_KEY` and every caller's key                  | Every call returns `401 invalid api key`                       |
| `MAX_UPLOAD_BYTES` and Traefik `maxRequestBodyBytes`      | Callers get an opaque proxy error instead of a clear `413`     |
| `METADATA_DOMAIN` and the DNS record                      | Traefik has no route; requests fall through to another service |

## References

- [Deployment](README.md)
- [Security](../architecture/SECURITY.md)
- [Traefik](TRAEFIK.md)
- [Docker](DOCKER.md)
- [Endpoint reference](../reference/ENDPOINTS.md)
- [Next.js integration](../integrations/NEXTJS.md)
