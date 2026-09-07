"""Sync Hammock — chainable wrapper over httpx.Client."""

from __future__ import annotations

import typing as t
from urllib.parse import urljoin

import httpx

from .base import HammockBase

if t.TYPE_CHECKING:
    from httpx import Client, Response

__all__ = ["Hammock"]


class Hammock(HammockBase):
    """Chainable, magical class helps you make requests to RESTful services"""

    _session: Client  # httpx.Client, kept as _session for backward compat
    _client: Client

    def __init__(
        self,
        name: str | None = None,
        parent: Hammock | None = None,
        append_slash: bool = False,
        session: Client | None = None,
        client: Client | None = None,
        **kwargs: t.Any,
    ) -> None:
        self._name = name
        self._parent = parent
        self._append_slash = append_slash
        _client = client if client is not None else session
        if _client is not None:
            self._session = _client  # type: ignore[assignment]
            self._client = _client  # type: ignore[assignment]
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
                self._client = httpx.Client(**kwargs)
            except TypeError as exc:
                raise AttributeError(str(exc)) from exc
            self._session = self._client

    def _close_session(self) -> None:
        if getattr(self, "_client", None):
            self._client.close()
        elif getattr(self, "_session", None):
            self._session.close()  # type: ignore[union-attr]

    def _request(self, method: str, *args: t.Any, **kwargs: t.Any) -> Response:
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
            return self._client.request(method, url, follow_redirects=False, **kwargs)

        resp = self._client.request(method, url, follow_redirects=False, **kwargs)
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
            resp = self._client.request(method, url, follow_redirects=False, **kwargs)
            count += 1
        return resp


def bind_method(method: str) -> t.Callable[..., Response]:
    def aux(hammock: Hammock, *args: t.Any, **kwargs: t.Any) -> Response:
        return hammock._request(method, *args, **kwargs)

    aux.__name__ = method.upper()
    return aux


for _method in Hammock.HTTP_METHODS:
    setattr(Hammock, _method.upper(), bind_method(_method))
