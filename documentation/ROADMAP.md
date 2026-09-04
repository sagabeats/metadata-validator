# Roadmap

Planned and in-progress work, ordered by how much it would change what the tool
can do. Shipped work is in [CHANGELOG.md](CHANGELOG.md).

Nothing here is scheduled. This is a record of known gaps and their reasoning,
so a contributor can pick one up with the context already written down.

## In progress

Nothing currently in progress.

## Planned

### Video stripping

**Status:** not started · **Blocks:** `/clean` on MP4, MOV, HEIC, AVIF

Video can be checked but not stripped. `strip_bytes()` raises `ValueError` and
the service returns `415`.

The obstacle is structural. Removing a box from an ISO base media file shifts
every subsequent byte, and `stco` / `co64` hold absolute file offsets into
`mdat`. A correct strip has to rewrite those offset tables — and `co64` when the
shift crosses the 32-bit boundary in either direction.

Scope: drop `udta`, `meta` and known metadata `uuid` boxes from `moov`, then fix
up every affected offset table. Verify by playing the result, not only by
re-scanning it.

See [architecture/STRIPPING.md](architecture/STRIPPING.md).

### A test suite

**Status:** not started · **Blocks:** any pull-request gate

There is no automated verification of detection, parsing or stripping. CI checks
that the image starts and that auth rejects, and nothing else — a change that
inverts a signature severity or corrupts a strip path publishes green.

Scope: `pytest`, with fixtures **generated at test time** rather than committed.
A minimal JPEG carrying a synthetic `APP11` segment containing `c2pa.assertions`
tests the same path as a real Content Credentials file, without the licensing and
size cost of committing one. Cover the strip paths first — they are the highest
risk, because a defect ships a file the user believes is clean — then the
container parsers, including truncated and malformed input.

Then add a pull-request job so something gates a merge.

See [standards/TESTING.md](standards/TESTING.md).

### GIF and TIFF support

**Status:** not started

Both are accepted by the CLI's directory recursion but fall through to the
unknown-container branch: the whole file becomes one region. The verdict is still
correct, but the location is useless and neither can be stripped without the
lossy Pillow fallback.

Scope: `parse_gif` for the comment and application extension blocks;
`parse_tiff` for the IFD chain, which also unlocks DNG and CR2. Both are
straightforward compared with ISOBMFF.

### AVIF and HEIC metadata items

**Status:** partial

Both parse as ISO base media, so `uuid` boxes and the container tag table already
work. What is missing is the `iinf` / `iloc` item structure that HEIF uses to
store EXIF and XMP as *items* rather than boxes — `iloc` is currently in the skip
set, so an EXIF item's payload is not resolved to a named region.

### Signature table maintenance

**Status:** ongoing

The tables are a denylist, and new generators appear constantly. Additions are
small, self-contained, and the easiest way into this codebase — see
[standards/CONTRIBUTING.md](standards/CONTRIBUTING.md).

Currently absent and worth adding as they stabilise: newer video model
identifiers, region-specific tools, and whatever replaces the current generation
of upscalers.

## Considered and rejected

| Idea                                  | Why not                                                                                     |
| ------------------------------------- | -------------------------------------------------------------------------------------------- |
| Pixel-based AI detection               | A different problem with a different failure model. This tool answers "will a platform label this?", and platforms read metadata |
| Validating C2PA signatures             | Presence of the manifest is the signal. Validity does not change whether a platform labels the upload |
| Bundling ExifTool                      | A Perl runtime dependency for something a few hundred lines of stdlib already does            |
| Persisting scan results                | Statelessness is what makes the deployment trivial. A caller that needs history should keep it |
| Selective metadata editing             | Everything-or-nothing keeps the verify-after-strip guarantee simple and total                 |
| A browser-callable API with CORS       | It would put the API key in shipped JavaScript. Proxy server-side instead                     |

## Contributing to any of this

Pick an item, read the linked architecture document first, and follow
[standards/CONTRIBUTING.md](standards/CONTRIBUTING.md). Signature additions are
the smallest useful contribution; video stripping is the largest.

## References

- [Changelog](CHANGELOG.md)
- [Stripping](architecture/STRIPPING.md)
- [Containers](architecture/CONTAINERS.md)
- [Testing](standards/TESTING.md)
- [Contributing](standards/CONTRIBUTING.md)
