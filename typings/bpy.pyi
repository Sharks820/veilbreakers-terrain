from __future__ import annotations

from typing import Any, Iterator


class _Dynamic:
    def __getattr__(self, name: str) -> Any: ...
    def __setattr__(self, name: str, value: Any) -> None: ...
    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
    def __iter__(self) -> Iterator[Any]: ...
    def __getitem__(self, key: Any) -> Any: ...
    def __setitem__(self, key: Any, value: Any) -> None: ...
    def get(self, key: Any, default: Any = ...) -> Any: ...
    def new(self, *args: Any, **kwargs: Any) -> Any: ...
    def remove(self, *args: Any, **kwargs: Any) -> Any: ...


class types:
    class ID(_Dynamic): ...
    class Object(_Dynamic):
        name: str
        type: str
        data: Any
        location: Any
        rotation_euler: Any
        scale: Any
        matrix_world: Any
        material_slots: Any
        active_material: Any
        modifiers: Any

    class Material(_Dynamic):
        name: str
        use_nodes: bool
        node_tree: Any
        diffuse_color: Any

    class Mesh(_Dynamic):
        name: str
        vertices: Any
        edges: Any
        polygons: Any
        materials: Any

    class Collection(_Dynamic):
        name: str
        objects: Any
        children: Any

    class Camera(_Dynamic):
        lens: float
        angle: float
        clip_end: float

    class Light(_Dynamic):
        type: str
        energy: float
        angle: float

    class Scene(_Dynamic):
        camera: Object | None
        collection: Collection
        render: Any
        world: Any
        frame_start: int
        frame_end: int

    class RenderSettings(_Dynamic):
        bl_rna: Any
        engine: str
        filepath: str
        resolution_x: int
        resolution_y: int

    class Image(_Dynamic):
        name: str
        filepath: str

    class NodeTree(_Dynamic):
        nodes: Any
        links: Any

    class Node(_Dynamic): ...
    class Operator(_Dynamic): ...
    class PropertyGroup(_Dynamic): ...
    class Panel(_Dynamic): ...
    class AddonPreferences(_Dynamic): ...


class props:
    @staticmethod
    def StringProperty(*args: Any, **kwargs: Any) -> Any: ...
    @staticmethod
    def IntProperty(*args: Any, **kwargs: Any) -> Any: ...
    @staticmethod
    def FloatProperty(*args: Any, **kwargs: Any) -> Any: ...
    @staticmethod
    def BoolProperty(*args: Any, **kwargs: Any) -> Any: ...
    @staticmethod
    def EnumProperty(*args: Any, **kwargs: Any) -> Any: ...
    @staticmethod
    def CollectionProperty(*args: Any, **kwargs: Any) -> Any: ...
    @staticmethod
    def PointerProperty(*args: Any, **kwargs: Any) -> Any: ...
    @staticmethod
    def FloatVectorProperty(*args: Any, **kwargs: Any) -> Any: ...
    @staticmethod
    def IntVectorProperty(*args: Any, **kwargs: Any) -> Any: ...
    @staticmethod
    def BoolVectorProperty(*args: Any, **kwargs: Any) -> Any: ...


data: _Dynamic
context: _Dynamic
ops: _Dynamic
app: _Dynamic
utils: _Dynamic


def __getattr__(name: str) -> Any: ...
