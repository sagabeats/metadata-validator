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
import datetime
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
    # Video generators. Same idea as the image tools above, but these are
    # the names that turn up in an MP4's udta/ilst/uuid boxes.
    (rb"Veo\s?[23]|google[ _-]?[Vv]eo", "Google Veo"),
    (rb"\bSora\b|openai[ _-]?sora", "OpenAI Sora"),
    (rb"(?i)pika[ _-]?(labs|art)|pikalabs", "Pika"),
    (rb"(?i)hailuo|minimax[ _-]?video", "MiniMax Hailuo"),
    (rb"(?i)\bvidu\b|viduai", "Vidu"),
    (rb"(?i)haiper[ _-]?ai", "Haiper"),
    (rb"(?i)heygen|synthesia|\bd-id\b|deepbrain", "AI avatar / talking-head tool"),
    (rb"(?i)elevenlabs|\bplay\.ht\b|resemble\.ai", "AI voice tool"),
    (rb"(?i)topaz[ _-]?video|\bdescript\b", "AI video enhancer / editor"),
    (rb"(?i)wan2\.\d|wanx|mochi-1|ltx-?video|hunyuanvideo|cogvideo|open-?sora",
     "open-source video generator"),
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

# --- ISO base media (MP4/MOV/M4A, and the HEIC/AVIF stills built on it) ---
# Boxes we descend into rather than dump whole.
ISOBMFF_CONTAINERS = {
    b"moov", b"trak", b"edts", b"mdia", b"minf", b"dinf", b"stbl", b"udta",
    b"mvex", b"moof", b"traf", b"mfra", b"ipro", b"sinf", b"schi", b"tref",
    b"iprp", b"ipco", b"iinf", b"grpl",
}

# Sample tables, timing and chunk offsets -- numbers, never text. Skipping
# them is what turns the report from a `strings` dump of stco/stsz/tkhd noise
# into something readable; nothing in this set can carry an AI marker.
ISOBMFF_SKIP = {
    # mvhd/tkhd/mdhd are pure binary; their dates, duration and geometry are
    # decoded into the tag summary instead of listed as unreadable blocks.
    b"mdat", b"mvhd", b"tkhd", b"mdhd", b"stts", b"stsc", b"stsz", b"stz2", b"stco", b"co64", b"stss",
    b"ctts", b"cslg", b"sdtp", b"sbgp", b"sgpd", b"saiz", b"saio", b"stsh",
    b"trun", b"tfhd", b"tfdt", b"mfhd", b"sidx", b"ssix", b"tfra", b"mfro",
    b"elst", b"dref", b"smhd", b"vmhd", b"nmhd", b"iloc",
}

# `uuid` is ISOBMFF's extension slot, and it is where the two markers that
# matter most in video actually live: XMP and the C2PA manifest.
ISOBMFF_UUIDS = {
    bytes.fromhex("be7acfcb97a942e89c71999491e3afac"): "XMP",
    bytes.fromhex("d8fec3d61b0e483c92975828877ec481"): "C2PA/JUMBF",
    bytes.fromhex("2c4c0100850440b9a03e562148d6dfeb"): "Photoshop/IPTC",
    bytes.fromhex("ffcc8263f8554a938814587a02521fdd"): "XMP (legacy)",
}

BRAND_FORMATS = {
    b"qt  ": "MOV", b"isom": "MP4", b"iso2": "MP4", b"iso4": "MP4",
    b"iso5": "MP4", b"iso6": "MP4", b"mp41": "MP4", b"mp42": "MP4",
    b"avc1": "MP4", b"dash": "MP4", b"cmfc": "MP4", b"M4V ": "M4V",
    b"M4A ": "M4A", b"M4P ": "M4P", b"3gp4": "3GP", b"3gp5": "3GP",
    b"3g2a": "3G2", b"mif1": "HEIF", b"msf1": "HEIF", b"heic": "HEIC",
    b"heix": "HEIC", b"hevc": "HEIC", b"avif": "AVIF", b"avis": "AVIF",
}

