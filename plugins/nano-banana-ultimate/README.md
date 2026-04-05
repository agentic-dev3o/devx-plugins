# Nano Banana Ultimate

**The best image generation plugin for Claude Code.** Generate and edit images via Google Gemini with domain-specialized auto-prompt building. You describe what you want in plain language — the plugin builds an optimized prompt following [Google's official best practices](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-nano-banana?hl=en).

## Requirements

- [`uv`](https://docs.astral.sh/uv/) installed
- `GEMINI_API_KEY` environment variable set — [get one here](https://aistudio.google.com/apikey)

## Installation

```
/plugin install nano-banana-ultimate@devx-plugins
```

## Skills

| Skill | Trigger | Default Ratio | Description |
|-------|---------|---------------|-------------|
| `banana` | "generate image", "edit image", "draw" | 1:1 | General-purpose catch-all for any image |
| `banana-ads` | "ad", "banner", "social ad" | varies by format | Online advertising visuals with format-aware sizing |
| `banana-web` | "hero background", "landing page", "web design" | 16:9 | Hero backgrounds, card images, section dividers |
| `banana-youtube` | "thumbnail", "youtube" | 16:9 | Bold, click-optimized YouTube thumbnails |
| `banana-illustration` | "illustration", "watercolor", "pixel art" | 1:1 / 4:3 | Flat vector, watercolor, 3D clay, pixel art, isometric |
| `banana-logo` | "logo", "brand mark", "monogram" | 1:1 | Minimal logo concepts and brand identity marks |
| `banana-people` | "portrait", "headshot", "lifestyle photo" | 3:4 / 3:2 | Portraits, editorial shots, team photos |
| `banana-objects` | "product photo", "still life", "food photo" | 1:1 / 4:5 | Product photography, mockups, food shots |

## Quick Start

```
/banana-youtube coding tutorial about async/await
```

```
/banana-logo minimal tech startup called "Nexus" in blue tones
```

```
/banana-ads Instagram story ad for a meditation app
```

Or just say what you want — Claude routes to the right skill automatically.

## Models

| Model | Name | Speed | Quality | Best For |
|-------|------|-------|---------|----------|
| `gemini-3-pro-image-preview` | Nano Banana Pro | Slower | Highest | Final output, complex scenes |
| `gemini-3.1-flash-image-preview` | Nano Banana 2 | Fast | Good | Drafts, iterations, simple images |

Default: **Nano Banana Pro** for maximum quality.

## Features

- **Auto-prompt building** — You say "a product photo of headphones", Claude builds a detailed prompt with lighting, camera specs, composition, and materiality
- **8 domain-specialized skills** — Each skill applies domain-specific defaults (aspect ratio, resolution, lighting style, composition rules)
- **Image editing** — Pass existing images with `--input-image` for background swaps, style transfers, and refinements (up to 14 reference images)
- **Google best practices** — Every prompt uses positive framing, strong verb openers, camera/lens specs, and materiality descriptions
- **63 reference prompts** — Curated examples across all domains for inspiration and consistency
- **Resolution control** — 1K for drafts, 2K for production, 4K for print
- **10 aspect ratios** — From 1:1 squares to 21:9 ultrawide banners

## How It Works

1. You describe what you want in plain language
2. Claude identifies the domain and applies the right skill
3. The skill builds an optimized Gemini prompt using the formula: `[Subject] + [Action] + [Location] + [Composition] + [Style]`
4. A Python script calls the Google Gemini API and saves a PNG
5. Claude reports the file path and offers to iterate

## File Structure

```
nano-banana-ultimate/
├── .claude-plugin/plugin.json        # Plugin manifest
├── scripts/banana.py                 # Single Python script (google-genai + Pillow)
├── skills/
│   ├── banana/                       # General-purpose catch-all
│   ├── banana-ads/                   # Online advertising
│   ├── banana-web/                   # Web design assets
│   ├── banana-youtube/               # YouTube thumbnails
│   ├── banana-illustration/          # Illustrations (7 sub-styles)
│   ├── banana-logo/                  # Logos and brand identity
│   ├── banana-people/                # People and portraits
│   └── banana-objects/               # Products and objects
└── README.md
```
