# Contributing

1. Fork and clone the repo
2. Edit the skill:
   - `skills/generate-image/SKILL.md`: the workflow, the questions asked before generating, prompt-writing rules and model notes
   - `skills/generate-image/scripts/imagegen.py`: every API call (building requests, checking options, saving images and records)
3. Run the offline tests: `python3 -m unittest discover -s skills/generate-image/scripts`
4. Install locally with `./install.sh --link`. This replaces any installed copy of the skill with links to this repo; run `./install.sh` again to go back to a copy.
5. Before spending on a real image, try a dry run from the repo root. It needs a provider key set; `--no-check` keeps it offline:

   ```bash
   python3 skills/generate-image/scripts/imagegen.py generate --name test --prompt "test" --dry-run --no-check
   ```

6. Open a PR with a clear description of what changed and why

## Adding a new provider

1. In `imagegen.py`, add its key variable to `KEY_ENV` and its default model (and default resolution, if any) to `DEFAULTS`.
2. Add a branch for it to `build_request`, `parse_images`, `usage_and_cost` and `cmd_options`, plus any limits the provider documents. `usage_and_cost` and `cmd_options` fall through to the Gemini branch for any provider they don't name, so a missing branch gives wrong output rather than an error.
3. Add tests for the request it builds and the response it parses.
4. Add a short section to "Providers and Models" in `SKILL.md`, and add the provider to the README's key table and "Providers and models" section.

## Guidelines

- Keep `SKILL.md` concise: the agent is capable and doesn't need verbose instructions. Let `imagegen.py options` hold the option lists.
- API details belong in the script, where they can be tested; judgement (prompt writing, which model to suggest) belongs in `SKILL.md`.
- The script uses only Python's standard library, and must never print, log or store an API key.
- Test with both Claude Code and Copilot CLI if possible.
- [TESTING.md](TESTING.md) covers every test level: unit tests, dry runs per provider, live smoke tests and a manual check of the skill.
