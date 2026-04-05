---
name: banana-logo
description: >-
  Generate logo concepts and brand identity marks — abstract marks, lettermarks,
  mascot emblems, and geometric icons with minimal clean aesthetics.
  Triggers on: logo, brand mark, wordmark, lettermark, icon logo, brand identity,
  monogram, emblem, logo design, logo concept.
allowed-tools: Bash(uv:*), Bash(ls:*), Read
---

# Logo & Brand Identity

**Input:** `$ARGUMENTS` (optional — brand name, industry, and style direction)

If `$ARGUMENTS` is provided, use it as the brand brief and skip to prompt building. If empty, ask about the brand.

## Requirements

- `uv` installed
- `GEMINI_API_KEY` environment variable set (get one at https://aistudio.google.com/apikey)

## Workflow

1. **Understand** — Clarify the brand name, industry, personality adjectives (e.g., bold, playful, minimal), and any existing color palette or symbol preferences the user has.
2. **Build prompt** — Compose a generation prompt following the Prompt Formula below, incorporating the user's brand attributes.
3. **Configure** — Apply the Defaults (1:1, 1K, Pro model). Override only if the user explicitly requests a different setting.
4. **Generate** — Run the script.
5. **Deliver** — Report the saved file path. Do NOT read the image file back. Remind the user of the Text Caveat if letterforms are included. Offer to iterate.

## Prompt Formula

```
[Brand Symbol/Shape] + [Static Balanced Pose] + [White Background] + [Centered Symmetric Composition] + [Minimal Flat Vector / Geometric]
```

## Defaults

ALWAYS apply these unless the user explicitly overrides:

| Setting | Value |
|---------|-------|
| Aspect ratio | 1:1 |
| Resolution | 1K |
| Model | Pro |

## Key Constraints

- **Favicon test** -- The logo must work at 16x16 px favicon size. Avoid fine details, thin strokes, and intricate ornamentation.
- **Color limit** -- Maximum 2-3 colors. Fewer colors reproduce better across media.
- **White background** -- Always include "on a white background" in the prompt for easy extraction and compositing.
- **Shape language** -- Angular shapes convey tech / aggressive energy. Rounded shapes convey friendly / approachable energy. Choose deliberately.
- **TEXT CAVEAT** -- Gemini is unreliable for exact letterforms. Warn the user: treat any text in the generated image as a visual concept only and recreate it in a proper vector tool (Figma, Illustrator, Inkscape) for final use.

## Logo Type Guidance

| Type | When to use | Prompt emphasis |
|------|------------|-----------------|
| **Abstract mark** | Brand wants a unique symbol not tied to a literal object | Geometric shapes, overlapping forms, negative space |
| **Lettermark** | Brand name is long or acronym-friendly | Bold single letter or monogram, simple sans-serif geometry |
| **Mascot** | Brand targets a playful or community-driven audience | Simplified character, minimal detail, bold outline |
| **Geometric icon** | App icon or tech product needing a clean scalable mark | Primitive shapes (circle, square, triangle), flat color fills |

## Generation

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/banana.py" \
  --prompt "<detailed prompt following the formula>" \
  --output "<YYYY-MM-DD-HH-MM-SS-descriptive-name>.png" \
  --resolution 1K \
  --aspect-ratio 1:1 \
  --model gemini-3-pro-image-preview
```

## Editing (with input images)

When the user provides an existing logo or sketch to refine:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/banana.py" \
  --prompt "<edit instruction: what to change AND what to keep>" \
  --output "<YYYY-MM-DD-HH-MM-SS-descriptive-name>.png" \
  --input-image "/path/to/source.png" \
  --resolution 1K \
  --aspect-ratio 1:1
```

For logo refinements, be explicit about what to preserve:
> "Simplify this sketch into a clean geometric vector mark using only two colors: deep navy and white. Keep the overall shape and proportions exactly the same."

Up to 14 input images can be passed (repeat `--input-image` for each).

## References

See [references/prompts.md](references/prompts.md) for ready-to-use example prompts.
