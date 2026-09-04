# Detection

**Applies to:** Anyone adding a signature, or disputing a verdict
**Related documents:** [Overview](OVERVIEW.md) · [Signature reference](../reference/SIGNATURES.md) · [Containers](CONTAINERS.md) · [Contributing](../standards/CONTRIBUTING.md)

Detection is three tables of byte patterns and one three-line rule. The value of
this document is the reasoning behind which table a pattern belongs in, because
putting it in the wrong one is the only way to make the tool useless.

## The two severities

| Severity | Table               | Claim being made                                                       | Effect on verdict                       |
| -------- | ------------------- | ---------------------------------------------------------------------- | --------------------------------------- |
| `hard`   | `HARD_SIGNATURES`   | The file **formally declares** AI involvement, in a format platforms parse | `AI METADATA DETECTED`, `ai_detected=true` |
| `soft`   | `SOFT_SIGNATURES`   | An AI tool **left a fingerprint**, without declaring anything            | `SUSPICIOUS` at most                    |

This is the load-bearing distinction in the whole project.

A `hard` finding means an upload will be labelled. A `soft` finding means it
might, or might not, and a human should decide. Collapsing the two would flag
every Photoshop export and callers would learn to ignore the verdict entirely —
which is the failure mode this design exists to avoid.

`server.py` and the Next.js reference handler both act on it: the handler
returns `willBeLabeled` from `ai_detected` alone, and lists `soft` findings
separately as `traces`.

## What counts as hard

Three families, and nothing else:

**C2PA / Content Credentials.** The signed manifest that Adobe, OpenAI, Google
and the Content Authenticity Initiative embed to record how an image was made.
Matched by its structural strings — `c2pa.assertions`, `c2pa.actions`,
`c2pa.claim`, the manifest URN, `jumbf`, `contentauth`, `contentcredentials`.
This is what YouTube actually reads.

**IPTC `digitalSourceType`.** The standardised field whose value declares the
origin of the file. Only the AI-valued variants are hard hits:
`trainedAlgorithmicMedia` (fully AI-generated),
`compositeWithTrainedAlgorithmicMedia` (partly AI), `algorithmicMedia`
(algorithm-generated).

There is deliberately **no bare `digitalSourceType` pattern**. The same field
declares `digitalCapture` for a real photograph, which is the opposite of a hit.
Adding the bare name would flag every camera JPEG that carries proper IPTC.

**Vendor declarations.** Canva's `ContainsAiGeneratedContent>Yes`, and Google's
`SynthID` marker. Note that Canva writes the same element with `No`, so this one
is matched by value; the `No` form is a benign signal instead.

## What counts as soft

Two kinds:

**Named tools.** Around fifty generator, editor and enhancer names that turn up
in `Software`, `Creator Tool`, XMP history or an MP4 tag: Midjourney, DALL·E,
Stable Diffusion, ComfyUI, Firefly, Generative Fill, Imagen, Gemini, Grok, FLUX,
Ideogram, Topaz, remove.bg, Runway, Veo, Sora, Pika, ElevenLabs, and so on. The
full list is in [reference/SIGNATURES.md](../reference/SIGNATURES.md).

**Workflow fingerprints.** Patterns that no photograph produces but every
diffusion pipeline does — `negative prompt`, `Steps: … CFG`, a sampler name,
`denoising_strength`, `Model hash:`, `.safetensors`, a LoRA reference, a
six-digit-or-longer seed.

The generic `ai[_ -]?generated` pattern carries a lookbehind, `(?<!contains)`,
which keeps it off Canva's `ContainsAiGeneratedContent` namespace. Without it,
a Canva export declaring **no** AI content would still trip the generic string.

## Benign signals

`BENIGN_SOURCE_TYPES` collects metadata that argues *against* AI:
`digitalSourceType = digitalCapture`, scanned film or print values, and Canva's
`ContainsAiGeneratedContent>No`.

