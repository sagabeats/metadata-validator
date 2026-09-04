# Continuous integration

**Applies to:** Anyone changing the workflow or diagnosing a failed publish
**Related documents:** [Docker](DOCKER.md) · [Deployment](README.md) · [Testing](../standards/TESTING.md)

There is one workflow: [.github/workflows/publish.yml](../../.github/workflows/publish.yml).
It builds the image, pushes it to GHCR, and smoke-tests what it pushed.

## Trigger

```yaml
on:
  push:
    branches: [main]
  workflow_dispatch:
```

Merges to `main` publish. `workflow_dispatch` allows a manual re-run — useful
after a transient registry failure, since the build is deterministic.

There is no pull-request job. Nothing runs before a merge, so **a broken change
is caught after it is published, not before**. See
[standards/TESTING.md](../standards/TESTING.md) for what that means for review.

## Tags

```yaml
env:
  IMAGE: ghcr.io/${{ github.repository_owner }}/metadata-validator
```

Every run pushes two tags:

| Tag              | Purpose                                                     |
| ---------------- | ----------------------------------------------------------- |
| `:prod`          | What Watchtower tracks. Moving it triggers the deployment   |
| `:<github.sha>`  | Immutable. This is what a rollback pins to                  |

The SHA tag is not decoration. It is the only way to return to a specific
previous build once `:prod` has moved — see [RUNBOOK.md](RUNBOOK.md).

## Steps

| Step                        | Action                          | Notes                                                     |
| --------------------------- | ------------------------------- | --------------------------------------------------------- |
| Checkout                    | `actions/checkout@v4`           | —                                                         |
| Buildx                      | `docker/setup-buildx-action@v3` | Needed for the GitHub Actions cache backend                |
| Registry login              | `docker/login-action@v3`        | `ghcr.io`, using the job's `GITHUB_TOKEN`                  |
| Build and push              | `docker/build-push-action@v6`   | Both tags, `cache-from`/`cache-to: type=gha, mode=max`     |
| Smoke test                  | Inline shell                    | Runs the pushed `:<sha>` image                             |

Permissions are minimal: `contents: read`, `packages: write`. No personal access
token is involved — the job's own `GITHUB_TOKEN` is scoped to the push.

`mode=max` caches every layer rather than only the final one, which matters
because the dependency layer is the expensive one to rebuild.

## The smoke test

The only automated verification in the project, and it runs against the image
that was actually pushed:

```bash
docker run -d --name smoke -p 8000:8000 -e API_KEY=ci-test $IMAGE:$SHA

for i in $(seq 1 30); do
  curl -sf localhost:8000/health >/dev/null && break || sleep 2
done

curl -sf localhost:8000/health | grep -q '"ok":true'
test "$(curl -s -o /dev/null -w '%{http_code}' -X POST localhost:8000/check)" = "401"

docker rm -f smoke
```

Three properties are asserted:

1. **The image starts and becomes healthy** within 60 seconds. This catches a
   missing dependency, an import error, or a bad `CMD` — the failures that would
   otherwise surface as a crash-loop on the VPS.
2. **`/health` reports `ok`.** Confirms the ASGI app is actually serving, not
   just that the process is alive.
3. **An unauthenticated `POST /check` returns `401`.** With `API_KEY` set in the
   environment, auth must reject. This is the one guard against a change that
   accidentally makes the service open.

What it does **not** verify: any detection behaviour. No sample image is scanned,
no verdict is asserted, and no strip is checked. A change to a signature table or
a container parser passes CI regardless of whether it is correct. Verify those by
hand — [standards/TESTING.md](../standards/TESTING.md).

## After a successful publish

Nothing in CI touches the VPS. Watchtower polls every 30 seconds, sees the new
`:prod` digest, and rolling-restarts the container. Deployment is a pull, not a
push, which is why the workflow needs no SSH key and no host credentials.

Expect roughly a minute between a green workflow and a running new version.

## Failure modes

| Symptom                                        | Cause and recovery                                                                      |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `denied: permission_denied` on push            | The `packages: write` permission was removed from the job                                 |
| Smoke test times out at `/health`              | The container starts but does not serve. Check the workflow logs for an import traceback  |
| Smoke test fails the `401` assertion           | Auth was broken by a change. Look at `require_key()` — the `Header()` annotation is load-bearing |
| Build is slow on every run                     | The GHA cache was evicted, or `cache-to` was changed. It is a cache, not a correctness issue |
| Workflow green but the VPS still runs old code | Watchtower is not running, or the container lacks `com.centurylinklabs.watchtower.enable=true` |

## References

- [Docker](DOCKER.md)
- [Deployment](README.md)
- [Runbook](RUNBOOK.md)
- [Testing](../standards/TESTING.md)
- [docker/build-push-action](https://github.com/docker/build-push-action)
- [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
