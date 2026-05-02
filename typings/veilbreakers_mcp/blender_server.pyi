from typing import Any

def _derive_terrain_validation_profiles(
    map_spec: dict[str, Any],
    terrain_result: dict[str, Any],
    object_names: list[str],
    location_results: list[Any],
) -> list[str]: ...

def get_blender_connection() -> Any: ...

def aaa_verify_map(
    paths: list[str],
    min_score: float = ...,
    **kwargs: Any,
) -> dict[str, Any]: ...

async def asset_pipeline(
    *,
    action: str,
    angles: int = ...,
    validation_profile: str | None = ...,
    **kwargs: Any,
) -> dict[str, Any]: ...
