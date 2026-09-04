# Contributing

**Applies to:** Anyone opening a pull request
**Related documents:** [Testing](TESTING.md) · [Detection](../architecture/DETECTION.md) · [Containers](../architecture/CONTAINERS.md) · [CI](../deployment/CI.md)

## Workflow

```bash
git checkout -b feat/short-description
# change, verify by hand
git commit -m "feat: add Ideogram signature"
git push -u origin feat/short-description
```

Merging to `main` publishes to production. CI builds `:prod`, and Watchtower
deploys it within a minute — see [deployment/CI.md](../deployment/CI.md). There
is no pull-request job, so **review is the only gate**.

## Commits

Conventional Commits, matching the existing history:

```text
feat: add batch image analysis endpoint to HTTP service
ci: publish container image to ghcr on push to main
```

Prefixes in use: `feat`, `fix`, `ci`, `docs`, `refactor`.

## What a pull request must contain

Because nothing is verified automatically beyond startup and auth, the
description carries the verification:

- **What changed and why.**
- **What you tested it against.** Name the files — "a Canva export with Magic
  Media", "a 4K MP4 from a Pixel", "a camera JPEG with full IPTC". Sample files
  are not in the repository, so the description is the record.
- **Both sides of a detection change.** A new signature needs a file that now
  matches *and* a file that must not.
- **The verdict before and after**, for anything touching detection.

See [TESTING.md](TESTING.md) for the specific checks per change type.

## Adding a signature

The most common contribution, and the easiest to get wrong.

### 1. Choose the table

One question decides it: **does a platform read this field and act on it?**

| Answer                                        | Table                  | Effect                       |
| --------------------------------------------- | ---------------------- | ---------------------------- |
| Yes — it is a formal declaration              | `HARD_SIGNATURES`      | `AI METADATA DETECTED`       |
| No, but only an AI tool would write it        | `SOFT_SIGNATURES`      | `SUSPICIOUS`                 |
| It declares the file is *not* AI              | `BENIGN_SOURCE_TYPES`  | Context only                 |

When unsure, use `soft`. A false `hard` is far more damaging: it tells a user
their upload will be labelled when it will not, and users who are told that once
too often stop reading the verdict at all.

### 2. Write the pattern

```python
(rb"Ideogram", "Ideogram"),
```

- Byte strings, not text. Regions are raw bytes.
- Case-sensitive by default. Add `(?i)` only when the tool genuinely varies its
  casing — a blanket `(?i)` widens false positives.
- **Check the negative form.** A field that declares AI often also declares its
  absence. Canva writes `ContainsAiGeneratedContent` as `Yes` *or* `No`; IPTC's
  `digitalSourceType` declares `digitalCapture` for real photographs. Matching
  the field name alone flags everything. That mistake has been made once already
  — the `(?<!contains)` lookbehind on the generic pattern is the scar.
- Keep it anchored enough not to hit ordinary prose. `Krea` is fine; a two-letter
  vendor name would not be.
- The label is what a user reads. Say what it means, not just what matched.

### 3. Verify

```bash
python ai_metadata_check.py sample-that-should-match.png -v
python ai_metadata_check.py sample-that-must-not-match.jpg -v
```

`-v` prints the matched text, so you can confirm the pattern hit what you meant
rather than something incidental. Then update
[reference/SIGNATURES.md](../reference/SIGNATURES.md) in the same pull request.

## Adding a container format

1. Write `parse_<fmt>(raw) -> list[Region]`, emitting metadata blocks only —
   never pixel or sample data. Region names become finding locations, so make
   them something a human can act on.
2. Add the magic-byte test to `extract_regions()`, above the unknown-container
   fallback.
3. Optionally add `strip_<fmt>(raw, keep_icc) -> bytes` and wire it into
   `strip_bytes()`. **Only if the container can be rebuilt without recompressing.**
   Check-only is a supported state — video is check-only today.
4. Extend `read_tag_summary()` if the format carries a tag table worth showing.
5. Add the extension to the CLI's directory-recursion set if it is a still image.
6. Update [architecture/CONTAINERS.md](../architecture/CONTAINERS.md) and
   [reference/CLI.md](../reference/CLI.md).

Parsers must **stop, not raise**, on malformed structure. Truncated files are
normal here — a browser upload preview sends `ftyp` + `moov` and none of the
frames — and half a tree is still a useful report.

## Changing the HTTP service

- Keep detection logic out of `server.py`. It calls `analyze()`, `clean()` and
  `strip_bytes()`; anything else belongs in the module. Two implementations means
  the CLI and the service will eventually disagree about a file.
- New routes need the `Auth` dependency unless there is a stated reason, as with
  `/health`.
- Do not simplify `Annotated[str | None, Header()]` in `require_key()`. Without
  the `Header()` marker FastAPI reads `authorization` as a query parameter and
  every request fails auth.
- Anything CPU-bound in an async route goes through `run_in_threadpool`.
- Update [reference/ENDPOINTS.md](../reference/ENDPOINTS.md) in the same pull
  request.

## Changing a strip path

The highest-risk change in the codebase, because a defect ships a file the user
believes is clean.

- Never decode and re-encode pixels in `strip_bytes()`. The compressed data is
  copied verbatim; that is the guarantee.
- Repair any structural field the removal invalidated — the `VP8X` flag byte is
  the existing example.
- Verify with a real file, and confirm the output still opens correctly in an
  image viewer, not just that the checker reports it clean.
- Never report success without re-analysing. `clean()` returns `verified`, and it
  is the contract.

## Documentation

Documentation lives in [documentation/](../). Update it in the same pull request
as the behaviour it describes — a reference page that lags the source is worse
than no page, because it is trusted.

| You changed                | Also update                                                              |
| -------------------------- | ------------------------------------------------------------------------ |
| A signature table          | [reference/SIGNATURES.md](../reference/SIGNATURES.md)                    |
| A route or response field  | [reference/ENDPOINTS.md](../reference/ENDPOINTS.md)                      |
| A CLI flag or exit code    | [reference/CLI.md](../reference/CLI.md)                                  |
| A public function          | [reference/PYTHON-API.md](../reference/PYTHON-API.md)                    |
| An environment variable    | [deployment/ENVIRONMENT.md](../deployment/ENVIRONMENT.md)                |
| A container parser         | [architecture/CONTAINERS.md](../architecture/CONTAINERS.md)              |
| A strip path               | [architecture/STRIPPING.md](../architecture/STRIPPING.md)                |
| Anything user-visible      | [CHANGELOG.md](../CHANGELOG.md)                                          |

## References

- [Testing](TESTING.md)
- [Detection](../architecture/DETECTION.md)
- [Containers](../architecture/CONTAINERS.md)
- [Stripping](../architecture/STRIPPING.md)
- [CI](../deployment/CI.md)
- [Conventional Commits](https://www.conventionalcommits.org/)
