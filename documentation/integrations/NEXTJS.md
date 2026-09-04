# Next.js integration

**Applies to:** Anyone wiring the service into a web upload flow
**Related documents:** [Endpoint reference](../reference/ENDPOINTS.md) · [Security](../architecture/SECURITY.md) · [Environment](../deployment/ENVIRONMENT.md)

A working route handler ships in the repository:
[nextjs-example/app/api/thumbnail-check/route.ts](../../nextjs-example/app/api/thumbnail-check/route.ts).

It is a reference to copy into your own project, not a package. Nothing imports
it, and it is excluded from the Docker build context.

## The shape

```text
Browser  ->  your Next.js origin  ->  metadata service
             /api/thumbnail-check     http://metadata-validator:8000
             (holds the API key)      (never reachable from the browser)
```

Two properties follow from that shape, and both are the reason for it:

**The API key never reaches the browser.** It lives in the server-side
environment of your own application. A browser that could call the service
directly would need the key in shipped JavaScript.

**CORS never enters the picture.** The browser only ever talks to your own
origin. `ALLOWED_ORIGINS` stays unset on the service, and the CORS middleware is
never installed. See [architecture/SECURITY.md](../architecture/SECURITY.md).

## Configuration

```bash
# .env.local
METADATA_SERVICE_URL=http://metadata-validator:8000   # internal Docker name
METADATA_API_KEY=<the service's API_KEY>
```

When Next.js runs on the same VPS, use the internal container name. Going out
through Traefik and back costs a TLS handshake, spends the rate limit, and
requires the service to be publicly exposed at all. Use the public URL only when
your application genuinely lives elsewhere — Vercel, another host.

`METADATA_API_KEY` must never be a `NEXT_PUBLIC_*` variable. That prefix compiles
the value into the client bundle.

## What the handler does

```ts
export const runtime = "nodejs";   // needs Node streams, not the edge runtime
```

1. Reads the multipart body and validates the file client-side of the service:
   present, non-empty, under 25 MB. Rejecting early saves a round trip.
2. Chooses `/check` or `/clean` based on a `?clean=1` query parameter.
3. Forwards the file with a bearer header and a 30-second `AbortSignal.timeout`.
4. On a network failure, returns `502 metadata service unreachable` — the service
   being down reads as a clear status, not a crash.
5. On `/clean`, passes the image through while preserving the `X-Verdict-*`
   headers so the browser learns what was removed.
6. On `/check`, reshapes the verdict into something a UI can render directly.

## The response reshaping

This is the part worth copying even if you write your own handler:

```ts
const blocking = result.findings.filter((f) => f.severity === "hard");

return NextResponse.json({
  safeToUpload: !result.ai_detected,
  verdict: result.verdict,
  willBeLabeled: result.ai_detected,
  reasons: blocking.map((f) => ({ what: f.label, where: f.location })),
  traces: result.findings.filter((f) => f.severity === "soft").map((f) => f.label),
  format: result.format,
  bytes: result.bytes,
});
```

`willBeLabeled` comes from `ai_detected` alone, because only `hard` findings are
what platforms read and act on. `soft` findings become `traces` — surfaced
separately, because they mean an AI tool touched the file without declaring
anything. Collapsing the two would flag every Photoshop export and train your
users to ignore the warning.

That distinction is the whole design; it is explained in
[architecture/DETECTION.md](../architecture/DETECTION.md).

## Calling it

```ts
const body = new FormData();
body.append("file", file);

const res = await fetch("/api/thumbnail-check", { method: "POST", body });
const { safeToUpload, willBeLabeled, reasons, traces } = await res.json();

if (willBeLabeled) {
  // Offer the strip
  const cleanRes = await fetch("/api/thumbnail-check?clean=1", {
    method: "POST",
    body,
  });
  const cleaned = new File(
    [await cleanRes.blob()],
    file.name.replace(/\.(\w+)$/, ".clean.$1"),
  );
}
```

## Adapting it

**Batch uploads.** The example handles one file. For a gallery, forward to
`/check/batch` instead: one request, one unit against the rate limiter rather
than twenty, and results matched back by `index` — not by filename, which is not
unique enough to key on.

**Strip everything unconditionally.** Skip `/check` and call `/clean` on every
upload. It is cheap, and it removes the branch. The cost is a `415` on video,
which you must handle.

**Show the evidence.** Set `include_content=true` and render
`metadata_blocks` where `flagged` is true. That is the C2PA manifest or XMP
packet that caused the verdict, and showing it is far more convincing to a user
than a boolean.

**Fail open or closed.** The example returns `502` and leaves the decision to the
caller. Decide deliberately: is an unchecked upload acceptable when the service
is down? For most products it is.

## Other frameworks

Nothing here is Next.js-specific. The pattern is: server-side proxy, key held
server-side, timeout, `502` on unreachable, branch on `ai_detected`. It
translates directly to an Express route, a Django view, a Laravel controller or
a Cloudflare Worker.

If your caller is Python, skip HTTP entirely and import the module —
[reference/PYTHON-API.md](../reference/PYTHON-API.md).

## References

- [Endpoint reference](../reference/ENDPOINTS.md)
- [Detection](../architecture/DETECTION.md)
- [Stripping](../architecture/STRIPPING.md)
- [Security](../architecture/SECURITY.md)
- [Environment](../deployment/ENVIRONMENT.md)
- [Next.js Route Handlers](https://nextjs.org/docs/app/building-your-application/routing/route-handlers)
