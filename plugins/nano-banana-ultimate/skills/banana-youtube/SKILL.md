---
name: banana-youtube
description: >-
  Generate bold, high-contrast YouTube thumbnail images with dramatic framing,
  exaggerated expressions, and click-optimized compositions via Gemini.
  Triggers on: youtube thumbnail, thumbnail, youtube, video thumbnail,
  yt thumbnail, video cover image, click-worthy thumbnail.
allowed-tools: Bash(uv:*), Bash(ls:*), Read
---

# YouTube Thumbnail Maker

**Input:** `$ARGUMENTS` (optional — video topic or thumbnail description)

If `$ARGUMENTS` is provided, use it as the video topic and skip to prompt building. If empty, ask what the video is about.

## Requirements

- `uv` installed
- `GEMINI_API_KEY` environment variable set (get one at https://aistudio.google.com/apikey)

## Workflow

1. **Understand** — Parse the user's request. Identify the video topic, target emotion, and channel style. If the subject or intent is unclear, ask ONE clarifying question.
2. **Build prompt** — Construct a detailed Gemini prompt using the Prompt Formula below. Prioritize dramatic facial expressions, bold colors, and high visual contrast.
3. **Configure** — ALWAYS use 16:9, 2K, and the Pro model. These are non-negotiable for thumbnails.
4. **Generate** — Run the script.
5. **Deliver** — Report the saved file path. Do NOT read the image file back. Offer to iterate: adjust expression, background color, composition, or prompt.

## Prompt Formula

Build every thumbnail prompt using this structure:

```
[Subject with Expression] + [Dramatic Reaction/Gesture] + [Bold Colored Background] + [Close-Up Rule-of-Thirds] + [Hyper-Saturated Photography with Rim Lighting]
```

### Rules

- **Positive framing**: Describe what IS in the image, never what is absent.
- **Strong verb opener**: Start with Generate, Create, Capture, Render, Design, Compose.
- **Faces sell clicks**: Always include a face with an exaggerated expression — wide eyes, open mouth, raised eyebrows, shocked grin.
- **Bold backgrounds**: Use solid, saturated colors (electric blue, hot pink, neon green, deep orange) or dramatic gradients.
- **Rim lighting**: Add a strong backlight or rim light to separate the subject from the background and create a cinematic pop.
- **Text space**: Reserve approximately one-third of the frame for text overlay — typically the opposite side from the subject.
- **No celebrity likenesses**: Never reference real public figures. Describe features generically.

## Defaults

| Parameter    | Default                        |
|--------------|--------------------------------|
| Aspect ratio | 16:9                           |
| Resolution   | 2K                             |
| Model        | gemini-3-pro-image-preview     |

ALWAYS use these defaults. Thumbnails require widescreen, high resolution, and the Pro model for maximum quality. Do not downgrade.

## Thumbnail Psychology

- **Faces with exaggerated expressions drive clicks.** A shocked, excited, or curious face is the single strongest thumbnail element. Always make the expression bigger than real life.
- **Place the subject on the left or right third.** Use rule-of-thirds positioning to leave space for title text on the opposite side.
- **High saturation, deep contrast.** Thumbnails are viewed at small sizes on crowded feeds. Muted tones disappear. Push saturation and contrast to make the image pop at 120px tall.
- **Shallow depth of field.** Blur the background aggressively to make the subject the undeniable focal point.
- **Reserve ~1/3 of the frame for text overlay.** The creator will add bold text in post — leave clean, uncluttered space for it.

## Common Video Genres

| Genre          | Subject Guidance                                      | Background Style                        | Expression / Gesture                    |
|----------------|-------------------------------------------------------|-----------------------------------------|-----------------------------------------|
| Tech review    | Person holding the device, angled toward camera       | Electric blue or dark gradient           | Wide-eyed amazement, mouth slightly open |
| Cooking        | Chef holding the finished dish at eye level           | Warm orange or kitchen bokeh             | Proud smile, steam rising from plate     |
| Travel         | Traveler with arms wide open, scenic landmark behind  | Vivid sky or sunset gradient             | Joyful awe, looking into the distance    |
| Tutorial       | Person pointing at a floating code block or diagram   | Deep purple or dark teal                 | Confident nod, direct eye contact        |
| Fitness        | Athlete mid-motion, muscles defined, sweat visible    | Bold red or neon green                   | Intense determination, clenched jaw      |
| Unboxing       | Hands lifting the product out of the box              | Bright yellow or white spotlight         | Surprised delight, eyebrows raised       |
| Storytime      | Person leaning toward camera, conspiratorial angle    | Moody dark background with spotlight     | Whispered secret expression, wide eyes   |
| Reaction       | Person recoiling or leaning back in shock             | Hot pink or chaotic gradient             | Jaw dropped, hands on cheeks             |
| Educational    | Presenter beside a whiteboard or floating infographic | Clean white or soft blue                 | Thoughtful curiosity, finger raised      |

## Generation

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/banana.py" \
  --prompt "<detailed prompt following the formula>" \
  --output "<YYYY-MM-DD-HH-MM-SS-descriptive-name>.png" \
  --resolution 2K \
  --aspect-ratio 16:9 \
  --model gemini-3-pro-image-preview
```

## Editing (with input images)

When the user provides an existing image to modify (e.g., swap a background, change expression, adjust colors):

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/banana.py" \
  --prompt "<edit instruction: what to change AND what to keep>" \
  --output "<YYYY-MM-DD-HH-MM-SS-descriptive-name>.png" \
  --input-image "/path/to/source.png" \
  --resolution 2K \
  --aspect-ratio 16:9
```

For edits, describe both the change and what must stay identical:
> "Change the background to a bold neon green gradient. Keep the subject's face, expression, clothing, and pose exactly the same."

Up to 14 input images can be passed (repeat `--input-image` for each).

## References

See [references/prompts.md](references/prompts.md) for ready-to-use example prompts covering common YouTube thumbnail scenarios across multiple video genres.
