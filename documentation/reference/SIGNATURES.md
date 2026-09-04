# Signature reference

**Applies to:** Anyone explaining a finding, or adding a pattern
**Related documents:** [Detection](../architecture/DETECTION.md) · [Contributing](../standards/CONTRIBUTING.md)

The complete signature tables from
[ai_metadata_check.py](../../ai_metadata_check.py), with what each pattern means
in practice. The source is authoritative when this page falls behind it.

Patterns are byte regexes matched against each metadata region, and against a
NUL-stripped copy of that region when it looks UTF-16 encoded. Findings are
deduplicated by `(label, region)`.

## Hard signatures

A match sets `ai_detected=true` and the verdict `AI METADATA DETECTED`. These are
the fields platforms read and act on.

### C2PA / Content Credentials

The signed manifest embedded by Adobe, OpenAI, Google, and the Content
Authenticity Initiative. This is what YouTube actually reads. In a JPEG it lives
in `APP11`; in an MP4, in a `uuid` box.

| Pattern                    | Label                                        |
| -------------------------- | -------------------------------------------- |
| `c2pa.assertions`          | C2PA assertion store                         |
| `c2pa.actions`             | C2PA action log (records how the image was made) |
| `c2pa.claim`               | C2PA claim                                   |
| `urn:uuid:.{0,40}c2pa`     | C2PA manifest URN                            |
| `contentauth`              | Content Authenticity Initiative manifest     |
| `contentcredentials`       | Content Credentials manifest                 |
| `jumbf`                    | JUMBF box (C2PA container)                   |

### IPTC digitalSourceType

The standardised field whose value declares how the file was produced. Only the
AI-valued variants are hard hits.

| Pattern                                | Label                                                        |
| -------------------------------------- | ------------------------------------------------------------ |
| `trainedAlgorithmicMedia`              | Declares **fully** AI-generated                              |
| `compositeWithTrainedAlgorithmicMedia` | Declares **partly** AI — a composite with generated content  |
| `algorithmicMedia`                     | Declares algorithm-generated                                 |

There is deliberately no bare `digitalSourceType` pattern. The same field
declares `digitalCapture` for a real photograph, and matching the field name
alone would flag every camera JPEG carrying proper IPTC.

### Vendor declarations

| Pattern                            | Label                                                     |
| ---------------------------------- | --------------------------------------------------------- |
| `ContainsAiGeneratedContent>\s*Yes` | Canva declares AI content in the design                   |
| `(?i)synthid`                      | Google SynthID marker                                     |

Canva stamps `ContainsAiGeneratedContent` on export whenever an AI feature
touched the design — and writes the same element with `No` when none did, which
is why this one is matched by value. The `No` form is a benign signal.

`SynthID` is matched as a metadata string. The pixel watermark it refers to is
not decoded here and cannot be.

## Benign signals

Metadata arguing that the file is camera-originated. Reported as context;
**never changes the verdict**.

| Pattern                              | Label                                              |
| ------------------------------------ | -------------------------------------------------- |
| `digitalCapture`                     | Declared camera original                           |
| `negativeFilm`, `positiveFilm`, `print` | Scanned film or print                           |
| `ContainsAiGeneratedContent>\s*No`   | Canva export declares no AI content                |

A file can carry both a benign signal and a hard finding — a photograph edited
with Generative Fill does exactly that — and the hard finding is what the
platform acts on.

## Soft signatures

A match sets the verdict `SUSPICIOUS` unless a hard finding also exists. These
mean an AI tool touched the file without declaring anything.

### Image generators

| Label                            | Matches on                                        |
| -------------------------------- | ------------------------------------------------- |
| Midjourney                       | `Midjourney`                                      |
| DALL-E / OpenAI                  | `DALL·E`, `DALLE` and its punctuation variants    |
| OpenAI                           | `openai.com`, `OpenAI`                            |
| Stable Diffusion                 | `Stable Diffusion`, `stable-diffusion`            |
| AUTOMATIC1111 WebUI              | `Automatic1111`                                   |
| ComfyUI                          | `ComfyUI`, `comfyanonymous`                       |
| InvokeAI                         | `InvokeAI`                                        |
| Adobe Firefly                    | `Firefly`                                         |
| Photoshop Generative Fill / Expand | `Generative Fill`, `generative_fill`, `Generative Expand` |
| Adobe Express                    | `Adobe Express`                                   |
| Google Imagen                    | `Imagen`, `imagen-3`, `imagen-4`                  |
| Google Gemini                    | `Gemini`, `gemini-`                               |
| Google Nano Banana               | `NanoBanana`, `nano-banana`                       |
| xAI Grok / Aurora                | `Grok`, `grok-`, `xAI`                            |
| Leonardo.Ai                      | `Leonardo.Ai`, `leonardo.ai`                      |
| Ideogram                         | `Ideogram`                                        |
| FLUX / Black Forest Labs         | `black-forest-labs`, `FLUX.1`                     |
| Recraft                          | `Recraft`                                         |
| Playground AI                    | `Playground AI`, `playgroundai`                   |
| NightCafe                        | `NightCafe`                                       |
| Craiyon                          | `Craiyon`                                         |
| DreamStudio                      | `DreamStudio`                                     |
| Microsoft Designer / Bing Image Creator | `Bing Image Creator`, `Image Creator`, `Designer.microsoft` |
| Microsoft Copilot                | `Copilot`                                         |
| Meta AI / Emu                    | `Meta AI`, `Emu`                                  |
| ByteDance Seedream / Jimeng      | `seedream`, `Doubao`, `Jimeng`                    |
| Alibaba Qwen-Image / Tongyi      | `Qwen-Image`, `Tongyi`, `Wanx`                    |
| Tencent Hunyuan                  | `Hunyuan`                                         |

