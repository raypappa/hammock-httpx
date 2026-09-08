"""Typed kwargs for Hammock request verbs.

Mirrors ``httpx.Client.request`` (and ``AsyncClient.request``) plus
legacy ``allow_redirects`` alias.  Used with ``Unpack`` so

    def GET(self, *args: PathPart, **kwargs: Unpack[HammockRequestKwargs]) -> Response

is checked instead of ``**kwargs: Any``.
"""

from __future__ import annotations

import ssl
import typing as t

from httpx._types import (  # type: ignore[attr-defined]
    AuthTypes,
    CertTypes,
    CookieTypes,
    HeaderTypes,
    ProxyTypes,
    QueryParamTypes,
    RequestContent,
    RequestData,
    RequestExtensions,
    RequestFiles,
    TimeoutTypes,
    URLTypes,
)
from typing_extensions import Self, Unpack  # type: ignore[import-not-found]

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


class HttpxClientKwargs(t.TypedDict, total=False):
    """Kwargs accepted by httpx.Client / AsyncClient (forwarded by Hammock.__init__)."""

    auth: AuthTypes | None
    params: QueryParamTypes | None
    headers: HeaderTypes | None
    cookies: CookieTypes | None
    verify: ssl.SSLContext | str | bool | None
    cert: CertTypes | None
    trust_env: bool | None
    http1: bool | None
    http2: bool | None
    proxy: ProxyTypes | None
    timeout: TimeoutTypes | None
    follow_redirects: bool | None
    max_redirects: int | None
    base_url: URLTypes | None
    mounts: t.Mapping[str, t.Any | None] | None
    limits: t.Any | None  # httpx.Limits
    event_hooks: t.Mapping[str, list[t.Any]] | None
    transport: t.Any | None  # BaseTransport
    default_encoding: str | t.Callable[[bytes], str] | None


__all__ = ["HammockRequestKwargs", "HttpxClientKwargs", "PathPart", "Self", "Unpack"]
