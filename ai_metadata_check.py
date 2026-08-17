#!/usr/bin/env python3
"""
ai_metadata_check.py -- Check whether an image carries "AI generated" markers
in its metadata, and optionally strip them.

Why this exists: YouTube (and Instagram, TikTok, LinkedIn) auto-apply the
"Altered or synthetic content" label by reading metadata that AI tools embed
into the file -- mainly C2PA Content Credentials and the IPTC
`digitalSourceType` field. A thumbnail can look 100% hand-made and still get
labeled because some tool in the chain (Photoshop Generative Fill, Canva Magic
Media, an upscaler, a background remover) stamped the file.

Usage:
    python ai_metadata_check.py thumb.jpg
    python ai_metadata_check.py *.png --verbose
    python ai_metadata_check.py thumb.jpg --strip            # writes thumb.clean.jpg
    python ai_metadata_check.py thumb.jpg --strip --inplace  # overwrites (keeps .bak)

Exit codes:
    0 = clean         1 = AI markers found
    2 = suspicious    3 = error reading file
"""

from __future__ import annotations

import argparse
import io
import re
import shutil
import struct
import sys
import zlib
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None


# --------------------------------------------------------------------------
# Signature table
# --------------------------------------------------------------------------
# (regex, human label, severity)
#   "hard"  -> platforms read this and will label the upload
#   "soft"  -> an AI tool touched the file; may or may not trigger a label

HARD_SIGNATURES: list[tuple[bytes, str]] = [
    # --- C2PA / Content Credentials: the thing YouTube actually reads ---
    (rb"c2pa\.assertions", "C2PA assertion store"),
    (rb"c2pa\.actions", "C2PA action log (records how the image was made)"),
    (rb"c2pa\.claim", "C2PA claim"),
    (rb"urn:uuid:.{0,40}c2pa", "C2PA manifest URN"),
    (rb"contentauth", "Content Authenticity Initiative manifest"),
    (rb"contentcredentials", "Content Credentials manifest"),
    (rb"jumbf", "JUMBF box (C2PA container)"),
    # --- IPTC digitalSourceType: the standardised "this is AI" flag ---
    (rb"trainedAlgorithmicMedia",
     "IPTC digitalSourceType = trainedAlgorithmicMedia (declares FULLY AI-generated)"),
    (rb"compositeWithTrainedAlgorithmicMedia",
     "IPTC digitalSourceType = compositeWithTrainedAlgorithmicMedia (declares PARTLY AI)"),
    (rb"algorithmicMedia",
     "IPTC digitalSourceType = algorithmicMedia (declares algorithm-generated)"),
    # NB: no bare `digitalSourceType` pattern here on purpose -- the field is
    # also used to declare digitalCapture (a real photo), which is the opposite
    # of what we are looking for. Only the AI-valued variants above count.
    # --- Canva stamps this on export when any AI feature touched the design ---
    (rb"ContainsAiGeneratedContent>\s*Yes",
     "Canva ContainsAiGeneratedContent = Yes (declares AI content in the design)"),
    # --- Google's AI watermark metadata ---
    (rb"(?i)synthid", "Google SynthID marker"),
]

# digitalSourceType values that mean "this is a real photo" -- reassuring, not a hit.
BENIGN_SOURCE_TYPES = [
    (rb"digitalCapture", "digitalSourceType = digitalCapture (declared camera original)"),
    (rb"negativeFilm|positiveFilm|print", "digitalSourceType = scanned film/print"),
    (rb"ContainsAiGeneratedContent>\s*No",
     "Canva ContainsAiGeneratedContent = No (export declares no AI content)"),
]

