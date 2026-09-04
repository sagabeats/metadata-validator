# Getting started

This guide takes you from a fresh clone to a working checker, then to a running
HTTP service. It assumes nothing but Python and, optionally, Docker.

Read [INSTALL.md](INSTALL.md) for the complete environment reference, and
[standards/CONTRIBUTING.md](standards/CONTRIBUTING.md) before you open a pull
request.

## Prerequisites

| Requirement | Version             | Notes                                                                          |
| ----------- | ------------------- | ------------------------------------------------------------------------------ |
| Python      | 3.10 or later       | The code uses PEP 604 unions and `from __future__ import annotations`; the image runs 3.14 |
| Pillow      | 11 or later         | Only for the EXIF table and the non-JPEG/PNG/WebP strip fallback               |
| Docker      | Any current release | Only if you want to run the service as a container                             |

Container parsing and stripping are pure standard library. Pillow is a
convenience, not a dependency of the detection path — the checker still returns
a correct verdict without it, it just prints no EXIF table.

## Install and run the CLI

```bash
git clone https://github.com/sagabeats/metadata-validator.git
cd metadata-validator

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt

python ai_metadata_check.py thumb.jpg
```

That is the whole installation. The checker is a single file with no package
layout and no build step.

## Read your first verdict

```text
thumb.jpg  (JPEG, 412 KB)
  [X] AI METADATA DETECTED

  !! C2PA assertion store
       in APP11 (JUMBF/C2PA)
  !! IPTC digitalSourceType = trainedAlgorithmicMedia (declares FULLY AI-generated)
       in APP1 (EXIF/XMP)

  EXIF:
    Software             Adobe Photoshop 26.0

  -> Platforms read this. Run again with --strip before uploading.
```

Three verdicts exist, and each maps onto an exit code:

| Verdict                | Exit | Meaning                                                                    |
| ---------------------- | ---- | -------------------------------------------------------------------------- |
| `CLEAN`                | `0`  | No signature matched. Nothing declares or fingerprints AI use               |
| `SUSPICIOUS`           | `2`  | Only `soft` findings. An AI tool touched the file but declared nothing      |
| `AI METADATA DETECTED` | `1`  | At least one `hard` finding. Platforms read this and will label the upload  |
| (error)                | `3`  | The file could not be read, was empty, or a strip failed                    |

That distinction is the whole point of the tool, and it is explained in
[architecture/DETECTION.md](architecture/DETECTION.md).

## Strip a file

```bash
python ai_metadata_check.py thumb.jpg --strip            # writes thumb.clean.jpg
python ai_metadata_check.py thumb.jpg --strip --inplace  # overwrites, keeps thumb.jpg.bak
```

For JPEG, PNG and WebP the compressed image data is copied verbatim, so the
pixels are bit-identical and the file is never recompressed. The ICC colour
profile is kept unless you pass `--strip-icc`. See
[architecture/STRIPPING.md](architecture/STRIPPING.md).

After writing, the checker re-scans what it wrote and prints `verified: clean`
or the number of markers that survived. Do not trust a strip that does not say
`clean`.

## Run the HTTP service

```bash
python server.py                                  # http://127.0.0.1:8000
python server.py --port 9000 --host 0.0.0.0       # bind publicly
python server.py --reload                         # restart on code changes
```

Then:

```bash
curl -s localhost:8000/health

curl -s -X POST localhost:8000/check -F file=@thumb.jpg

curl -s -X POST localhost:8000/clean -F file=@thumb.jpg -o thumb.clean.jpg -D -
```

With no `API_KEY` in the environment the service is open, which is fine on
localhost and unacceptable anywhere else. Binding beyond `127.0.0.1` without a
key prints a warning; it does not stop you. Set one:

```bash
export API_KEY=$(openssl rand -hex 32)
curl -s -X POST localhost:8000/check \
  -H "Authorization: Bearer $API_KEY" \
  -F file=@thumb.jpg
```

Every route and response shape is in
[reference/ENDPOINTS.md](reference/ENDPOINTS.md).

## Run it as a container

```bash
docker build -t metadata-validator .
docker run --rm -p 8000:8000 -e API_KEY=local-dev metadata-validator
curl -s localhost:8000/health
```

The published image is `ghcr.io/sagabeats/metadata-validator:prod`. See
[deployment/DOCKER.md](deployment/DOCKER.md).

## Verify the installation

1. `python ai_metadata_check.py <any camera photo>` prints `[OK] CLEAN`.
2. `python ai_metadata_check.py <a Canva or Photoshop export>` prints findings
   with a location such as `APP1 (EXIF/XMP)`.
3. `--strip` on that same file writes a `.clean.` copy and reports
   `verified: clean`.
4. `curl -s localhost:8000/health` returns `{"ok":true,...}`.

If step 2 produces nothing on a file you know was AI-touched, that is a genuine
gap in the signature table, not a misconfiguration. Add the pattern — see
[standards/CONTRIBUTING.md](standards/CONTRIBUTING.md).

## Common failures

| Symptom                                      | Cause and recovery                                                                            |
| -------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Every request returns `401 missing bearer token` | `API_KEY` is set in the service environment. Send `Authorization: Bearer <key>`             |
| `413 file exceeds 26,214,400 bytes`          | Raise `MAX_UPLOAD_BYTES`, and the Traefik body cap with it — the proxy rejects first           |
| `415` from `/clean` on an MP4                | In-memory stripping supports JPEG, PNG and WebP only. Video is check-only today                 |
| `500 strip did not remove every marker`      | A marker survived the rebuild. Do not ship the file; report it with the sample                  |
| No EXIF table at all                         | Pillow is not installed. Detection still works; only the table is missing                       |
| `*.png` matches nothing on Windows           | cmd.exe and PowerShell do not expand globs. The CLI expands them itself, so quote the pattern   |
| A directory scan skips your MP4s             | Directory recursion walks image extensions only. Pass video files as explicit paths              |
| Odd characters in a printed report           | Expected. stdout is reconfigured with `errors="replace"` so a cp1252 console degrades instead of crashing |

## Next steps

- Read [architecture/OVERVIEW.md](architecture/OVERVIEW.md) to see how the
  pipeline is put together.
- Read [architecture/DETECTION.md](architecture/DETECTION.md) before you trust
  or dispute a verdict.
- Read [integrations/NEXTJS.md](integrations/NEXTJS.md) if you are wiring this
  into an upload flow.

## References

- [Installation](INSTALL.md)
- [Technology map](TECHNOLOGIES.md)
- [Architecture overview](architecture/OVERVIEW.md)
- [CLI reference](reference/CLI.md)
- [Endpoint reference](reference/ENDPOINTS.md)
- [Contributing](standards/CONTRIBUTING.md)
- [C2PA specifications](https://c2pa.org/specifications/specifications/2.1/index.html)
- [IPTC digitalSourceType vocabulary](https://cv.iptc.org/newscodes/digitalsourcetype/)
