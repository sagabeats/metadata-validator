# Stripping

**Applies to:** Anyone changing a strip path, or explaining a `415` or a failed verify
**Related documents:** [Containers](CONTAINERS.md) · [Overview](OVERVIEW.md) · [Endpoint reference](../reference/ENDPOINTS.md)

Stripping rebuilds the container without its metadata blocks. For JPEG, PNG and
WebP the compressed image data is copied byte-for-byte, so the pixels come out
identical and the file is never re-encoded.

## The rule that governs everything here

**A strip is not a success until the output has been re-scanned.**

`clean()` runs `analyze()` on the stripped bytes and returns `verified`, which is
simply `after["clean"]`. `/clean` and `/clean/json` refuse to hand back an
unverified file — the binary route raises `500 strip did not remove every
marker` rather than return it. The CLI re-reads what it wrote and prints either
`verified: clean` or `N marker(s) STILL present`, and downgrades its exit code
accordingly.

Silence is not proof. Never report a strip as done on the basis that it did not
raise.

## Format support

| Format          | Check | Strip | Method                                                        |
| --------------- | ----- | ----- | ------------------------------------------------------------- |
| JPEG            | Yes   | Yes   | Segment surgery, pixels untouched                             |
| PNG             | Yes   | Yes   | Chunk filtering, pixels untouched                             |
| WebP            | Yes   | Yes   | RIFF rebuild with `VP8X` flag repair, pixels untouched        |
| MP4 / MOV / M4A | Yes   | No    | `strip_bytes()` raises `ValueError`; the service returns `415` |
| HEIC / AVIF     | Yes   | No    | Same                                                          |
| Anything else   | Yes   | CLI only | Pillow re-save, **lossy**                                  |

`strip_bytes()` — the in-memory path used by the HTTP service — supports JPEG,
PNG and WebP and nothing else. The CLI has one extra fallback, described at the
end.

## JPEG

`strip_jpeg()` writes a fresh `FF D8`, then copies segments forward, dropping
every marker in `JPEG_MARKER_NAMES`. Three exceptions are kept:

| Kept                              | Why                                                                    |
| --------------------------------- | ---------------------------------------------------------------------- |
| `APP0` (JFIF)                     | Structural header; some decoders expect it                             |
| `APP14` (Adobe)                   | Carries the colour transform. Dropping it breaks CMYK and some YCCK files |
| `APP2` when it starts `ICC_PROFILE` | Only when `keep_icc` is true — removing it shifts colours              |

At `SOS` the parser finds the last `FF D9` and copies everything from `SOS`
through `EOI` verbatim. That is the whole trick: the entropy-coded scan is
transplanted, not decoded, so nothing is recompressed — and anything appended
past `EOI` is left behind.

## PNG

`strip_png()` copies the eight-byte signature, then keeps only chunks in
`PNG_SAFE_CHUNKS`, plus `iCCP` when `keep_icc` is true. `tEXt`, `zTXt`, `iTXt`,
`eXIf` and every proprietary chunk are dropped.

The walk stops at `IEND`, which discards anything appended past it.

Chunk CRCs are copied with their chunks, so no CRC recomputation is needed —
another consequence of never modifying a chunk's contents.

## WebP

`strip_webp()` is the fiddliest of the three, because WebP advertises its own
contents.

Chunks in `WEBP_METADATA_CHUNKS` (`EXIF`, `XMP `, `C2PA`) are dropped, and
`ICCP` is dropped when `keep_icc` is false. Everything else is copied.

The complication is `VP8X`, the extended-format header, whose flag byte declares
which optional chunks exist. Leaving those bits set after removing the chunks
produces a file that claims metadata it no longer has, and strict decoders
reject it. So the rebuild clears the bits it invalidated:

| Bit    | Meaning | Cleared when         |
| ------ | ------- | -------------------- |
| `0x20` | ICC     | `ICCP` was dropped   |
| `0x08` | EXIF    | `EXIF` was dropped   |
| `0x04` | XMP     | `XMP ` was dropped   |

Finally the RIFF header is rewritten with the new payload length. Chunk padding
to even lengths is preserved throughout the copy.

## Video

Not supported. `strip_bytes()` raises:

```text
in-memory strip supports JPEG, PNG and WebP only;
MP4/MOV can be checked but not yet stripped
```

`server.py` maps that `ValueError` to `415 Unsupported Media Type`.

The reason is structural, not an oversight: removing a box from an ISO base
media file shifts every subsequent byte, and `stco` / `co64` hold absolute file
offsets into `mdat`. A correct strip has to rewrite those tables. That work is
on the [roadmap](../ROADMAP.md); until it lands, video is check-only and callers
should treat a video hit as "re-export this from a clean source".

## The CLI fallback

`strip_file()` tries `strip_bytes()` first and falls back to `strip_generic()`
on `ValueError`. That fallback opens the file with Pillow, copies the pixel data
into a fresh image, and saves it — producing a file with no metadata because it
has no history.

It is **lossy for any lossy format**: the image is decoded and re-encoded, so a
JPEG loses quality. It is only reached for containers the byte-surgery paths
cannot rebuild, and it is not available over HTTP at all — the service returns
`415` instead of silently recompressing a caller's image.

## ICC profiles

`keep_icc` defaults to true everywhere: the CLI keeps ICC unless `--strip-icc`,
and both clean endpoints default `keep_icc=true`.

An ICC profile carries no AI marker. Dropping it changes how the image renders —
often visibly, on wide-gamut source material. Keep it unless you have a reason.

## CLI output modes

| Invocation                    | Result                                                        |
| ----------------------------- | ------------------------------------------------------------- |
| `--strip`                     | Writes `name.clean.ext` alongside the original                 |
| `--strip --inplace`           | Copies to `name.ext.bak` (if absent), writes a `.tmp`, then atomically replaces the original |
| `--strip --strip-icc`         | As above, also removing the ICC profile                        |

The in-place path never overwrites an existing `.bak`, so running it twice does
not destroy the true original.

After writing, the CLI prints the size delta and the verification result:

```text
  -> wrote thumb.clean.jpg  (-84,213 bytes)  verified: clean
```

## References

- [Containers](CONTAINERS.md)
- [Overview](OVERVIEW.md)
- [CLI reference](../reference/CLI.md)
- [Endpoint reference](../reference/ENDPOINTS.md)
- [Python API](../reference/PYTHON-API.md)
- [Roadmap](../ROADMAP.md)
