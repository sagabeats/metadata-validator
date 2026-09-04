# Endpoint reference

**Applies to:** Anyone calling the HTTP service
**Related documents:** [Overview](../architecture/OVERVIEW.md) · [Security](../architecture/SECURITY.md) · [Next.js integration](../integrations/NEXTJS.md) · [Python API](PYTHON-API.md)

Every route on [server.py](../../server.py). All POST bodies are
`multipart/form-data`.

Interactive documentation is served by FastAPI at `/docs` and `/redoc` when the
service is running.

## Routes

| Method | Path            | Auth | Body                                    | Returns                          |
| ------ | --------------- | ---- | --------------------------------------- | -------------------------------- |
| GET    | `/health`       | No   | —                                       | Liveness and configuration       |
| POST   | `/check`        | Yes  | `file`, `include_content`               | Verdict, findings, metadata dump |
| POST   | `/check/batch`  | Yes  | `files` (repeated), `include_content`   | One entry per file               |
| POST   | `/clean`        | Yes  | `file`, `keep_icc`                      | The stripped image bytes         |
| POST   | `/clean/json`   | Yes  | `file`, `keep_icc`                      | Verdicts plus base64 image       |

## Authentication

When `API_KEY` is set in the service environment, every route except `/health`
requires:

```http
Authorization: Bearer <API_KEY>
```

When `API_KEY` is unset the service is open. See
[architecture/SECURITY.md](../architecture/SECURITY.md).

| Status | Detail                 | Cause                                            |
| ------ | ---------------------- | ------------------------------------------------ |
| `401`  | `missing bearer token` | No header, or it does not start with `Bearer `   |
| `401`  | `invalid api key`      | The token does not match                          |

---

## GET /health

No authentication. Used by the Docker healthcheck, Traefik, and CI.

```bash
curl -s localhost:8000/health
```

```json
{
  "ok": true,
  "service": "ai-metadata-checker",
  "version": "1.0.0",
  "auth_required": true,
  "max_upload_bytes": 26214400
}
```

`auth_required` reflects whether `API_KEY` is set — useful for confirming a
deployment is not accidentally open without having to trigger a 401.

---

## POST /check

Analyse one image or video.

| Field             | Type    | Default | Meaning                                                     |
| ----------------- | ------- | ------- | ----------------------------------------------------------- |
| `file`            | file    | —       | Required                                                    |
| `include_content` | boolean | `true`  | Include the decoded text of each metadata block in the dump |

```bash
curl -s -X POST https://metadata.example.com/check \
  -H "Authorization: Bearer $API_KEY" \
  -F file=@thumb.jpg \
  -F include_content=false
```

### Response

```json
{
  "file": "thumb.jpg",
  "format": "JPEG",
  "bytes": 421890,
  "verdict": "AI METADATA DETECTED",
  "ai_detected": true,
  "suspicious": false,
  "clean": false,
  "exit_code": 1,
  "findings": [
    {
      "severity": "hard",
      "label": "C2PA assertion store",
      "location": "APP11 (JUMBF/C2PA)",
      "excerpt": "...c2pa.assertions...jumbf...",
      "matched": "c2pa.assertions"
    }
  ],
  "benign_signals": [],
  "exif": { "Software": "Adobe Photoshop 26.0" },
  "metadata_blocks": [
    {
      "name": "APP1 (EXIF/XMP)",
      "bytes": 4096,
      "flagged": false,
      "content": "<x:xmpmeta ...>"
    }
  ]
}
```

| Field             | Notes                                                                                        |
| ----------------- | -------------------------------------------------------------------------------------------- |
| `verdict`         | `CLEAN`, `SUSPICIOUS`, or `AI METADATA DETECTED`                                              |
| `ai_detected`     | True only when a `hard` finding exists. **This is the field to branch on**                     |
| `suspicious`      | True when findings exist but none is `hard`                                                    |
| `clean`           | True when there are no findings at all                                                         |
| `exit_code`       | `0` clean, `1` AI detected, `2` suspicious — mirrors the CLI                                   |
| `findings[]`      | See [Detection](../architecture/DETECTION.md) for what `severity` means                        |
| `benign_signals`  | Metadata declaring camera capture. Context only; never changes the verdict                     |
| `exif`            | Full tag table. Container tags for MP4/MOV, EXIF for stills. May be `{}` without Pillow        |
| `metadata_blocks` | Every region found. `flagged` marks the ones that produced a finding                           |
| `content`         | Present only when `include_content` is true. Binary blocks are rendered as printable runs      |

Set `include_content=false` when you only need the verdict. A C2PA manifest is
tens of kilobytes of certificate text and dominates the response otherwise.

### Errors

| Status | Cause                                                    |
| ------ | -------------------------------------------------------- |
| `400`  | Empty file, or `analyze()` raised `ValueError`           |
| `401`  | Missing or wrong bearer token                            |
| `413`  | Body exceeds `MAX_UPLOAD_BYTES`                          |

---

## POST /check/batch

Analyse up to `MAX_BATCH_FILES` (default 20) images in one request.

| Field             | Type          | Default | Meaning                          |
| ----------------- | ------------- | ------- | -------------------------------- |
| `files`           | file, repeated | —      | Required, at least one           |
| `include_content` | boolean       | `true`  | As for `/check`                  |

