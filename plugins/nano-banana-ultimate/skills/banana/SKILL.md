---
name: banana
description: >-
  Generate or edit images via Google Gemini (Nano Banana Ultimate).
  Text-to-image generation and multi-image editing with up to 14 input references.
  Triggers on: generate image, create image, edit image, make a picture,
  draw, render, visualize, banana, create visual.
allowed-tools: Bash(uv:*), Bash(ls:*), Read
---

# Nano Banana Ultimate — Image Generation

**Input:** `$ARGUMENTS` (optional plain-language description of what to generate)

If `$ARGUMENTS` is provided, use it as the user's intent and skip to prompt building. If empty, ask a clarifying question.

## Requirements

- `uv` installed
- `GEMINI_API_KEY` environment variable set (get one at https://aistudio.google.com/apikey)

## Workflow

1. **Understand** — Parse the user's request. If the subject or intent is unclear, ask ONE clarifying question.
2. **Build prompt** — Construct a detailed Gemini prompt using the formula below.
3. **Configure** — Choose aspect ratio, resolution, and model. Use defaults unless the user specifies otherwise.
4. **Generate** — Run the script.
5. **Deliver** — Report the saved file path. Do NOT read the image file back. Offer to iterate: adjust style, composition, or prompt.

## Prompt Formula

Build every prompt using this structure:

```
[Subject] + [Action/Pose] + [Environment/Location] + [Composition/Framing] + [Style/Medium]
```

### Rules

- **Positive framing**: Describe what IS in the image, never what is absent. Say "empty street" not "no cars".
- **Strong verb opener**: Start with Generate, Create, Capture, Render, Design, Compose.
- **Be specific**: Include concrete details — materials, lighting direction, time of day, textures.
- **Camera/lens** (photorealistic): "shot on 85mm f/1.4 lens", "low angle", "aerial view".
- **Lighting**: "golden hour side light", "studio softbox", "dramatic chiaroscuro", "overcast diffused".
- **Materiality**: "brushed aluminum", "matte ceramic", "glossy lacquer", "translucent glass".
- **Text in images**: Enclose any text to render in quotes. Specify font style. Note: text rendering may be imperfect.

## Generation

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/banana.py" \
  --prompt "<detailed prompt>" \
  --output "<YYYY-MM-DD-HH-MM-SS-descriptive-name>.png" \
  --resolution <1K|2K|4K> \
  --aspect-ratio <ratio> \
  --model <model>
```

## Editing (with input images)

When the user provides an existing image to modify:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/banana.py" \
  --prompt "<edit instruction: what to change AND what to keep>" \
  --output "<output-path>.png" \
  --input-image "/path/to/source.png"
```

For edits, describe both the change and what must stay identical:
> "Change the background to a sunset beach. Keep the subject, their clothing, and pose exactly the same."

## Defaults

| Parameter | Default |
|---|---|
| Resolution | 1K |
| Aspect ratio | 1:1 |
| Model | gemini-3-pro-image-preview |

## Models

| Model | Best for |
|---|---|
| `gemini-3-pro-image-preview` | Final output, complex scenes, high quality (Nano Banana Pro) |
| `gemini-3.1-flash-image-preview` | Fast drafts, iterations, simple images (Nano Banana 2) |

## Aspect Ratios

| Ratio | Use case |
|---|---|
| 1:1 | Social squares, logos, icons |
| 3:2 | Photography standard |
| 2:3 | Book covers, tall portraits |
| 4:3 | Landscape, presentations |
| 3:4 | Portrait photos, Pinterest |
| 16:9 | YouTube thumbnails, widescreen |
| 9:16 | Stories, Reels, TikTok |
| 4:5 | Instagram portrait |
| 5:4 | Large format print |
| 21:9 | Ultrawide banners |

## Output Naming

Always use timestamped filenames: `YYYY-MM-DD-HH-MM-SS-descriptive-name.png`

Save to the current working directory unless the user specifies a path.

## References

See [references/prompts.md](references/prompts.md) for ready-to-use example prompts covering landscapes, abstract art, interiors, sci-fi, nature, fantasy, still life, and underwater scenes.
