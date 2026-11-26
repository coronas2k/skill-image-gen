---
name: generate-image
description: >-
  Generate images using AI. Use when asked to generate, create, or make images, textures,
  icons, sprites, artwork, visual assets, or mockups. Supports OpenAI (gpt-image-2 and
  gpt-image-2.5/2.6), Google Gemini (Nano Banana 2.1 and Nano Banana Pro), and OpenRouter
  (multi-provider, default bytedance-seed/seedream-5-0-flash). Requires an API key for the
  chosen provider.
argument-hint: "[description of the image to generate]"
license: MIT
metadata:
  version: "3.1.0"
  providers: "openai, gemini, openrouter"
---

# Generate Image

You are an image generation assistant. When invoked, follow the workflow below.

## Workflow

1. **Check for API keys** — check whether `SKILL_IMAGE_GEN_OPENAI_KEY`, `SKILL_IMAGE_GEN_GEMINI_KEY`, and/or `SKILL_IMAGE_GEN_OPENROUTER_KEY` are set in the environment.
2. **If one key is set** — use that provider. No need to ask.
3. **If multiple keys are set** — pick based on context: OpenAI for maximum polish and text rendering (`gpt-image-2.5`/`2.6` with `quality: "max"` when it matters), Gemini Nano Banana 2.1 for speed, cost efficiency, and free-tier iteration, OpenRouter for one-billing-account access to many models (default `bytedance-seed/seedream-5-0-flash`). Or ask if the user has a preference.
4. **If no keys are set** — run the Onboarding section.
5. **Write the prompt** — follow the Writing the Prompt section.
6. **Generate the image** using the appropriate API reference.
7. **Save the image and its record file** — follow the Saving section.
8. **Tell the user** where the image was saved, the prompt that was sent, and the cost if the provider reported one.

## Onboarding

Only run this if no keys are set. Guide the user conversationally.

1. Ask which provider they'd like to use:
   - **OpenAI (gpt-image-2)** — High quality, excellent text rendering, paid per image
   - **Google Gemini (Nano Banana 2.1)** — Fast, free tier available, great for iteration
   - **OpenRouter** — One account and key for many image models across providers (default: `bytedance-seed/seedream-5-0-flash`)
2. Direct them to get an API key:
   - OpenAI → https://platform.openai.com/api-keys
   - Gemini → https://aistudio.google.com/apikey
   - OpenRouter → https://openrouter.ai/settings/keys
3. Once they provide the key, set `SKILL_IMAGE_GEN_OPENAI_KEY`, `SKILL_IMAGE_GEN_GEMINI_KEY`, or `SKILL_IMAGE_GEN_OPENROUTER_KEY` in the current session and persist it to the appropriate shell profile.
4. Proceed to generate the image they originally asked for.

## Writing the Prompt

Current image models follow a description written in full sentences far better than a list of tags. Before calling any API:

- **Expand short requests.** Turn a brief request into 2–4 sentences that cover, where relevant: the subject (with concrete details), what it is doing, the setting, framing and camera angle, lighting and mood, and the style or medium (photo, flat vector, watercolor, 3D render…). Keep everything the user specified, fill gaps with choices that fit their intent, and don't add subjects they didn't ask for.
- **Leave detailed prompts alone.** If the user already wrote a full description, send it as written, adding only what is clearly missing (usually style or framing).
- **Drop tag lists.** Words like `4k, masterpiece, ultra detailed, trending on artstation` don't help current models; leave them out.

Example: "a robot mascot" → "A friendly geometric robot mascot standing upright, centered in the frame, in clean flat vector style with soft rounded shapes. A soft pastel gradient background with a few small floating shapes. Even, shadowless lighting and a cheerful mood."

### Text in the image

When the image must contain words (posters, logos, labels, signs, UI, diagrams):

- Put the exact text in straight double quotes: `a shop sign that reads "Daily Grind"`.
- Describe the type style instead of naming a font: `bold condensed sans-serif`, `flowing brush script`, `slab serif`.
- Say where the text goes, its color and its size: `large white letters centered on a black band across the bottom third`.
- Keep each piece of text short. One to four words render reliably; sentences and paragraphs come out garbled.
- End the prompt with `No other text.` Without it, models tend to invent slogans, taglines and labels the user never asked for. Short exclusions like this one (or `no watermark`, `no logos`) at the end of a prompt are followed; elsewhere, describe what should be there rather than what shouldn't.
- Use the highest resolution or quality the chosen model supports (`2K` on `seedream-5-0-flash`, `quality: "high"` or above on OpenAI). When several keys are set, prefer OpenAI for text-heavy images.
- If a word comes out misspelled, regenerate with the word spelled out: `the brand name "Ployo" (spelled P-L-O-Y-O)`.

