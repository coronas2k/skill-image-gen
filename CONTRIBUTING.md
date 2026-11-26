# Contributing

1. Fork and clone the repo
2. Edit the skill:
   - `skills/generate-image/SKILL.md` — the workflow, the questions asked before generating, prompt-writing rules and model notes
   - `skills/generate-image/scripts/imagegen.py` — every API call: building requests, checking options, saving images and records
3. Run the offline tests: `python3 -m unittest discover -s skills/generate-image/scripts`
4. Test by installing locally: `./install.sh --link`, and try `imagegen.py generate --dry-run` before spending on a real image
5. Open a PR with a clear description of what changed and why

## Adding a new provider

1. In `imagegen.py`, add its key variable to `KEY_ENV`, its default model to `DEFAULTS`, a branch in `build_request` and `parse_images`, and any limits the provider documents.
2. Add tests for the request it builds and the response it parses.
3. Add a short section to "Providers and Models" in `SKILL.md`.

## Guidelines

- Keep SKILL.md concise — the agent is smart, it doesn't need verbose instructions
- API details belong in the script, where they can be tested; judgement (prompt writing, which model to suggest) belongs in SKILL.md
- The script uses only Python's standard library, and must never print, log or store an API key
- Test with both Claude Code and Copilot CLI if possible