### Editors, enhancers, upscalers

These are the ones that catch people out. None of them generates an image from
nothing, and all of them stamp the file.

| Label                          | Matches on                                    |
| ------------------------------ | --------------------------------------------- |
| Canva Magic Media              | `Magic Media`, `magic-media`                  |
| Canva Magic Studio             | `Magic Studio`                                |
| Picsart AI                     | `Picsart AI`, `picsart_ai`                    |
| Fotor AI                       | `Fotor AI`                                    |
| remove.bg (AI background removal) | `remove.bg`, `removebg`                    |
| Topaz AI upscaler              | `Topaz Gigapixel`, `Topaz Photo AI`, `Topaz Labs` |
| Let's Enhance (AI upscaler)    | `Let's Enhance`, `letsenhance`                |
| AI upscaler (ESRGAN family)    | `waifu2x`, `Real-ESRGAN`, `ESRGAN`            |
| Freepik AI / Pikaso            | `Freepik AI`, `Pikaso`                        |
| Krea AI                        | `Krea`                                        |

### Diffusion workflow fingerprints

Patterns no photograph produces and every diffusion pipeline does. These are how
a locally generated image is caught even when the tool never named itself.

| Label                            | Matches on                                    |
| -------------------------------- | --------------------------------------------- |
| Diffusion "negative prompt" block | `negative prompt`, `negative_prompt`          |
| Diffusion sampler parameters     | `Steps: <n> … CFG`                            |
| Diffusion sampler name           | `sampler:` followed by euler, dpm, ddim, lms, heun or unipc |
| Diffusion denoising_strength     | `denoising_strength`                          |
| Diffusion model hash             | `Model hash:`                                 |
| Model checkpoint reference       | `.safetensors`, `.ckpt`                       |
| LoRA reference                   | `<lora:`, `lora_name`, `lora_weight`, `lora_hash`, `lora_model` |
| Latent upscaler                  | `latent upscal…`                              |
| Generation seed                  | `seed` followed by six or more digits         |
| Explicit "AI generated" string   | `ai generated`, `ai-generated`, `aigc`        |
| Generative AI reference          | `generative ai`, `genai`                      |

The "AI generated" pattern carries a `(?<!contains)` lookbehind so it cannot fire
on Canva's `ContainsAiGeneratedContent` namespace, which declares `Yes` **or**
`No` and is judged by value in the hard table instead.

### Video generators and tools

The names that turn up in an MP4's `udta`, `ilst` or `uuid` boxes.

| Label                          | Matches on                                                    |
| ------------------------------ | ------------------------------------------------------------- |
| Google Veo                     | `Veo 2`, `Veo 3`, `google-veo`                                |
| OpenAI Sora                    | `Sora`, `openai-sora`                                         |
| Pika                           | `pika labs`, `pika-art`, `pikalabs`                           |
| MiniMax Hailuo                 | `hailuo`, `minimax-video`                                     |
| Vidu                           | `vidu`, `viduai`                                              |
| Haiper                         | `haiper-ai`                                                   |
| Runway                         | `RunwayML`, `runwayml`                                        |
| Luma AI                        | `Luma AI`, `lumalabs`                                         |
| Kling AI                       | `Kling`, `kling-ai`                                           |
| AI avatar / talking-head tool  | `heygen`, `synthesia`, `d-id`, `deepbrain`                    |
| AI voice tool                  | `elevenlabs`, `play.ht`, `resemble.ai`                        |
| AI video enhancer / editor     | `topaz-video`, `descript`                                     |
| Open-source video generator    | `wan2.x`, `wanx`, `mochi-1`, `ltx-video`, `hunyuanvideo`, `cogvideo`, `open-sora` |

## Where a finding is reported

The `location` on a finding is the metadata region it came from. Common ones:

| Location                   | Container | Typically holds                             |
| -------------------------- | --------- | ------------------------------------------- |
| `APP1 (EXIF/XMP)`          | JPEG      | EXIF, XMP — most soft hits                  |
| `APP11 (JUMBF/C2PA)`       | JPEG      | The C2PA manifest                           |
| `APP13 (Photoshop/IPTC)`   | JPEG      | IPTC, including `digitalSourceType`         |
| `iTXt chunk`, `tEXt chunk` | PNG       | Generation parameters from local tools      |
| `eXIf chunk`               | PNG       | EXIF                                        |
| `XMP  chunk`, `C2PA chunk` | WebP      | XMP, C2PA                                   |
| `uuid box (C2PA/JUMBF)`    | MP4/MOV   | The C2PA manifest                           |
| `moov/udta/meta/ilst box`  | MP4/MOV   | Encoder, Software, Title tags               |
| `trailing data after EOI`  | JPEG      | Anything appended past the end marker       |

Region naming is explained in
[architecture/CONTAINERS.md](../architecture/CONTAINERS.md).

## Known gaps

- The tables are a denylist. A generator absent from them produces no soft
  finding.
- A hard hit needs the marker to survive as readable bytes. A future binary-only
  C2PA encoding would evade the current patterns.
- No C2PA signature is validated; presence is the signal.
- Prose containing the literal phrase "AI generated" produces a soft finding.
  That is the correct weight for it, not a bug.

## References

- [Detection](../architecture/DETECTION.md)
- [Containers](../architecture/CONTAINERS.md)
- [Contributing](../standards/CONTRIBUTING.md)
- [C2PA specifications](https://c2pa.org/specifications/specifications/2.1/index.html)
- [IPTC digitalSourceType vocabulary](https://cv.iptc.org/newscodes/digitalsourcetype/)
- [Content Authenticity Initiative](https://contentauthenticity.org/)