# iTunes-style tag atoms, found under moov/udta/meta/ilst and -- for the
# QuickTime ones -- directly under moov/udta.
ILST_TAGS = {
    b"\xa9nam": "Title", b"\xa9ART": "Artist", b"\xa9alb": "Album",
    b"\xa9cmt": "Comment", b"\xa9gen": "Genre", b"\xa9day": "Date",
    b"\xa9too": "Encoder", b"\xa9swr": "Software", b"\xa9enc": "EncodedBy",
    b"\xa9wrt": "Composer", b"\xa9cpy": "Copyright", b"\xa9inf": "Information",
    b"\xa9mak": "Make", b"\xa9mod": "Model", b"\xa9xyz": "GPSCoordinates",
    b"\xa9des": "Description", b"\xa9prd": "Producer", b"\xa9cmr": "CameraSoftware",
    b"desc": "Description", b"ldes": "LongDescription", b"cprt": "Copyright",
    b"auth": "Author", b"titl": "Title", b"perf": "Performer",
    b"albm": "Album", b"yrrc": "Year",
}

# QuickTime `keys`-flavoured metadata names its tags by reverse-DNS string.
QT_KEY_TAGS = {
    "com.apple.quicktime.software": "Software",
    "com.apple.quicktime.make": "Make",
    "com.apple.quicktime.model": "Model",
    "com.apple.quicktime.creationdate": "CreateDate",
    "com.apple.quicktime.title": "Title",
    "com.apple.quicktime.author": "Author",
    "com.apple.quicktime.description": "Description",
    "com.apple.quicktime.comment": "Comment",
    "com.apple.quicktime.copyright": "Copyright",
    "com.apple.quicktime.location.ISO6709": "GPSCoordinates",
    "com.android.version": "AndroidVersion",
    "com.android.capture.fps": "CaptureFrameRate",
}

# MP4 timestamps count from 1904-01-01 UTC, not the Unix epoch.
ISO_EPOCH = 2_082_844_800

# A leaf box should never be huge once mdat is out of the way, but an unknown
# proprietary box could be -- cap what we carry into the report.
ISOBMFF_REGION_CAP = 4 * 1024 * 1024


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


# --------------------------------------------------------------------------
# ISO base media parser -- MP4/MOV/M4A and the HEIC/AVIF stills built on it
# --------------------------------------------------------------------------
# Before this existed an MP4 fell through to the "unknown container" branch in
# extract_regions() and the report was a `strings` dump of the entire file:
# one undifferentiated block, box names (stco, stsz, tkhd) as noise, and an
# empty EXIF table. Everything worth reading in an MP4 sits in a named box, so
# walk the tree and report per box the way parse_jpeg does per APP segment.

def is_isobmff(raw: bytes) -> bool:
    """True for ISO base media files -- MP4, MOV, M4A, HEIC, AVIF.

    They open with a `ftyp` box. A few QuickTime writers lead with `moov`,
    `mdat`, `free` or `wide` instead, so accept those when the leading length
    reads like a real box header.
    """
    if len(raw) < 12:
        return False
    if raw[4:8] in (b"ftyp", b"styp"):
        return True
    return (raw[4:8] in (b"moov", b"mdat", b"free", b"skip", b"wide", b"pnot")
            and 8 <= int.from_bytes(raw[:4], "big") <= len(raw))


def _iso_boxes(buf: bytes, start: int, end: int):
    """Yield (type, start, end, header_size) for each box in [start, end).

    Stops rather than raises on a malformed length -- half a tree is still
    worth reporting, and partial files are normal here: the browser sends
    ftyp+moov only, so it never ships the 170 MB of frames.
    """
    i = start
    while i + 8 <= end:
        size = int.from_bytes(buf[i:i + 4], "big")
        btype = buf[i + 4:i + 8]
        header = 8
        if size == 1:  # 64-bit length lives in the eight bytes after the type
            if i + 16 > end:
                return
            size = int.from_bytes(buf[i + 8:i + 16], "big")
            header = 16
        elif size == 0:  # "runs to the end of the file"
            size = end - i
        if size < header or i + size > end:
            return
        yield btype, i, i + size, header
        i += size


def _looks_like_box(buf: bytes, at: int, end: int) -> bool:
    if at + 8 > end:
        return False
    size = int.from_bytes(buf[at:at + 4], "big")
    return (all(32 <= b < 127 for b in buf[at + 4:at + 8])
            and (size in (0, 1) or 8 <= size <= end - at))


