from __future__ import annotations

from typing import Any, Iterator


class _Dynamic:
    def __getattr__(self, name: str) -> Any: ...
    def __setattr__(self, name: str, value: Any) -> None: ...
    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
    def __iter__(self) -> Iterator[Any]: ...
    def __getitem__(self, key: Any) -> Any: ...


class types:
    class BMVert(_Dynamic):
        co: Any
        index: int

    class BMEdge(_Dynamic): ...
    class BMFace(_Dynamic):
        normal: Any
        verts: Any

    class BMesh(_Dynamic):
        verts: Any
        edges: Any
        faces: Any
        def from_mesh(self, mesh: Any) -> None: ...
        def to_mesh(self, mesh: Any) -> None: ...
        def free(self) -> None: ...


ops: _Dynamic


def new() -> types.BMesh: ...
def __getattr__(name: str) -> Any: ...