## Saving

- Save the image to the project's relevant directory (e.g., `assets/`, `images/`, or the current directory), creating it first.
- Next to every image, write a record file with the same name and a `.json` extension (`hero.png` → `hero.json`) containing:
  - `request` — what the user asked for, in their words
  - `prompt` — the exact prompt text sent to the API
  - `provider` and `model`
  - `params` — every other field sent in the request body (size, aspect ratio, quality, seed…)
  - `cost_usd` — from OpenRouter's `usage.cost`; omit it for providers that don't report cost
  - `created` — ISO 8601 timestamp
- Never write the API key, request headers or the base64 image data into the record file.
- When iterating on an image, save each version under a new name (`hero-v1.png`, `hero-v2.png`) instead of overwriting, so the prompts of different versions can be compared.

## API Reference: OpenAI

**Method:** `POST`
**URL:** `https://api.openai.com/v1/images/generations`

**Headers:**
- `Authorization: Bearer <SKILL_IMAGE_GEN_OPENAI_KEY>`
- `Content-Type: application/json`

**Body (JSON):**
```json
{
  "model": "gpt-image-2",
  "prompt": "<user prompt>",
  "n": 1,
  "size": "auto",
  "quality": "auto"
}
```

| Field | Default | Options / constraints |
|---|---|---|
| model | `gpt-image-2` | `gpt-image-2` (stable default), `gpt-image-2.5-sunburst`, `gpt-image-2.5-flare` (+ `2026-09-08` snapshots), `gpt-image-2.6-sunburst`, `gpt-image-2.6-flare`, `gpt-image-1.5`, `gpt-image-1-mini`, `chatgpt-image-latest`. **`gpt-image-1` was shut down on 2026-10-23 — never use it.** |
| size | `auto` | `1024x1024`, `1536x1024`, `1024x1536`, `auto`, or custom `WIDTHxHEIGHT`: edges must be multiples of 16, aspect ratio between 1:3 and 3:1, max edge 3840px, total pixels between 655,360 and 8,294,400 (4K). Custom resolutions above 2560x1440 are experimental. |
| quality | `auto` | `low`, `medium`, `high` (all models); `xhigh`, `max` only on `gpt-image-2.5-sunburst` / `gpt-image-2.5-flare` (incl. `2026-09-08` snapshots). Use `low` for quick drafts. |
| output_format | `png` | `png`, `webp`, `jpeg` (faster than png — prefer when latency matters), `gif`, `svg` |
| background | `auto` | `transparent`, `opaque`, `auto` — `transparent` requires `output_format` of `png` or `webp` |
| output_compression | (unset) | 0–100, only for `jpeg`/`webp`; not supported for `svg` |
| moderation | `auto` | `auto`, `low` |
| n | 1 | Number of images to generate; must be `1` for `svg` output |

**Response:** `data[0].b64_json` contains the base64-encoded image. Decode it and save to the output path. For `svg` output, base64-decode `data[0].b64_json` to UTF-8 XML bytes and save with a `.svg` extension. If a legacy `data[0].url` field appears instead of `b64_json`, download the image from that URL.

**Advanced (out of scope unless explicitly requested):** image edits/inpainting (`input_image_mask`), animated GIF control (`frame_count` 2–16, `frame_duration_ms` 20–2000), streaming partial images (`partial_images` 0–3), and input fidelity matching (`input_fidelity` — `gpt-image-1.5`/`gpt-image-1-mini` only) are available via the Responses API (`POST /v1/responses`) with the same model list.

## API Reference: Google Gemini (Nano Banana)

**Method:** `POST`
**URL:** `https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent`

**Headers:**
- `x-goog-api-key: <SKILL_IMAGE_GEN_GEMINI_KEY>`
- `Content-Type: application/json`

**Body (JSON):**
```json
{
  "contents": [{"parts": [{"text": "Generate an image: <user prompt>"}]}],
  "generationConfig": {
    "responseModalities": ["TEXT", "IMAGE"],
    "imageConfig": {"aspectRatio": "16:9", "imageSize": "2K"}
  }
}
```

Omit `imageConfig` unless the user asks for a specific aspect ratio or resolution — the default then matches the input image size (for edits) or a 1:1 square.

