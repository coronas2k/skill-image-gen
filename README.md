# 🎨 AI Image Generation Skill

> Generate images on-the-fly from your coding workflow — powered by OpenAI, Google Gemini, or OpenRouter.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![VS Code](https://img.shields.io/badge/VS%20Code-Agent%20Plugin-007ACC?logo=visualstudiocode)](https://code.visualstudio.com/docs/copilot/customization/agent-plugins)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-compatible-6f42c1)](https://www.anthropic.com/claude-code)
[![GitHub Copilot CLI](https://img.shields.io/badge/Copilot%20CLI-compatible-24292f?logo=github)](https://github.com/github/copilot-cli)

An agent plugin that gives your AI coding assistant the ability to generate images. Just ask — the skill handles provider selection, API key setup, and generation conversationally.

## ✨ Features

- **Three providers:** OpenAI (`gpt-image-2`, `gpt-image-2.5`/`2.6`), Google Gemini (Nano Banana 2.1, Nano Banana Pro), and OpenRouter (multi-model, default `black-forest-labs/flux-3-image-klein` at 4K)
- **Zero config up front** — the skill onboards you the first time you use it
- **Better prompts** — short requests are expanded into full descriptions, with rules for rendering text inside images
- **Prompt records** — each image is saved with a `.json` file holding the exact prompt, model, settings and cost
- **Cross-tool compatible** — works in VS Code, Copilot CLI, and Claude Code
- **Agent plugin format** — discoverable, installable, and manageable from the Extensions view

## 🚀 Install

### VS Code (recommended)

Open the Command Palette (`Cmd+Shift+P`) and run:

```
Chat: Install Plugin From Source
```

Enter this repo URL:

```
https://github.com/coronas2k/skill-image-gen
```

The plugin and its skills will appear in your Extensions sidebar under **Agent Plugins**.

### Copilot CLI / Claude Code

```bash
git clone https://github.com/coronas2k/skill-image-gen.git
cd skill-image-gen
./install.sh
```

<details>
<summary>Installer flags</summary>

| Flag | Description |
|---|---|
| `--claude-only` | Install for Claude Code only |
| `--copilot-only` | Install for Copilot CLI only |
| `--link` | Symlink instead of copy (for development) |
| `--uninstall` | Remove installed skill |
| `--dry-run` | Preview what would happen |

</details>

## 💬 Usage

Just ask your AI assistant to generate an image:

- *"Generate a hero image for my landing page"*
- *"Create a seamless grass texture for my game"*
- *"Make an app icon for a weather app"*

The skill takes care of the rest — including walking you through API key setup if it's your first time.

## 📁 Structure

```
skill-image-gen/
├── plugin.json              # Plugin manifest
├── skills/
│   └── generate-image/
│       └── SKILL.md         # The skill — all logic lives here
├── install.sh               # CLI installer
├── README.md
├── CONTRIBUTING.md
└── LICENSE
```

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## 🙏 Acknowledgements

This plugin is based on [skill-image-gen](https://github.com/adamd9/skill-image-gen) by [adamd9](https://github.com/adamd9), updated for the latest OpenAI and Gemini image models.

## 📄 License

MIT — see [LICENSE](LICENSE).
