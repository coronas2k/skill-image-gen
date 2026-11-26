# Testing

This guide tests the project at four levels, cheapest first. Run every command from the repo root.

| Level | What it proves | Needs | Cost |
| --- | --- | --- | --- |
| 1. Offline unit tests | The script's logic: request building, option checks, parsing, saving, key handling | Python 3 | Free, about 2 seconds |
| 2. Dry runs | The command line works end to end up to the point of sending | A key variable set (a placeholder works in most cases) | Free |
| 3. Live smoke tests | A real provider accepts the request and the image and record are saved | A real key | Real money, from 0.008 USD |
| 4. Skill behaviour | The agent follows `SKILL.md`: key check, questions, prompt file, report | A real key and Claude Code (or Copilot CLI) | One image |

There is no CI in this repo, so all four levels are run by hand. Pass `-B` to Python so no `__pycache__` folders are left behind.

## 1. Offline unit tests

The 48 tests in `skills/generate-image/scripts/test_imagegen.py` need no key and no internet. Provider responses and the `/endpoints` listing are mocked; the `Network` tests start small HTTP servers on `127.0.0.1`, so they need local sockets.

### Run all tests

```bash
python3 -B -m unittest discover -s skills/generate-image/scripts
```

Expected: `Ran 48 tests` and `OK`. Add `-v` to see each test name.

### Run one class or one test

`-k` matches part of a test's full name (`test_imagegen.Class.test_name`) and can be repeated:

```bash
python3 -B -m unittest discover -s skills/generate-image/scripts -k Secrets
python3 -B -m unittest discover -s skills/generate-image/scripts -k Secrets -k Network
python3 -B -m unittest discover -s skills/generate-image/scripts -k test_key_headers_do_not_follow_redirects
```

Or name it exactly, with the scripts folder on the path:

```bash
PYTHONPATH=skills/generate-image/scripts python3 -B -m unittest test_imagegen.GenerateCommand
PYTHONPATH=skills/generate-image/scripts python3 -B -m unittest test_imagegen.Network.test_https_redirect_may_not_downgrade
```

### Run on more than one Python version

The documented minimum is Python 3.8. Run the suite on every version you have:

```bash
python3 -B -m unittest discover -s skills/generate-image/scripts
/usr/bin/python3 -B -m unittest discover -s skills/generate-image/scripts
python3.8 -B -m unittest discover -s skills/generate-image/scripts
```

On macOS, `/usr/bin/python3` is Apple's system Python (3.9.6 on the machine this guide was checked on), usually older than a Homebrew or python.org `python3`. The `python3.8` line works only if Python 3.8 is installed. If you use `uv`, `uv run --no-project --python 3.8 python -B -m unittest discover -s skills/generate-image/scripts` should also work, but it downloads Python 3.8 when it is missing and has not been tried for this project.

