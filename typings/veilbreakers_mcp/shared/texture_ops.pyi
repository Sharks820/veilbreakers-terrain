from typing import Any

from PIL import Image

def generate_uv_mask_image(
    polygons: list[list[tuple[float, float]]],
    texture_size: int = ...,
    feather_radius: int = ...,
) -> Image.Image: ...

def make_tileable(image_bytes: bytes, overlap_pct: float = ...) -> bytes: ...

def render_wear_map(
    curvature_data: dict[int, float],
    texture_size: int = ...,
    uv_data: Any | None = ...,
) -> bytes: ...

def apply_hsv_adjustment(
    image_bytes: bytes,
    mask_bytes: bytes,
    hue_shift: float = ...,
    saturation_scale: float = ...,
    **kwargs: Any,
) -> bytes: ...

def inpaint_texture(
    image_bytes: bytes,
    mask_bytes: bytes,
    prompt: str,
    fal_key: str | None = ...,
    **kwargs: Any,
) -> dict[str, Any]: ...
