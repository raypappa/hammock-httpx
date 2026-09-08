# hammock-httpx

```
 _                                   _
| |                                 | |
| |__  _____ ____  ____   ___   ____| |  _
|  _ \(____ |    \|    \ / _ \ / ___) |_/ )
| | | / ___ | | | | | | | |_| ( (___|  _ (
|_| |_\_____|_|_|_|_|_|_|\___/ \____)_| \_)
```

> Rest like a boss — chainable, typed wrapper over [httpx](https://www.python-httpx.org/) for REST. Fork of `kadirpekel/hammock` modernized to `httpx` + async + `src` layout.

> **Distribution**: `hammock-httpx` on PyPI, **import** remains `import hammock` / `from hammock import Hammock` for backwards compat.

Hammock lets you turn any REST API into a dead-simple programmatic API by mapping URL segments to Python attributes and calls. No manual string formatting, full reuse of base URLs, sync **and** async.

`httpx` is used under the hood, so you get modern TLS, HTTP/2, connection pooling, timeouts and auth for free.

## Features

* **Chainable URL building** — `api.users("foo").posts("bar").comments.GET()` → `http://.../users/foo/posts/bar/comments`
* **Sync + Async** — `Hammock` (`httpx.Client`) and `AsyncHammock` (`httpx.AsyncClient`)
* **Typed** — PEP 561 `py.typed`, `mypy` clean, supports `3.9+`
* **All verbs** — `GET HEAD OPTIONS POST PUT PATCH DELETE TRACE CONNECT QUERY` (QUERY per [RFC 10008](https://www.rfc-editor.org/rfc/rfc10008.html))
* **Resource URIs** — `api("/api/v1/users/4711/")` correctly strips leading/trailing `/` (no `//`)
* **Custom sessions** — inject your own `httpx.Client`/`AsyncClient` (OAuth, custom transports)
* **Trailing slash** — `append_slash=True`
* **Redirect-safe** — preserves `POST`/`PUT`/`PATCH` on `301`/`302` (issue #21), `303` → `GET`
* **src layout + uv** — `src/hammock/` package, `pyproject.toml`, `uv` dev

## Install

```bash
# pip (new distribution name)
pip install hammock-httpx
# import stays compatible:
# import hammock; from hammock import Hammock, AsyncHammock

# uv
uv add hammock-httpx

# from source (uv)
uv sync
```

Requires Python `>=3.9` and `httpx>=0.27`. Import package is still `hammock` (`src/hammock`).

## Quickstart — GitHub API

```python
from hammock import Hammock

github = Hammock("https://api.github.com")

# GET /repos/kadirpekel/hammock/watchers
resp = github.repos("kadirpekel", "hammock").watchers.GET()
for watcher in resp.json():
    print(watcher["login"])

# PUT with auth / headers
resp = github.user.watched("kadirpekel", "hammock").PUT(
    auth=("user", "pass"),
    headers={"content-length": "0"},
)
print(resp.status_code)  # 204
```

Same with **async**:

```python
import asyncio
from hammock import AsyncHammock

async def main():
    async with AsyncHammock("https://api.github.com") as github:
        resp = await github.repos("kadirpekel", "hammock").watchers.GET()
        print(resp.json())

asyncio.run(main())
```

## How it works

`Hammock` is a thin wrapper over `httpx`. Attribute access and `()` build the URL, upper-cased HTTP verbs execute it and return an `httpx.Response`.

All of these make the same request to `http://localhost:8000/users/foo/posts/bar/comments`:

```python
import hammock

api = hammock.Hammock("http://localhost:8000")

api.users("foo").posts("bar").comments.GET()
api.users.foo.posts("bar").GET("comments")
api.users.foo.posts.bar.comments.GET()
api.users("foo", "posts", "comments").GET()
api("users")("foo", "posts").GET("bar", "comments")
# any other combination
```

Signature of every verb is `Hammock.VERB(*args, **kwargs)` where `*args` are extra path components and `**kwargs` are passed straight to `httpx` (`params`, `headers`, `json`, `content`, `timeout`, `follow_redirects`, …). Return type is always `httpx.Response`.

Available verbs: `GET HEAD OPTIONS POST PUT PATCH DELETE TRACE CONNECT QUERY` (lower-cased list in `Hammock.HTTP_METHODS`, bound as upper-cased methods).

### Real-world example

```python
import hammock

twitter = hammock.Hammock("https://api.twitter.com/1")
resp = twitter.statuses("user_timeline.json").GET(
    params={"screen_name": "kadirpekel", "count": "10"}
)
for tweet in resp.json():
    print(tweet["text"])
```

## Sessions & Auth

Pass any `httpx.Client` option to the constructor – it is forwarded to the underlying client. The client is shared across the whole chain (shallow copy via `copy.copy`).

```python
import hammock
import httpx

# Basic auth reused across requests
jira = hammock.Hammock(
    "https://jira.atlassian.com/rest/api/latest",
    auth=("user", "pass"),
)

issue = jira.issue("JRA-9").GET()                          # auth reused
watched = jira.issue("JRA-9").watchers.POST(params={"name": "user"})
print(watched)

# Custom client (OAuth, custom transport, headers, etc.)
client = httpx.Client(headers={"X-Sess": "1"}, auth=("user", "pass"))
api = hammock.Hammock("https://api.example.com", session=client)  # or client=client
# or: client=httpx.AsyncClient(...) for AsyncHammock
```

All `httpx.Client` kwargs are supported: `headers`, `params`, `auth`, `cookies`, `timeout`, `follow_redirects`, `max_redirects`, `verify`, … Invalid kwargs raise `AttributeError`.

Chain shares the session:

```python
api = Hammock("http://example.com", headers={"X-Test": "1"})
assert api.foo._client is api.bar._client is api._session
```

Close when done (or use context manager for async):

```python
api._close_session()          # sync
await api.close()             # async
async with AsyncHammock("...") as api:
    ...
```

## Resource URIs

APIs often return resource URIs like `"/api/v1/users/4711/"`. Pass them directly – Hammock strips leading/trailing slashes so you never get `//`:

```python
api = Hammock("http://localhost:8000")
uri = "/api/v1/users/4711/"
print(api(uri))  # http://localhost:8000/api/v1/users/4711
# with trailing slash preserved if you need it:
api_slash = Hammock("http://localhost:8000", append_slash=True)
print(api_slash(uri))  # http://localhost:8000/api/v1/users/4711/
```

## Trailing slash

```python
api = hammock.Hammock("http://localhost:8000", append_slash=True)
print(api.foo.bar)  # http://localhost:8000/foo/bar/
```

## Redirects

By default `follow_redirects=True` and Hammock follows redirects **manually** preserving the original verb for `301`/`302`/`307`/`308` (issue #21). `POST` stays `POST` on `http → https` redirects; `303` correctly becomes `GET`. Pass `follow_redirects=False` (or legacy `allow_redirects=False`) to return the redirect response.

## Async

`AsyncHammock` mirrors `Hammock` but all verbs are coroutines:

```python
from hammock import AsyncHammock
import httpx

# URL building is sync
api = AsyncHammock("http://localhost:8000")
print(api.users("foo").posts)  # http://localhost:8000/users/foo/posts

# Execution is async
resp = await api.users.foo.GET()
resp = await api.users("foo").posts.POST(json={"x": 1})

# Custom async client
client = httpx.AsyncClient(headers={"X": "y"})
api = AsyncHammock("http://example.com", client=client)

# Context manager closes the client
async with AsyncHammock("http://example.com") as api:
    resp = await api.foo.GET()
```

All `Hammock` features (resource URIs, `append_slash`, redirect handling, verb list) work for `AsyncHammock`.

## Project layout

```
src/hammock/
  __init__.py       # re-exports Hammock, AsyncHammock, HammockBase, bind_method
  base.py           # HammockBase – URL chaining (_spawn, _chain, _url, __getattr__, __iter__)
  hammock.py        # Hammock(httpx.Client) + bind_method
  async_hammock.py  # AsyncHammock(httpx.AsyncClient) + _bind_async_method
  py.typed          # PEP 561
```

## Development

```bash
uv sync                  # create .venv, install dev deps
uv run pytest -q         # 47 tests (sync + async, httpretty + mocks)
uv run mypy -p hammock   # types (src layout)
uv run ruff check src/hammock
uv build                 # wheel + sdist
```

Dev deps: `httpretty`, `pytest`, `pytest-asyncio`, `mypy`, `ruff`.

## Contributors

* @maraujop (Miguel Araujo)
* @rubik (Michele Lacchia)

## License

Copyright (c) 2012 Kadir Pekel.

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
