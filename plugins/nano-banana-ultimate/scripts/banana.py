#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "google-genai>=1.0.0",
#     "pillow>=10.0.0",
# ]
# ///
"""Nano Banana Ultimate — Image generation and editing via Google Gemini."""

import argparse
import os
import sys

ASPECT_RATIOS = [
    "1:1", "3:2", "2:3", "4:3", "3:4",
    "16:9", "9:16", "4:5", "5:4", "21:9",
]

MODELS = [
    "gemini-3-pro-image-preview",
    "gemini-3.1-flash-image-preview",
]

RESOLUTIONS = ["1K", "2K", "4K"]


def parse_args():
    parser = argparse.ArgumentParser(description="Generate or edit images via Google Gemini")
    parser.add_argument("-p", "--prompt", required=True, help="Image description or edit instruction")
    parser.add_argument("-o", "--output", required=True, help="Output file path (.png)")
    parser.add_argument("-i", "--input-image", action="append", default=[], help="Input image path (repeatable, up to 14)")
    parser.add_argument("-r", "--resolution", choices=RESOLUTIONS, default=None, help="Output resolution (default: 1K)")
    parser.add_argument("-a", "--aspect-ratio", choices=ASPECT_RATIOS, default="1:1", help="Aspect ratio (default: 1:1)")
    parser.add_argument("-m", "--model", choices=MODELS, default="gemini-3-pro-image-preview", help="Gemini model to use")
    return parser.parse_args()


def detect_resolution(images):
    """Auto-detect resolution from input image dimensions."""
    max_dim = 0
    for img in images:
        max_dim = max(max_dim, img.width, img.height)
    if max_dim <= 1500:
        return "1K"
    elif max_dim <= 3000:
        return "2K"
    return "4K"


def load_input_images(paths):
    """Load and validate input images."""
    from PIL import Image

    if len(paths) > 14:
        print("Error: Maximum 14 input images allowed.", file=sys.stderr)
        sys.exit(1)

    images = []
    for path in paths:
        if not os.path.isfile(path):
            print(f"Error: Input image not found: {path}", file=sys.stderr)
            sys.exit(1)
        images.append(Image.open(path))
    return images


def save_image(image, output_path):
    """Save image as PNG, handling RGBA to RGB conversion."""
    from PIL import Image

    if image.mode == "RGBA":
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[3])
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    image.save(output_path, format="PNG")


def generate(args):
    """Run image generation or editing."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable is not set.", file=sys.stderr)
        print("Get a key at https://aistudio.google.com/apikey", file=sys.stderr)
        sys.exit(1)

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    input_images = load_input_images(args.input_image) if args.input_image else []

    resolution = args.resolution
    if not resolution:
        resolution = detect_resolution(input_images) if input_images else "1K"

    if input_images:
        contents = input_images + [args.prompt]
    else:
        contents = [args.prompt]

    response = client.models.generate_content(
        model=args.model,
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=args.aspect_ratio,
                image_size=resolution,
            ),
        ),
    )

    from PIL import Image
    import io

    saved = False
    for part in response.parts:
        if hasattr(part, "inline_data") and part.inline_data:
            image_bytes = part.inline_data.data
            pil_image = Image.open(io.BytesIO(image_bytes))
            save_image(pil_image, args.output)
            saved = True
            print(args.output)
            break
        elif hasattr(part, "text") and part.text:
            print(part.text, file=sys.stderr)

    if not saved:
        print("Error: No image was generated. The model returned only text.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    args = parse_args()
    generate(args)