def _meta_children(buf: bytes, start: int, end: int) -> int:
    """Where `meta`'s children begin.

    ISO BMFF makes `meta` a FullBox -- four version/flags bytes before the
    first child -- but QuickTime-flavoured writers emit it as a bare container.
    Guessing wrong loses the whole tag table, so test both.
    """
    return start if _looks_like_box(buf, start, end) else start + 4


def _box_label(btype: bytes) -> str:
    # latin-1, not ascii: the iTunes tag atoms open with 0xA9 and should read
    # as the copyright sign rather than a replacement character.
    return btype.decode("latin-1").strip()


def _iso_region(name: str, data: bytes, offset: int) -> Region:
    if len(data) > ISOBMFF_REGION_CAP:
        return Region(f"{name} (first {ISOBMFF_REGION_CAP // (1024 * 1024)} MB)",
                      data[:ISOBMFF_REGION_CAP], offset)
    return Region(name, data, offset)


def parse_mp4(raw: bytes) -> tuple[list[Region], str]:
    regions: list[Region] = []

    def walk(start: int, end: int, path: str, depth: int) -> None:
        if depth > 8:
            return
        boxes = list(_iso_boxes(raw, start, end))
        # Two tracks mean two moov/trak/mdia/hdlr boxes; number the repeats so
        # a finding points at the one it came from.
        totals: dict[bytes, int] = {}
        for btype, _s, _e, _h in boxes:
            totals[btype] = totals.get(btype, 0) + 1
        seen: dict[bytes, int] = {}

        for btype, box_start, box_end, header in boxes:
            if btype in ISOBMFF_SKIP:
                continue
            seen[btype] = seen.get(btype, 0) + 1
            label = _box_label(btype)
            if totals[btype] > 1:
                label = f"{label}[{seen[btype]}]"
            here = f"{path}/{label}" if path else label
            body_at = box_start + header

            if btype == b"uuid":
                uid = raw[body_at:body_at + 16]
                known = ISOBMFF_UUIDS.get(uid, f"unknown {uid.hex()[:8]}")
                regions.append(_iso_region(f"uuid box ({known})",
                                           raw[body_at + 16:box_end], box_start))
                continue
            if btype == b"meta":
                walk(_meta_children(raw, body_at, box_end), box_end, here, depth + 1)
                continue
            if btype in ISOBMFF_CONTAINERS:
                walk(body_at, box_end, here, depth + 1)
                continue

            payload = raw[body_at:box_end]
            # free/skip/wide are usually reserved padding, but writers do park
            # leftovers there -- keep the ones holding actual bytes.
            if btype in (b"free", b"skip", b"wide") and not payload.strip(b"\x00"):
                continue
            regions.append(_iso_region(f"{here} box", payload, box_start))

    top = list(_iso_boxes(raw, 0, len(raw)))
    walk(0, len(raw), "", 0)

    consumed = top[-1][2] if top else 0
    if consumed < len(raw) and raw[consumed:].strip(b"\x00"):
        regions.append(_iso_region("trailing data after last box",
                                   raw[consumed:], consumed))

    if not regions:  # unreadable tree -- report the bytes rather than nothing
        regions.append(Region("whole file (unparsed ISOBMFF)", raw, 0))

    brand = b""
    for btype, box_start, _e, header in top:
        if btype == b"ftyp":
            brand = raw[box_start + header:box_start + header + 4]
            break
    fmt = BRAND_FORMATS.get(brand)
    if not fmt:
        fmt = f"ISOBMFF ({_box_label(brand)})" if brand.strip() else "ISOBMFF"
    return regions, fmt


# --------------------------------------------------------------------------
# ISO base media tag summary -- the MP4 answer to the EXIF table
# --------------------------------------------------------------------------