**Benign signals never change the verdict.** They are printed under the findings
and returned as `benign_signals` so a human can weigh them. A file can carry
both a `digitalCapture` declaration and a C2PA manifest — a photograph edited
with Generative Fill does exactly that — and the C2PA manifest is still what the
platform will act on.

## How a scan runs

`scan_regions()` walks each region produced by the container parser:

```text
for each region:
    haystacks = [region.data]
    if the first 200 bytes contain a NUL:
        haystacks += [region.data with NULs removed]

    for table in (HARD, SOFT):          # hard first, so severity is stable
        for pattern, label in table:
            for haystack in haystacks:
                match -> record one Finding, stop searching this pattern
```

Three details matter:

**UTF-16 handling.** XMP packets are frequently UTF-16, which puts a NUL between
every ASCII character. The patterns are ASCII byte strings and would never match.
Stripping NULs from a second copy of the buffer makes them match, at the cost of
one extra pass over blobs that look wide-encoded.

**Deduplication by `(label, region)`.** The key is the pair, not the label alone.
A C2PA manifest split across several `APP11` segments reports once per segment —
which is informative, since it tells you where the manifest lives — but a single
segment mentioning `c2pa.actions` forty times reports once.

**First match wins per pattern.** Only `re.search`, never `finditer`. The excerpt
is taken from the first hit, 60 bytes wide, with non-printable bytes rendered as
dots. It exists to make a report legible, not to be exhaustive.

## What a finding contains

| Field      | Meaning                                                                     |
| ---------- | --------------------------------------------------------------------------- |
| `severity` | `hard` or `soft`                                                            |
| `label`    | The human explanation from the table, e.g. `C2PA action log`                |
| `location` | The region name, e.g. `APP11 (JUMBF/C2PA)`, `iTXt chunk`, `moov/udta box`   |
| `matched`  | The literal text that tripped the pattern, decoded UTF-8 with replacement    |
| `excerpt`  | ~60 printable bytes around the match, for context                            |

`location` is what makes a finding actionable. It tells you which block to look
at in the metadata dump, and — if you are stripping by hand — which segment to
remove.

## Where the detection is weakest

Documented honestly, because callers should know:

- **Signature tables are a denylist.** A generator not in the table produces no
  soft finding. New tools appear constantly; the table needs maintenance.
- **A hard hit requires the marker to be present as text.** A C2PA manifest is
  CBOR inside JUMBF, and the structural strings happen to survive as readable
  bytes. A future binary-only encoding would evade the current patterns.
- **Nothing verifies a C2PA signature.** The presence of the manifest is the
  signal; whether it validates is not checked, and platforms may treat an invalid
  manifest differently.
- **`SynthID` is matched as a metadata string only.** The pixel watermark it
  names is not decoded and cannot be, here.
- **False positives are possible on prose.** A file whose description literally
  contains the phrase "AI generated" trips the generic soft pattern. It is a
  soft finding, which is the correct weight for it.

## Adding a signature

The rule is one question: **does a platform read this field and act on it?**

- Yes → `HARD_SIGNATURES`.
- No, but only an AI tool would write it → `SOFT_SIGNATURES`.
- It declares the file is *not* AI → `BENIGN_SOURCE_TYPES`.

Then check the pattern cannot match the negative form of the same field. That
mistake has been made once already, and the lookbehind on the generic pattern is
the scar. Procedure and review expectations:
[standards/CONTRIBUTING.md](../standards/CONTRIBUTING.md).

## References

- [Signature reference](../reference/SIGNATURES.md)
- [Overview](OVERVIEW.md)
- [Containers](CONTAINERS.md)
- [Contributing](../standards/CONTRIBUTING.md)
- [C2PA specifications](https://c2pa.org/specifications/specifications/2.1/index.html)
- [IPTC digitalSourceType vocabulary](https://cv.iptc.org/newscodes/digitalsourcetype/)
- [YouTube: disclosing altered or synthetic content](https://support.google.com/youtube/answer/14328491)
