---
name: banana-web
description: >-
  Generate web design assets — hero backgrounds, landing page visuals, card images,
  section dividers, and motion design keyframes with dark/light mode support.
  Triggers on: web design, hero image, hero background, landing page background,
  website asset, section graphic, UI mockup, web banner, motion design asset,
  web illustration.
allowed-tools: Bash(uv:*), Bash(ls:*), Read
---

# Web Design Assets

**Input:** `$ARGUMENTS` (optional — asset type and visual description)

If `$ARGUMENTS` is provided, use it as the design brief and skip to prompt building. If empty, ask about the asset type and theme.

## Requirements

- `uv` installed
- `GEMINI_API_KEY` environment variable set (get one at https://aistudio.google.com/apikey)

## Workflow

1. **Understand** — Parse the user's request. Identify the asset type (hero, card, section divider, banner, motion keyframe), its placement context, and intended visual tone. Ask whether the asset targets **dark mode or light mode** if not specified. If the subject or intent is unclear, ask ONE clarifying question.
2. **Build prompt** — Construct a detailed Gemini prompt using the Prompt Formula below. Ensure the prompt specifies negative space placement and focal point offset for headline overlay compatibility.
3. **Configure** — Choose aspect ratio, resolution, and model based on the Asset Type Defaults table. Use defaults unless the user specifies otherwise.
4. **Generate** — Run the script.
5. **Deliver** — Report the saved file path. Do NOT read the image file back. Offer to iterate: adjust palette, composition, theme, or prompt.

## Prompt Formula

Build every web design asset prompt using this structure:

```
[UI Element/Scene] + [Visual Hierarchy Direction] + [Theme Context: dark/light] + [Wide Cinematic Composition] + [Modern Digital Art / Gradient Mesh / 3D Abstract]
```

### Rules

- **Positive framing**: Describe what IS in the image, never what is absent.
- **Strong verb opener**: Start with Design, Compose, Render, Create, Generate.
- **Background-first thinking**: Generate assets that work as backgrounds — large negative space, non-centered focal point positioned to allow headline overlay.
- **Dark/light mode awareness**: Always consider the target theme. Dark mode assets use deep bases (#0a0a0a to #1a1a2e) with luminous accents. Light mode assets use soft whites and pastels with subtle depth.
- **Modern aesthetics**: Favor gradient meshes, abstract 3D shapes, glassmorphism elements, soft glows, and volumetric lighting.
- **Composition**: Offset the focal point to one side or corner, leaving generous negative space for text content.

## Asset Type Defaults

| Asset Type | Aspect Ratio | Resolution | Notes |
|---|---|---|---|
| Hero background | 16:9 | 2K | Wide composition, focal point offset for headline overlay |
| Card image | 3:2 | 1K | Contained composition, centered or subtly offset subject |
| Section divider | 21:9 | 1K | Ultra-wide, horizontal flow, seamless horizontal tiling |
| Motion keyframe | 16:9 | 2K | Dynamic composition, implied movement, animation-ready |

## Generation

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/banana.py" \
  --prompt "<detailed prompt following the formula>" \
  --output "<YYYY-MM-DD-HH-MM-SS-descriptive-name>.png" \
  --resolution <1K|2K> \
  --aspect-ratio <ratio> \
  --model gemini-3-pro-image-preview
```

## Editing (with input images)

When the user provides an existing asset to modify (e.g., change palette, swap theme, adjust composition):

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/banana.py" \
  --prompt "<edit instruction: what to change AND what to keep>" \
  --output "<YYYY-MM-DD-HH-MM-SS-descriptive-name>.png" \
  --input-image "/path/to/source.png" \
  --aspect-ratio <ratio>
```

For edits, describe both the change and what must stay identical:
> "Convert this hero background to dark mode — shift the base to deep navy, change accent colors to luminous cyan. Keep the composition, shapes, and layout exactly the same."

Up to 14 input images can be passed (repeat `--input-image` for each).

## Reference Prompts

See [references/prompts.md](references/prompts.md) for ready-to-use example prompts covering hero backgrounds, card illustrations, section dividers, dashboard mockups, and gradient mesh compositions for both dark and light themes.
