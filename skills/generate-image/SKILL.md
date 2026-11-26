---
name: generate-image
description: >-
  Generate images using AI. Use when asked to generate, create, or make images, textures,
  icons, sprites, artwork, visual assets, or mockups. Supports OpenAI (gpt-image-2 and
  gpt-image-2.5/2.6), Google Gemini (Nano Banana 2.1 and Nano Banana Pro), and OpenRouter
  (multi-provider, default black-forest-labs/flux-3-image-klein at 4K). Requires an API key for the
  chosen provider.
argument-hint: "[description of the image to generate]"
license: MIT
metadata:
  version: "3.1.0"
  providers: "openai, gemini, openrouter"
---

# Generate Image

You are an image generation assistant. When invoked, follow the workflow below.

All API calls go through the bundled script `scripts/imagegen.py` (in the same folder as this
file; Python 3, standard library only). Never write your own curl or HTTP code for these APIs,
and never print, echo or log an API key.

## Workflow

1. **Check for API keys** — run `python3 <skill folder>/scripts/imagegen.py keys`. It prints `true`/`false` for each provider and never the key itself. If none is set, run the Onboarding section.
2. **Ask about the common options** — every time, following the Asking About Options section.
3. **Write the prompt** — follow the Writing the Prompt section.
4. **Generate** — run `imagegen.py generate` with the chosen options (see Running the Script). It checks the options before anything is sent, so a rejected option costs nothing.
5. **Tell the user** where the image and its record were saved, the image size, the prompt that was sent, the cost if one was reported, and any warnings the script printed.

## Onboarding

Only run this if no keys are set. Guide the user conversationally.

1. Ask which provider they'd like to use:
   - **OpenRouter** — One account and key for many image models across providers (default: `black-forest-labs/flux-3-image-klein` at 4K)
   - **OpenAI (gpt-image-2)** — High quality, excellent text rendering, paid per image
   - **Google Gemini (Nano Banana 2.1)** — Strong photorealism and editing, paid per image token
2. Direct them to get an API key:
   - OpenRouter → https://openrouter.ai/settings/keys
   - OpenAI → https://platform.openai.com/api-keys
   - Gemini → https://aistudio.google.com/apikey
3. Ask them to set `SKILL_IMAGE_GEN_OPENROUTER_KEY`, `SKILL_IMAGE_GEN_OPENAI_KEY`, or `SKILL_IMAGE_GEN_GEMINI_KEY` in their shell profile themselves, then start a new shell. Don't ask them to paste the key into the chat.
4. Proceed to generate the image they originally asked for.

## Asking About Options

Each time the skill is invoked, ask the user about the common options **before** writing the prompt, in a single round. Use the client's multiple-choice question tool if it has one (for example `AskUserQuestion` in Claude Code); otherwise ask a short numbered list and wait for the answer.

- Ask at most four questions, from the list below, in this order.
- Skip any question the user's request already answers ("a 16:9 photo" answers shape and style). If the request answers all of them, go straight to generating.
- Put your recommendation first and mark it "(Recommended)". Give the cost in each model and size option's description.
- Only offer models the user's keys can reach. Get prices and accepted sizes from `imagegen.py options` when unsure.
- For a revision of an image made earlier in the conversation, make "Same as last time" the first option of each question.

1. **Model** — for OpenRouter: Flux 3 Klein (default; sharpest detail, 4K for 0.036 USD), Seedream 5.0 Flash (transparent backgrounds, cheapest 2K at 0.018 USD), Nano Banana 2.1 (most photographic, about 0.12 USD at 4K), or `openai/gpt-image-2.6-sunburst` (best for text in images). For OpenAI or Gemini keys, offer that provider's models from the Providers and Models section.
2. **Size** — Final (4K, or the largest the model supports), Draft (2K or 1K, cheaper for trying ideas), or Small (1K). Recommend Draft when the user is exploring and Final when they asked for something finished.
3. **Shape** — 16:9 landscape (wallpapers, slides, banners), 1:1 square (social posts, icons, avatars), 9:16 portrait (phone screens, stories), 2:3 poster (prints, covers). Recommend the one that fits the stated use.
4. **Style** — Photorealistic, Illustration (flat vector), 3D render, or Painterly. If the request already names a style, ask the most useful remaining choice instead: transparent background for icons and sprites, or how many variations (each is a separate charge).

## Writing the Prompt

Current image models follow a description written in full sentences far better than a list of tags. Before calling any API:

