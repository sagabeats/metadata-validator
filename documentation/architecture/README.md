# Architecture decisions and boundaries

This folder records how the metadata validator is built: the pipeline a file
travels through, how a verdict is decided, how each container format is taken
apart, how metadata is removed without touching pixels, and the security model
of the HTTP service.

Contribution rules live in [standards/](../standards/). Exhaustive contract
facts — routes, flags, signature tables — live in [reference/](../reference/).

## Core architecture

- [Overview](OVERVIEW.md) — the pipeline, the two processes, and what each layer owns.
- [Detection](DETECTION.md) — hard versus soft signatures, benign signals, deduplication, and the verdict rule.
- [Containers](CONTAINERS.md) — how JPEG, PNG, WebP and ISO base media files are reduced to metadata regions.
- [Stripping](STRIPPING.md) — byte surgery per format, what is deliberately kept, and the verify-after-strip rule.
- [Security](SECURITY.md) — the threat model, bearer auth, resource limits, and vulnerability reporting.

## Decisions that constrain everything else

Four decisions shape the rest of the system. Each is enforced in one place, and
each fails quietly when violated.

| Decision                                                | Enforced in                                            | Consequence if violated                                              |
| ------------------------------------------------------- | ------------------------------------------------------ | -------------------------------------------------------------------- |
| All logic lives in `ai_metadata_check.py`; transports are thin | [OVERVIEW.md](OVERVIEW.md)                       | The CLI and the service start disagreeing about the same file        |
| Only `hard` findings set `ai_detected`                  | [DETECTION.md](DETECTION.md)                           | Every Photoshop export reads as AI-generated and callers stop trusting the verdict |
| A strip is re-analysed before it is called a success    | [STRIPPING.md](STRIPPING.md)                           | A file is shipped as clean while a marker survives                    |
| The service holds no state and writes no files          | [SECURITY.md](SECURITY.md)                             | Uploads accumulate on a host that was never meant to store them       |

## Why this exists at all

YouTube, Instagram, TikTok and LinkedIn apply their "Altered or synthetic
content" label by reading file metadata, not by looking at the image. Two
metadata families drive it: C2PA Content Credentials, and the IPTC
`digitalSourceType` field.

The practical consequence is counterintuitive. A thumbnail can be entirely
hand-made and still get labelled, because a tool somewhere in the chain —
Photoshop Generative Fill, Canva Magic Media, an AI upscaler, a background
remover — stamped the file on export. This project exists to answer "will this
upload be labelled?" before the upload happens, and to remove the cause when
the answer is yes.

That framing is why the tool never inspects pixels. It reads exactly what the
platforms read, and nothing else.

## Historical context

Some shapes in the code exist for reasons the current code does not show:

- **ISO base media parsing was added after MP4 files fell through to the
  unknown-container branch.** Before that, a video report was a `strings` dump
  of the whole file: box names as noise, an empty EXIF table, one undifferentiated
  block. The box walker in [CONTAINERS.md](CONTAINERS.md) replaced it.
- **There is no bare `digitalSourceType` pattern.** The field is also used to
  declare `digitalCapture` — a real photograph — which is the opposite of a hit.
  Only the AI-valued variants count, and the camera-valued ones are reported as
  reassurance.
- **The Canva `ContainsAiGeneratedContent` pair is judged by value, not by
  name.** Canva writes it as `Yes` or `No`, so a name match alone would flag
  every Canva export. A lookbehind keeps the generic "AI generated" soft pattern
  off that namespace.
- **`/check/batch` came later than `/check`.** Batch entries carry their own
  `ok` and `error` fields precisely because a single bad file must not fail the
  other nineteen.

None of these are patterns to copy. Each is recorded in the document that owns
the subject.

## References

- [Documentation index](../README.md)
- [Reference](../reference/README.md)
- [Deployment](../deployment/README.md)
- [Integrations](../integrations/README.md)
- [Standards](../standards/README.md)
- [Technology map](../TECHNOLOGIES.md)
