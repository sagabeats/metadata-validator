# Container parsing

**Applies to:** Anyone adding a format, or explaining where a finding came from
**Related documents:** [Overview](OVERVIEW.md) · [Detection](DETECTION.md) · [Stripping](STRIPPING.md)

`extract_regions()` turns a file into a list of `Region` objects — the metadata
blocks, and only the metadata blocks. Everything downstream operates on that
list, so this is where the report gets its precision.

## Dispatch

Format is decided by magic bytes, never by file extension:

| Test                                        | Parser        | Reported format                              |
| ------------------------------------------- | ------------- | -------------------------------------------- |
| `FF D8`                                     | `parse_jpeg`  | `JPEG`                                       |
| `89 50 4E 47 0D 0A 1A 0A`                   | `parse_png`   | `PNG`                                        |
| `RIFF` + `WEBP` at offset 8                 | `parse_webp`  | `WebP`                                       |
| `is_isobmff()`                              | `parse_mp4`   | From the `ftyp` brand: MP4, MOV, HEIC, AVIF… |
| anything else                               | —             | The file suffix, uppercased                  |

The fallback is not a failure. An unknown container becomes one region covering
the whole file, named `whole file (unknown container)`, and the scan proceeds.
The verdict is still correct; only the location precision is lost.

## A Region

```python
class Region:
    name: str      # human location, e.g. "APP11 (JUMBF/C2PA)"
    data: bytes    # the block itself
    offset: int    # byte offset in the source file
```

`name` becomes the `location` of any finding inside it, which is what makes a
report say *where* rather than *whether*.

## JPEG

A JPEG is a sequence of marker segments. `parse_jpeg` walks them, emitting a
region for every segment in `JPEG_MARKER_NAMES`:

| Marker  | Region name              | What lives there                                  |
| ------- | ------------------------ | ------------------------------------------------- |
| `0xE0`  | `APP0 (JFIF)`            | Structural JFIF header                            |
| `0xE1`  | `APP1 (EXIF/XMP)`        | EXIF, and the XMP packet — most soft hits         |
| `0xE2`  | `APP2 (ICC/MPF)`         | ICC profile, multi-picture format                 |
| `0xEB`  | `APP11 (JUMBF/C2PA)`     | **The C2PA manifest**                             |
| `0xED`  | `APP13 (Photoshop/IPTC)` | Photoshop resources and IPTC — `digitalSourceType`|
| `0xEE`  | `APP14 (Adobe)`          | Adobe colour transform                            |
| `0xFE`  | `COM (comment)`          | Free text                                         |

`APP3` through `APP10`, `APP12` and `APP15` are captured too, unnamed beyond
their number.

Two structural details:

- At `SOS` (`0xDA`) the compressed scan begins. The parser jumps straight to the
  last `FF D9` rather than scanning entropy-coded bytes, which would be both slow
  and meaningless.
- **Anything after `EOI` is captured** as `trailing data after EOI`. Appended
  junk past the end marker is a real hiding place, and viewers ignore it.

## PNG

A PNG is a chunk stream. `parse_png` emits a region for every chunk *not* in
`PNG_SAFE_CHUNKS` — that set being the structural and rendering chunks
(`IHDR`, `PLTE`, `IDAT`, `IEND`, `tRNS`, `gAMA`, `cHRM`, `sRGB`, `sBIT`,
`bKGD`, `pHYs`, `acTL`, `fcTL`, `fdAT`).

In practice the regions are `tEXt`, `zTXt`, `iTXt`, `eXIf`, `iCCP` and anything
proprietary.

Text chunks may be zlib-compressed, and a compressed `zTXt` would defeat the
scan entirely, so they are inflated first:

- `zTXt` — split on the keyword NUL, skip the compression-method byte, inflate
  the rest.
- `iTXt` — parse keyword, compression flag and language; inflate only when the
  flag byte is `\x01`.

`_safe_inflate()` caps output at 4 MiB and returns the input unchanged on any
failure, so a corrupt or hostile stream degrades instead of raising.

As with JPEG, anything after `IEND` is captured as `trailing data after IEND`.

## WebP

A WebP is a RIFF container. `parse_webp` skips the twelve-byte header, then
emits a region for every chunk except the image ones (`VP8 `, `VP8L`, `VP8X`,
`ALPH`, `ANIM`, `ANMF`). What remains is `EXIF`, `XMP `, `ICCP` and `C2PA`.

RIFF chunks are padded to an even length, and the parser advances by
`8 + size + (size & 1)`. Getting that wrong desynchronises the whole walk.

## ISO base media — MP4, MOV, M4A, HEIC, AVIF

The largest parser, and the one with the most reasoning behind it.

### Recognition

`is_isobmff()` accepts a leading `ftyp` or `styp` box. It also accepts files
that open with `moov`, `mdat`, `free`, `skip`, `wide` or `pnot` — some QuickTime
writers lead with those — but only when the leading four bytes read like a
plausible box length.

### Walking the tree

`parse_mp4` recurses through `ISOBMFF_CONTAINERS` (`moov`, `trak`, `mdia`,
`minf`, `stbl`, `udta`, `iprp`, `iinf`, and the fragment boxes) to a depth of 8,
building a path as it goes. A region is named by that path — `moov/udta/meta/ilst
box` — so a finding points at the exact box.