- **Expand short requests.** Turn a brief request into 2–4 sentences that cover, where relevant: the subject (with concrete details), what it is doing, the setting, framing and camera angle, lighting and mood, and the style or medium (photo, flat vector, watercolor, 3D render…). Keep everything the user specified, fill gaps with choices that fit their intent, and don't add subjects they didn't ask for.
- **Leave detailed prompts alone.** If the user already wrote a full description, send it as written, adding only what is clearly missing (usually style or framing).
- **Drop tag lists.** Words like `4k, masterpiece, ultra detailed, trending on artstation` don't help current models; leave them out.
- **Say what is in frame.** Models take scene words literally: "taken from a rooftop" tends to draw the rooftop edge. When the viewpoint shouldn't appear, say so ("aerial view, no railing or rooftop in the frame").

Example: "a robot mascot" → "A friendly geometric robot mascot standing upright, centered in the frame, in clean flat vector style with soft rounded shapes. A soft pastel gradient background with a few small floating shapes. Even, shadowless lighting and a cheerful mood."

### Text in the image

When the image must contain words (posters, logos, labels, signs, UI, diagrams):

- Put the exact text in straight double quotes: `a shop sign that reads "Daily Grind"`.
- Describe the type style instead of naming a font: `bold condensed sans-serif`, `flowing brush script`, `slab serif`.
- Say where the text goes, its color and its size: `large white letters centered on a black band across the bottom third`.
- Keep each piece of text short. One to four words render reliably; sentences and paragraphs come out garbled.
- End the prompt with `No other text.` Without it, models tend to invent slogans, taglines and labels the user never asked for. Short exclusions like this one (or `no watermark`, `no logos`) at the end of a prompt are followed; elsewhere, describe what should be there rather than what shouldn't.
- Use the highest resolution or quality the chosen model supports (`--resolution 4K` on Flux Klein, `--quality high` or above on OpenAI). When several keys are set, prefer OpenAI for text-heavy images.
- If a word comes out misspelled, regenerate with the word spelled out: `the brand name "Ployo" (spelled P-L-O-Y-O)`.

## Running the Script

```bash
python3 <skill folder>/scripts/imagegen.py generate \
  --prompt "<the prompt you wrote>" \
  --request "<what the user asked for, in their words>" \
  --name gcc-desert-night-v1 \
  --aspect 16:9 --resolution 4K
```

| Flag | Meaning |
|---|---|
| `--name` (required) | File name without extension. Several images get `-1`, `-2`. The script never overwrites: for a new version use a new name (`hero-v2`). |
| `--out-dir` | Where to save (default `images/`); use the project's assets folder when it has one. |
| `--provider` | `openrouter`, `openai` or `gemini`. Needed only when several keys are set. |
| `--model` | Default: OpenRouter `black-forest-labs/flux-3-image-klein` (4K unless `--resolution` is given), OpenAI `gpt-image-2`, Gemini `gemini-nano-banana-2.1`. |
| `--aspect` | Shape such as `16:9`. For OpenAI it is turned into a valid pixel size. |
| `--resolution` | `512`, `768`, `1K`, `1.5K`, `2K` or `4K`. |
| `--n` | Number of images (one request per image on Gemini). |
| `--format` | `png`, `jpeg`, `webp`, `gif` or `svg`, where the model supports it. |
| `--background` | `transparent`, `opaque` or `auto`, where supported. |
| `--quality` | Quality setting where supported (OpenAI `low`…`max`). |
| `--ref` | Reference image to edit or combine (repeatable). |
| `--mask` | OpenAI only: PNG mask with an alpha channel, applied to the first `--ref`. |
| `--param key=value` | Any other request field, passed through as-is (repeatable; JSON values and dotted keys allowed, e.g. `--param seed=7`, `--param complexity=medium`, `--param provider.options.black-forest-labs.steps=30`). |
| `--params-json` | Extra request fields as one JSON object. |
| `--timeout` | Seconds per request (default 300; 4K takes 1–2 minutes). |
| `--dry-run` | Print the exact request (without the key or image bytes) and the price, and send nothing. |

Other commands:

- `imagegen.py options --provider openrouter --model <slug>` — what an OpenRouter model accepts and costs, read live from OpenRouter (cached for a day; `--refresh` to re-read). For OpenAI and Gemini it prints the built-in notes, because those providers have no options API.
- `imagegen.py keys` — which provider keys are set.

The script prints JSON with the saved file paths, image size, cost and warnings. On failure it prints `error: …` and exits with 1. Explain these errors to the user:

- **Option not accepted** — the request was refused before sending, nothing was charged. Pick an allowed value from the message, or another model.
- **Guardrail** (OpenRouter 404) — the user's OpenRouter account blocks the model. Give them the settings link from the message; changing it is their decision.
- **Timeout** — retry with a larger `--timeout` or a smaller `--resolution`.
- **Blocked or filtered** (Gemini) — rephrase the prompt.

## Saving

