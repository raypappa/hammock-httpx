"""Shared base for sync and async Hammock."""

from __future__ import annotations

import copy
import typing as t

from ._types import PathPart

__all__ = ["HammockBase"]


class HammockBase:
    """Common URL-chaining logic for Hammock / AsyncHammock."""

    HTTP_METHODS: list[str] = [
        "get",
        "options",
        "head",
        "post",
        "put",
        "patch",
        "delete",
        "trace",
        "connect",
        "query",
    ]

    # attributes set by subclasses
    _name: str | None = None  # type: ignore[assignment]
    _parent: t.Any = None
    _append_slash: bool = False

    def _spawn(self, name: str) -> t.Any:
        """Return a shallow copy as nested child, stripping slashes for resource URIs."""
        child = copy.copy(self)
        if isinstance(name, str):
            name = name.strip("/")
        child._name = name  # type: ignore[attr-defined]
        child._parent = self  # type: ignore[attr-defined]
        return child

    def __getattr__(self, name: str) -> t.Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return self._spawn(name)

    def __iter__(self) -> t.Iterator[t.Any]:
        current: t.Any = self
        while current:
            if current._name:  # type: ignore[attr-defined]
                yield current
            current = current._parent  # type: ignore[attr-defined]

    def _chain(self, *path: PathPart) -> t.Any:
        chain: t.Any = self
        for arg in path:
            chain = chain._spawn(str(arg))
        return chain

    def __call__(self, *path: PathPart) -> t.Any:
        return self._chain(*path)

    def _url(self, *path: PathPart) -> str:
        path_comps: list[str] = [
            c._name
            for c in self._chain(*path)
            if c._name is not None  # type: ignore[attr-defined,misc]
        ]
        url: str = "/".join(reversed(path_comps))
        if self._append_slash:  # type: ignore[attr-defined]
            url = url + "/"
        return url

    def __repr__(self) -> str:
        return self._url()
