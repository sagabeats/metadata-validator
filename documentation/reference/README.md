# Reference

This folder holds the exhaustive contract facts: every HTTP route, every CLI
flag, every public Python function, and every signature pattern. The reasoning
behind them lives in [architecture/](../architecture/).

When this folder and the source disagree, the source wins. Update the page in
the same pull request that changed the behaviour.

## Contents

- [Endpoints](ENDPOINTS.md) — every HTTP route, its form fields, response shape and status codes.
- [CLI](CLI.md) — every flag, exit code, and the shape of the terminal report.
- [Python API](PYTHON-API.md) — `analyze`, `clean`, `strip_bytes`, the lower-level helpers, and threading notes.
- [Signatures](SIGNATURES.md) — the complete hard, soft and benign tables, with what each pattern means.

## Which surface should you use?

| Situation                                              | Use                                          |
| ------------------------------------------------------ | -------------------------------------------- |
| Checking files by hand, or in a shell script            | [CLI](CLI.md)                                |
| An upload flow in a web application                     | [Endpoints](ENDPOINTS.md), server-side       |
| A Python service that already has the bytes in memory   | [Python API](PYTHON-API.md)                  |
| A batch job over many files at once                     | `POST /check/batch`, or the CLI over a directory |

All three run the same `analyze()`, so they cannot disagree about a file.

## The response shape, in one place

`analyze()` is the single structure this project returns. The CLI prints it with
`--json`, `/check` serves it directly, and `/check/batch` nests one per file.

| Field             | Type            | Notes                                                    |
| ----------------- | --------------- | -------------------------------------------------------- |
| `file`            | `str`           | The filename that was passed in                          |
| `format`          | `str`           | `JPEG`, `PNG`, `WebP`, `MP4`, `MOV`, `HEIC`, …           |
| `bytes`           | `int`           | Input size                                               |
| `verdict`         | `str`           | `CLEAN`, `SUSPICIOUS`, `AI METADATA DETECTED`            |
| `ai_detected`     | `bool`          | **Branch on this.** True only for a `hard` finding       |
| `suspicious`      | `bool`          | Findings exist, none `hard`                              |
| `clean`           | `bool`          | No findings at all                                       |
| `exit_code`       | `int`           | `0` / `1` / `2`, mirroring the CLI                       |
| `findings`        | `list[dict]`    | `severity`, `label`, `location`, `excerpt`, `matched`    |
| `benign_signals`  | `list[str]`     | Camera-origin evidence. Never changes the verdict        |
| `exif`            | `dict`          | Tag table; container tags for video                      |
| `metadata_blocks` | `list[dict]`    | `name`, `bytes`, `flagged`, and `content` when requested |

## References

- [Documentation index](../README.md)
- [Architecture](../architecture/README.md)
- [Deployment](../deployment/README.md)
- [Integrations](../integrations/README.md)
- [Standards](../standards/README.md)
