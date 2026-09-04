# Integrations

This service is a leaf. It calls nothing — no database, no queue, no third-party
API — so this folder documents callers, not dependencies.

## Contents

- [Next.js](NEXTJS.md) — the reference route handler, and why the service stays server-side.

## What calls this service

| Caller                       | Transport                          | Failure mode                                                    |
| ---------------------------- | ---------------------------------- | ---------------------------------------------------------------- |
| A Next.js route handler      | HTTP, server-side                  | Return `502` and let the upload proceed, or block — your choice  |
| The CLI                      | Direct import, same process        | Non-zero exit code                                               |
| A Python service             | Direct import                      | `ValueError` on unreadable bytes                                 |
| `curl`, scripts, cron        | HTTP                               | Status code                                                      |

## What this service depends on

Nothing at runtime beyond its own process. That is worth stating explicitly,
because it determines the failure model: this service cannot fail *because
something else did*. If it is down, it is down for its own reasons — the image,
the host, or a resource limit.

| Dependency        | When                          | Notes                                                          |
| ----------------- | ----------------------------- | -------------------------------------------------------------- |
| Pillow            | EXIF table, CLI strip fallback | Optional. Detection is unaffected by its absence               |
| Traefik           | Only when exposed publicly     | Owned by the shared VPS stack, not by this project             |
| Watchtower        | Only in the deployed stack     | Update mechanism, not a runtime dependency                     |
| GHCR              | Build and pull                 | Not touched at runtime                                         |

## Rules for a caller

Whatever the transport, four rules hold:

1. **Branch on `ai_detected`, not on the verdict string.** The string is for
   humans. `ai_detected` is true only for a `hard` finding — the case where a
   platform will actually apply a label. See
   [architecture/DETECTION.md](../architecture/DETECTION.md).
2. **Keep the API key server-side.** A browser that can call the service directly
   is a browser that has the key. Proxy through your own origin instead — which
   also removes CORS from the picture entirely.
3. **Set a timeout, and treat the service being down as a `502`.** It is not a
   dependency worth failing an upload over unless your product says it is.
4. **Check `verified` before using a cleaned file.** `/clean/json` returns
   `verified: false` rather than raising when a marker survives.

## Choosing an endpoint

| Situation                                            | Endpoint                                       |
| ---------------------------------------------------- | ---------------------------------------------- |
| One file, verdict only                                | `POST /check` with `include_content=false`     |
| One file, and you want to show the evidence           | `POST /check` with `include_content=true`      |
| Several files at once                                 | `POST /check/batch` — one unit against the rate limit |
| Strip and stream the file straight back to the browser| `POST /clean`                                  |
| Strip, and want the verdict and file in one response  | `POST /clean/json`                             |

Full contract: [reference/ENDPOINTS.md](../reference/ENDPOINTS.md).

## References

- [Next.js](NEXTJS.md)
- [Endpoint reference](../reference/ENDPOINTS.md)
- [Detection](../architecture/DETECTION.md)
- [Security](../architecture/SECURITY.md)
- [Environment](../deployment/ENVIRONMENT.md)
