# CLI reference

**Applies to:** Anyone running the checker from a terminal or a script
**Related documents:** [Getting started](../GETTING-STARTED.md) · [Stripping](../architecture/STRIPPING.md) · [Detection](../architecture/DETECTION.md)

```text
python ai_metadata_check.py PATH [PATH ...] [options]
```

Source: [ai_metadata_check.py](../../ai_metadata_check.py).

## Arguments

`PATH` may be a file, a directory, or a glob. It is repeatable.

- **A directory** is walked recursively, keeping files whose extension is one of
  `.jpg .jpeg .png .webp .gif .tif .tiff .avif .heic`. Video extensions are not
  in that set — pass video files explicitly.
- **A glob** is expanded by the CLI itself when the shell did not, because
  cmd.exe and PowerShell do not expand wildcards for a program. Quote the pattern
  on Windows: `"*.png"`.
- A path that matches nothing prints `not found: <spec>` to stderr and is
  skipped. If nothing at all resolves, the run exits `3`.

## Options

| Flag                | Effect                                                                          |
| ------------------- | ------------------------------------------------------------------------------- |
| `--strip`           | Write a metadata-free copy. JPEG, PNG and WebP are not recompressed              |
| `--inplace`         | With `--strip`, overwrite the original. A `.bak` is kept                         |
| `--strip-icc`       | Also drop the ICC colour profile. May shift colours                              |
| `-v`, `--verbose`   | Show the matched text for each finding, and every metadata block                 |
| `--full`            | Print flagged metadata in full, with no truncation                               |
| `--dump-limit N`    | Characters printed per flagged block. Default `4000`                             |
| `--flagged-only`    | Print only the metadata blocks that tripped a signature                          |
| `--no-dump`         | Do not print metadata contents at all                                            |
| `-q`, `--quiet`     | Skip the EXIF / container tag table                                              |
| `--json`            | Machine-readable output instead of the report                                    |
| `--no-color`        | Disable ANSI colour. Colour is off automatically when stdout is not a TTY        |

## Exit codes

| Code | Verdict                | Meaning                                                       |
| ---- | ---------------------- | ------------------------------------------------------------- |
| `0`  | `CLEAN`                | No signature matched                                          |
| `1`  | `AI METADATA DETECTED` | At least one `hard` finding. Platforms will label this upload  |
| `2`  | `SUSPICIOUS`           | Only `soft` findings — an AI tool left traces                  |
| `3`  | error                  | Unreadable file, empty file, no targets, or a failed strip     |

Over several files, the **worst** code is returned. Worst is not numerically
largest: the codes are named, not ordered, so `EXIT_RANK` defines the real
ordering — `0 < 2 < 1 < 3` — and `worse()` compares through it. A run that finds
one AI file among fifty clean ones exits `1`.

With `--strip`, the exit code is recomputed from the stripped output: `0` if the
copy verified clean, `1` if a marker survived.

## The report

```text
thumb.jpg  (JPEG, 412 KB)
  [X] AI METADATA DETECTED

  !! C2PA assertion store
       in APP11 (JUMBF/C2PA)
   ~ Photoshop Generative Fill / Expand
       in APP1 (EXIF/XMP)

  ok digitalSourceType = digitalCapture (declared camera original)

  EXIF:
    Software             Adobe Photoshop 26.0
    DateTimeOriginal     2026:07:14 09:22:31

  ...metadata blocks...

  -> Platforms read this. Run again with --strip before uploading.
```

| Element         | Meaning                                                           |
| --------------- | ----------------------------------------------------------------- |
| `[OK]` green    | `CLEAN`                                                           |
| `[!]` yellow    | `SUSPICIOUS`                                                      |
| `[X]` red       | `AI METADATA DETECTED`                                            |
| `!!` red        | A `hard` finding                                                  |
| `~` yellow      | A `soft` finding                                                  |
| `ok` green      | A benign signal — context only, it does not change the verdict     |
| `EXIF:`         | The tag table. Reads `container tags:` for MP4, MOV, HEIC, AVIF   |

The metadata dump is printed **whatever the verdict**. On a hit it is the
evidence; on a clean file it is the proof that there is nothing to find. Suppress
it with `--no-dump`, or narrow it with `--flagged-only`.

## JSON output

`--json` prints exactly the dictionary `analyze()` returns — the same shape the
`/check` endpoint serves, documented in [ENDPOINTS.md](ENDPOINTS.md) and
[PYTHON-API.md](PYTHON-API.md).

`--no-dump` sets `include_content=false`, dropping the `content` field from each
metadata block.

With `--json`, the per-file trailer and the "checked N files" summary are not
printed, but each file still emits its own JSON object. Piping several files into
a single JSON parser will not work — process one file per invocation when you
need one document.

## Recipes

```bash
# One file, quick verdict
python ai_metadata_check.py thumb.jpg

# A whole folder of thumbnails, verdicts only
python ai_metadata_check.py ./thumbnails --no-dump -q

# Why was this flagged? Show matched text and every block, untruncated
python ai_metadata_check.py thumb.jpg -v --full

# Only the blocks that tripped a signature
python ai_metadata_check.py thumb.jpg --flagged-only

# Clean copy alongside the original
python ai_metadata_check.py thumb.jpg --strip

# Clean in place, keeping thumb.jpg.bak
python ai_metadata_check.py thumb.jpg --strip --inplace

# Machine-readable, into jq
python ai_metadata_check.py thumb.jpg --json --no-dump

# Gate an upload in a shell script
python ai_metadata_check.py thumb.jpg --no-dump -q || echo "do not upload"
```

## Windows notes

- Quote globs: `python ai_metadata_check.py "*.png"`.
- stdout is reconfigured with `errors="replace"` at startup, because metadata is
  arbitrary text — BOMs, CJK, emoji — and the console is cp1252. Unencodable
  characters degrade instead of crashing the run.
- Colour is enabled only when stdout is a TTY, so redirecting to a file produces
  clean text without `--no-color`.

## References

- [Getting started](../GETTING-STARTED.md)
- [Detection](../architecture/DETECTION.md)
- [Stripping](../architecture/STRIPPING.md)
- [Endpoint reference](ENDPOINTS.md)
- [Python API](PYTHON-API.md)
- [Signature reference](SIGNATURES.md)
