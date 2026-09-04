# Runbook

**Applies to:** Whoever is on the deployment
**Related documents:** [Deployment](README.md) · [CI](CI.md) · [Traefik](TRAEFIK.md) · [Environment](ENVIRONMENT.md)

Operating this service is unusually simple because it holds no state. There is
no database, no migration, no volume and no cache. Every recovery action is
either "restart it" or "pin an older image".

## Verify a deployment

Run these after every release. They take under a minute.

```bash
# 1. The container is up and healthy
docker compose ps
docker inspect --format '{{.State.Health.Status}}' metadata-validator

# 2. The service answers, and auth is on
curl -s https://metadata.example.com/health
# expect: {"ok":true,...,"auth_required":true,...}

# 3. An unauthenticated call is rejected
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://metadata.example.com/check
# expect: 401

# 4. A real file gets a real verdict
curl -s -X POST https://metadata.example.com/check \
  -H "Authorization: Bearer $API_KEY" \
  -F file=@sample.jpg -F include_content=false
```

`auth_required: false` in step 2 on a public deployment is an incident, not a
warning. Set `API_KEY` and restart immediately.

Step 4 is the one that matters most. Steps 1–3 pass on an image whose detection
is completely broken — CI asserts nothing about verdicts, so keep a known-bad
sample file handy and confirm it still reports `ai_detected: true`.

## Deploy

Merge to `main`. CI publishes `:prod`, Watchtower picks it up within 30 seconds
and rolling-restarts the container. Expect about a minute end to end.

To force it rather than wait:

```bash
docker compose pull
docker compose up -d
```

**A configuration change deploys nothing on its own.** Watchtower swaps images
and nothing else, so editing `docker-compose.yml` or `.env` — in the repository
or on the host — has no effect until you run `docker compose up -d` on the VPS.

## Roll back

`:prod` moves on every merge, so it cannot be used to go backwards. The SHA tags
exist for this.

```bash
# Find the previous good build
docker images ghcr.io/sagabeats/metadata-validator

# Pin it
docker compose down
docker run -d --name metadata-validator \
  --network project-network \
  -e API_KEY="$API_KEY" \
  ghcr.io/sagabeats/metadata-validator:<previous-sha>
```

Or edit the `image:` line in the compose file to the SHA tag and
`docker compose up -d`. Remember to remove the Watchtower label, or set the tag
back, otherwise the next `:prod` push will undo the pin.

There is no data to migrate back and no cache to clear. A rollback is complete
the moment the old container is healthy.

## Diagnose

```bash
docker compose logs -f --tail=100 metadata-validator
docker stats metadata-validator
docker inspect metadata-validator --format '{{json .State.Health}}'
docker exec metadata-validator env | grep -E 'API_KEY|MAX_|WEB_'   # careful, prints the key
```

`PYTHONUNBUFFERED=1` means logs appear immediately; if `docker logs` is empty,
the process is genuinely producing nothing, not buffering.

## Symptom table

| Symptom                                      | Likely cause                                              | Action                                                            |
| -------------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------ |
| Container restarts in a loop                  | `API_KEY` unset with the `:?` guard, or an import error    | `docker compose logs`; set the variable, or roll back              |
| `/health` unreachable, container healthy      | Traefik router or DNS                                       | [TRAEFIK.md](TRAEFIK.md)                                           |
| Every call `401`                              | Caller key does not match the service key                   | Compare both `.env` files; restart after changing either            |
| `413` on a file well under 25 MB              | The Traefik body cap is lower than the app limit            | Raise both together — [ENVIRONMENT.md](ENVIRONMENT.md)             |
| `429` under normal use                        | 30/min per source exceeded                                  | Use `/check/batch`, or raise `ratelimit.average`                    |
| `415` on `/clean`                             | Not JPEG, PNG or WebP. Expected for video                   | [STRIPPING.md](../architecture/STRIPPING.md)                       |
| `500 strip did not remove every marker`       | A real defect in a strip path                               | Keep the sample, open an issue, do not ship the file                |
| Memory climbing toward 512 MB                 | Concurrent large uploads, or `WEB_CONCURRENCY` raised       | Lower `MAX_UPLOAD_BYTES` or workers; the service holds no state so a restart is safe |
| OOM-killed container                          | Same, past the limit                                        | Restart; it comes back clean. Then reduce the limits above          |
| Everything green but old behaviour            | Watchtower is not running, or the label is missing          | Check `com.centurylinklabs.watchtower.enable=true`, then pull manually |
| A known AI file now reports clean             | A signature-table regression                                | Roll back to the previous SHA, then bisect the table change         |

## Known pitfalls

**Watchtower deploys images, not configuration.** The single most common
surprise. A merged compose change is not deployed.

**`:prod` is a moving tag.** `docker pull` on it after a release gives you the
new build, not the one you were testing. Pin the SHA when you need determinism.

**The apex DNS record is shared.** Orange-clouding it in Cloudflare breaks
certificate renewal for every subdomain CNAMEd to it, not just this one. If
several services lose TLS at once, check the apex first.

**CI verifies startup and auth, nothing else.** A change that inverts a signature
severity, breaks a container parser, or corrupts a strip path publishes green.
Manual verification is not optional — [standards/TESTING.md](../standards/TESTING.md).

**`/check/batch` returns 200 with failures inside it.** Monitoring that only
watches status codes will not see per-file errors. Check `ok_count` against
`count`.

## Escalation

There is no on-call rotation. The service has no dependants that block on it
beyond the callers you control, and it holds no data, so the safe default under
any uncertainty is: **stop the container**. Callers should already treat an
unreachable service as a `502` and degrade — the Next.js reference handler does
exactly that.

## References

- [Deployment](README.md)
- [CI](CI.md)
- [Traefik](TRAEFIK.md)
- [Environment](ENVIRONMENT.md)
- [Security](../architecture/SECURITY.md)
- [Testing](../standards/TESTING.md)