def _iso_time(seconds: int) -> str:
    try:
        stamp = datetime.datetime.fromtimestamp(seconds - ISO_EPOCH,
                                                datetime.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return ""
    return stamp.strftime("%Y-%m-%d %H:%M:%S UTC")


def _hms(seconds: float) -> str:
    total = int(round(seconds))
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _mvhd_rows(payload: bytes) -> dict[str, str]:
    """Creation/modification stamps and duration from the movie header."""
    if len(payload) < 20:
        return {}
    if payload[0] == 1:
        if len(payload) < 32:
            return {}
        created = int.from_bytes(payload[4:12], "big")
        modified = int.from_bytes(payload[12:20], "big")
        timescale = int.from_bytes(payload[20:24], "big")
        duration = int.from_bytes(payload[24:32], "big")
    else:
        created = int.from_bytes(payload[4:8], "big")
        modified = int.from_bytes(payload[8:12], "big")
        timescale = int.from_bytes(payload[12:16], "big")
        duration = int.from_bytes(payload[16:20], "big")

    rows: dict[str, str] = {}
    if created:
        rows["CreateDate"] = _iso_time(created)
    if modified:
        rows["ModifyDate"] = _iso_time(modified)
    # 0xFFFFFFFF is the "unknown duration" sentinel fragmented files write.
    if timescale and duration and duration != 0xFFFFFFFF:
        rows["Duration"] = _hms(duration / timescale)
    return rows


def _hdlr_name(payload: bytes) -> str:
    """A track handler's name -- often the only provenance string in the file.

    YouTube's own exports write "ISO Media file produced by Google Inc." here.
    """
    if len(payload) < 24:
        return ""
    name = payload[24:]
    if name[:1] and name[0] == len(name) - 1:  # QuickTime writes a Pascal string
        name = name[1:]
    return name.split(b"\x00")[0].decode("utf-8", "replace").strip()


def _stsd_rows(payload: bytes) -> dict[str, str]:
    """Codec, frame size, and the 32-byte compressor name the encoder stamps."""
    if len(payload) < 16:
        return {}
    entry_size = int.from_bytes(payload[8:12], "big")
    entry = payload[8:8 + entry_size]
    if len(entry) < 86:
        return {}
    width = int.from_bytes(entry[32:34], "big")
    height = int.from_bytes(entry[34:36], "big")
    if not (0 < width < 20_000 and 0 < height < 20_000):
        return {}  # an audio or subtitle entry -- it has no visual fields

    rows = {"VideoCodec": _box_label(entry[4:8]), "ImageSize": f"{width}x{height}"}
    length = entry[50]
    if 0 < length <= 31:
        name = entry[51:51 + length].decode("utf-8", "replace").strip()
        if name:
            rows["CompressorName"] = name
    return rows


def _keys_list(payload: bytes) -> list[str]:
    """The `keys` table that `ilst` indexes into. Its entries are shaped like
    boxes whose type field is the namespace and whose body is the tag name."""
    return [payload[start + header:end].decode("utf-8", "replace")
            for _ns, start, end, header in _iso_boxes(payload, 8, len(payload))]


def _qt_key_name(key: str) -> str:
    named = QT_KEY_TAGS.get(key)
    if named:
        return named
    tail = key.rsplit(".", 1)[-1]
    return tail[:1].upper() + tail[1:] if tail else key


def _ilst_value(blob: bytes) -> str:
    for btype, start, end, header in _iso_boxes(blob, 0, len(blob)):
        if btype != b"data" or end - start < header + 8:
            continue
        kind = int.from_bytes(blob[start + header:start + header + 4], "big") & 0xFFFFFF
        body = blob[start + header + 8:end]
        if kind == 1:
            return body.decode("utf-8", "replace").strip()
        if kind == 2:
            return body.decode("utf-16-be", "replace").strip()
        if kind in (21, 22) and 1 <= len(body) <= 8:
            return str(int.from_bytes(body, "big", signed=kind == 21))
        return " ".join(m.group(0).decode("ascii")
                        for m in re.finditer(rb"[\x20-\x7e]{4,}", body))
    return ""


def _ilst_rows(payload: bytes, keys: list[str]) -> dict[str, str]:
    rows: dict[str, str] = {}
    for btype, start, end, header in _iso_boxes(payload, 0, len(payload)):
        if keys:
            # mdta-flavoured metadata numbers each item into the keys table.
            index = int.from_bytes(btype, "big")
            name = _qt_key_name(keys[index - 1]) if 1 <= index <= len(keys) else ""
        else:
            name = ILST_TAGS.get(btype) or _box_label(btype).lstrip("\xa9")
        value = _ilst_value(payload[start + header:end])
        if name and value:
            rows.setdefault(name, value)
    return rows


def _udta_text(payload: bytes) -> str:
    """QuickTime text atoms sitting straight under udta: length, language, text."""
    if len(payload) < 4:
        return ""
    length = int.from_bytes(payload[0:2], "big")
    if 0 < length <= len(payload) - 4:
        return payload[4:4 + length].decode("utf-8", "replace").strip()
    # Writers do get that length field wrong. Decoding the whole atom anyway
    # would put the length and language bytes into the report as mojibake, so
    # take the longest printable run instead.
    runs = re.findall(rb"[\x20-\x7e]{3,}", payload)
    return max(runs, key=len).decode("ascii") if runs else ""


def read_video_summary(raw: bytes) -> list[tuple[str, str]]:
    """The ISOBMFF answer to read_exif_summary: who wrote this file, when, how."""
    rows: dict[str, str] = {}
    keys: list[str] = []
    ilst_blobs: list[bytes] = []
    handlers: list[str] = []
    extensions: list[str] = []

    def put(name: str, value: object) -> None:
        text = str(value).strip().replace("\x00", "")
        if text and name not in rows:
            rows[name] = text[:120]

    def visit(parent: bytes, start: int, end: int, depth: int) -> None:
        if depth > 8:
            return
        for btype, box_start, box_end, header in _iso_boxes(raw, start, end):
            body = raw[box_start + header:box_end]
            if btype == b"ftyp":
                put("MajorBrand", _box_label(body[:4]))
                rest = [_box_label(body[i:i + 4]) for i in range(8, len(body), 4)]
                put("CompatibleBrands", " ".join(b for b in rest if b))
            elif btype == b"mvhd":
                for name, value in _mvhd_rows(body).items():
                    put(name, value)
            elif btype == b"hdlr":
                name = _hdlr_name(body)
                if name and name not in handlers:
                    handlers.append(name)
            elif btype == b"stsd":
                for name, value in _stsd_rows(body).items():
                    put(name, value)
            elif btype == b"keys":
                keys.extend(_keys_list(body))
            elif btype == b"ilst":
                ilst_blobs.append(body)
            elif btype == b"uuid" and body[:16] in ISOBMFF_UUIDS:
                known = ISOBMFF_UUIDS[body[:16]]
                if known not in extensions:
                    extensions.append(known)
            elif parent == b"udta" and btype in ILST_TAGS:
                put(ILST_TAGS[btype], _udta_text(body))

            if btype == b"meta":
                visit(btype, _meta_children(raw, box_start + header, box_end),
                      box_end, depth + 1)
            elif btype in ISOBMFF_CONTAINERS:
                visit(btype, box_start + header, box_end, depth + 1)

    visit(b"", 0, len(raw), 0)

    # ilst is resolved last: `keys` can be collected after it during the walk,
    # and without that table its item types are bare indices.
    for blob in ilst_blobs:
        for name, value in _ilst_rows(blob, keys).items():
            put(name, value)
    if handlers:
        put("HandlerDescription", ", ".join(handlers))
    if extensions:
        put("ExtensionBoxes", ", ".join(extensions))
    return list(rows.items())


def read_tag_summary(raw: bytes, every_tag: bool = False) -> list[tuple[str, str]]:
    """EXIF for stills, container tags for ISOBMFF video -- one shape either way."""
    if is_isobmff(raw):
        return read_video_summary(raw)
    return read_exif_summary(raw, every_tag=every_tag)


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
    if is_isobmff(raw):
        return parse_mp4(raw)
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

# Formats whose tag table comes from box walking, not EXIF.
ISO_TAG_FORMATS = set(BRAND_FORMATS.values()) | {"ISOBMFF"}

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
        label = "container tags" if fmt in ISO_TAG_FORMATS else "EXIF"
        print(paint(f"  {label}:", "dim", color))
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
        "exif": dict(read_tag_summary(raw, every_tag=True)),
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
    raise ValueError("in-memory strip supports JPEG, PNG and WebP only; "
                     "MP4/MOV can be checked but not yet stripped")


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
    exif_rows = [] if args.quiet else read_tag_summary(
        raw, every_tag=not args.no_dump)

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
