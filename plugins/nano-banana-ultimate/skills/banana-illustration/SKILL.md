---
name: banana-illustration
description: >-
  Generate illustrations in various styles — flat vector, watercolor, line art,
  3D clay render, pixel art, and isometric. Auto-detects style from context.
  Triggers on: illustration, illustrate, flat design, watercolor, line art,
  pixel art, 3D illustration, isometric, sketch, cartoon, vector art, hand drawn.
allowed-tools: Bash(uv:*), Bash(ls:*), Read
---

# Illustration Generator

**Input:** `$ARGUMENTS` (optional — subject and style description)

If `$ARGUMENTS` is provided, use it as the illustration brief and skip to prompt building. If empty, ask about subject and style.

## Requirements

- `uv` installed
- `GEMINI_API_KEY` environment variable set (get one at https://aistudio.google.com/apikey)

## Workflow

1. **Understand** — Parse the user's request. Identify the subject, narrative action, environment, and desired art style. If the style is ambiguous, ask ONE clarifying question or default to flat vector.
2. **Build prompt** — Apply the Prompt Formula below to construct a detailed, positive-framed illustration description.
3. **Configure** — Select aspect ratio and resolution from the Domain Defaults table.
4. **Generate** — Run the script.
5. **Deliver** — Report the saved file path. Do NOT read the image file back. Offer to iterate: swap style, adjust palette, or tweak composition.

## Prompt Formula

```
[Subject/Character] + [Narrative Action] + [Illustrated Environment] + [Balanced Composition] + [Explicit Art Style]
```

## Style Detection Rules

| User Keywords              | Resolved Style                                                    |
|----------------------------|-------------------------------------------------------------------|
| "flat" / "vector"          | Flat vector with solid fills, clean edges                         |
| "watercolor"               | Wet-on-wet watercolor with paper texture, visible brushstrokes    |
| "3D" / "clay"              | Pixar-style clay render, soft shadows                             |
| "pixel"                    | Pixel art with visible grid, limited palette                      |
| "isometric"                | Isometric projection, no perspective vanishing points             |
| "line art" / "ink"         | Consistent weight ink lines, minimal fills                        |
| Ambiguous                  | Default to flat vector                                            |

## Domain Defaults

| Domain         | Aspect Ratio | Resolution |
|----------------|--------------|------------|
| Spot / Icon    | 1:1          | 1K         |
| Scene          | 4:3          | 1K         |

## Generation

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/banana.py" \
  --prompt "<detailed prompt following the formula>" \
  --output "<YYYY-MM-DD-HH-MM-SS-descriptive-name>.png" \
  --resolution 1K \
  --aspect-ratio <ratio from Domain Defaults> \
  --model gemini-3-pro-image-preview
```

## Editing (with input images)

When the user provides an existing image to restyle or modify:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/banana.py" \
  --prompt "<edit instruction: what to change AND what to keep>" \
  --output "<YYYY-MM-DD-HH-MM-SS-descriptive-name>.png" \
  --input-image "/path/to/source.png" \
  --aspect-ratio <ratio>
```

For style transfers, describe the target style and what to preserve:
> "Recreate this photograph as a flat vector illustration with a limited palette of teal, coral, and cream. Keep the composition, subject pose, and environment layout exactly the same."

Up to 14 input images can be passed (repeat `--input-image` for each).

## References

See [references/prompts.md](references/prompts.md) for ready-to-use example prompts covering common illustration styles and scenarios.
