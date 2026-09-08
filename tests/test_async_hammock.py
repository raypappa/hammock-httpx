import unittest
from unittest import mock

import pytest

from hammock import AsyncHammock


class TestAsyncHammock(unittest.TestCase):
    BASE = "http://localhost:8000"

    def test_async_url_building(self):
        api = AsyncHammock(self.BASE)
        self.assertEqual(str(api.users.foo), f"{self.BASE}/users/foo")
        self.assertEqual(str(api("/a/b")), f"{self.BASE}/a/b")
        self.assertEqual(str(api("/a/b/")), f"{self.BASE}/a/b")

    def test_async_spawn_shares_client(self):
        import httpx

        client = httpx.AsyncClient()
        api = AsyncHammock(self.BASE, client=client)
        self.assertIs(api._client, client)
        self.assertIs(api.foo._client, client)

    def test_async_repr_and_iter(self):
        api = AsyncHammock(self.BASE)
        chain = api.a.b.c
        self.assertEqual(repr(chain), f"{self.BASE}/a/b/c")
        names = [n._name for n in chain]
        self.assertEqual(names, ["c", "b", "a", self.BASE])

    def test_async_methods_are_coroutines(self):
        import inspect

        for m in AsyncHammock.HTTP_METHODS:
            attr = getattr(AsyncHammock, m.upper())
            self.assertTrue(inspect.iscoroutinefunction(attr))

    def test_async_append_slash(self):
        api = AsyncHammock(self.BASE, append_slash=True)
        self.assertEqual(str(api.foo.bar), f"{self.BASE}/foo/bar/")


class TestAsyncHammockRequest(unittest.IsolatedAsyncioTestCase):
    BASE = "http://localhost:8000"

    async def test_async_post_preserved_on_redirect(self):
        api = AsyncHammock(self.BASE)
        redirect_resp = mock.Mock(
            status_code=302,
            headers={"Location": f"{self.BASE}/redirected"},
            url=f"{self.BASE}/foo",
        )
        final_resp = mock.Mock(status_code=200, headers={}, url=f"{self.BASE}/redirected")
        with mock.patch.object(api._client, "request", new_callable=mock.AsyncMock) as m:
            m.side_effect = [redirect_resp, final_resp]
            resp = await api.foo.POST(json={"x": 1})
            self.assertEqual(resp, final_resp)
            self.assertEqual(m.call_count, 2)
            self.assertEqual(m.call_args_list[0][0][0], "post")
            self.assertEqual(m.call_args_list[1][0][0], "post")

    async def test_async_get_simple(self):
        api = AsyncHammock(self.BASE)
        with mock.patch.object(api._client, "request", new_callable=mock.AsyncMock) as m:
            m.return_value = mock.Mock(status_code=200, headers={}, url=f"{self.BASE}/foo")
            resp = await api.foo.GET(params={"q": 1})
            m.assert_called_once()
            args, kwargs = m.call_args
            self.assertEqual(args[0], "get")
            self.assertEqual(args[1], f"{self.BASE}/foo")
            self.assertEqual(kwargs["params"], {"q": 1})
            self.assertEqual(kwargs.get("follow_redirects"), False)

    async def test_async_custom_client(self):
        import httpx

        client = httpx.AsyncClient(headers={"X-Sess": "1"})
        api = AsyncHammock(self.BASE, client=client)
        self.assertIs(api._client, client)
        with mock.patch.object(client, "request", new_callable=mock.AsyncMock) as m:
            m.return_value = mock.Mock(status_code=200, headers={}, url=f"{self.BASE}/foo")
            await api.foo.GET()
            m.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        # Test async with
        async with AsyncHammock(self.BASE) as api:
            self.assertEqual(str(api.foo), f"{self.BASE}/foo")
            with mock.patch.object(api._client, "request", new_callable=mock.AsyncMock) as m:
                m.return_value = mock.Mock(status_code=200, headers={}, url=f"{self.BASE}/foo")
                await api.foo.GET()
                m.assert_called_once()


if __name__ == "__main__":
    unittest.main()