SOFT_SIGNATURES: list[tuple[bytes, str]] = [
    # Generators
    (rb"Midjourney", "Midjourney"),
    (rb"DALL[\xb7\xc2\xa7\x2d]?.?E|DALLE", "DALL-E / OpenAI"),
    (rb"openai\.com|OpenAI", "OpenAI"),
    (rb"Stable\s?Diffusion|stable-diffusion", "Stable Diffusion"),
    (rb"Automatic1111|AUTOMATIC1111", "AUTOMATIC1111 WebUI"),
    (rb"ComfyUI|comfyanonymous", "ComfyUI"),
    (rb"InvokeAI", "InvokeAI"),
    (rb"Firefly|firefly", "Adobe Firefly"),
    (rb"Generative Fill|generative_fill|Generative Expand",
     "Photoshop Generative Fill / Expand"),
    (rb"Adobe Express", "Adobe Express"),
    (rb"Imagen|imagen-3|imagen-4", "Google Imagen"),
    (rb"Gemini|gemini-", "Google Gemini"),
    (rb"NanoBanana|nano-banana", "Google Nano Banana"),
    (rb"Grok|grok-|xAI", "xAI Grok / Aurora"),
    (rb"Leonardo\.?Ai|leonardo\.ai", "Leonardo.Ai"),
    (rb"Ideogram", "Ideogram"),
    (rb"black-forest-labs|BlackForestLabs|FLUX\.1", "FLUX / Black Forest Labs"),
    (rb"Recraft", "Recraft"),
    (rb"Playground\s?AI|playgroundai", "Playground AI"),
    (rb"NightCafe", "NightCafe"),
    (rb"Craiyon", "Craiyon"),
    (rb"DreamStudio", "DreamStudio"),
    (rb"RunwayML|runwayml", "Runway"),
    (rb"Luma\s?AI|lumalabs", "Luma AI"),
    (rb"Kling|kling-ai", "Kling AI"),
    (rb"Magic Media|magic-media", "Canva Magic Media"),
    (rb"Magic Studio", "Canva Magic Studio"),
    (rb"Picsart\s?AI|picsart_ai", "Picsart AI"),
    (rb"Fotor\s?AI", "Fotor AI"),
    (rb"remove\.bg|removebg", "remove.bg (AI background removal)"),
    (rb"Topaz\s?(Gigapixel|Photo\s?AI|Labs)", "Topaz AI upscaler"),
    (rb"Let'?s Enhance|letsenhance", "Let's Enhance (AI upscaler)"),
    (rb"waifu2x|Real-?ESRGAN|ESRGAN", "AI upscaler (ESRGAN family)"),
    (rb"Freepik\s?AI|Pikaso", "Freepik AI / Pikaso"),
    (rb"Krea", "Krea AI"),
    (rb"Bing Image Creator|Image Creator|Designer\.microsoft",
     "Microsoft Designer / Bing Image Creator"),
    (rb"Copilot", "Microsoft Copilot"),
    (rb"Meta AI|Emu\b", "Meta AI / Emu"),
    (rb"seedream|Seedream|Doubao|Jimeng", "ByteDance Seedream / Jimeng"),
    (rb"Qwen-?Image|Tongyi|Wanx", "Alibaba Qwen-Image / Tongyi"),
    (rb"Hunyuan", "Tencent Hunyuan"),
    # Generic generator-workflow fingerprints
    (rb"(?i)negative[ _]prompt", "diffusion 'negative prompt' block"),
    (rb"(?i)\bsteps:\s*\d+.{0,80}\bcfg", "diffusion sampler parameters"),
    (rb"(?i)sampler:\s*(euler|dpm|ddim|lms|heun|unipc)", "diffusion sampler name"),
    (rb"(?i)denoising[ _]strength", "diffusion denoising_strength"),
    (rb"(?i)model hash:", "diffusion model hash"),
    (rb"\.safetensors|\.ckpt\b", "model checkpoint reference"),
    (rb"(?i)<lora:|lora[_ ](name|weight|hash|model)", "LoRA reference"),
    (rb"(?i)latent[_ ]?upscal", "latent upscaler"),
    (rb"(?i)\bseed[\"'\s:=]{1,4}\d{6,}", "generation seed"),
    # Lookbehind keeps this off Canva's ContainsAiGeneratedContent namespace,
    # which declares Yes *or* No -- that pair is judged by value above, not here.
    (rb"(?i)(?<!contains)ai[_ -]?generated|\baigc\b", "explicit 'AI generated' string"),
    (rb"(?i)generative[ _-]?ai\b|\bgenai\b", "generative AI reference"),
]

# Metadata chunks/segments that can legitimately hold these markers.
JPEG_MARKER_NAMES = {
    0xE0: "APP0 (JFIF)", 0xE1: "APP1 (EXIF/XMP)", 0xE2: "APP2 (ICC/MPF)",
    0xE3: "APP3", 0xE4: "APP4", 0xE5: "APP5", 0xE6: "APP6", 0xE7: "APP7",
    0xE8: "APP8", 0xE9: "APP9", 0xEA: "APP10", 0xEB: "APP11 (JUMBF/C2PA)",
    0xEC: "APP12 (Ducky)", 0xED: "APP13 (Photoshop/IPTC)", 0xEE: "APP14 (Adobe)",
    0xEF: "APP15", 0xFE: "COM (comment)",
}