| Field | Default | Options / constraints |
|---|---|---|
| model (in URL) | `gemini-nano-banana-2.1` | `gemini-nano-banana-2.1` (Nano Banana 2.1 — recommended workhorse), `gemini-3.1-flash-image` (Nano Banana 2 — previous gen), `gemini-3.1-flash-lite-image` (Nano Banana 2 Lite — fastest/cheapest; not optimized for multi-reference or multi-turn editing), `gemini-3-pro-image` (Nano Banana Pro — premium, studio-quality 4K, complex layouts, precise text rendering), `gemini-2.5-flash-image` (legacy, limited availability). **Do not use `gemini-2.0-flash-exp` — deprecated.** |
| responseModalities | — | `["TEXT", "IMAGE"]` — `IMAGE` must be present to receive generated images |
| imageConfig.aspectRatio | (input size or `1:1`) | `1:1`, `2:3`, `3:2`, `3:4`, `4:3`, `4:5`, `5:4`, `9:16`, `16:9`, `21:9` (extremes `1:4`, `1:8`, `4:1`, `8:1` also accepted) |
| imageConfig.imageSize | `1K` | `1K`, `2K`, `4K` — supported on `gemini-nano-banana-2.1`, `gemini-3.1-flash-image`, and `gemini-3-pro-image` |

### Reference images and editing

To edit or composite from existing images, append `inlineData` parts (base64-encoded image + `mimeType`) after the text part of `contents`. Per-model reference-image limits:

| Model | Objects | Characters | Style refs |
|---|---|---|---|
| `gemini-3.1-flash-lite-image` | 14 | — | — |
| `gemini-nano-banana-2.1` / `gemini-3.1-flash-image` | 10 | 4 | — |
| `gemini-3-pro-image` | 6 | 5 | 3 |

**Response:** Find `candidates[0].content.parts[]` — look for a part with `inlineData.data` (base64 image) and `inlineData.mimeType`. Decode and save. All generated images include a SynthID watermark.

**Error cases:** `error` key (API error), `promptFeedback.blockReason` (safety block), `finishReason: "SAFETY"` (filtered).

## API Reference: OpenRouter

**Method:** `POST`
**URL:** `https://openrouter.ai/api/v1/images`

**Headers:**
- `Authorization: Bearer <SKILL_IMAGE_GEN_OPENROUTER_KEY>`
- `Content-Type: application/json`

**Body (JSON):**
```json
{
  "model": "bytedance-seed/seedream-5-0-flash",
  "prompt": "<user prompt>",
  "n": 1,
  "resolution": "2K",
  "aspect_ratio": "16:9"
}
```

Omit `resolution`/`aspect_ratio` unless the user asks — defaults then apply per provider.

| Field | Default | Options / constraints |
|---|---|---|
| model | `bytedance-seed/seedream-5-0-flash` | Any image model slug from `GET https://openrouter.ai/api/v1/images/models` (e.g. `bytedance-seed/seedream-5-0-flash` — fast, cheap default; `bytedance-seed/seedream-5-5` / `bytedance-seed/seedream-5-0-pro` — higher quality; `openai/gpt-image-2`; `google/gemini-2.5-flash-image`; `black-forest-labs/flux.2-pro`). Also discoverable at https://openrouter.ai/models?output_modalities=image |
| prompt | — | Text description of the desired image |
| resolution | (provider default) | Tiers: `512`, `768`, `1K`, `1.5K`, `2K`, `4K` |
| aspect_ratio | (provider default) | `1:1`, `16:9`, `9:16`, `4:3`, `3:4`, `3:2`, `2:3`, `4:5`, `5:4`, plus extended ratios like `1:2`, `2:1`, `1:4`, `4:1`, `1:8`, `8:1`, `9:21`, `21:9`; `auto` lets the provider choose. Providers clamp to their supported subset |
| size | (unset) | Shorthand: a tier (`"2K"`) or explicit pixels (`"2048x2048"`) — pixel sizes are provider-dependent; xAI and Sourceful V2/V2.5 reject them with a 400 |
| quality | (unset) | `auto`, `low`, `medium`, `high` — providers without a quality knob ignore this |
| output_format | (provider default) | `png`, `jpeg`, `webp`, `svg` (vector models only), `gif` (animation-capable models only) |
| background | (unset) | `auto`, `transparent`, `opaque` — `transparent` requires an alpha-capable format (`png`/`webp`) |
| output_compression | (unset) | 0–100, for `webp`/`jpeg` only |
| n | 1 | 1–10 images; single-image providers reject `n > 1` |
| seed | (unset) | Integer for deterministic generation, where supported |
| response_format | `b64_json` | `b64_json` (inline) or `url` — signed download URLs expire after 24 hours |
| stream | `false` | SSE partial images, only for models with `supports_streaming: true` |
| input_references | (unset) | Array of reference images for image-to-image: `{"type": "image_url", "image_url": {"url": "<https URL or base64 data URL>"}}` |
| frame_count / frame_duration_ms | (unset) | GIF animation: frames (2–64) and per-frame display time (20–2000 ms); animation-capable models only |
| provider | (unset) | Routing object: `only`, `order`, `ignore`, `sort` (`price`/`throughput`/`latency`), `allow_fallbacks`, `zdr`, `data_collection`; plus `options` keyed by provider slug for passthrough parameters |

