---
name: banana-people
description: >-
  People & portrait photography via Google Gemini (Nano Banana Ultimate).
  Triggers on: portrait, headshot, lifestyle photo, people, person,
  editorial photo, team photo, professional photo, face, human.
allowed-tools: Bash(uv:*), Bash(ls:*), Read
---

# People & Portrait Photography

**Input:** `$ARGUMENTS` (optional — subject description and scene)

If `$ARGUMENTS` is provided, use it as the portrait brief and skip to prompt building. If empty, ask about the subject and setting.

## Requirements

- `uv` installed
- `GEMINI_API_KEY` environment variable set (get one at https://aistudio.google.com/apikey)

## Workflow

1. **Understand** — Parse the user's request. Identify the subject (age, build, expression), setting, and intended use. If the subject or intent is unclear, ask ONE clarifying question.
2. **Build prompt** — Construct a detailed Gemini prompt using the Prompt Formula below. Always describe clothing, environment, and camera distance explicitly.
3. **Configure** — Choose aspect ratio, resolution, and lens based on the Domain Defaults table. Use defaults unless the user specifies otherwise.
4. **Generate** — Run the script.
5. **Deliver** — Report the saved file path. Do NOT read the image file back. Offer to iterate: adjust pose, lighting, framing, or prompt.

## Prompt Formula

Build every people/portrait prompt using this structure:

```
[Person: age/build/expression/clothing] + [Natural Action/Pose] + [Real-World Environment] + [Portrait Framing + Rule of Thirds] + [Natural Light Photography, specific lens]
```

### Rules

- **Positive framing**: Describe what IS in the image, never what is absent.
- **Strong verb opener**: Start with Capture, Photograph, Shoot, Frame, Compose.
- **Clothing and environment**: Always describe what the person is wearing and the specific setting they are in.
- **Camera distance**: Specify explicitly — close-up, medium shot, full-body, three-quarter length.
- **Mood keywords**: Use "candid" for natural, spontaneous moments. Use "editorial" for styled, intentional compositions.
- **No celebrity likenesses**: Never reference real public figures. Describe features generically (e.g., "a person in their 30s with short dark hair").

## Domain Defaults

| Domain | Aspect Ratio | Lens | Notes |
|---|---|---|---|
| Headshot | 3:4 | 85mm f/1.4 | Tight crop, shallow depth of field, subject fills frame |
| Editorial / Lifestyle | 3:2 | 35mm f/2.0 | Environmental context, wider framing |
| Group scene / Team | 16:9 | 24mm f/4.0 | Deep focus, everyone sharp |
| **Resolution** | **2K** | | All people domains default to 2K |
| **Lighting** | **Natural window light or golden hour** | | Soft, flattering, directional |

## Generation

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/banana.py" \
  --prompt "<detailed prompt following the formula>" \
  --output "<YYYY-MM-DD-HH-MM-SS-descriptive-name>.png" \
  --resolution 2K \
  --aspect-ratio <ratio> \
  --model gemini-3-pro-image-preview
```

## Editing (with input images)

When the user provides an existing photo to modify (e.g., change background, adjust lighting, swap clothing):

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/banana.py" \
  --prompt "<edit instruction: what to change AND what to keep>" \
  --output "<YYYY-MM-DD-HH-MM-SS-descriptive-name>.png" \
  --input-image "/path/to/source.png" \
  --resolution 2K \
  --aspect-ratio <ratio>
```

For edits, describe both the change and what must stay identical:
> "Change the background to a warm golden-hour park scene. Keep the subject's face, expression, clothing, and pose exactly the same."

Up to 14 input images can be passed (repeat `--input-image` for each).

## Reference Prompts

See [references/prompts.md](references/prompts.md) for ready-to-use example prompts covering headshots, lifestyle, editorial, group, and environmental portrait scenarios.
