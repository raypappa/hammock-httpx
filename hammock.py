from __future__ import annotations

import copy
import typing as t
from urllib.parse import urljoin

import requests

if t.TYPE_CHECKING:
    from requests import Response, Session

__all__ = ["Hammock"]


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
    ]

    _name: str | None
    _parent: Hammock | None
    _append_slash: bool
    _session: Session

    def __init__(
        self,
        name: str | None = None,
        parent: Hammock | None = None,
        append_slash: bool = False,
        session: Session | None = None,
        **kwargs: t.Any,
    ) -> None:
        """Constructor

        Arguments:
            name -- name of node
            parent -- parent node for chaining
            append_slash -- flag if you want a trailing slash in urls
            session -- existing ``requests.Session`` to use (e.g. OAuth);
                if None a new session is created
            **kwargs -- ``requests`` session attributes to initiate
        """
        self._name = name
        self._parent = parent
        self._append_slash = append_slash
        self._session = session if session is not None else requests.session()
        for k, v in kwargs.items():
            orig = getattr(self._session, k)  # Let it throw exception if unknown
            if isinstance(orig, dict):
                orig.update(v)  # type: ignore[attr-defined]
            else:
                setattr(self._session, k, v)

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
        if self._session:
            self._session.close()

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
        """Makes the HTTP request using requests module

        Handles redirects manually to preserve the original HTTP verb for
        301/302 redirects (issue #21). ``requests`` would otherwise change
        POST/PUT/PATCH to GET on 301/302, breaking RESTful interaction
        (e.g. http -> https redirect). When ``allow_redirects`` is True
        (default) we follow redirects ourselves preserving the verb; when
        False we return the redirect response directly.
        """
        # Respect explicit allow_redirects=False — do not follow
        allow_redirects = kwargs.pop("allow_redirects", True)
        url = self._url(*args)
        if not allow_redirects:
            return self._session.request(method, url, allow_redirects=False, **kwargs)

        # Follow redirects manually preserving method (except 303 -> GET)
        resp = self._session.request(method, url, allow_redirects=False, **kwargs)
        redirect_codes = (301, 302, 303, 307, 308)
        max_redirects = getattr(self._session, "max_redirects", 30)
        count = 0
        # Use status_code check for redirect; avoid relying on is_redirect which
        # is truthy for mocks (Mock.is_redirect is a Mock instance)
        while resp.status_code in redirect_codes and count < max_redirects:
            location = resp.headers.get("Location") if hasattr(resp.headers, "get") else None
            if not location or not isinstance(location, str):
                break
            # 303 See Other — spec says change to GET
            if resp.status_code == 303:
                method = "get"
                kwargs.pop("data", None)
                kwargs.pop("json", None)
                kwargs.pop("files", None)
            # Resolve relative Location against current response URL
            next_url = urljoin(getattr(resp, "url", None) or url, location)
            url = next_url
            resp = self._session.request(method, url, allow_redirects=False, **kwargs)
            count += 1
        return resp


def bind_method(method: str) -> t.Callable[..., Response]:
    """Bind ``requests`` module HTTP verbs to ``Hammock`` class as
    static methods."""

    def aux(hammock: Hammock, *args: t.Any, **kwargs: t.Any) -> Response:
        return hammock._request(method, *args, **kwargs)

    # preserve metadata for introspection
    aux.__name__ = method.upper()
    return aux


for _method in Hammock.HTTP_METHODS:
    setattr(Hammock, _method.upper(), bind_method(_method))
