# Traefik

**Applies to:** Anyone exposing the service publicly, or debugging a certificate
**Related documents:** [Deployment](README.md) · [Environment](ENVIRONMENT.md) · [Security](../architecture/SECURITY.md) · [Runbook](RUNBOOK.md)

Traefik is only involved when the service must be reachable from outside the
VPS. When the caller runs on the same host, skip this document entirely and use
the internal name — see [README.md](README.md).

Configuration lives in the labels on
[docker-compose.yml](../../docker-compose.yml). This project does not own the
Traefik instance; it joins the `project-network` that Traefik, `crm-api` and
`crm-web` already share, declared `external: true`.

## Routing

```yaml
- "traefik.enable=true"
- "traefik.http.routers.metadata.rule=Host(`${METADATA_DOMAIN}`)"
- "traefik.http.routers.metadata.entrypoints=websecure"
- "traefik.http.routers.metadata.tls.certresolver=myresolver"
- "traefik.http.services.metadata.loadbalancer.server.port=8000"
```

Only the `websecure` entrypoint. There is no HTTP router, so there is no
plaintext path to the service at all.

The container uses `expose`, not `ports`. Traefik reaches port 8000 over
`project-network`; the host's public interface never binds it.

## Middleware chain

```yaml
- "traefik.http.routers.metadata.middlewares=crowdsec@docker,metadatalimit@docker,metadatabody@docker"
```

Applied in order:

| Middleware      | Scope         | Purpose                                              |
| --------------- | ------------- | ---------------------------------------------------- |
| `crowdsec`      | Shared        | Blocks addresses already banned across the VPS       |
| `metadatalimit` | This service  | Rate limit, sized for uploads                        |
| `metadatabody`  | This service  | Request body cap                                     |

### Rate limit

```yaml
- "traefik.http.middlewares.metadatalimit.ratelimit.average=30"
- "traefik.http.middlewares.metadatalimit.ratelimit.period=1m"
- "traefik.http.middlewares.metadatalimit.ratelimit.burst=10"
```

30 requests per minute with a burst of 10, per source address.

This service gets its own limiter rather than reusing the 100/min `ratelimit`
defined on `crm-web`. Uploads are far heavier than page views: each one holds a
file in memory and runs two signature tables across it. A limit tuned for page
views would let a handful of clients saturate the CPU budget.

A caller that legitimately checks many files should use `/check/batch` — twenty
images in one request costs one unit against the limiter, not twenty.

### Body cap

```yaml
- "traefik.http.middlewares.metadatabody.buffering.maxRequestBodyBytes=26214400"
- "traefik.http.middlewares.metadatabody.buffering.memRequestBodyBytes=2097152"
```

Traefik streams request bodies with **no size cap by default**. Without this
middleware a large upload commits memory before the application's own
`MAX_UPLOAD_BYTES` check can refuse it — the check runs after the body has been
read.

`maxRequestBodyBytes` (25 MiB) must track `MAX_UPLOAD_BYTES`.
`memRequestBodyBytes` (2 MiB) is the point at which Traefik spills to a temporary
file rather than holding the body in RAM.

## TLS and DNS

Certificates are issued by the shared `myresolver` ACME resolver using the
**TLS-ALPN-01** challenge.

That choice constrains DNS. The record must be:

```text
metadata  CNAME  example.com
```

and it must stay **DNS only** — the grey cloud in Cloudflare, not the orange one.

A proxied record terminates TLS at Cloudflare, so the TLS-ALPN-01 challenge never
reaches Traefik and issuance fails. This matches how `www` and `support` are
already configured on the same apex.

**Orange-clouding the apex breaks every subdomain CNAMEd to it at once**, not
just this one. If several services lose their certificates simultaneously, check
the apex record first.

## Verifying

```bash
curl -s https://metadata.example.com/health

# Certificate chain and expiry
echo | openssl s_client -connect metadata.example.com:443 -servername metadata.example.com 2>/dev/null \
  | openssl x509 -noout -issuer -dates

# The rate limiter is live: the 31st request in a minute returns 429
for i in $(seq 1 35); do
  curl -s -o /dev/null -w "%{http_code} " https://metadata.example.com/health
done
```

## Failure modes

| Symptom                                  | Cause and recovery                                                                              |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `404` from Traefik                       | The router did not match. Check `METADATA_DOMAIN` against the DNS record and the container labels |
| Certificate never issues                 | The DNS record is proxied. Set it to DNS only, then restart Traefik to retry ACME                 |
| `413` before the request reaches the app | The Traefik body cap is lower than `MAX_UPLOAD_BYTES`. Raise both together                         |
| `429` on normal use                      | 30/min exceeded. Batch the calls, or raise `ratelimit.average`                                     |
| Connection refused from another container| Wrong network. The caller must be on `project-network`                                             |
| Certificates lost across several services| The apex was orange-clouded. Every CNAME to it is affected                                         |

## Disabling public access

The safer configuration. In
[docker-compose.traefik.yml](../../docker-compose.traefik.yml) the Traefik labels
are commented out by default: the service stays off the internet and callers on
the same VPS reach it at `http://metadata-validator:8000`.

Nothing to expose, nothing to rate-limit, no certificate to manage. Enable the
router only when a caller genuinely lives elsewhere.

## References

- [Deployment](README.md)
- [Environment](ENVIRONMENT.md)
- [Security](../architecture/SECURITY.md)
- [Runbook](RUNBOOK.md)
- [Traefik routers](https://doc.traefik.io/traefik/routing/routers/)
- [Traefik rate limit](https://doc.traefik.io/traefik/middlewares/http/ratelimit/)
- [Traefik buffering](https://doc.traefik.io/traefik/middlewares/http/buffering/)
