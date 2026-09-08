# AGENTS.md

## Structure
- `src` layout, import stays `hammock`: `src/hammock/{__init__.py,base.py,hammock.py,async_hammock.py,_types.py,py.typed}`. Distribution is `hammock-httpx` (`pyproject.toml:2`) — don't rename import; fork of `kadirpekel/hammock` modernized to `httpx`.
- Python `>=3.9`, runtime `httpx>=0.27` + `typing-extensions>=4.8` (not `requests`). No `setup.py`/`setup.cfg`; all config in `pyproject.toml`.
- Package manager is `uv` (`uv.lock` present, `.venv`/`dist`/`*.egg-info` ignored). No `Makefile`/`tox.ini`.

## Commands
- Bootstrap: `uv sync --all-groups` (creates `.venv`, installs `dev` group from `[dependency-groups]`).
- All tests: `uv run pytest -q` (47 tests, `pyproject.toml:53` `testpaths=["tests"]`, `asyncio_mode=auto`).
- Single test: `uv run pytest tests/test_hammock.py::TestHammockUrlBuilding::test_attr_chaining -v` or `uv run pytest tests/test_async_hammock.py -k test_async_get_simple -v` (`-k` works for both files).
- Typecheck: `uv run ty check` (or `ty check src`; `tool.ty.src` `include=["src"]` `exclude=["tests/**"]`, `tool.ty.environment.python-version="3.10"`). Was `mypy`, now `ty`.
- Lint: `uv run ruff check src/hammock` (tests have 11 intentional `F841`/`UP031` needing `--unsafe-fixes`; CI only checks `src`), `tool.ruff` line-length 100, `target-version=py39`, `E,F,W,I,UP,B,C4,SIM`.
- Format: `uv run ruff format --check` (CI) / `uv run ruff format` (fix).
- Build: `uv build` (setuptools `packages.find where=["src"]`, wheel `hammock-httpx-*.whl` + sdist).

## Architecture
- `src/hammock/base.py:13` `HammockBase` owns URL chaining. `__getattr__`/`__call__` → `_spawn` (`base.py:34` `copy.copy(self)`) — every chained node shares the same `httpx.Client`/`AsyncClient` (`_session`/`_client` aliases). Mutating client state affects whole chain.
- `_spawn` strips leading/trailing `/` (`base.py:36`) so resource URIs like `"/api/v1/users/4711/"` don't produce `//`. `_url` (`base.py:64`) collects via `__iter__` (leaf→root, skips falsy `_name`), reverses, joins with `/`; `append_slash=True` appends trailing `/`.
- Verbs bound at import time: `HammockBase.HTTP_METHODS` (`base.py:16`, 10 lower-cased `get…query`) → upper-cased attributes via `bind_method` (`hammock.py:133`/`async_hammock.py:169`). `*path: PathPart` (`str|bytes|int|float|bool`) extends URL via `_chain`; `**kwargs: Unpack[HammockRequestKwargs]` (`_types.py:36`) passes to `httpx` (`params`, `json`, `headers`, `timeout`, etc.) + `follow_redirects`/`allow_redirects` legacy alias.
- `Hammock.__init__` (`hammock.py:40`) / `AsyncHammock.__init__` (`async_hammock.py:58`) accept `session` or `client` (inject custom `httpx.Client`/`AsyncClient`). Remaining `**kwargs: Unpack[HttpxClientKwargs]` (`_types.py:54`) forwarded to client: mapping attrs `update()`, scalars `setattr()`. Invalid kwargs raise `AttributeError` (wrapped from `TypeError`) — not silently ignored.
- Redirects handled manually (`hammock.py:97`, `async_hammock.py:125`): always `request(..., follow_redirects=False)` then loops `301/302/303/307/308` up to `max_redirects`. `301/302/307/308` preserve verb+body; `303` forces `GET` and drops `data/json/content/files`. Supports both `follow_redirects` and legacy `allow_redirects`.
- Subclassing: custom kwargs must be `pop()`ed before `super().__init__` (`tests/test_hammock.py:279`) or they hit `setattr` path and raise `AttributeError`.

## Testing Quirks
- Stack is `pytest` + `pytest-asyncio` + `httpretty` + `unittest.mock` (`tests/test_hammock.py:1`, `tests/test_async_hammock.py:1`). Tests split: `tests/test_hammock.py` (38 sync) + `tests/test_async_hammock.py` (9 async). Don't use `requests`/`responses` fixtures; responses are `httpx.Response` (`resp.json()` is a method, `resp.status_code`).
- `httpretty` only intercepts sync `httpx.Client`; async tests use `mock.AsyncMock` on `client.request` (`tests/test_async_hammock.py:1`). Sync tests use `@httprettified` + `HTTPretty.register_uri(HTTPretty.GET, url)` / `HTTPretty.last_request` (`tests/test_hammock.py:17`). `httpretty>=1.1.4` via `uv` — old `0.5.4`/`httpretty.httprettified` paths are stale.
- Redirect tests don't hit network — `mock.patch.object(client, "request")` with `side_effect=[redirect_resp, final_resp]` (`tests/test_hammock.py:391`, `tests/test_async_hammock.py:520`). Follow same pattern for new redirect cases.
- `uv run pytest -q` is canonical; `testpaths=["tests"]` + `asyncio_mode=auto` required for `TestAsyncHammockRequest`; `ty check` excludes `tests/**` by default.

## CI / Workflows
- `.github/workflows/test.yml:1` matrix `3.9`-`3.14` (`setup-uv@v6`, `uv sync --all-groups`, `ruff check src/hammock`, `ruff format --check`, `ty check`, `pytest -q`, `uv build`).
- `.github/workflows/publish.yml:1` builds + publishes `hammock-httpx` to PyPI via trusted publishing (`id-token: write`, `uv publish --no-cache`) on `release:published` / `tags: v*.*.*` / `workflow_dispatch`.

## Conventions
- Keep `src/hammock` typed: `py.typed` marker, `Self`/`Unpack` via `typing_extensions` (`_types.py:30`), `HammockRequestKwargs`/`HttpxClientKwargs`/`PathPart` in `_types.py`. Run `ty check` + `ruff check src/hammock` before pushing; `ruff format` is enforced.
- Branch is `main` (rewritten fork, `origin/main`; `master`/`upstream` is `kadirpekel/hammock` original). No pre-commit hooks. Distribution `hammock-httpx` but import `hammock` stays.
