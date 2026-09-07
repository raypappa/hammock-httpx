from __future__ import annotations

import copy
import typing as t
from urllib.parse import urljoin

import httpx

if t.TYPE_CHECKING:
    from httpx import AsyncClient, Client, Response

__all__ = ["Hammock", "AsyncHammock"]


class Hammock:
    """Chainable, magical class helps you make requests to RESTful services"""

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

    _name: str | None
    _parent: Hammock | None
    _append_slash: bool
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
        """Constructor

        Arguments:
            name -- name of node
            parent -- parent node for chaining
            append_slash -- flag if you want a trailing slash in urls
            session -- existing ``httpx.Client`` to use (e.g. custom transport);
                also accepts ``requests.Session`` for backward compat if it
                has a ``request`` method
            client -- alias for ``session``
            **kwargs -- ``httpx.Client`` attributes to initiate with if available
        """
        self._name = name
        self._parent = parent
        self._append_slash = append_slash
        # support both `session` and `client` kwargs
        _client = client if client is not None else session
        if _client is not None:
            self._session = _client  # type: ignore[assignment]
            self._client = _client  # type: ignore[assignment]
            # Apply kwargs to provided client (e.g. headers, auth)
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
            # Create new client with kwargs (httpx validates)
            try:
                self._client = httpx.Client(**kwargs)
            except TypeError as exc:
                raise AttributeError(str(exc)) from exc
            self._session = self._client

    def _spawn(self, name: str) -> Hammock:
        """Returns a shallow copy of current ``Hammock`` instance as nested child

        Arguments:
            name -- name of child
        """
        child: Hammock = copy.copy(self)
        # Strip leading/trailing slashes to allow resource URIs like '/api/v1/users/4711/'
        # to be used directly without producing double slashes (PR #13, #16).
        if isinstance(name, str):
            name = name.strip("/")
        child._name = name
        child._parent = self
        return child

    def __getattr__(self, name: str) -> Hammock:
        """Here comes some magic. Any absent attribute typed within class
        falls here and return a new child ``Hammock`` instance in the chain.
        """
        # Ignore specials (Otherwise shallow copying causes infinite loops)
        if name.startswith("__"):
            raise AttributeError(name)
        return self._spawn(name)

    def __iter__(self) -> t.Iterator[Hammock]:
        """Iterator implementation which iterates over ``Hammock`` chain."""
        current: Hammock | None = self
        while current:
            if current._name:
                yield current
            current = current._parent

    def _chain(self, *args: t.Any) -> Hammock:
        """This method converts args into chained Hammock instances

        Arguments:
            *args -- array of string representable objects
        """
        chain: Hammock = self
        for arg in args:
            chain = chain._spawn(str(arg))
        return chain

    def _close_session(self) -> None:
        """Closes session if exists"""
        if getattr(self, "_client", None):
            self._client.close()
        elif getattr(self, "_session", None):
            self._session.close()  # type: ignore[union-attr]

    def __call__(self, *args: t.Any) -> Hammock:
        """Here comes second magic. If any ``Hammock`` instance called it
        returns a new child ``Hammock`` instance in the chain
        """
        return self._chain(*args)

    def _url(self, *args: t.Any) -> str:
        """Converts current ``Hammock`` chain into a url string

        Arguments:
            *args -- extra url path components to tail
        """
        path_comps: list[str] = [
            mock._name for mock in self._chain(*args) if mock._name is not None
        ]  # type: ignore[misc]
        url: str = "/".join(reversed(path_comps))
        if self._append_slash:
            url = url + "/"
        return url

    def __repr__(self) -> str:
        """String representation of current ``Hammock`` chain"""
        return self._url()

    def _request(self, method: str, *args: t.Any, **kwargs: t.Any) -> Response:
        """Makes the HTTP request using httpx

        Handles redirects manually to preserve the original HTTP verb for
        301/302 redirects (issue #21). ``httpx`` would otherwise follow
        redirects, and for 301/302 it may change POST/PUT/PATCH to GET.
        When ``follow_redirects`` (or legacy ``allow_redirects``) is True
        (default) we follow redirects ourselves preserving the verb; when
        False we return the redirect response directly.
        """
        # Normalize redirect flag: support both httpx (follow_redirects) and
        # requests legacy (allow_redirects)
        follow_redirects: bool | None = None
        if "follow_redirects" in kwargs:
            follow_redirects = kwargs.pop("follow_redirects")
        if "allow_redirects" in kwargs:
            # legacy, allow_redirects -> follow_redirects
            allow = kwargs.pop("allow_redirects")
            if follow_redirects is None:
                follow_redirects = bool(allow)
        if follow_redirects is None:
            follow_redirects = True

        url = self._url(*args)
        if not follow_redirects:
            return self._client.request(method, url, follow_redirects=False, **kwargs)

        # Follow redirects manually preserving method (except 303 -> GET)
        resp = self._client.request(method, url, follow_redirects=False, **kwargs)
        redirect_codes = (301, 302, 303, 307, 308)
        max_redirects = getattr(self._client, "max_redirects", 20)
        count = 0
        while resp.status_code in redirect_codes and count < max_redirects:
            location = resp.headers.get("Location") if hasattr(resp.headers, "get") else None
            if not location or not isinstance(location, str):
                break
            # 303 See Other — spec says change to GET
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
    """Bind HTTP verbs to ``Hammock`` class as static methods."""

    def aux(hammock: Hammock, *args: t.Any, **kwargs: t.Any) -> Response:
        return hammock._request(method, *args, **kwargs)

    # preserve metadata for introspection
    aux.__name__ = method.upper()
    return aux


