"""Async Hammock — chainable wrapper over httpx.AsyncClient."""

from __future__ import annotations

import typing as t
from urllib.parse import urljoin

import httpx

from .base import HammockBase

if t.TYPE_CHECKING:
    from httpx import AsyncClient

__all__ = ["AsyncHammock"]


class AsyncHammock(HammockBase):
    """Async chainable wrapper over ``httpx.AsyncClient``"""

    _client: AsyncClient  # type: ignore[name-defined]
    _session: AsyncClient  # alias for compat

    def __init__(
        self,
        name: str | None = None,
        parent: AsyncHammock | None = None,
        append_slash: bool = False,
        session: AsyncClient | None = None,  # type: ignore[name-defined]
        client: AsyncClient | None = None,  # type: ignore[name-defined]
        **kwargs: t.Any,
    ) -> None:
        self._name = name
        self._parent = parent  # type: ignore[assignment]
        self._append_slash = append_slash
        _client = client if client is not None else session
        if _client is not None:
            self._client = _client  # type: ignore[assignment]
            self._session = _client  # type: ignore[assignment]
            for k, v in kwargs.items():
                try:
                    orig = getattr(self._client, k)
                except AttributeError as exc:
                    raise AttributeError(
                        f"'{type(self._client).__name__}' has no attribute '{k}'"
                    ) from exc
                if (
                    hasattr(orig, "update")
                    and callable(orig.update)  # type: ignore[union-attr]
                    and isinstance(v, dict)
                ):
                    try:
                        orig.update(v)  # type: ignore[attr-defined]
                    except Exception:
                        try:
                            setattr(self._client, k, v)
                        except AttributeError as exc2:
                            raise AttributeError(
                                f"'{type(self._client).__name__}' has no attribute '{k}'"
                            ) from exc2
                else:
                    try:
                        setattr(self._client, k, v)
                    except AttributeError as exc2:
                        raise AttributeError(
                            f"'{type(self._client).__name__}' has no attribute '{k}'"
                        ) from exc2
        else:
            try:
                self._client = httpx.AsyncClient(**kwargs)
            except TypeError as exc:
                raise AttributeError(str(exc)) from exc
            self._session = self._client

    async def _aclose(self) -> None:
        if getattr(self, "_client", None):
            await self._client.aclose()

    def _close_session(self) -> None:  # pragma: no cover
        try:
            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._client.aclose())
            else:
                loop.run_until_complete(self._client.aclose())
        except Exception:
            pass

    async def _request(self, method: str, *args: t.Any, **kwargs: t.Any) -> httpx.Response:
        follow_redirects: bool | None = None
        if "follow_redirects" in kwargs:
            follow_redirects = kwargs.pop("follow_redirects")
        if "allow_redirects" in kwargs:
            allow = kwargs.pop("allow_redirects")
            if follow_redirects is None:
                follow_redirects = bool(allow)
        if follow_redirects is None:
            follow_redirects = True

        url = self._url(*args)
        if not follow_redirects:
            return await self._client.request(method, url, follow_redirects=False, **kwargs)

        resp = await self._client.request(method, url, follow_redirects=False, **kwargs)
        redirect_codes = (301, 302, 303, 307, 308)
        max_redirects = getattr(self._client, "max_redirects", 20)
        count = 0
        while resp.status_code in redirect_codes and count < max_redirects:
            location = resp.headers.get("Location") if hasattr(resp.headers, "get") else None
            if not location or not isinstance(location, str):
                break
            if resp.status_code == 303:
                method = "get"
                kwargs.pop("data", None)
                kwargs.pop("json", None)
                kwargs.pop("content", None)
                kwargs.pop("files", None)
            next_url = urljoin(getattr(resp, "url", None) and str(resp.url) or url, location)
            url = next_url
            resp = await self._client.request(method, url, follow_redirects=False, **kwargs)
            count += 1
        return resp

    async def __aenter__(self) -> AsyncHammock:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._client.aclose()

    async def close(self) -> None:
        await self._client.aclose()


def _bind_async_method(method: str) -> t.Callable[..., t.Awaitable[httpx.Response]]:
    async def aux(hammock: AsyncHammock, *args: t.Any, **kwargs: t.Any) -> httpx.Response:
        return await hammock._request(method, *args, **kwargs)

    aux.__name__ = method.upper()
    return aux


for _method in AsyncHammock.HTTP_METHODS:
    setattr(AsyncHammock, _method.upper(), _bind_async_method(_method))