Repeated siblings are numbered. Two tracks mean two `trak/mdia/hdlr` boxes, and
a finding in the second reads `trak[2]`.

`_iso_boxes()` handles the three length encodings — 32-bit, the `size == 1`
64-bit extension, and `size == 0` meaning "to end of file" — and **stops rather
than raises** on a malformed length. That is deliberate: partial files are normal
here. A browser upload preview may send `ftyp` + `moov` and none of the frames,
and half a tree is still worth reporting.

### Three special cases

**`uuid` boxes.** ISOBMFF's extension slot, and where the two markers that matter
most in video actually live. Four UUIDs are recognised by name:

| UUID (first 8 hex) | Contents          |
| ------------------ | ----------------- |
| `be7acfcb…`        | XMP               |
| `d8fec3d6…`        | C2PA / JUMBF      |
| `2c4c0100…`        | Photoshop / IPTC  |
| `ffcc8263…`        | XMP (legacy)      |

An unrecognised UUID is still emitted, labelled with its first four bytes.

**`meta` boxes.** ISO BMFF defines `meta` as a FullBox — four version/flags bytes
before the first child — but QuickTime-flavoured writers emit it as a bare
container. Guessing wrong loses the entire tag table, so `_meta_children()` tests
whether the bytes at the child offset look like a box header and picks the offset
accordingly.

**`free` / `skip` / `wide`.** Usually reserved padding, so they are dropped when
they contain only NULs — but writers do park leftovers there, so a non-empty one
is kept.

### What is skipped, and why

`ISOBMFF_SKIP` holds the sample tables, timing tables and chunk offsets:
`mdat`, `mvhd`, `tkhd`, `mdhd`, `stts`, `stsc`, `stsz`, `stco`, `co64`, `elst`,
`trun`, `sidx` and the rest.

They are pure numbers and cannot carry a marker. Skipping them is what turns the
report from a `strings` dump of `stco`/`stsz` noise into something readable —
which was exactly the problem before this parser existed. The information those
boxes do carry (dates, duration, geometry) is decoded into the tag summary
instead.

Any single box carried into the report is truncated at `ISOBMFF_REGION_CAP`
(4 MiB) and renamed to say so.

### The tag summary

`read_video_summary()` is the video answer to the EXIF table. It walks the same
tree collecting:

| Source                          | Rows produced                                         |
| ------------------------------- | ----------------------------------------------------- |
| `ftyp`                          | `MajorBrand`, `CompatibleBrands`                       |
| `mvhd`                          | `CreateDate`, `ModifyDate`, `Duration`                 |
| `hdlr`                          | `HandlerDescription`                                   |
| `stsd`                          | Codec rows                                             |
| `ilst` (+ `keys`)               | Title, Artist, Encoder, Software, Copyright, GPS, …    |
| `udta` direct children          | The QuickTime `©`-prefixed atoms                       |
| known `uuid` boxes              | `ExtensionBoxes`                                       |

Two ordering rules are load-bearing:

- **`ilst` is resolved last.** A QuickTime `keys` table can appear *after* the
  `ilst` that references it, and without that table the item types are bare
  indices. Blobs are collected during the walk and decoded once it finishes.
- **First value wins.** `put()` ignores a second write to the same name, so the
  outermost/earliest occurrence is the one reported.

MP4 timestamps count from 1904-01-01 UTC, not the Unix epoch —
`ISO_EPOCH = 2_082_844_800` is the correction, and `_iso_time()` returns an empty
string rather than raising on an out-of-range value.

Box type labels are decoded latin-1, not ASCII, so the iTunes atoms that open
with `0xA9` read as `©nam` rather than a replacement character.

## Rendering a block for humans

`readable_text()` decides how to print a region:

1. If NULs make up between 30% and 70% of the first 4 KiB, treat it as UTF-16
   and decode it before anything else — otherwise the byte-ratio test below
   would call legible text "binary".
2. If it is mostly printable, decode and tidy it: drop XMP packet BOMs, collapse
   runs of blank lines that NUL-splitting leaves behind.
3. Otherwise extract printable runs the way `strings` does. C2PA/JUMBF blocks
   embed X.509 certificates and CBOR, and printing them raw is noise.

`prettify_xmp()` adds line breaks to XMP so a packet does not print as one
2000-character line.

## Adding a container format

1. Write `parse_<fmt>(raw) -> list[Region]` that emits metadata blocks only, with
   names a human can act on.
2. Add the magic-byte test to `extract_regions()`, before the fallback.
3. If the format can be rebuilt without recompressing, add a `strip_<fmt>` and
   wire it into `strip_bytes()` — see [STRIPPING.md](STRIPPING.md). If it cannot,
   leave it check-only; that is a supported state.
4. If it carries a tag table worth summarising, extend `read_tag_summary()`.
5. If it is a still image, add its extension to the CLI's directory-recursion set.

## References

- [Overview](OVERVIEW.md)
- [Detection](DETECTION.md)
- [Stripping](STRIPPING.md)
- [JPEG File Interchange Format](https://www.w3.org/Graphics/JPEG/jfif3.pdf)
- [PNG specification](https://www.w3.org/TR/png-3/)
- [WebP container specification](https://developers.google.com/speed/webp/docs/riff_container)
- [ISO base media file format overview](https://en.wikipedia.org/wiki/ISO_base_media_file_format)