PNG_SAFE_CHUNKS = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS",
                   b"gAMA", b"cHRM", b"sRGB", b"sBIT", b"bKGD",
                   b"pHYs", b"acTL", b"fcTL", b"fdAT"}
PNG_ICC_CHUNK = b"iCCP"

WEBP_METADATA_CHUNKS = {b"EXIF", b"XMP ", b"C2PA"}


# --------------------------------------------------------------------------
# Container parsers -- pull out only the metadata regions
# --------------------------------------------------------------------------

class Region:
    """One metadata blob found in the file."""

    def __init__(self, name: str, data: bytes, offset: int):
        self.name = name
        self.data = data
        self.offset = offset

    def __repr__(self) -> str:
        return f"<Region {self.name} {len(self.data)}B @{self.offset}>"


def parse_jpeg(raw: bytes) -> list[Region]:
    regions: list[Region] = []
    i = 2  # skip SOI
    n = len(raw)
    while i < n - 1:
        if raw[i] != 0xFF:
            i += 1
            continue
        marker = raw[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker == 0xD9:  # EOI -- anything after is appended junk, scan it
            tail = raw[i + 2:]
            if tail.strip():
                regions.append(Region("trailing data after EOI", tail, i + 2))
            break
        if marker == 0xDA:  # SOS -- compressed pixels start; skip to EOI
            eoi = raw.rfind(b"\xff\xd9")
            if eoi > i:
                tail = raw[eoi + 2:]
                if tail.strip():
                    regions.append(Region("trailing data after EOI", tail, eoi + 2))
            break
        if i + 4 > n:
            break
        seg_len = struct.unpack(">H", raw[i + 2:i + 4])[0]
        payload = raw[i + 4:i + 2 + seg_len]
        if marker in JPEG_MARKER_NAMES:
            regions.append(Region(JPEG_MARKER_NAMES[marker], payload, i))
        i += 2 + seg_len
    return regions


def parse_png(raw: bytes) -> list[Region]:
    regions: list[Region] = []
    i = 8  # skip signature
    n = len(raw)
    while i + 8 <= n:
        length = struct.unpack(">I", raw[i:i + 4])[0]
        ctype = raw[i + 4:i + 8]
        payload = raw[i + 8:i + 8 + length]
        if ctype == b"IEND":
            tail = raw[i + 12:]
            if tail.strip():
                regions.append(Region("trailing data after IEND", tail, i + 12))
            break
        if ctype not in PNG_SAFE_CHUNKS and ctype != b"IDAT":
            data = payload
            # zTXt / iTXt may be zlib-compressed -- inflate so we can read it
            if ctype == b"zTXt":
                key, _, rest = payload.partition(b"\x00")
                data = key + b"\x00" + _safe_inflate(rest[1:])
            elif ctype == b"iTXt":
                parts = payload.split(b"\x00", 2)
                if len(parts) == 3 and len(parts[1]) >= 1 and parts[1][:1] == b"\x01":
                    body = parts[2].split(b"\x00", 2)[-1]
                    data = parts[0] + b"\x00" + _safe_inflate(body)
            regions.append(Region(f"{ctype.decode('ascii', 'replace')} chunk", data, i))
        i += 12 + length
    return regions


def parse_webp(raw: bytes) -> list[Region]:
    regions: list[Region] = []
    i = 12  # RIFF hdr + WEBP fourcc
    n = len(raw)
    while i + 8 <= n:
        ctype = raw[i:i + 4]
        size = struct.unpack("<I", raw[i + 4:i + 8])[0]
        payload = raw[i + 8:i + 8 + size]
        if ctype not in (b"VP8 ", b"VP8L", b"VP8X", b"ALPH", b"ANIM", b"ANMF"):
            regions.append(Region(f"{ctype.decode('ascii', 'replace')} chunk", payload, i))
        i += 8 + size + (size & 1)  # chunks are padded to even length
    return regions


def _safe_inflate(blob: bytes) -> bytes:
    try:
        return zlib.decompressobj().decompress(blob, 1 << 22)
    except Exception:
        return blob


def extract_regions(raw: bytes, path: Path) -> tuple[list[Region], str]:
    """Return (metadata regions, detected container format)."""
    if raw[:2] == b"\xff\xd8":
        return parse_jpeg(raw), "JPEG"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return parse_png(raw), "PNG"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return parse_webp(raw), "WebP"
    # Unknown container: scan the whole file, minus nothing.
    return [Region("whole file (unknown container)", raw, 0)], path.suffix.upper().lstrip(".")


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

class Finding:
    def __init__(self, severity: str, label: str, where: str, excerpt: str,
                 matched: str = ""):
        self.severity = severity
        self.label = label
        self.where = where
        self.excerpt = excerpt
        self.matched = matched  # literal text that tripped the pattern


def scan_regions(regions: list[Region]) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for region in regions:
        # Compare case-sensitively but also catch UTF-16 XMP by stripping NULs.
        haystacks = [region.data]
        if b"\x00" in region.data[:200]:
            haystacks.append(region.data.replace(b"\x00", b""))
        for severity, table in (("hard", HARD_SIGNATURES), ("soft", SOFT_SIGNATURES)):
            for pattern, label in table:
                for hay in haystacks:
                    m = re.search(pattern, hay)
                    if not m:
                        continue
                    key = (label, region.name)
                    if key in seen:
                        break
                    seen.add(key)
                    findings.append(Finding(
                        severity, label, region.name, _excerpt(hay, m.start()),
                        m.group(0).decode("utf-8", "replace"),
                    ))
                    break
    return findings


def _tidy(text: str) -> str:
    """Drop XMP packet BOMs and collapse the blank lines NUL-splitting leaves."""
    return re.sub(r"\n{3,}", "\n\n", text.replace("﻿", "")).strip()


def readable_text(data: bytes) -> tuple[str, bool]:
    """Render a metadata blob for human eyes.

    Returns (text, was_binary). Text blocks (XMP, PNG tEXt) are decoded as-is.
    Binary ones (C2PA/JUMBF, which embed X.509 certs and CBOR) would be
    unreadable noise, so we pull out the printable runs the way `strings` does.
    """
    if not data:
        return "", False
    sample = data[:4096]

    # UTF-16 text (NUL between every character) would look "binary" by byte
    # ratio, so detect and decode it before the printable test.
    if sample.count(0) > len(sample) * 0.3 and sample.count(0) < len(sample) * 0.7:
        for codec in ("utf-16-le", "utf-16-be"):
            try:
                text = data.decode(codec)
            except (UnicodeDecodeError, LookupError):
                continue
            if sum(c.isprintable() or c.isspace() for c in text[:512]) > len(text[:512]) * 0.9:
                return _tidy(text), False

    printable = sum(1 for b in sample if 32 <= b < 127 or b in (9, 10, 13))
    if printable / len(sample) >= 0.85:
        # NUL is a field separator here (PNG tEXt key\0value, APP1 namespace\0
        # payload) -- turn it into a line break rather than gluing fields.
        return _tidy(re.sub(r"\x00+", "\n", data.decode("utf-8", "replace"))), False
    # Min run of 6 keeps signal (labels, JSON, cert subjects) and drops most of
    # the random printable runs that fall out of compressed/CBOR bytes. Only
    # affects readability -- detection always scans the raw bytes.
    runs = [m.group(0).decode("ascii") for m in re.finditer(rb"[\x20-\x7e]{6,}", data)]
    return "\n".join(runs), True


def prettify_xmp(text: str) -> str:
    """Put each XMP tag on its own line -- packets often arrive as one long line."""
    if "<" not in text or ">" not in text:
        return text
    spaced = re.sub(r">\s*<", ">\n<", text)
    out, depth = [], 0
    for line in spaced.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("</"):
            depth = max(0, depth - 1)
        out.append("  " * depth + line)
        if (line.startswith("<") and not line.startswith("</")
                and not line.startswith("<?") and not line.endswith("/>")
                and "</" not in line):
            depth += 1
    return "\n".join(out)


def dump_regions(regions: list[Region], findings: list[Finding],
                 color: bool, limit: int, only_flagged: bool = False) -> None:
    """Print the contents of the file's metadata blocks.

    Every block is shown by default -- a clean file is worth reading too, since
    that is how you confirm what your editor actually wrote. Blocks that tripped
    a signature are marked and their matched text highlighted.
    """
    flagged = {f.where for f in findings}
    hits = sorted({f.matched for f in findings if f.matched}, key=len, reverse=True)
    shown = regions if not only_flagged else [r for r in regions if r.name in flagged]

    print()
    if not shown:
        msg = ("  metadata: no flagged blocks "
               f"({len(regions)} present, hidden by --flagged-only)"
               if only_flagged and regions else
               "  metadata: none -- the file carries no EXIF, XMP, "
               "comment or C2PA blocks at all")
        print(paint(msg, "dim", color))
        return

    total = sum(len(r.data) for r in shown)
    print(paint(f"  metadata blocks ({len(shown)}, {total:,} bytes total):",
                "bold", color))

    for region in shown:
        is_flagged = region.name in flagged
        text, was_binary = readable_text(region.data)
        if "XMP" in region.name or text.lstrip().startswith(("<?xpacket", "<x:xmpmeta")):
            text = prettify_xmp(text)

        tags = []
        if is_flagged:
            tags.append("FLAGGED")
        if was_binary and text:  # redundant to say so when nothing readable came out
            tags.append("printable strings only")
        suffix = f"  [{', '.join(tags)}]" if tags else ""

        print()
        print(paint(f"  --- {region.name}: {len(region.data):,} bytes{suffix} ---",
                    "red" if is_flagged else "bold", color))

        if not text:
            print(paint("    (no readable text -- binary only)", "dim", color))
            continue

        truncated = len(text) > limit
        for line in text[:limit].splitlines():
            for chunk in _wrap(line.rstrip(), 96):
                print("    " + _highlight(chunk, hits, color))
        if truncated:
            print(paint(f"    ... {len(text) - limit:,} more characters "
                        f"(use --full to see everything)", "dim", color))


def _wrap(line: str, width: int) -> list[str]:
    if len(line) <= width:
        return [line]
    indent = len(line) - len(line.lstrip())
    pad = " " * min(indent, width - 8)
    parts, rest = [], line
    while len(rest) > width:
        parts.append(rest[:width])
        rest = pad + rest[width:]
    parts.append(rest)
    return parts


def _highlight(text: str, hits: list[str], color: bool) -> str:
    if not color or not hits:
        return text
    for hit in hits:
        if len(hit) < 3 or hit not in text:
            continue
        text = text.replace(hit, f"{COLORS['red']}{COLORS['bold']}{hit}{COLORS['off']}")
    return text


def scan_benign(regions: list[Region]) -> list[str]:
    """Positive signals -- metadata that declares the image as camera-captured."""
    notes: list[str] = []
    for region in regions:
        for pattern, label in BENIGN_SOURCE_TYPES:
            if re.search(pattern, region.data) and label not in notes:
                notes.append(label)
    return notes


def _excerpt(blob: bytes, at: int, span: int = 60) -> str:
    lo = max(0, at - span // 3)
    chunk = blob[lo:lo + span]
    text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
    return re.sub(r"\.{3,}", "...", text).strip()


def read_exif_summary(src: "Path | bytes", every_tag: bool = False) -> list[tuple[str, str]]:
    """Human-readable EXIF fields worth showing (camera vs. software).

    Accepts a path or the raw bytes, so the HTTP service can use it without
    first spilling an upload to disk.
    """
    if Image is None:
        return []
    rows: list[tuple[str, str]] = []
    if isinstance(src, (bytes, bytearray)):
        src = io.BytesIO(src)
    try:
        with Image.open(src) as im:
            exif = im.getexif()
            if not exif:
                return []
            from PIL.ExifTags import TAGS
            interesting = {"Software", "Make", "Model", "Artist", "Copyright",
                           "ImageDescription", "DateTimeOriginal", "DateTime",
                           "HostComputer", "ProcessingSoftware", "UserComment"}
            for tag_id, value in exif.items():
                name = TAGS.get(tag_id, str(tag_id))
                if not every_tag and name not in interesting:
                    continue
                if isinstance(value, bytes):
                    value = value.decode("utf-8", "replace")
                text = str(value).strip().replace("\x00", "")
                if text:
                    rows.append((name, text[:120]))
    except Exception:
        pass
    return rows


def verdict_for(findings: list[Finding]) -> tuple[str, int]:
    if any(f.severity == "hard" for f in findings):
        return "AI METADATA DETECTED", 1
    if findings:
        return "SUSPICIOUS", 2
    return "CLEAN", 0


# Exit codes are named, not ordered, so a batch result cannot be max()'d --
# rank them explicitly and report the worst.
EXIT_RANK = {0: 0, 2: 1, 1: 2, 3: 3}


def worse(a: int, b: int) -> int:
    return a if EXIT_RANK[a] >= EXIT_RANK[b] else b


# --------------------------------------------------------------------------
# Stripping -- byte surgery, so JPEG/PNG pixels are never recompressed
# --------------------------------------------------------------------------

def strip_jpeg(raw: bytes, keep_icc: bool) -> bytes:
    out = bytearray(b"\xff\xd8")
    i, n = 2, len(raw)
    while i < n - 1:
        if raw[i] != 0xFF:
            i += 1
            continue
        marker = raw[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker == 0xDA:  # SOS: copy everything up to and including EOI
            eoi = raw.rfind(b"\xff\xd9")
            out += raw[i:eoi + 2] if eoi > i else raw[i:]
            return bytes(out)
        if i + 4 > n:
            break
        seg_len = struct.unpack(">H", raw[i + 2:i + 4])[0]
        segment = raw[i:i + 2 + seg_len]
        payload = raw[i + 4:i + 2 + seg_len]
        drop = marker in JPEG_MARKER_NAMES
        if marker == 0xE0:  # JFIF header is structural, keep it
            drop = False
        if marker == 0xEE:  # Adobe APP14 carries colour transform, keep it
            drop = False
        if marker == 0xE2 and keep_icc and payload.startswith(b"ICC_PROFILE"):
            drop = False
        if not drop:
            out += segment
        i += 2 + seg_len
    return bytes(out)


def strip_png(raw: bytes, keep_icc: bool) -> bytes:
    out = bytearray(raw[:8])
    i, n = 8, len(raw)
    while i + 8 <= n:
        length = struct.unpack(">I", raw[i:i + 4])[0]
        ctype = raw[i + 4:i + 8]
        chunk = raw[i:i + 12 + length]
        keep = ctype in PNG_SAFE_CHUNKS or (keep_icc and ctype == PNG_ICC_CHUNK)
        if keep:
            out += chunk
        if ctype == b"IEND":
            break  # drop anything appended past IEND
        i += 12 + length
    return bytes(out)


def strip_webp(raw: bytes, keep_icc: bool) -> bytes:
    body = bytearray()
    i, n = 12, len(raw)
    dropped_exif = dropped_xmp = dropped_icc = False
    vp8x_at = None
    while i + 8 <= n:
        ctype = raw[i:i + 4]
        size = struct.unpack("<I", raw[i + 4:i + 8])[0]
        total = 8 + size + (size & 1)
        chunk = raw[i:i + total]
        if ctype in WEBP_METADATA_CHUNKS:
            dropped_exif |= ctype == b"EXIF"
            dropped_xmp |= ctype == b"XMP "
        elif ctype == b"ICCP" and not keep_icc:
            dropped_icc = True
        else:
            if ctype == b"VP8X":
                vp8x_at = len(body)
            body += chunk
        i += total
    # VP8X advertises which optional chunks exist -- clear the bits we removed.
    if vp8x_at is not None:
        flags = body[vp8x_at + 8]
        if dropped_icc:
            flags &= ~0x20
        if dropped_exif:
            flags &= ~0x08
        if dropped_xmp:
            flags &= ~0x04
        body[vp8x_at + 8] = flags
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + bytes(body)


def strip_generic(path: Path, dest: Path) -> None:
    if Image is None:
        raise RuntimeError("Pillow is required to strip this format")
    with Image.open(path) as im:
        clean = Image.new(im.mode, im.size)
        clean.putdata(list(im.getdata()))
        clean.save(dest)


def strip_file(path: Path, raw: bytes, dest: Path, keep_icc: bool) -> None:
    try:
        dest.write_bytes(strip_bytes(raw, keep_icc))
    except ValueError:  # container we cannot rebuild -- re-save via Pillow
        strip_generic(path, dest)


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

COLORS = {"red": "\033[91m", "yellow": "\033[93m", "green": "\033[92m",
          "dim": "\033[2m", "bold": "\033[1m", "off": "\033[0m"}


def paint(text: str, color: str, enabled: bool) -> str:
    return f"{COLORS[color]}{text}{COLORS['off']}" if enabled else text


def report(path: Path, fmt: str, size: int, findings: list[Finding],
           exif_rows: list[tuple[str, str]], regions: list[Region],
           verdict: str, benign: list[str], color: bool,
           args: argparse.Namespace) -> None:
    verbose = args.verbose
    tone = {"AI METADATA DETECTED": "red", "SUSPICIOUS": "yellow", "CLEAN": "green"}[verdict]
    icon = {"AI METADATA DETECTED": "[X]", "SUSPICIOUS": "[!]", "CLEAN": "[OK]"}[verdict]

    print()
    print(paint(f"{path.name}", "bold", color)
          + paint(f"  ({fmt}, {size / 1024:.0f} KB)", "dim", color))
    print(paint(f"  {icon} {verdict}", tone, color))

    if findings:
        print()
        for f in findings:
            bullet = "!!" if f.severity == "hard" else " ~"
            line = f"  {bullet} {f.label}"
            print(paint(line, "red" if f.severity == "hard" else "yellow", color))
            print(paint(f"       in {f.where}", "dim", color))
            if verbose:
                print(paint(f"       {f.excerpt}", "dim", color))

    if benign:
        print()
        for note in benign:
            print(paint(f"  ok {note}", "green", color))

    if exif_rows:
        print()
        print(paint("  EXIF:", "dim", color))
        for name, value in exif_rows:
            print(paint(f"    {name:<20} {value}", "dim", color))

    # Show the raw metadata whatever the verdict -- on a hit it is the evidence,
    # on a clean file it is the proof that there is nothing to find.
    if not args.no_dump:
        dump_regions(regions, findings, color,
                     limit=10 ** 9 if args.full else args.dump_limit,
                     only_flagged=args.flagged_only)

    if verdict == "AI METADATA DETECTED":
        print()
        print(paint("  -> Platforms read this. Run again with --strip before uploading.",
                    "red", color))
    elif verdict == "SUSPICIOUS":
        print()
        print(paint("  -> No formal AI declaration, but an AI tool left traces. "
                    "--strip is cheap insurance.", "yellow", color))


# --------------------------------------------------------------------------
# Reusable API -- used by the CLI below and by server.py
# --------------------------------------------------------------------------

def analyze(raw: bytes, filename: str = "image", include_content: bool = True) -> dict:
    """Inspect image bytes and return the same structure the CLI's --json prints."""
    if not raw:
        raise ValueError("empty file")

    regions, fmt = extract_regions(raw, Path(filename))
    findings = scan_regions(regions)
    benign = scan_benign(regions)
    verdict, code = verdict_for(findings)
    flagged = {f.where for f in findings}

    return {
        "file": filename,
        "format": fmt,
        "bytes": len(raw),
        "verdict": verdict,
        # Booleans the caller can branch on without parsing the verdict string.
        "ai_detected": code == 1,
        "suspicious": code == 2,
        "clean": code == 0,
        "exit_code": code,
        "findings": [{"severity": f.severity, "label": f.label,
                      "location": f.where, "excerpt": f.excerpt,
                      "matched": f.matched} for f in findings],
        "benign_signals": benign,
        "exif": dict(read_exif_summary(raw, every_tag=True)),
        "metadata_blocks": [
            {"name": r.name, "bytes": len(r.data), "flagged": r.name in flagged,
             **({"content": readable_text(r.data)[0]} if include_content else {})}
            for r in regions
        ],
    }


def strip_bytes(raw: bytes, keep_icc: bool = True) -> bytes:
    """Return the image with every metadata block removed, in memory.

    JPEG/PNG/WebP are rebuilt by copying the compressed image data verbatim, so
    the pixels are untouched. Other containers raise -- the caller decides
    whether to fall back to a lossy Pillow re-save.
    """
    if raw[:2] == b"\xff\xd8":
        return strip_jpeg(raw, keep_icc)
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return strip_png(raw, keep_icc)
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return strip_webp(raw, keep_icc)
    raise ValueError("in-memory strip supports JPEG, PNG and WebP only")


def clean(raw: bytes, filename: str = "image", keep_icc: bool = True) -> dict:
    """Strip metadata and verify the result, reporting both sides."""
    before = analyze(raw, filename, include_content=False)
    stripped = strip_bytes(raw, keep_icc)
    after = analyze(stripped, filename, include_content=False)
    return {
        "before": before,
        "after": after,
        "data": stripped,
        "bytes_removed": len(raw) - len(stripped),
        # False here means a marker survived -- never report success blindly.
        "verified": after["clean"],
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def process(path: Path, args: argparse.Namespace, color: bool) -> int:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        print(paint(f"\n{path.name}\n  [ERR] cannot read: {exc}", "red", color))
        return 3
    if not raw:
        print(paint(f"\n{path.name}\n  [ERR] empty file", "red", color))
        return 3

    regions, fmt = extract_regions(raw, path)
    findings = scan_regions(regions)
    benign = scan_benign(regions)
    verdict, code = verdict_for(findings)
    # When dumping we show the whole EXIF table, not just the usual suspects.
    exif_rows = [] if args.quiet else read_exif_summary(
        path, every_tag=not args.no_dump)

    if args.json:
        import json
        payload = analyze(raw, str(path), include_content=not args.no_dump)
        print(json.dumps(payload, indent=2))
    else:
        report(path, fmt, len(raw), findings, exif_rows, regions, verdict,
               benign, color, args)

    if args.strip:
        dest = path if args.inplace else path.with_suffix(f".clean{path.suffix}")
        try:
            if args.inplace:
                backup = path.with_suffix(path.suffix + ".bak")
                if not backup.exists():
                    shutil.copy2(path, backup)
                tmp = path.with_suffix(path.suffix + ".tmp")
                strip_file(path, raw, tmp, keep_icc=not args.strip_icc)
                tmp.replace(path)
            else:
                strip_file(path, raw, dest, keep_icc=not args.strip_icc)
        except Exception as exc:
            print(paint(f"  [ERR] strip failed: {exc}", "red", color))
            return 3

        leftover = scan_regions(extract_regions(dest.read_bytes(), dest)[0])
        after = "clean" if not leftover else f"{len(leftover)} marker(s) STILL present"
        tone = "green" if not leftover else "red"
        delta = dest.stat().st_size - len(raw)
        print(paint(f"  -> wrote {dest.name}  ({delta:+,} bytes)  verified: {after}",
                    tone, color))
        if args.inplace:
            print(paint(f"     original kept at {path.name}.bak", "dim", color))
        code = 0 if not leftover else 1

    return code


def main() -> int:
    p = argparse.ArgumentParser(
        description="Check images for AI-generated metadata markers "
                    "(C2PA Content Credentials, IPTC digitalSourceType, generator tags).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="exit codes: 0 clean, 1 AI detected, 2 suspicious, 3 error",
    )
    p.add_argument("paths", nargs="+", help="image files, directories, or globs")
    p.add_argument("--strip", action="store_true",
                   help="write a metadata-free copy (JPEG/PNG/WebP are not recompressed)")
    p.add_argument("--inplace", action="store_true",
                   help="with --strip, overwrite the original (a .bak is kept)")
    p.add_argument("--strip-icc", action="store_true",
                   help="also drop the ICC colour profile (may shift colours)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="show matched text and every metadata block")
    p.add_argument("--full", action="store_true",
                   help="print flagged metadata in full, no truncation")
    p.add_argument("--dump-limit", type=int, default=4000, metavar="N",
                   help="characters printed per flagged block (default 4000)")
    p.add_argument("--flagged-only", action="store_true",
                   help="print only the metadata blocks that tripped a signature")
    p.add_argument("--no-dump", action="store_true",
                   help="do not print metadata contents at all")
    p.add_argument("-q", "--quiet", action="store_true", help="skip the EXIF table")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--no-color", action="store_true")
    args = p.parse_args()

    # Metadata is arbitrary text (BOMs, CJK, emoji) but the Windows console is
    # cp1252 -- degrade unencodable characters instead of crashing the run.
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, OSError):
        pass

    color = not args.no_color and sys.stdout.isatty()
    exts = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff", ".avif", ".heic"}

    targets: list[Path] = []
    for spec in args.paths:
        path = Path(spec)
        if path.is_dir():
            targets += sorted(f for f in path.rglob("*") if f.suffix.lower() in exts)
        elif path.exists():
            targets.append(path)
        else:  # unexpanded glob (cmd.exe / PowerShell don't expand for us)
            matched = sorted(Path().glob(spec))
            if matched:
                targets += matched
            else:
                print(f"not found: {spec}", file=sys.stderr)

    if not targets:
        print("no images to check", file=sys.stderr)
        return 3

    worst = 0
    for path in targets:
        worst = worse(worst, process(path, args, color))

    if len(targets) > 1 and not args.json:
        print()
        print(f"  checked {len(targets)} files")
    return worst


if __name__ == "__main__":
    sys.exit(main())
