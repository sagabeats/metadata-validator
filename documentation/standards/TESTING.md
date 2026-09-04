# Testing

**Applies to:** Anyone changing behaviour, and anyone reviewing such a change
**Related documents:** [Contributing](CONTRIBUTING.md) · [CI](../deployment/CI.md) · [Runbook](../deployment/RUNBOOK.md)

## What is verified automatically

One thing: the CI smoke test in
[.github/workflows/publish.yml](../../.github/workflows/publish.yml), which runs
against the image it just pushed.

| Assertion                                    | Catches                                       |
| -------------------------------------------- | --------------------------------------------- |
| The container becomes healthy within 60s      | Missing dependency, import error, bad `CMD`   |
| `/health` returns `"ok":true`                 | The ASGI app is not serving                    |
| Unauthenticated `POST /check` returns `401`   | Auth broken or accidentally disabled           |

## What is not verified

Everything that makes this tool useful:

- No sample file is ever scanned.
- No verdict is asserted.
- No strip is performed or checked.
- No container parser is exercised beyond whatever `/health` touches, which is
  nothing.

**A change that inverts a signature severity, breaks the MP4 walker, or corrupts
the WebP rebuild passes CI and deploys to production.** There is no pull-request
job either, so review and manual verification are the only gates.

This is a stated position, not an oversight: the project has no sample corpus,
and committing real AI-generated files to a public repository has licensing and
size consequences. It is on the [roadmap](../ROADMAP.md) to fix with synthetic
fixtures.

## Manual verification

Keep a small local corpus. Files worth holding onto:

| File                                          | Should report                                   |
| --------------------------------------------- | ----------------------------------------------- |
| A camera JPEG with full EXIF and IPTC          | `CLEAN`, with a `digitalCapture` benign signal  |
| A Canva export with an AI feature used         | `AI METADATA DETECTED`                          |
| A Canva export with no AI feature used         | `CLEAN`, with the `ContainsAiGeneratedContent = No` benign signal |
| A Photoshop file touched by Generative Fill    | `AI METADATA DETECTED` (C2PA)                    |
| A local Stable Diffusion PNG                   | `SUSPICIOUS` — workflow fingerprints in `tEXt`   |
| A phone MP4                                    | `CLEAN`, with a populated container tag table    |
| An already-stripped file                       | `CLEAN`, and an empty metadata dump              |
| A truncated file (first 100 KB of a large MP4) | A verdict, not a traceback                       |

### Before merging any change

```bash
# 1. The CLI runs and the help is intact
python ai_metadata_check.py --help

# 2. Every corpus file still gets its expected verdict
python ai_metadata_check.py ./corpus --no-dump -q

# 3. A round trip through the strip path
python ai_metadata_check.py corpus/ai-sample.jpg --strip
# expect: verified: clean

# 4. The service starts and answers
python server.py &
curl -s localhost:8000/health
curl -s -X POST localhost:8000/check -F file=@corpus/ai-sample.jpg
```

### For a signature change

Both directions, always:

```bash
python ai_metadata_check.py the-file-that-should-now-match.png -v
python ai_metadata_check.py a-file-that-must-not-match.jpg -v
```

`-v` prints the matched text. Confirm the pattern hit what you intended and not
something incidental — a substring of an unrelated tool name, or ordinary prose.

Then re-run the whole corpus. A widened pattern that newly flags a camera JPEG is
the failure this step exists to catch.

### For a container change

```bash
python ai_metadata_check.py sample.<ext> -v --full
```

Read the region list. Check that:

- Metadata blocks are named usefully, not `whole file (unknown container)`.
- No pixel or sample data leaked into a region — a region of several megabytes
  on a small file usually means it did.
- A truncated copy of the same file still produces a report rather than a
  traceback: `head -c 100000 sample.mp4 > truncated.mp4`.

### For a strip change

```bash
python ai_metadata_check.py sample.webp --strip
```

Then verify three things, in order:

1. The checker reports `verified: clean`.
2. **The output opens correctly in an image viewer.** The checker cannot tell you
   whether you produced a valid file, only whether it has markers. A broken
   `VP8X` flag byte passes step 1 and fails here.
3. The pixels are unchanged for JPEG, PNG and WebP — compare a decoded hash, or
   diff the images.

### For a service change

```bash
export API_KEY=test-key
python server.py &

curl -s localhost:8000/health
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/check          # 401
curl -s -X POST localhost:8000/check -H "Authorization: Bearer test-key" -F file=@sample.jpg
curl -s -X POST localhost:8000/check/batch -H "Authorization: Bearer test-key" \
  -F files=@a.jpg -F files=@b.png
```

For batch, include one deliberately empty file and confirm the response is still
`200` with that entry carrying `ok: false` — one bad file must never sink the
batch.

FastAPI's `/docs` is a fast way to exercise the routes by hand.

### Before a container change reaches CI

```bash
docker build -t metadata-validator:test .
docker run --rm -d --name t -p 8000:8000 -e API_KEY=test metadata-validator:test
curl -s localhost:8000/health
docker rm -f t
```

This is the same sequence CI runs, and running it locally saves a round trip
through a failed publish — which, on this project, means a failed publish of a
tag that Watchtower is already watching.

## If you add a test suite

The likeliest first step, and the one the roadmap assumes:

- `pytest`, with fixtures generated at test time rather than committed — build a
  minimal JPEG with a synthetic `APP11` segment containing `c2pa.assertions`,
  rather than committing a real Content Credentials file.
- Cover the strip paths first. They are the highest-risk code, because a defect
  there ships a file the user believes is clean.
- Then the container parsers, including truncated and malformed input.
- Add a pull-request job to the workflow, so something gates a merge.

## References

- [Contributing](CONTRIBUTING.md)
- [CI](../deployment/CI.md)
- [Runbook](../deployment/RUNBOOK.md)
- [Detection](../architecture/DETECTION.md)
- [Stripping](../architecture/STRIPPING.md)
- [Roadmap](../ROADMAP.md)
