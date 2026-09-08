"""Typed kwargs for Hammock request verbs.

Mirrors ``httpx.Client.request`` (and ``AsyncClient.request``) plus
legacy ``allow_redirects`` alias.  Used with ``Unpack`` so

    def GET(self, *args: PathPart, **kwargs: Unpack[HammockRequestKwargs]) -> Response

is checked instead of ``**kwargs: Any``.
"""

from __future__ import annotations

import typing as t

from httpx._types import (  # type: ignore[attr-defined]
    AuthTypes,
    CookieTypes,
    HeaderTypes,
    QueryParamTypes,
    RequestContent,
    RequestData,
    RequestExtensions,
    RequestFiles,
    TimeoutTypes,
)
from typing_extensions import Unpack  # type: ignore[import-not-found]

# Path part is any object that can be str()'d; keep permissive but not Any
PathPart = t.Union[str, bytes, int, float, bool]


class HammockRequestKwargs(t.TypedDict, total=False):
    """Kwargs accepted by Hammock verbs = httpx.request kwargs + redirect alias."""

    params: QueryParamTypes | None
    headers: HeaderTypes | None
    cookies: CookieTypes | None
    auth: AuthTypes | None
    content: RequestContent | None
    data: RequestData | None
    files: RequestFiles | None
    json: t.Any | None
    timeout: TimeoutTypes | None
    extensions: RequestExtensions | None
    # httpx uses follow_redirects; Hammock also accepts legacy allow_redirects
    follow_redirects: bool | None
    allow_redirects: bool | None  # legacy alias -> follow_redirects


__all__ = ["HammockRequestKwargs", "PathPart", "Unpack"]