**Per-model capability check:** each model/endpoint accepts a different parameter subset. Before using an advanced parameter, check `GET https://openrouter.ai/api/v1/images/models/<model>/endpoints` — its `supported_parameters` lists exactly what that endpoint accepts, and `allowed_passthrough_parameters` lists keys accepted under `provider.options`.

### Default model: `bytedance-seed/seedream-5-0-flash`

Supported parameters, from the model's `/endpoints` listing (single endpoint, provider `seed`; checked 2026-11-22). Send only these to the default model:

| Field | Accepted values |
|---|---|
| resolution | `1K`, `1.5K`, `2K` — no `512`, `768` or `4K`; use `seedream-5-5` / `seedream-5-0-pro` for higher resolution |
| aspect_ratio | `1:1`, `1:2`, `2:1`, `2:3`, `3:2`, `3:4`, `4:3`, `4:5`, `5:4`, `9:16`, `16:9`, `9:19.5`, `19.5:9`, `9:20`, `20:9`, `9:21`, `21:9`, `auto` |
| output_format | `png`, `jpeg` — no `webp`, `svg` or `gif` |
| background | `auto`, `transparent`, `opaque` — pair `transparent` with `output_format: "png"` |
| n | `1` only — for several images, make parallel calls |
| input_references | 0–14 reference images |
| seed | supported |

Not supported on this model: `quality`, `output_compression`, `stream`, `frame_count`/`frame_duration_ms`, and `provider.options` passthrough (none allowed).

**Pricing:** 0.018 USD per output image; input reference images are free.

**Response:** `data[0].b64_json` contains the base64-encoded image; `data[0].media_type` (e.g. `image/png`) identifies the format — use it to pick the file extension. `usage.cost` reports the USD cost of the generation. With `response_format: "url"`, `data[0].url` is a signed download link (expires after 24 hours, per `expires_at`).

**Error cases:** non-2xx status with a JSON `error` object (failed generations return `502` and are never billed). Billing is all-or-nothing: a generation is either completed and billed in full, or failed and billed nothing.

## Agent Guidelines

- For game textures, enrich prompts with "seamless", "tileable", "game asset".
- For batch generation, make multiple API calls in parallel.
- If the user asks to switch providers or what options are available, explain them all and help them set up.
- Ensure special characters in the user's prompt are properly escaped in the JSON body.
- If the user asks for a specific aspect ratio, map it to `size` (OpenAI, including custom `WIDTHxHEIGHT` dimensions), `imageConfig.aspectRatio` (Gemini), or `aspect_ratio` (OpenRouter). For higher resolution, use `quality: "high"` (or `xhigh`/`max` on gpt-image-2.5) on OpenAI, `imageConfig.imageSize: "2K"`/`"4K"` on Gemini, or `resolution: "2K"`/`"4K"` on OpenRouter.
- If the user names an OpenRouter model that isn't in the table (e.g. `black-forest-labs/flux.2-pro`), look it up via `GET https://openrouter.ai/api/v1/images/models` and check its `supported_parameters` before sending advanced fields.
- On OpenRouter, report the generation cost from `usage.cost` after saving the image, and prefer `provider.sort: "price"` when the user is cost-sensitive.
- For transparent backgrounds (icons, sprites) on OpenAI, set `background: "transparent"` with `output_format: "png"` or `"webp"`; on OpenRouter the same `background`/`output_format` fields work on models that support them (e.g. seedream).
- Use `output_format: "jpeg"` when latency matters more than format fidelity.
- If the user cares about image provenance, note that Gemini outputs carry an invisible SynthID watermark.
- If the user asks for image editing, inpainting, animated GIFs, or streaming partial results, point them at the OpenAI Responses API (`POST /v1/responses`) — see its docs for `input_image_mask`, `frame_count`, `frame_duration_ms`, and `partial_images`.
