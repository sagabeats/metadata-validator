# System overview

**Applies to:** Anyone changing the checker, the service, or a caller
**Related documents:** [Detection](DETECTION.md) · [Containers](CONTAINERS.md) · [Stripping](STRIPPING.md) · [Endpoint reference](../reference/ENDPOINTS.md)

## Shape of the system

Two files, one of which is optional:

| File                                            | Lines | Responsibility                                                            |
| ----------------------------------------------- | ----- | ------------------------------------------------------------------------- |
| [ai_metadata_check.py](../../ai_metadata_check.py) | ~1330 | Signature tables, container parsers, scanning, verdicts, stripping, CLI |
| [server.py](../../server.py)                    | ~230  | HTTP transport: auth, size limits, threadpool dispatch, response shaping   |

`server.py` imports `ai_metadata_check` and calls three functions from it:
`analyze()`, `clean()` and, indirectly, `strip_bytes()`. It contains no
detection logic of its own. That is the single most important structural fact
about this project: **the CLI and the service cannot produce different verdicts
for the same bytes**, because they run the same function.

## The pipeline

Every path — CLI, HTTP, direct Python import — runs the same five steps.

```text
raw bytes
   |
   |  extract_regions(raw, path)          architecture/CONTAINERS.md
   v
list[Region]        one entry per metadata block; pixel data is never included
   |
   |  scan_regions(regions)               architecture/DETECTION.md
   v
list[Finding]       severity, label, location, matched text, excerpt
   |
   |  verdict_for(findings)
   v
("CLEAN" | "SUSPICIOUS" | "AI METADATA DETECTED", exit_code)
   |
   |  strip_bytes(raw, keep_icc)          architecture/STRIPPING.md   [optional]
   v
rebuilt bytes  ->  analyze() again  ->  verified: bool
```

### 1. Extract regions

`extract_regions()` sniffs the container by magic bytes and dispatches to a
parser. Each parser returns a list of `Region` objects — a name, the bytes, and
the byte offset where it was found.

Regions are only metadata. `IDAT`, `mdat` and JPEG scan data are never included.
That is what makes the scan fast and the report readable: a signature match is
reported against `APP11 (JUMBF/C2PA)` or `moov/udta/meta/ilst box`, not against
"somewhere in a 40 MB file".

An unrecognised container is not an error. It becomes a single region covering
the whole file, and the scan proceeds — degraded but correct.

### 2. Scan

`scan_regions()` runs two ordered tables of compiled byte patterns over every
region: `HARD_SIGNATURES` first, then `SOFT_SIGNATURES`. Matches are deduplicated
by `(label, region name)`, so one C2PA manifest spanning several APP11 segments
produces one finding per segment, not one per occurrence.

Each region is searched twice when it looks like UTF-16 — once as-is, once with
NUL bytes removed — because XMP packets are commonly written UTF-16 and the
patterns are ASCII.

### 3. Judge

`verdict_for()` is three lines and deliberately blunt:

- any `hard` finding → `AI METADATA DETECTED`, exit `1`
- any finding at all → `SUSPICIOUS`, exit `2`
- otherwise → `CLEAN`, exit `0`

`scan_benign()` runs alongside and collects positive signals — metadata that
declares the file as camera-captured. Benign signals never change the verdict.
They are context for a human, not an input to the decision.

### 4. Summarise tags

`read_tag_summary()` produces the table printed under the verdict. It has two
implementations behind one shape:

- stills → `read_exif_summary()`, via Pillow's `getexif()`
- ISO base media → `read_video_summary()`, by walking `ftyp`, `mvhd`, `hdlr`,
  `stsd`, `keys`, `ilst`, `udta` and known `uuid` boxes

Both return `list[tuple[str, str]]`, so the reporting code does not branch.

### 5. Strip, then verify

Stripping rebuilds the container with the metadata blocks omitted. It never
decodes or re-encodes pixels for JPEG, PNG and WebP.

The result is always re-analysed. `clean()` returns `verified=False` if any
marker survived; the `/clean` endpoint turns that into a `500` rather than
returning a file it cannot vouch for. See [STRIPPING.md](STRIPPING.md).

## The two processes

### CLI

`main()` expands the arguments — files, directories, or globs the shell did not
expand — into a target list, then runs `process()` per file and reports the
worst outcome.

"Worst" is not `max()`. Exit codes are named, not ordered (`1` is worse than
`2`), so `EXIT_RANK` maps them onto a real ordering and `worse()` compares
through it.

Directory recursion only walks image extensions: `.jpg .jpeg .png .webp .gif
.tif .tiff .avif .heic`. Video files must be passed as explicit paths. Full flag
list: [reference/CLI.md](../reference/CLI.md).

### HTTP service

`server.py` is a FastAPI application with five routes. Its responsibilities, in
order:

1. **Auth.** `require_key()` is a dependency on every route except `/health`.
   Unset `API_KEY` means open. Comparison is `secrets.compare_digest`, so the key
   cannot be recovered by timing.
2. **Size.** `read_upload()` reads the body into memory and rejects anything
   over `MAX_UPLOAD_BYTES` with `413`. `/check/batch` additionally caps the file
   count at `MAX_BATCH_FILES`.
3. **Dispatch.** `analyze()` is synchronous and CPU-bound. In `/check/batch` it
   is pushed onto a threadpool with `run_in_threadpool`, so a 20-image batch
   cannot stall `/health` and the other routes.
4. **Shaping.** `/clean` returns the image itself with verdicts in response
   headers; `/clean/json` returns the same information with the image
   base64-encoded, costing about 33% more bytes on the wire.

Every route, field and status code: [reference/ENDPOINTS.md](../reference/ENDPOINTS.md).

## Memory profile

Each request holds one file in memory at a time. `/check/batch` processes
sequentially, so peak memory is roughly `MAX_UPLOAD_BYTES` per in-flight
request — not `MAX_UPLOAD_BYTES × MAX_BATCH_FILES`. That is why the container
runs comfortably under a 512 MB limit with two workers.

The one bound that is not the upload size: `ISOBMFF_REGION_CAP` truncates any
single ISO box carried into the report at 4 MB. A proprietary box could
otherwise be arbitrarily large.

## What this system is not

- **It is not a detector of AI imagery.** It reads declarations and tool
  fingerprints. An AI image whose metadata was already stripped reads as
  `CLEAN`, correctly — because that is also how the platform will read it.
- **It is not a forensic tool.** No pixel analysis, no watermark decoding, no
  statistical modelling. `SynthID` is matched as a metadata string, not decoded
  from pixels.
- **It is not a general metadata editor.** It removes everything or nothing
  (with ICC as the one exception). There is no selective edit path.

## References

- [Detection](DETECTION.md)
- [Containers](CONTAINERS.md)
- [Stripping](STRIPPING.md)
- [Security](SECURITY.md)
- [CLI reference](../reference/CLI.md)
- [Endpoint reference](../reference/ENDPOINTS.md)
- [Python API](../reference/PYTHON-API.md)
