# Deployment

This folder covers how the service is built, shipped and operated. Pick a target
below, then follow the release sequence.

## Contents

- [Docker](DOCKER.md) — how the image is built and why it is a single stage.
- [CI](CI.md) — the publish workflow and its smoke test.
- [Environment](ENVIRONMENT.md) — every variable, its default, and what it protects.
- [Traefik](TRAEFIK.md) — routing, TLS, the dedicated rate limiter, and the body cap.
- [Runbook](RUNBOOK.md) — verification, rollback, diagnosis, and known pitfalls.

## Choose a target

| Target                                     | When                                                             | Start here                                             |
| ------------------------------------------ | ---------------------------------------------------------------- | ------------------------------------------------------ |
| Local process                              | Development, or a one-off batch                                   | [Getting started](../GETTING-STARTED.md)               |
| Container, internal only                   | Your caller runs on the same VPS. **The default, and the safest** | [docker-compose.traefik.yml](../../docker-compose.traefik.yml) |
| Container, public through Traefik          | The caller lives elsewhere — Vercel, another host, a webhook      | [docker-compose.yml](../../docker-compose.yml) · [Traefik](TRAEFIK.md) |

Prefer internal-only whenever the caller is on the same VPS. It reaches the
service at `http://metadata-validator:8000` on `project-network`: nothing to
expose, nothing to rate-limit, no certificate to manage.

## The two compose files

Their names are the wrong way round, so read this before you copy one:

| File                                                            | What it actually is                                                            |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| [docker-compose.yml](../../docker-compose.yml)                   | A standalone stack that joins the existing `project-network`, **with Traefik routing active**. Public |
| [docker-compose.traefik.yml](../../docker-compose.traefik.yml)   | A service block to paste into an existing VPS compose file, **with the Traefik labels commented out**. Internal by default |

Both pull `ghcr.io/sagabeats/metadata-validator:prod`, both use `expose` rather
than `ports`, both carry the Watchtower label, and both cap memory at 512 MB.

## The release sequence

Deployment is image-swap only. There is no migration, no build step on the host,
and no state to preserve.

1. Merge to `main`.
2. CI builds and pushes `:prod` and `:<sha>` to GHCR, then smoke-tests the
   `:<sha>` image. See [CI.md](CI.md).
3. Watchtower on the VPS polls every 30 seconds, sees the new `:prod` digest, and
   rolling-restarts the container — the same flow as `crm-api` and `crm-web`.
4. Verify with `/health` and one real upload. See [RUNBOOK.md](RUNBOOK.md).

**Editing a compose file or a `.env` on the VPS and merging it changes nothing
by itself.** Watchtower swaps images and nothing else. A configuration change
needs `docker compose up -d` on the host.

## First deployment

```bash
# On the VPS, beside the compose file
printf 'API_KEY=%s\n' "$(openssl rand -hex 32)" >> .env
printf 'METADATA_DOMAIN=metadata.example.com\n' >> .env

docker compose up -d
curl -s https://metadata.example.com/health
```

`API_KEY` is declared with `:?` in [docker-compose.yml](../../docker-compose.yml),
so the stack refuses to start without it. That is intentional — this variant is
reachable from the internet.

If you are exposing it publicly, the DNS record must be **DNS only** in
Cloudflare, not proxied. [TRAEFIK.md](TRAEFIK.md) explains why, and what breaks
when it is orange-clouded.

## Operational profile

| Property           | Value                                                     |
| ------------------ | --------------------------------------------------------- |
| Image              | `ghcr.io/sagabeats/metadata-validator:prod`               |
| Port               | `8000`, exposed to the Docker network only                |
| Workers            | 2 uvicorn workers, `WEB_CONCURRENCY`                      |
| Memory limit       | 512 MB                                                     |
| Healthcheck        | `GET /health` every 30s, 15s start period, 3 retries      |
| Persistent state   | None. No volumes, no database, no disk writes             |
| Restart policy     | `always`                                                   |
| Updates            | Watchtower, on the `:prod` tag                            |

Because there is no state, recovery is always the same action: restart the
container, or roll the image tag back to a known `:<sha>`.

## References

- [Documentation index](../README.md)
- [Architecture overview](../architecture/OVERVIEW.md)
- [Security](../architecture/SECURITY.md)
- [Installation](../INSTALL.md)
- [Watchtower](https://containrrr.dev/watchtower/)
