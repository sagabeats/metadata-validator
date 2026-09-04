# Changelog

**Applies to:** Everyone tracking what shipped and when
**Related documents:** [Roadmap](ROADMAP.md) · [Contributing](standards/CONTRIBUTING.md) · [Deployment](deployment/README.md)

Every commit on `main`, grouped by date, newest first. Work not yet done is in
[ROADMAP.md](ROADMAP.md).

## Releases are dated, not numbered

There are no release tags. `main` deploys directly to production through CI and
Watchtower, so one working day is one release.

The container image carries `:prod` and `:<sha>` tags, and the SHA tag is what a
rollback pins to — see [deployment/RUNBOOK.md](deployment/RUNBOOK.md). The
service reports its own version at `/health`, currently `1.0.0`, set in
[server.py](../server.py).

To adopt numbered releases, begin tagging:

```bash
git tag v1.1.0
git push --tags
```

## Categories

Derived from the Conventional Commits prefix, which is why the commit convention
in [standards/CONTRIBUTING.md](standards/CONTRIBUTING.md) matters.

| Prefix     | Category                |
| ---------- | ----------------------- |
| `feat`     | Features                |
| `fix`      | Fixes                   |
| `docs`     | Documentation           |
| `refactor` | Refactoring             |
| `ci`       | Continuous integration  |
| none       | Other                   |

---

## Unreleased

### Documentation

- Added the [documentation/](README.md) hub: architecture, reference, deployment,
  integrations and standards, plus a rewritten root README.

---

## 2026-08-24

### Features

- **Enhanced AI metadata detection for video formats, and improved tag
  reporting** (`2937f1b`).

  Added an ISO base media parser covering MP4, MOV, M4A, M4V, 3GP, HEIC and
  AVIF. Before this, an MP4 fell through to the unknown-container branch and the
  report was a `strings` dump of the whole file: one undifferentiated block, box
  names such as `stco` and `stsz` as noise, and an empty EXIF table.

  The parser walks the box tree and reports per box, the way the JPEG parser
  reports per APP segment. Sample and timing tables are skipped; `uuid` boxes are
  resolved against four known UUIDs, including the C2PA/JUMBF and XMP extension
  boxes where video markers actually live.

  `read_video_summary()` gives ISOBMFF files the equivalent of the EXIF table:
  brand, creation and modification dates, duration, codecs, handler, and the
  iTunes and QuickTime tag atoms. `read_tag_summary()` dispatches between it and
  the EXIF path, so callers see one shape either way.

  Signature tables gained video generators and tools — Veo, Sora, Pika, Hailuo,
  Vidu, Haiper, avatar and voice tools, video enhancers, and the open-source
  video models.

  Video is check-only. Stripping it is on the [roadmap](ROADMAP.md).

---

## 2026-08-17

The initial build. Everything below shipped on one day.

### Features

- **Image AI-metadata checker with C2PA and IPTC detection** (`b926d62`).

  The engine: signature tables, JPEG, PNG and WebP container parsers, region
  scanning, the three-verdict model, byte-surgery stripping that never
  recompresses, the EXIF summary, the metadata dump, and the CLI with its four
  exit codes.

- **HTTP service exposing check and clean endpoints** (`f2b00fa`).

  [server.py](../server.py): `/health`, `/check`, `/clean` and `/clean/json`,
  with optional bearer authentication, an upload size ceiling, and verdicts
  carried in response headers on the binary clean route.

- **Next.js route handler for calling the service** (`0f38ebf`).

  [nextjs-example/](../nextjs-example/): a reference server-side proxy that keeps
  the API key out of the browser, avoids CORS entirely, and reshapes the verdict
  into `safeToUpload` / `willBeLabeled` / `reasons` / `traces`.

- **Docker image and Traefik deployment compose** (`acdcfd9`).

  A single-stage image on `python:3.14-slim` running unprivileged, with an
  interpreter-based healthcheck because the slim image has no `curl`. Plus a
  compose service block for pasting into an existing VPS stack.

- **Docker Compose configuration for VPS deployment with Traefik integration**
  (`08ccd65`).

  A standalone stack joining the shared `project-network`: TLS through the
  existing resolver, a dedicated 30/min rate limiter sized for uploads rather
  than page views, and a request body cap — Traefik streams bodies with no size
  limit by default, which would let a large upload commit memory before the
  application could refuse it.

  `API_KEY` is declared with `:?` so the stack refuses to start
  unauthenticated. This variant is internet-reachable.

- **Batch image analysis endpoint** (`8bfd9db`).

  `POST /check/batch`, up to `MAX_BATCH_FILES` (default 20) images per request.
  Each entry carries its own `ok` and `error`, so one bad image never sinks the
  batch, and results are matched back by `index` rather than filename. `analyze()`
  runs on a threadpool so a large batch cannot stall `/health`.

### Continuous integration

- **Publish the container image to GHCR on push to main** (`af41204`).

  Builds and pushes `:prod` and `:<sha>`, with the GitHub Actions cache backend.
  Smoke-tests the pushed image: it must become healthy, `/health` must report
  `ok`, and an unauthenticated `POST /check` must return `401`.

  Watchtower on the VPS polls every 30 seconds and rolling-restarts once a new
  `:prod` digest appears — the same flow as `crm-api` and `crm-web`.

## References

- [Roadmap](ROADMAP.md)
- [Deployment](deployment/README.md)
- [Runbook](deployment/RUNBOOK.md)
- [Contributing](standards/CONTRIBUTING.md)
- [Conventional Commits](https://www.conventionalcommits.org/)