for _method in Hammock.HTTP_METHODS:
    setattr(Hammock, _method.upper(), bind_method(_method))


# ---------------------------------------------------------------------------
# Async variant — mirrors Hammock but uses httpx.AsyncClient and async verbs
# ---------------------------------------------------------------------------


class AsyncHammock:
    """Async chainable wrapper over ``httpx.AsyncClient``"""

    HTTP_METHODS: list[str] = Hammock.HTTP_METHODS

    _name: str | None
    _parent: AsyncHammock | None
    _append_slash: bool
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
        self._parent = parent
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

    def _spawn(self, name: str) -> AsyncHammock:
        child: AsyncHammock = copy.copy(self)
        if isinstance(name, str):
            name = name.strip("/")
        child._name = name
        child._parent = self
        return child

    def __getattr__(self, name: str) -> AsyncHammock:
        if name.startswith("__"):
            raise AttributeError(name)
        return self._spawn(name)

    def __iter__(self) -> t.Iterator[AsyncHammock]:
        current: AsyncHammock | None = self
        while current:
            if current._name:
                yield current
            current = current._parent

    def _chain(self, *args: t.Any) -> AsyncHammock:
        chain: AsyncHammock = self
        for arg in args:
            chain = chain._spawn(str(arg))
        return chain

    async def _aclose(self) -> None:
        """Async close of the underlying client"""
        if getattr(self, "_client", None):
            await self._client.aclose()

    def _close_session(self) -> None:  # pragma: no cover - sync close not used for async
        """Sync close fallback (closes via async loop if needed)"""
        # httpx.AsyncClient should be closed via aclose; try sync close if available
        try:
            import asyncio

            # run aclose if loop is available, otherwise skip
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._client.aclose())
            else:
                loop.run_until_complete(self._client.aclose())
        except Exception:
            pass

    def __call__(self, *args: t.Any) -> AsyncHammock:
        return self._chain(*args)

    def _url(self, *args: t.Any) -> str:
        path_comps: list[str] = [
            mock._name for mock in self._chain(*args) if mock._name is not None
        ]  # type: ignore[misc]
        url: str = "/".join(reversed(path_comps))
        if self._append_slash:
            url = url + "/"
        return url

    def __repr__(self) -> str:
        return self._url()

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

    # Async context manager support
    async def __aenter__(self) -> AsyncHammock:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._client.aclose()

    # Alias for close
    async def close(self) -> None:
        await self._client.aclose()


def _bind_async_method(method: str) -> t.Callable[..., t.Awaitable[httpx.Response]]:
    async def aux(hammock: AsyncHammock, *args: t.Any, **kwargs: t.Any) -> httpx.Response:
        return await hammock._request(method, *args, **kwargs)

    aux.__name__ = method.upper()
    return aux


for _method in AsyncHammock.HTTP_METHODS:
    setattr(AsyncHammock, _method.upper(), _bind_async_method(_method))