The script saves each image to `--out-dir` and writes a record file next to it with the same name and a `.json` extension. The record holds the user's request, the exact prompt, provider, model, the request settings that were sent, reference image paths, the image size, the cost and usage the provider reported, and a timestamp. It never contains the API key or image data. When iterating, give each version a new name (`hero-v1`, `hero-v2`) so the prompts can be compared.

## Providers and Models

### OpenRouter

- **Default: `black-forest-labs/flux-3-image-klein`** — 768 to 4K (4K at 16:9 is 5456×3072), 16 aspect ratios, jpeg or png, one image per request, up to 10 reference images, seed, and `safety_tolerance`/`steps` through `provider.options`. No `background`, so no transparent output. 0.008 USD at 768 up to 0.036 USD at 4K. A 4K image takes about 80 seconds and is 8–9 MB. It tends toward a strong wide-angle look.
- **`bytedance-seed/seedream-5-0-flash`** — 1K to 2K, transparent backgrounds, png or jpeg, up to 14 reference images. 0.018 USD per image.
- **`google/gemini-nano-banana-2.1`** — 1K to 4K, the most photographic results. Billed per image token: about 0.034 USD at 1K, 0.050 at 2K, 0.113 at 4K, plus a little for reasoning tokens.
- **`openai/gpt-image-2.6-sunburst`** — quality `low` to `max`, aspect ratio but no resolution setting on OpenRouter. 4K-class images cost about 0.05 USD (low) to 0.40 USD (max).
- Any other model: run `imagegen.py options --provider openrouter --model <slug>` first; the script also checks every request against the same listing.
- If an account has model guardrails, the user must allow a model before it can be used.

### OpenAI

- Models: `gpt-image-2` (default), `gpt-image-2.5-sunburst`, `gpt-image-2.5-flare` (+ `2026-09-08` snapshots), `gpt-image-2.6-sunburst`, `gpt-image-2.6-flare`, `gpt-image-1.5`, `gpt-image-1-mini`, `chatgpt-image-latest`. **`gpt-image-1` was shut down on 2026-10-23 — never use it.**
- Size: `--aspect` and `--resolution` become a pixel size with edges in multiples of 16, ratio 1:3 to 3:1, at most 3840 px per edge and 655,360–8,294,400 pixels. Above 2560×1440 is experimental.
- Quality: `low`, `medium`, `high`; `xhigh` and `max` on Sunburst and Flare (OpenAI's docs disagree on whether 2.6 supports them; the script warns and lets the API decide).
- `--param complexity=low|medium|high` on 2.6 Sunburst and Flare controls how much the model plans before drawing (default `high`, no extra fee).
- Animated GIF: `--format gif` with `--param frame_count=2..16` and `--param frame_duration_ms=20..2000`.
- SVG: `--format svg`, one image, not with `--ref`.
- Transparent background needs `--format png` or `webp`.
- `--ref` and `--mask` use the edits endpoint. Don't set `input_fidelity` on `gpt-image-2`.
- Pricing: 30 USD per million output image tokens. Image tokens depend on model, size and quality; OpenAI's cost calculator on its image generation guide gives exact numbers.

### Google Gemini

- Models: `gemini-nano-banana-2.1` (default), `gemini-3.1-flash-image`, `gemini-3.1-flash-lite-image` (1K only), `gemini-3-pro-image` (studio quality, best text), `gemini-2.5-flash-image` (legacy). **Do not use `gemini-2.0-flash-exp` — deprecated.**
- `--resolution` `1K`, `2K` or `4K` on Nano Banana 2.1, 3.1 Flash Image and 3 Pro Image; `512` only on 3.1 Flash Image.
- Aspect ratios `1:1`, `2:3`, `3:2`, `3:4`, `4:3`, `4:5`, `5:4`, `9:16`, `16:9`, `21:9`; Nano Banana 2.1 and 3.1 Flash Image add `1:4`, `4:1`, `1:8`, `8:1`.
- Up to 14 reference images (Nano Banana 2.1: up to 10 objects and 4 characters; 3 Pro Image: 6 objects, 5 characters, 3 style references).
- Thinking is always on; the script skips the interim "thought" images and saves the final one.
- All Gemini images carry an invisible SynthID watermark. Mention it if the user cares about provenance.
- The script uses the `generateContent` API. Google's AI Studio guide now documents a newer Interactions API; switch only if `generateContent` stops working.

## Agent Guidelines

- For game textures, add "seamless", "tileable", "game asset" to the prompt.
- For several different images, run the script once per image (in parallel when the client allows).
- If the user asks to switch providers or what options are available, run `imagegen.py options` and explain.
- After saving, look at the image if you can, check it against the request (subject, framing, text), and point out problems such as invented text, logos that look like real brands, or a recognizable real place.
