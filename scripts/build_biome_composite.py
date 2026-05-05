"""Build a single side-by-side composite of all 3 biomes for quick review.

Picks the best representative camera per biome and stacks them in a
1×3 grid for a quick AAA-comparison glance.
"""
from __future__ import annotations
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "renders/coastal/_3_BIOME_COMPOSITE.png"

# Best representative per biome
PICKS = [
    ("Coastal", "renders/coastal/c1_coastal_cycles/vb_coastal_player_camera.png",
     "Bezier-SDF shoreline, animated water, 6 species, drift+boulder props"),
    ("Mountain + Forest", "renders/coastal/m1_mountain_forest/vb_mountain_valley.png",
     "320m peaks, 5-zone PBR (forest→alpine→scree→rock→snow), 5 alpine species"),
    ("Grassland", "renders/coastal/g1_grassland/vb_grassland_valley.png",
     "Rolling hills + river + pond, 4-zone PBR, 7 pastoral species"),
]

W, H = 1600, 900
PAD = 40
LABEL_H = 80
TOTAL_W = W * 3 + PAD * 4
TOTAL_H = H + LABEL_H + PAD * 2
canvas = Image.new("RGB", (TOTAL_W, TOTAL_H), (24, 24, 28))

draw = ImageDraw.Draw(canvas)
try:
    font_big = ImageFont.truetype("arial.ttf", 36)
    font_small = ImageFont.truetype("arial.ttf", 18)
except Exception:
    font_big = ImageFont.load_default()
    font_small = ImageFont.load_default()

draw.text((PAD, PAD // 2), "VeilBreakers — 3-Biome AAA Visual Verification (4096m × 4096m each)",
          fill=(220, 220, 230), font=font_big)

for i, (name, path, desc) in enumerate(PICKS):
    x = PAD + i * (W + PAD)
    y = PAD + LABEL_H
    src = REPO / path
    if src.exists():
        im = Image.open(src).convert("RGB")
        im.thumbnail((W, H))
        canvas.paste(im, (x, y))
    else:
        draw.rectangle((x, y, x + W, y + H), fill=(60, 60, 70))
        draw.text((x + W // 2 - 100, y + H // 2),
                  f"(MISSING: {path})", fill=(200, 80, 80), font=font_small)
    # Label
    draw.text((x, y - 30), name, fill=(255, 255, 255), font=font_big)
    # Description (wrap)
    draw.text((x, y + H + 5), desc, fill=(180, 180, 200), font=font_small)

OUT.parent.mkdir(parents=True, exist_ok=True)
canvas.save(OUT)
print(f"COMPOSITE_BUILT {OUT} {OUT.stat().st_size} bytes")
