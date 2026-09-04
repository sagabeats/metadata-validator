# Python API

**Applies to:** Anyone importing the checker rather than shelling out to it
**Related documents:** [Overview](../architecture/OVERVIEW.md) · [Endpoint reference](ENDPOINTS.md) · [Containers](../architecture/CONTAINERS.md)

[ai_metadata_check.py](../../ai_metadata_check.py) is importable as a module.
`server.py` uses nothing else, so this is the same surface the HTTP service is
built on.

```python
import ai_metadata_check as checker
```

There is no package install. Put the file on the import path — same directory,
or `sys.path` — as the Dockerfile does.

## The three functions you need

### `analyze(raw, filename="image", include_content=True) -> dict`

Inspect bytes and return the verdict structure.

```python
raw = open("thumb.jpg", "rb").read()
result = checker.analyze(raw, "thumb.jpg", include_content=False)

if result["ai_detected"]:
    print("will be labelled:", result["verdict"])
```

| Parameter         | Meaning                                                                 |
| ----------------- | ----------------------------------------------------------------------- |
| `raw`             | The file bytes. Raises `ValueError("empty file")` on empty input        |
| `filename`        | Used for the `file` field and to guess a format for unknown containers  |
| `include_content` | Include decoded text for each metadata block. Set false for verdicts only |

Returns the dictionary documented in [ENDPOINTS.md](ENDPOINTS.md#post-check):
`file`, `format`, `bytes`, `verdict`, `ai_detected`, `suspicious`, `clean`,
`exit_code`, `findings`, `benign_signals`, `exif`, `metadata_blocks`.

Branch on `ai_detected`, not on the `verdict` string.

### `strip_bytes(raw, keep_icc=True) -> bytes`

Return the image with every metadata block removed, in memory.

```python
try:
    cleaned = checker.strip_bytes(raw, keep_icc=True)
except ValueError:
    ...  # not JPEG, PNG or WebP
```

JPEG, PNG and WebP are rebuilt by copying the compressed image data verbatim, so
the pixels are untouched. Every other container raises `ValueError` — the caller
decides whether to fall back to a lossy re-save. See
[architecture/STRIPPING.md](../architecture/STRIPPING.md).

### `clean(raw, filename="image", keep_icc=True) -> dict`

Strip, then verify, reporting both sides.

```python
result = checker.clean(raw, "thumb.jpg")

if not result["verified"]:
    raise RuntimeError("a marker survived the strip")

open("thumb.clean.jpg", "wb").write(result["data"])
```

| Key             | Type    | Meaning                                                        |
| --------------- | ------- | -------------------------------------------------------------- |
| `before`        | `dict`  | `analyze()` of the input, `include_content=False`              |
| `after`         | `dict`  | `analyze()` of the output, `include_content=False`             |
| `data`          | `bytes` | The stripped image                                             |
| `bytes_removed` | `int`   | Size difference                                                |
| `verified`      | `bool`  | `after["clean"]` — **check this before using `data`**           |

`verified` is the contract. `clean()` does not raise when a marker survives; it
tells you, and leaves the decision with you. The HTTP layer turns a false into a
`500`.

## Lower-level functions

Useful when you want part of the pipeline rather than a verdict.

| Function                                       | Returns                        | Use for                                            |
| ---------------------------------------------- | ------------------------------ | -------------------------------------------------- |
| `extract_regions(raw, path) -> (list, str)`    | Regions and the format name    | Inspecting metadata blocks yourself                |
| `scan_regions(regions) -> list[Finding]`       | Findings                       | Running the tables over regions you built           |
| `scan_benign(regions) -> list[str]`            | Benign signal labels           | Camera-origin evidence                              |
| `verdict_for(findings) -> (str, int)`          | Verdict and exit code          | Re-deriving a verdict from filtered findings        |
| `read_tag_summary(raw, every_tag=False)`       | `list[tuple[str, str]]`        | EXIF for stills, container tags for ISOBMFF         |
| `read_exif_summary(src, every_tag=False)`      | `list[tuple[str, str]]`        | Stills only. Accepts a `Path` or bytes              |
| `read_video_summary(raw)`                      | `list[tuple[str, str]]`        | ISOBMFF only                                        |
| `readable_text(data) -> (str, bool)`           | Text and a was-binary flag     | Rendering a block for human eyes                    |
| `is_isobmff(raw) -> bool`                      | —                              | Detecting MP4/MOV/HEIC/AVIF before dispatching      |
| `worse(a, b) -> int`                           | The worse of two exit codes    | Aggregating results across files                    |

`Region` has `name`, `data` and `offset`. `Finding` has `severity`, `label`,
`where`, `excerpt` and `matched` — note `where`, which becomes `location` in the
serialised form.

`read_exif_summary()` accepts bytes as well as a path, which is what lets the
HTTP service produce an EXIF table without spilling an upload to disk.

## Signature tables

`HARD_SIGNATURES`, `SOFT_SIGNATURES` and `BENIGN_SOURCE_TYPES` are module-level
lists of `(bytes pattern, label)` tuples. They can be extended at runtime:

```python
checker.SOFT_SIGNATURES.append((rb"MyInternalTool", "Internal render farm"))
```

Prefer a pull request over a runtime patch — a local table means your verdicts
stop matching the service's. See
[standards/CONTRIBUTING.md](../standards/CONTRIBUTING.md).

## Threading and performance

`analyze()` is synchronous and CPU-bound. It holds the whole file in memory and
runs both signature tables across every region.

In an async application, dispatch it to a worker thread — which is exactly what
`/check/batch` does:

```python
from fastapi.concurrency import run_in_threadpool

result = await run_in_threadpool(
    checker.analyze, raw, name, include_content=False
)
```

Nothing in the module holds state between calls, so concurrent use from multiple
threads is safe as long as you do not mutate the signature tables while a scan is
running.

## A complete example

```python
from pathlib import Path
import ai_metadata_check as checker

def prepare_for_upload(path: Path) -> Path:
    """Return a path safe to upload, stripping only when necessary."""
    raw = path.read_bytes()
    verdict = checker.analyze(raw, path.name, include_content=False)

    if verdict["clean"]:
        return path

    for finding in verdict["findings"]:
        print(f"  [{finding['severity']}] {finding['label']} in {finding['location']}")

    result = checker.clean(raw, path.name)
    if not result["verified"]:
        raise RuntimeError(f"{path.name}: strip did not remove every marker")

    out = path.with_suffix(f".clean{path.suffix}")
    out.write_bytes(result["data"])
    print(f"  wrote {out.name}, {result['bytes_removed']:,} bytes removed")
    return out
```

## References

- [Overview](../architecture/OVERVIEW.md)
- [Detection](../architecture/DETECTION.md)
- [Containers](../architecture/CONTAINERS.md)
- [Stripping](../architecture/STRIPPING.md)
- [Endpoint reference](ENDPOINTS.md)
- [CLI reference](CLI.md)
