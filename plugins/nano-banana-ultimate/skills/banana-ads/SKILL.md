---
name: banana-ads
description: >-
  Generate advertising visuals — banners, social media ads, display ads, and
  promotional graphics with auto-prompt building and format-aware aspect ratios.
  Triggers on: ad, banner, advertisement, display ad, social ad, promo graphic,
  campaign visual, marketing image, sponsored post image, ad creative.
allowed-tools: Bash(uv:*), Bash(ls:*), Read
---

# Online Advertising Visuals

**Input:** `$ARGUMENTS` (optional — product/service and ad format)

If `$ARGUMENTS` is provided, use it as the campaign brief and skip to prompt building. If empty, ask about the product and target placement.

## Requirements

- `uv` installed
- `GEMINI_API_KEY` environment variable set (get one at https://aistudio.google.com/apikey)

## Workflow

1. **Understand** — Clarify the product or service, the value proposition, and the target ad placement (Instagram feed, YouTube pre-roll, web banner, etc.).
2. **Build prompt** — Apply the Prompt Formula below to construct a bold, commercially viable image description.
3. **Configure** — Detect the ad format from context and select aspect ratio and resolution from the Ad Format Detection table.
4. **Generate** — Run the script. the generation script with the assembled prompt and settings.
5. **Deliver** — Report the saved file path. Do NOT read the image file back. Offer to iterate: adjust composition, color palette, or layout.

## Prompt Formula

```
[Product/Service] + [Value Proposition as Action] + [Ad Placement Context] + [Bold Center-Weighted Composition] + [Clean Commercial Photography or Flat Design]
```

## Ad Format Detection

| Placement              | Aspect Ratio | Resolution |
|------------------------|--------------|------------|
| Instagram/Facebook feed | 4:5          | 2K         |
| Instagram story         | 9:16         | 2K         |
| YouTube pre-roll        | 16:9         | 2K         |
| Web banner              | 21:9         | 2K         |
| Square social           | 1:1          | 2K         |

## Key Instructions

- **Negative space for text overlay** -- Always leave generous negative space (top, bottom, or side) for headline and CTA placement. Ad visuals are incomplete without copy; design the composition to accommodate it.
- **No baked-in text** -- Do NOT prompt Gemini to render text into the image. Gemini text rendering is unreliable and produces artifacts. Advise the user to add headlines, CTAs, and legal copy in a separate design tool (Figma, Canva, Photoshop).
- **Bold center-weighted composition** -- Place the hero product or key visual element at the center or slightly off-center with clean breathing room around it.
- **Commercial lighting** -- Default to clean, bright studio lighting with soft shadows. Use high-key lighting for upbeat campaigns and moody side lighting for premium or luxury positioning.
- **Color psychology** -- Match the color palette to the campaign intent: warm tones for urgency and sales, cool tones for trust and tech, vibrant saturated hues for youth and energy.

## Generation

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/banana.py" \
  --prompt "<detailed prompt following the formula>" \
  --output "<YYYY-MM-DD-HH-MM-SS-descriptive-name>.png" \
  --resolution <2K> \
  --aspect-ratio <ratio from Ad Format Detection table> \
  --model gemini-3-pro-image-preview
```

## Editing (with input images)

When the user provides a product photo or existing visual to modify:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/banana.py" \
  --prompt "<edit instruction: what to change AND what to keep>" \
  --output "<YYYY-MM-DD-HH-MM-SS-descriptive-name>.png" \
  --input-image "/path/to/source.png" \
  --aspect-ratio <ratio>
```

For edits, describe both the change and what must stay identical:
> "Place this product on a clean bright studio background with soft shadow. Keep the product, its color, and proportions exactly the same."

Up to 14 input images can be passed (repeat `--input-image` for each).

## References

See [references/prompts.md](references/prompts.md) for ready-to-use example prompts covering common advertising visual scenarios.
