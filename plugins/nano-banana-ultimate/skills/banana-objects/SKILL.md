---
name: banana-objects
description: >-
  Generate product photography and object images — product shots, still life,
  packaging mockups, food photography, and item compositions with studio lighting.
  Triggers on: product photo, product shot, still life, object, packaging,
  food photo, mockup, e-commerce photo, item photography.
allowed-tools: Bash(uv:*), Bash(ls:*), Read
---

# Object & Product Photography

**Input:** `$ARGUMENTS` (optional — product description and intended use)

If `$ARGUMENTS` is provided, use it as the product brief and skip to prompt building. If empty, ask about the product and context.

## Requirements

- `uv` installed
- `GEMINI_API_KEY` environment variable set (get one at https://aistudio.google.com/apikey)

## Workflow

1. **Understand** — Clarify the product, surface, and intended use (catalog, social, editorial).
2. **Build prompt** — Apply the Prompt Formula below to construct a detailed, positive-framed image description.
3. **Configure** — Select aspect ratio and resolution from the Domain Defaults table.
4. **Generate** — Run the script.
5. **Deliver** — Report the saved file path. Do NOT read the image file back. Offer to iterate: adjust angle, lighting, or surface.

## Prompt Formula

```
[Object with Material Description] + [Resting/Floating on Surface] + [Studio or Lifestyle Setting] + [Center-Weighted Hero Composition] + [Studio Photography, Controlled Lighting]
```

## Domain Defaults

| Domain              | Aspect Ratio | Resolution |
|---------------------|--------------|------------|
| E-commerce catalog  | 1:1          | 2K         |
| Instagram product   | 4:5          | 2K         |
| Lifestyle context   | 4:3          | 2K         |

**Lighting guidance:** Use soft diffused studio lighting as the default. Switch to backlit setups for glass and translucent materials to emphasize clarity and refraction.

## Key Instructions

- **Material properties** -- Always describe the material explicitly: matte aluminum, glossy ceramic, brushed steel, frosted glass, soft-touch rubber. Material language drives realism.
- **Surface specification** -- State the surface the object rests on: marble slab, reclaimed wooden table, white sweep, linen cloth, terrazzo countertop.
- **Food photography** -- Include sensory texture cues: rising steam, a drip of honey mid-fall, glistening condensation, crispy golden edges, powdered sugar dusting.
- **Sense of scale** -- Place a contextual element nearby (a hand, a coin, a coffee cup) or describe relative size so the viewer anchors the object's dimensions.

## Generation

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/banana.py" \
  --prompt "<detailed prompt following the formula>" \
  --output "<YYYY-MM-DD-HH-MM-SS-descriptive-name>.png" \
  --resolution 2K \
  --aspect-ratio <ratio from Domain Defaults> \
  --model gemini-3-pro-image-preview
```

## Editing (with input images)

When the user provides an existing product photo to modify (e.g., change background, adjust lighting, add props):

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/banana.py" \
  --prompt "<edit instruction: what to change AND what to keep>" \
  --output "<YYYY-MM-DD-HH-MM-SS-descriptive-name>.png" \
  --input-image "/path/to/source.png" \
  --resolution 2K \
  --aspect-ratio <ratio>
```

For edits, describe both the change and what must stay identical:
> "Replace the white background with a lifestyle scene on a rustic wooden table with warm morning light. Keep the product, its label, color, and proportions exactly the same."

Up to 14 input images can be passed (repeat `--input-image` for each).

## References

See [references/prompts.md](references/prompts.md) for ready-to-use example prompts covering common product photography scenarios.
