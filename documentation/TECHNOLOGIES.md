# Technology map

This document lists what the project depends on, the standard that governs each
one here, and the official documentation to consult. Treat
[requirements.txt](../requirements.txt) and the
[Dockerfile](../Dockerfile) as authoritative when they disagree with this page.

The baseline is CPython 3.14 in the image (3.10+ locally), Pillow 11, FastAPI
0.115, uvicorn 0.32, and Docker on a Traefik-fronted VPS.

## Runtime

| Technology         | Standard in this repository                       | Official documentation                                              |
| ------------------ | -------------------------------------------------- | -------------------------------------------------------------------- |
| CPython 3.10+      | [Installation](INSTALL.md)                         | [Python](https://docs.python.org/3/)                                 |
| CPython 3.14       | [Docker](deployment/DOCKER.md)                     | [What's new in 3.14](https://docs.python.org/3/whatsnew/3.14.html)   |
| Pillow 11          | [Detection](architecture/DETECTION.md)             | [Pillow](https://pillow.readthedocs.io/en/stable/)                   |

Pillow is used in exactly two places: the EXIF tag table
(`Image.getexif`, `PIL.ExifTags.TAGS`) and the CLI's lossy strip fallback for
containers the byte-surgery paths cannot rebuild. Everything else — container
parsing, scanning, JPEG/PNG/WebP stripping — is standard library:
`struct`, `zlib`, `re`, `io`, `datetime`, `pathlib`, `shutil`.

## HTTP service

| Technology         | Standard in this repository                       | Official documentation                                              |
| ------------------ | -------------------------------------------------- | -------------------------------------------------------------------- |
| FastAPI 0.115      | [Endpoints](reference/ENDPOINTS.md)                | [FastAPI](https://fastapi.tiangolo.com/)                             |
| uvicorn 0.32       | [Docker](deployment/DOCKER.md)                     | [uvicorn](https://www.uvicorn.org/)                                  |
| python-multipart   | [Endpoints](reference/ENDPOINTS.md)                | [python-multipart](https://github.com/Kludex/python-multipart)       |
| Starlette CORS     | [Security](architecture/SECURITY.md)               | [Starlette middleware](https://www.starlette.io/middleware/)         |

`python-multipart` is not optional despite never being imported by name: FastAPI
requires it to parse `multipart/form-data`, which is every POST route here.

## Deployment

| Technology         | Standard in this repository                       | Official documentation                                              |
| ------------------ | -------------------------------------------------- | -------------------------------------------------------------------- |
| Docker             | [Docker](deployment/DOCKER.md)                     | [Docker](https://docs.docker.com/)                                   |
| Docker Compose     | [Deployment](deployment/README.md)                 | [Compose](https://docs.docker.com/compose/)                          |
| GitHub Actions     | [CI](deployment/CI.md)                             | [Actions](https://docs.github.com/en/actions)                        |
| GHCR               | [CI](deployment/CI.md)                             | [Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry) |
| Traefik            | [Traefik](deployment/TRAEFIK.md)                   | [Traefik](https://doc.traefik.io/traefik/)                           |
| Watchtower         | [Deployment](deployment/README.md)                 | [Watchtower](https://containrrr.dev/watchtower/)                     |
| CrowdSec           | [Security](architecture/SECURITY.md)               | [CrowdSec](https://docs.crowdsec.net/)                               |

Traefik, Watchtower and CrowdSec belong to the shared VPS stack. This project
joins `project-network` and inherits them; it does not own or configure them
beyond its own labels.

## Formats and specifications

The specifications the parsers and signature tables implement against. These are
the real dependencies of the detection logic.

| Specification               | Where it is used                                          | Reference                                                                       |
| --------------------------- | ---------------------------------------------------------- | -------------------------------------------------------------------------------- |
| C2PA / Content Credentials  | Hard signatures, `APP11`, `uuid` boxes                     | [C2PA](https://c2pa.org/specifications/specifications/2.1/index.html)            |
| IPTC digitalSourceType      | Hard signatures and benign signals                          | [IPTC vocabulary](https://cv.iptc.org/newscodes/digitalsourcetype/)              |
| XMP                         | `APP1`, PNG `iTXt`, WebP `XMP `, ISOBMFF `uuid`            | [XMP](https://developer.adobe.com/xmp/docs/)                                     |
| EXIF                        | The tag table                                               | [CIPA DC-008](https://www.cipa.jp/std/documents/e/DC-008-Translation-2019-E.pdf) |
| JPEG / JFIF                 | `parse_jpeg`, `strip_jpeg`                                  | [JFIF](https://www.w3.org/Graphics/JPEG/jfif3.pdf)                               |
| PNG                         | `parse_png`, `strip_png`                                    | [PNG](https://www.w3.org/TR/png-3/)                                              |
| WebP / RIFF                 | `parse_webp`, `strip_webp`                                  | [WebP container](https://developers.google.com/speed/webp/docs/riff_container)   |
| ISO base media (MP4/MOV)    | `parse_mp4`, `read_video_summary`                           | [ISO/IEC 14496-12](https://en.wikipedia.org/wiki/ISO_base_media_file_format)     |
| JUMBF                       | C2PA container detection                                    | [ISO/IEC 19566-5](https://www.iso.org/standard/73604.html)                       |

## Platform behaviour this tracks

Why the hard signatures are what they are:

| Platform  | Behaviour                                                   | Reference                                                                     |
| --------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------ |
| YouTube   | Reads C2PA and IPTC to auto-apply the synthetic-content label | [Altered or synthetic content](https://support.google.com/youtube/answer/14328491) |
| Instagram | "AI info" label driven by industry metadata standards          | [Meta AI labelling](https://about.fb.com/news/2024/02/labeling-ai-generated-images-on-facebook-instagram-and-threads/) |
| TikTok    | Reads Content Credentials                                      | [TikTok and C2PA](https://newsroom.tiktok.com/en-us/partnering-with-our-industry-to-advance-ai-transparency-and-literacy) |
| LinkedIn  | Displays C2PA Content Credentials                              | [C2PA adopters](https://c2pa.org/)                                             |

These behaviours change. When one does, the change lands in
[architecture/DETECTION.md](architecture/DETECTION.md) and the tables in
[reference/SIGNATURES.md](reference/SIGNATURES.md).

## What is deliberately absent

| Not used         | Why                                                                              |
| ---------------- | --------------------------------------------------------------------------------- |
| ExifTool         | A Perl runtime dependency for something a few hundred lines of stdlib does here    |
| A C2PA SDK       | Presence of the manifest is the signal; validating a signature is not the question |
| A database       | The service is stateless by design — see [Security](architecture/SECURITY.md)      |
| A test framework | None yet. See [Testing](standards/TESTING.md) and the [Roadmap](ROADMAP.md)        |
| A packaging setup| Two scripts run directly; there is nothing to install                              |

## References

- [Installation](INSTALL.md)
- [Getting started](GETTING-STARTED.md)
- [Architecture](architecture/README.md)
- [Deployment](deployment/README.md)
- [Signature reference](reference/SIGNATURES.md)