```bash
curl -s -X POST https://metadata.example.com/check/batch \
  -H "Authorization: Bearer $API_KEY" \
  -F files=@a.jpg -F files=@b.png -F files=@c.webp \
  -F include_content=false
```

### Response

```json
{
  "count": 3,
  "ok_count": 2,
  "results": [
    { "index": 0, "filename": "a.jpg", "ok": true, "result": { "...": "as /check" } },
    { "index": 1, "filename": "b.png", "ok": false, "error": "empty file" },
    { "index": 2, "filename": "c.webp", "ok": true, "result": { "...": "as /check" } }
  ]
}
```

**One bad file never sinks the batch.** Each entry carries its own `ok` and
either `result` or `error`, and the response is `200` as long as the request
itself was well-formed. Check `ok` per entry; do not infer success from the
status code.

**Match results back by `index`, not by `filename`.** The index mirrors the order
the files were sent in. Filenames are not unique enough to key on, and a caller
uploading two files both named `thumbnail.png` would otherwise mis-attribute a
verdict.

`analyze()` runs on a threadpool here, so a large batch does not block `/health`
or concurrent requests.

### Errors

| Status | Cause                                     |
| ------ | ----------------------------------------- |
| `400`  | `no files`                                |
| `401`  | Missing or wrong bearer token             |
| `413`  | More than `MAX_BATCH_FILES` files         |

A per-file `413` or `400` becomes an `error` string on that entry, not a request
failure.

---

## POST /clean

Strip metadata and return the cleaned image itself.

| Field      | Type    | Default | Meaning                                              |
| ---------- | ------- | ------- | ---------------------------------------------------- |
| `file`     | file    | —       | Required. JPEG, PNG or WebP                          |
| `keep_icc` | boolean | `true`  | Keep the ICC colour profile. Removing it shifts colours |

```bash
curl -s -X POST https://metadata.example.com/clean \
  -H "Authorization: Bearer $API_KEY" \
  -F file=@thumb.jpg \
  -o thumb.clean.jpg -D headers.txt
```

### Response

The image bytes, with `Content-Type` set from the detected format
(`image/jpeg`, `image/png`, `image/webp`, else `application/octet-stream`).

Verdicts ride along in headers so the caller learns what was removed without a
second request:

| Header                | Example                              |
| --------------------- | ------------------------------------ |
| `X-Verdict-Before`    | `AI METADATA DETECTED`               |
| `X-Verdict-After`     | `CLEAN`                              |
| `X-Bytes-Removed`     | `84213`                              |
| `X-Findings`          | `3`                                  |
| `Content-Disposition` | `inline; filename="thumb.clean.jpg"` |

The returned filename inserts `.clean` before the extension:
`thumb.jpg` → `thumb.clean.jpg`, and a name without an extension becomes
`thumb.clean`.

### Errors

| Status | Cause                                                                              |
| ------ | ---------------------------------------------------------------------------------- |
| `400`  | Empty file                                                                         |
| `401`  | Missing or wrong bearer token                                                      |
| `413`  | Body exceeds `MAX_UPLOAD_BYTES`                                                    |
| `415`  | Not JPEG, PNG or WebP. Video can be checked but not stripped                       |
| `500`  | `strip did not remove every marker` — the output failed re-verification            |

A `500` here is not a transport failure. It means the strip ran and a marker
survived, and the service refused to return a file it could not vouch for.
Report the sample; see [architecture/STRIPPING.md](../architecture/STRIPPING.md).

---

## POST /clean/json

The same operation as `/clean`, returning JSON with the image base64-encoded.

```json
{
  "filename": "thumb.clean.jpg",
  "verified": true,
  "bytes_removed": 84213,
  "before": { "...": "an analyze() result, include_content=false" },
  "after":  { "...": "an analyze() result, include_content=false" },
  "image_base64": "/9j/4AAQSkZJRgABAQ...",
  "mime": "image/jpeg"
}
```

Easier to consume from a route handler that wants the verdict and the file in
one response; costs about 33% more bytes on the wire than `/clean`.

Unlike `/clean`, this route returns `verified: false` rather than raising when a
marker survives. **Check `verified` before using `image_base64`.**

Errors are as `/clean`, minus the `500`.

## Status code summary

| Status | Meaning across the API                                       |
| ------ | ------------------------------------------------------------ |
| `200`  | Request handled. For `/check/batch`, check per-entry `ok`     |
| `400`  | Empty file, no files, or unreadable bytes                     |
| `401`  | Missing or invalid bearer token                               |
| `413`  | File too large, or too many files in a batch                  |
| `415`  | Container cannot be stripped in memory                        |
| `422`  | FastAPI validation — a required form field is missing         |
| `500`  | Strip verification failed                                     |

## References

- [Overview](../architecture/OVERVIEW.md)
- [Detection](../architecture/DETECTION.md)
- [Stripping](../architecture/STRIPPING.md)
- [Security](../architecture/SECURITY.md)
- [Environment](../deployment/ENVIRONMENT.md)
- [Next.js integration](../integrations/NEXTJS.md)
- [Python API](PYTHON-API.md)