All 48 tests passed on Python 3.15.2 and 3.9.6 on 2026-11-27. Python 3.8 has not been run (see [Known gaps](#known-gaps)).

### What each test class covers

| Class | Tests | Covers |
| --- | --- | --- |
| `OpenAISize` | 6 | Turning `--aspect` and `--resolution` into an OpenAI pixel size: 16-pixel grid, minimum pixel count, `auto`, every result inside the limits, ratios outside 1:3 to 3:1 refused, bad sizes refused |
| `OpenAIChecks` | 6 | OpenAI rules checked before sending: transparent needs png or webp, SVG rules, GIF-only fields, no `input_fidelity` on `gpt-image-2`, `--ref`/`--mask` use the edits endpoint, warnings where OpenAI's docs disagree |
| `OpenRouterChecks` | 6 | The options check against a trimmed real `/endpoints` listing for Flux 3 Klein: accepted and refused fields and values, `provider.options` passthrough keys, reference count, price per image and per token, reference images hidden in the shown request, the guardrail hint on a 404 |
| `Gemini` | 4 | Size and aspect rules per model, request body shape, interim "thought" images skipped, blocked and filtered responses |
| `Parsing` | 4 | OpenRouter base64 and URL responses, OpenAI media type from `--format`, image dimensions for PNG, JPEG and GIF, `--param` and `--params-json` |
| `ProvidersAndFiles` | 4 | Choosing the provider from the keys set, `--name` rules, the no-overwrite check across every image and record extension, exclusive file creation, dangling symlinks, the `-v2` fallback |
| `GenerateCommand` | 8 | The whole `generate` command with sending mocked: dry-run defaults (Flux at 4K, price, key hidden), image and record saved, a refused option or a name clash stops before sending, a clash after paying saves as `-v2`, Gemini keeps saved images after a later failure, dry runs check `--name` and `--out-dir`, a missing `--prompt-file` |
| `Secrets` | 2 | Key whitespace stripped, a key with whitespace inside refused without showing it, a blank key counts as unset, an unexpected error's text hidden |
| `Network` | 5 | Key headers not sent on to a redirect target, no https to http redirect, friendly read timeout on every Python version, dropped connection, downloads refused unless https, a real image and under the size cap |
| `BadInput` | 3 | A non-text `size`, a malformed OpenRouter `provider` field, a Gemini text-only answer shown in the error |

## 2. Dry runs

`generate --dry-run` runs every check a real run does, prints the request it would send, and stops. It generates nothing and writes nothing to `--out-dir`.

What a dry run does:

- It needs the chosen provider's key variable set, as a real run does. For OpenAI and Gemini a placeholder value is enough, because nothing is sent. The same goes for OpenRouter with `--no-check`.
- It checks the prompt or `--prompt-file`, `--n`, `--name`, `--out-dir`, that no image or record already uses the name, any `--ref` or `--mask` files, `--param` values, that the key has no whitespace inside it, and the provider's built-in limits.
- It prints JSON with the provider, model, number of calls, price, warnings and the request (method, URL, body). The key is never shown, and image data is replaced by a note such as `<base64, 1234 chars>`.
- On OpenRouter, unless `--no-check` is given, it reads the model's `/endpoints` listing and refuses any option the listing doesn't accept. The listing comes from the cache in `~/.cache/skill-image-gen/` (or under `XDG_CACHE_HOME`) when it is less than a day old; otherwise it is fetched from OpenRouter with the key, so that needs a real key and the network. `--refresh` forces a fetch.
- The price is shown only on OpenRouter, and only when the listing check runs. It is `null` for OpenAI, for Gemini and with `--no-check`.
- Exit status: `0` for success, `1` for a refused request (`error: ...` on stderr), `2` for a usage error such as a missing `--name`.

Always pass `--provider`: with a real key in your environment and a placeholder for another provider, the script would otherwise stop with `several API keys are set`. Writing `VAR=placeholder` before the command sets the variable for that one command only.

### OpenRouter

```bash
# Offline: no listing check, so no price
SKILL_IMAGE_GEN_OPENROUTER_KEY=placeholder python3 -B skills/generate-image/scripts/imagegen.py generate \
  --provider openrouter --prompt 'A small red cube on a white table' --name dry-test \
  --aspect 16:9 --resolution 768 --dry-run --no-check

# With the listing check and price: uses your real key, makes a network call unless cached, generates nothing
python3 -B skills/generate-image/scripts/imagegen.py generate \
  --provider openrouter --prompt 'A small red cube on a white table' --name dry-test \
  --aspect 16:9 --resolution 768 --dry-run
```

The second command should show `"price": "0.008 USD per image"`. Add `--background transparent` to the second command (the first skips the check) to see Flux 3 Klein refuse an option before sending (`won't accept this request` ... `background not supported`).

### OpenAI

```bash
SKILL_IMAGE_GEN_OPENAI_KEY=placeholder python3 -B skills/generate-image/scripts/imagegen.py generate \
  --provider openai --prompt 'A small red cube on a white table' --name dry-test \
  --aspect 1:1 --resolution 1K --quality low --dry-run
```

The body shows `"size": "1024x1024"`. To see refusals and warnings, try `--background transparent --format jpeg` (refused: `transparent background needs output_format png or webp`) or `--aspect 16:9 --resolution 4K` (warning: `sizes above 2560x1440 are experimental`).

### Gemini

```bash
SKILL_IMAGE_GEN_GEMINI_KEY=placeholder python3 -B skills/generate-image/scripts/imagegen.py generate \
  --provider gemini --prompt 'A small red cube on a white table' --name dry-test \
  --aspect 1:1 --resolution 1K --dry-run
```

The body's `generationConfig.imageConfig` shows `aspectRatio` and `imageSize`. Try `--resolution 512` to see it refused on the default model.

### options and keys

```bash
python3 -B skills/generate-image/scripts/imagegen.py keys
python3 -B skills/generate-image/scripts/imagegen.py options --provider openai
python3 -B skills/generate-image/scripts/imagegen.py options --provider gemini --model gemini-3.1-flash-image
python3 -B skills/generate-image/scripts/imagegen.py options --provider openrouter --model black-forest-labs/flux-3-image-klein
```

- `keys` prints `true` or `false` for each provider, never a value.
- `options` for OpenAI and Gemini prints built-in notes and needs no key or network.
- `options` for OpenRouter reads the live `/endpoints` listing (cached for a day, `--refresh` to re-read), sending the OpenRouter key when it is set.

## 3. Live smoke tests

These cost real money. Run the matching dry run first, and use a new `--name` each time: the script refuses a name already used in `images/` before sending. `images/` is gitignored.

### OpenRouter (verified live)

Flux 3 Klein at `--resolution 768` costs 0.008 USD, the cheapest request known for this project.

```bash
P="$(mktemp)"
printf '%s\n' 'A small red cube on a white table, soft daylight, plain background.' > "$P"
python3 -B skills/generate-image/scripts/imagegen.py generate \
  --provider openrouter --model black-forest-labs/flux-3-image-klein \
  --prompt-file "$P" --request 'smoke test' \
  --name smoke-openrouter-768 --aspect 16:9 --resolution 768
rm -f "$P"
```

Then check:

```bash
ls images/smoke-openrouter-768.*
python3 -B -c 'import json; r = json.load(open("images/smoke-openrouter-768.json")); print(r["size"], r.get("cost_usd"))'
grep -c -i 'bearer\|sk-' images/smoke-openrouter-768.json
python3 -B -c 'import os, sys; k = os.environ.get(sys.argv[1], "").strip(); print("key not set" if not k else k in open(sys.argv[2]).read())' SKILL_IMAGE_GEN_OPENROUTER_KEY images/smoke-openrouter-768.json
```

| Check | Pass |
| --- | --- |
| `ls` | An image (a `.jpg` in earlier runs) and a `.json` record with the same name |
| size and cost | A pixel size and a cost; an earlier live run with these settings recorded `1024x576 0.008` |
| `grep -c` | Prints `0`. grep exits with status 1 when nothing matches, which is the pass here. Keep the prompt free of words such as "desk-" or "mask-", which contain `sk-` |
| key check | Prints `False`: the record does not contain your key. The key itself is never printed |

The JSON summary on stdout also shows `cost_usd` and `seconds`.

If the account has model guardrails, a blocked model fails with an OpenRouter 404 and `hint: a guardrail on the OpenRouter account blocks this model`, followed by a settings link. Nothing is generated; allowing the model is the account owner's decision.

### OpenAI (unverified)

The OpenAI path has not been called live yet. This is the next step; record the result in the PR. The command builds a 1024x1024 request at quality `low`, the smallest the script makes for OpenAI. Its cost has not been measured; `options --provider openai` lists OpenAI's token prices.

```bash
P="$(mktemp)"
printf '%s\n' 'A small red cube on a white table, soft daylight, plain background.' > "$P"
python3 -B skills/generate-image/scripts/imagegen.py generate \
  --provider openai --model gpt-image-2 \
  --prompt-file "$P" --request 'smoke test' \
  --name smoke-openai-1k --aspect 1:1 --resolution 1K --quality low
rm -f "$P"
```

Check as for OpenRouter, with `images/smoke-openai-1k.json` and `SKILL_IMAGE_GEN_OPENAI_KEY`. The record has `cost_usd` only if OpenAI's response reports a cost in `usage`, which is not yet known; `usage` should still be recorded.

### Gemini (unverified)

The Gemini path has not been called live yet either. The script's own notes give 1,120 image tokens at 1K and 30 USD per million tokens for the default model, about 0.034 USD; this has not been measured.

```bash
P="$(mktemp)"
printf '%s\n' 'A small red cube on a white table, soft daylight, plain background.' > "$P"
python3 -B skills/generate-image/scripts/imagegen.py generate \
  --provider gemini --model gemini-nano-banana-2.1 \
  --prompt-file "$P" --request 'smoke test' \
  --name smoke-gemini-1k --aspect 1:1 --resolution 1K
rm -f "$P"
```

Check as for OpenRouter, with `images/smoke-gemini-1k.json` and `SKILL_IMAGE_GEN_GEMINI_KEY`. A Gemini record never has `cost_usd`, because the script reads no cost from Gemini; it should have `usage` (Gemini's `usageMetadata`).

## 4. Skill behaviour

This checks the agent's side, which no unit test covers. Run it by hand in a fresh session.

1. Install the skill for Claude Code:

   ```bash
   ./install.sh --claude-only --dry-run   # preview only
   ./install.sh --claude-only             # copy SKILL.md and scripts/ into ~/.claude/skills/generate-image/
   ./install.sh --claude-only --link      # or link them to this repo, so edits apply without reinstalling
   ```

   Both forms replace the installed `SKILL.md` and `scripts/`; the installer warns that it is overwriting. `--link` replaces an installed copy with links to this repo. Run `./install.sh --claude-only` again to go back to a copy, or `./install.sh --claude-only --uninstall` to remove it.
2. Fully restart Claude Code from a terminal where the key is exported. A running session keeps the environment it started with.
3. Ask for an image, for example `Generate an image of a friendly robot mascot for our README.` or `/generate-image a friendly robot mascot`. To keep the cost near 0.009 USD, answer Flux 3 Klein and Small (1K).

What to observe:

- [ ] The agent runs `imagegen.py keys` by its absolute path, and the output shows only `true` or `false`. No key or environment listing appears anywhere.
- [ ] One round of questions through `AskUserQuestion`: at most four (Model, Size, Shape, Style), each with 2 to 4 options and no hand-added "Other".
- [ ] The recommended option is first and marked "(Recommended)", and Model and Size options show prices.
- [ ] Only models your keys can reach are offered.
- [ ] Questions the request answers are skipped: "a 16:9 photo of a lighthouse" asks no Shape or Style question; "just make it" asks nothing, and the report says which options were used.
- [ ] The prompt is written to a new temp file outside the project and passed with `--prompt-file`; the prompt text never appears on the command line. `--request` holds your words in single quotes.
- [ ] The command passes both `--provider` and `--model` with the full slug.
- [ ] The report gives the image and record paths, the image size, the prompt sent and the cost, plus any warnings.
- [ ] The temp prompt file is deleted afterwards (`ls` the path from the command shows nothing).
- [ ] The image and its `.json` record are in `images/`, or the project's assets folder if it has one, and the record passes the key checks from level 3.

**Copilot CLI (untested).** Install with `./install.sh --copilot-only` (or add `--link`) and restart Copilot CLI. `SKILL.md` tells an agent without a multiple-choice question tool to ask a short numbered list and wait for the answer; the rest of the checklist is the same. This flow has not been tried yet.

## Security checks

The script must never print, log or store a key.

Unit tests: `Secrets` and `Network` cover key handling, redirects and downloads, and `GenerateCommand` asserts that a dummy key appears in neither dry-run output nor a saved record.

```bash
python3 -B -m unittest discover -s skills/generate-image/scripts -k Secrets -k Network -k GenerateCommand
```

Manual probes, using only dummy keys. `env -u` hides any real keys from these commands; each `grep -c` should print `0`.

```bash
# A key never appears in dry-run output
env -u SKILL_IMAGE_GEN_OPENROUTER_KEY -u SKILL_IMAGE_GEN_OPENAI_KEY -u SKILL_IMAGE_GEN_GEMINI_KEY \
  SKILL_IMAGE_GEN_OPENAI_KEY=sk-DUMMY-probe python3 -B skills/generate-image/scripts/imagegen.py generate \
  --provider openai --prompt probe --name probe --dry-run 2>&1 | grep -c DUMMY

env -u SKILL_IMAGE_GEN_OPENROUTER_KEY -u SKILL_IMAGE_GEN_OPENAI_KEY -u SKILL_IMAGE_GEN_GEMINI_KEY \
  SKILL_IMAGE_GEN_GEMINI_KEY=DUMMY-probe python3 -B skills/generate-image/scripts/imagegen.py generate \
  --provider gemini --prompt probe --name probe --dry-run 2>&1 | grep -c DUMMY

env -u SKILL_IMAGE_GEN_OPENROUTER_KEY -u SKILL_IMAGE_GEN_OPENAI_KEY -u SKILL_IMAGE_GEN_GEMINI_KEY \
  SKILL_IMAGE_GEN_OPENROUTER_KEY=sk-DUMMY-probe python3 -B skills/generate-image/scripts/imagegen.py generate \
  --provider openrouter --prompt probe --name probe --dry-run --no-check 2>&1 | grep -c DUMMY

# A key with whitespace inside is refused without being shown
env -u SKILL_IMAGE_GEN_OPENROUTER_KEY -u SKILL_IMAGE_GEN_OPENAI_KEY -u SKILL_IMAGE_GEN_GEMINI_KEY \
  SKILL_IMAGE_GEN_OPENAI_KEY='sk-DUMMY inside' python3 -B skills/generate-image/scripts/imagegen.py generate \
  --provider openai --prompt probe --name probe --dry-run 2>&1 | grep -c DUMMY

# keys shows only true or false
env -u SKILL_IMAGE_GEN_OPENROUTER_KEY -u SKILL_IMAGE_GEN_OPENAI_KEY -u SKILL_IMAGE_GEN_GEMINI_KEY \
  SKILL_IMAGE_GEN_OPENAI_KEY=sk-DUMMY-probe python3 -B skills/generate-image/scripts/imagegen.py keys
```

A `0` also appears when a command fails for another reason, so run each probe once without the `| grep` part first: the first three should print the request JSON, and the whitespace probe should print `error: SKILL_IMAGE_GEN_OPENAI_KEY contains whitespace or control characters`. The last probe prints `"openai": true` and the other two `false`.

Never print your real key or environment to check any of this; use the `False` check from level 3 for real records.

## Before opening a PR

- [ ] `python3 -B -m unittest discover -s skills/generate-image/scripts` passes, and so does at least one other Python version (for example `/usr/bin/python3`).
- [ ] New behaviour has a test, and a bug fix has a regression test.
- [ ] A dry run passes for each provider your change touches.
- [ ] The security probes print `0`.
- [ ] If you changed a request or response path and spent money on a live smoke test, the PR says which provider, model, size and cost.
- [ ] If you changed `SKILL.md`, you ran level 4, or the PR says you didn't.
- [ ] `find . -name __pycache__` prints nothing.
- [ ] `grep -nE '\$[0-9]' README.md CONTRIBUTING.md TESTING.md skills/generate-image/SKILL.md` prints nothing. The skill loader mishandles a dollar sign followed by a digit, so write prices as "0.008 USD".
- [ ] The test count in `README.md` and this file, README's "Not yet verified" list and the gaps below are updated in the same commit.
- [ ] `git status` shows no images, records or files holding keys.

## Known gaps

- OpenAI direct has never been called live; whether its response reports a cost is unknown.
- Gemini direct has never been called live. Whether Gemini returns more than one image per request is unconfirmed, so the script makes one call per image.
- Python 3.8, the documented minimum, has not been run; the tests pass on 3.9.6 and 3.15.2.
- The Copilot CLI flow (numbered-list questions) has not been tried.
- The question round hasn't been tried in a fresh session.
- There is no CI; every level above is run by hand.
