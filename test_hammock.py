import unittest
from unittest import mock

from httpretty import HTTPretty
from httpretty import httprettified

import pytest

from hammock import AsyncHammock, Hammock, bind_method


class TestCaseWrest(unittest.TestCase):
    HOST = "localhost"
    PORT = 8000
    BASE_URL = "http://%s:%s" % (HOST, PORT)
    PATH = "/sample/path/to/resource"
    URL = BASE_URL + PATH

    @httprettified
    def test_methods(self):
        client = Hammock(self.BASE_URL)
        for method in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            HTTPretty.register_uri(getattr(HTTPretty, method), self.URL)
            request = getattr(client, method)
            resp = request("sample", "path", "to", "resource")
            self.assertEqual(HTTPretty.last_request.method, method)

    @httprettified
    def test_urls(self):
        HTTPretty.register_uri(HTTPretty.GET, self.URL)
        client = Hammock(self.BASE_URL)
        combs = [
            client.sample.path.to.resource,
            client("sample").path("to").resource,
            client("sample", "path", "to", "resource"),
            client("sample")("path")("to")("resource"),
            client.sample("path")("to", "resource"),
            client(
                "sample",
                "path",
            ).to.resource,
        ]

        for comb in combs:
            self.assertEqual(str(comb), self.URL)
            resp = comb.GET()
            self.assertEqual(HTTPretty.last_request.path, self.PATH)

    @httprettified
    def test_append_slash_option(self):
        HTTPretty.register_uri(HTTPretty.GET, self.URL + "/")
        client = Hammock(self.BASE_URL, append_slash=True)
        resp = client.sample.path.to.resource.GET()
        self.assertEqual(HTTPretty.last_request.path, self.PATH + "/")

    @httprettified
    def test_inheritance(self):
        """https://github.com/kadirpekel/hammock/pull/5/files#L1R99"""

        class CustomHammock(Hammock):
            def __init__(self, name=None, parent=None, **kwargs):
                if "testing" in kwargs:
                    self.testing = kwargs.pop("testing")
                super(CustomHammock, self).__init__(name, parent, **kwargs)

            def _url(self, *args):
                assert isinstance(self.testing, bool)
                global called
                called = True
                return super(CustomHammock, self)._url(*args)

        global called
        called = False
        HTTPretty.register_uri(HTTPretty.GET, self.URL)
        client = CustomHammock(self.BASE_URL, testing=True)
        resp = client.sample.path.to.resource.GET()
        self.assertTrue(called)
        self.assertEqual(HTTPretty.last_request.path, self.PATH)

    @httprettified
    def test_session(self):
        ACCEPT_HEADER = "application/json"
        kwargs = {
            "headers": {"Accept": ACCEPT_HEADER},
            "auth": ("foo", "bar"),
        }
        client = Hammock(self.BASE_URL, **kwargs)
        HTTPretty.register_uri(HTTPretty.GET, self.URL)
        client.sample.path.to.resource.GET()
        request = HTTPretty.last_request
        self.assertIn("User-Agent", request.headers)
        self.assertIn("Authorization", request.headers)
        self.assertIn("Accept", request.headers)
        self.assertEqual(request.headers.get("Accept"), ACCEPT_HEADER)
        client.sample.path.to.resource.GET()
        request = HTTPretty.last_request
        self.assertIn("User-Agent", request.headers)
        self.assertIn("Authorization", request.headers)
        self.assertIn("Accept", request.headers)
        self.assertEqual(request.headers.get("Accept"), ACCEPT_HEADER)


class TestHammockUrlBuilding(unittest.TestCase):
    BASE = "http://localhost:8000"

    def test_attr_chaining(self):
        api = Hammock(self.BASE)
        self.assertEqual(str(api.users.foo), f"{self.BASE}/users/foo")
        self.assertEqual(str(api.users("foo").posts), f"{self.BASE}/users/foo/posts")

    def test_call_chaining(self):
        api = Hammock(self.BASE)
        self.assertEqual(str(api("users", "foo")), f"{self.BASE}/users/foo")
        self.assertEqual(str(api("users")("foo")("posts")), f"{self.BASE}/users/foo/posts")

    def test_mixed_chaining(self):
        api = Hammock(self.BASE)
        combos = [
            api.users.foo.posts.bar.comments,
            api.users("foo").posts("bar").comments,
            api("users", "foo", "posts", "bar", "comments"),
            api.users.foo.posts("bar").GET,  # just url part
        ]
        for comb in combos[:3]:
            self.assertEqual(str(comb), f"{self.BASE}/users/foo/posts/bar/comments")

    def test_call_with_non_string_args(self):
        api = Hammock(self.BASE)
        self.assertEqual(str(api.users(123, 456)), f"{self.BASE}/users/123/456")
        self.assertEqual(str(api(123).foo), f"{self.BASE}/123/foo")

    def test_url_with_extra_args_via_method(self):
        api = Hammock(self.BASE)
        with mock.patch.object(api._session, "request") as m:
            m.return_value = mock.Mock(
                status_code=200, headers={}, url=f"{self.BASE}/users/foo/bar/baz"
            )
            api.users.foo.GET("bar", "baz", params={"q": 1})
            m.assert_called_once()
            args, kwargs = m.call_args
            self.assertEqual(args[0], "get")
            self.assertEqual(args[1], f"{self.BASE}/users/foo/bar/baz")
            self.assertEqual(kwargs["params"], {"q": 1})
            self.assertEqual(kwargs.get("follow_redirects"), False)

    def test_repr_equals_url(self):
        api = Hammock(self.BASE)
        chain = api.users.foo
        self.assertEqual(repr(chain), str(chain))
        self.assertEqual(repr(chain), f"{self.BASE}/users/foo")

    def test_iter_yields_reversed(self):
        api = Hammock(self.BASE)
        chain = api.a.b.c
        names = [node._name for node in chain]
        # __iter__ yields from leaf to root filtering None
        self.assertEqual(names, ["c", "b", "a", self.BASE])

    def test_iter_root_only(self):
        api = Hammock(self.BASE)
        nodes = list(api)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]._name, self.BASE)


class TestHammockSession(unittest.TestCase):
    BASE = "http://localhost:8000"

    def test_spawn_shares_session(self):
        api = Hammock(self.BASE, headers={"X-Test": "1"})
        child = api.foo
        grand = child.bar
        self.assertIs(api._session, child._session)
        self.assertIs(child._session, grand._session)

    def test_session_headers_update_not_replace(self):
        api = Hammock(self.BASE, headers={"Accept": "application/json", "X-Custom": "a"})
        # headers should be merged (httpx preserves defaults via update)
        self.assertEqual(api._session.headers.get("Accept"), "application/json")
        self.assertEqual(api._session.headers.get("X-Custom"), "a")
        # User-Agent should still be present (httpx merges via update)
        self.assertIn("User-Agent", api._session.headers)
        self.assertIn("user-agent", api._session.headers)
        # Verify that without headers kwarg, session has default User-Agent
        api2 = Hammock(self.BASE)
        self.assertIn("User-Agent", api2._session.headers)

    def test_session_auth_set(self):
        api = Hammock(self.BASE, auth=("user", "pass"))
        # httpx stores auth as BasicAuth object
        import httpx

        self.assertIsInstance(api._session.auth, httpx.BasicAuth)
        # basic check that auth was set (not None)
        self.assertIsNotNone(api._session.auth)

    def test_session_scalar_kwargs(self):
        # verify max_redirects and follow_redirects are valid httpx Client scalars
        api2 = Hammock(self.BASE, max_redirects=5)
        self.assertEqual(api2._session.max_redirects, 5)
        api3 = Hammock(self.BASE, follow_redirects=True)
        self.assertTrue(api3._session.follow_redirects)
        # timeout is also configurable via httpx
        api4 = Hammock(self.BASE, timeout=10.0)
        self.assertEqual(api4._session.timeout.read, 10.0)
        # headers scalar through dict update still works
        api5 = Hammock(self.BASE, headers={"X-A": "1"})
        self.assertEqual(api5._session.headers.get("X-A"), "1")

    def test_invalid_session_kwarg_raises(self):
        with self.assertRaises(AttributeError):
            Hammock(self.BASE, nonexistent_attr_xyz="boom")

    def test_spawn_inherits_append_slash(self):
        api = Hammock(self.BASE, append_slash=True)
        child = api.foo.bar
        self.assertTrue(child._append_slash)
        self.assertEqual(str(child), f"{self.BASE}/foo/bar/")

    def test_close_session(self):
        api = Hammock(self.BASE)
        with mock.patch.object(api._session, "close") as mock_close:
            api._close_session()
            mock_close.assert_called_once()

    def test_special_attr_raises(self):
        api = Hammock(self.BASE)
        with self.assertRaises(AttributeError):
            _ = api.__some_special__
        with self.assertRaises(AttributeError):
            _ = api.__another__
        # __class__ and __dict__ are real attributes, should not raise via __getattr__
        self.assertIsNotNone(api.__class__)
        self.assertIsInstance(api.__dict__, dict)

    def test_bind_method_exists_for_all_http_methods(self):
        for m in Hammock.HTTP_METHODS:
            self.assertTrue(hasattr(Hammock, m.upper()))
            self.assertTrue(callable(getattr(Hammock, m.upper())))
            # lower case should not be bound as class attribute
            self.assertFalse(hasattr(Hammock, m)) if m != m.upper() else None

    def test_request_forwards_kwargs_and_uses_url(self):
        api = Hammock(self.BASE)
        with mock.patch.object(api._session, "request") as mocked:
            mocked.return_value = mock.Mock(status_code=200, headers={}, url=f"{self.BASE}/foo/bar")
            resp = api.foo.bar.POST(json={"x": 1}, headers={"X-A": "b"})
            mocked.assert_called_once_with(
                "post",
                f"{self.BASE}/foo/bar",
                follow_redirects=False,
                json={"x": 1},
                headers={"X-A": "b"},
            )
            self.assertEqual(resp.status_code, 200)

    def test_http_methods_are_uppercase_on_class(self):
        # bind_method creates upper case methods that call _request
        api = Hammock(self.BASE)
        for method in [
            "GET",
            "POST",
            "PUT",
            "DELETE",
            "PATCH",
            "OPTIONS",
            "HEAD",
            "TRACE",
            "CONNECT",
        ]:
            self.assertTrue(hasattr(api, method))
            with mock.patch.object(api, "_request") as mk:
                getattr(api, method)("foo")
                mk.assert_called_once()
                call_method = mk.call_args[0][0]
                self.assertEqual(call_method, method.lower())

    def test_inheritance_custom_kwargs(self):
        class MyHammock(Hammock):
            def __init__(self, name=None, parent=None, custom=None, **kwargs):
                self.custom = custom
                super().__init__(name, parent, **kwargs)

        h = MyHammock(self.BASE, custom="value", headers={"X": "y"})
        self.assertEqual(h.custom, "value")
        self.assertEqual(h._session.headers.get("X"), "y")
        child = h.foo
        self.assertEqual(child.custom, "value")

    def test_custom_session_kwarg(self):
        import httpx

        sess = httpx.Client(headers={"X-Sess": "1"})
        api = Hammock(self.BASE, session=sess)
        self.assertIs(api._session, sess)
        self.assertIs(api._client, sess)
        # chaining shares the same session
        self.assertIs(api.foo._session, sess)
        self.assertIs(api.foo.bar._session, sess)
        # kwargs still applied to provided session
        sess2 = httpx.Client()
        api2 = Hammock(self.BASE, session=sess2, headers={"X-New": "2"})
        self.assertIs(api2._session, sess2)
        self.assertEqual(api2._session.headers.get("X-New"), "2")
        # also test client alias
        sess3 = httpx.Client()
        api3 = Hammock(self.BASE, client=sess3)
        self.assertIs(api3._session, sess3)
        # request uses the custom session
        with mock.patch.object(sess, "request") as m:
            m.return_value = mock.Mock(status_code=200, headers={}, url=f"{self.BASE}/foo")
            api.foo.GET()
            m.assert_called_once()
            self.assertEqual(m.call_args[0][1], f"{self.BASE}/foo")
            self.assertEqual(m.call_args[1].get("follow_redirects"), False)


class TestResourceUri(unittest.TestCase):
    """PR #13: allow resource URIs with leading/trailing slashes"""

    BASE = "http://localhost:8000"
    PATH = "/sample/path/to/resource"
    URL = BASE + PATH

    @httprettified
    def test_strip_leading_slash_via_call(self):
        HTTPretty.register_uri(HTTPretty.GET, self.URL)
        client = Hammock(self.BASE)
        # resource URI with leading slash via __call__
        self.assertEqual(str(client(self.PATH)), self.URL)
        resp = client(self.PATH).GET()
        self.assertEqual(HTTPretty.last_request.path, self.PATH)

    @httprettified
    def test_strip_both_slashes(self):
        HTTPretty.register_uri(HTTPretty.GET, self.URL)
        client = Hammock(self.BASE)
        self.assertEqual(str(client(self.PATH + "/")), self.URL)
        resp = client(self.PATH + "/").GET()
        self.assertEqual(HTTPretty.last_request.path, self.PATH)

    @httprettified
    def test_strip_with_append_slash(self):
        HTTPretty.register_uri(HTTPretty.GET, self.URL + "/")
        client = Hammock(self.BASE, append_slash=True)
        # strip then append_slash should yield trailing slash
        resp = client(self.PATH).GET()
        self.assertEqual(HTTPretty.last_request.path, self.PATH + "/")
        resp = client(self.PATH + "/").GET()
        self.assertEqual(HTTPretty.last_request.path, self.PATH + "/")

    def test_strip_internal_slashes_preserved(self):
        api = Hammock(self.BASE)
        self.assertEqual(str(api("/api/v1/users/4711/")), f"{self.BASE}/api/v1/users/4711")
        self.assertEqual(str(api("/a/b/c/")), f"{self.BASE}/a/b/c")
        # double leading slashes stripped, internal double kept
        self.assertEqual(str(api("//a//b")), f"{self.BASE}/a//b")

    @httprettified
    def test_resource_uri_with_params(self):
        HTTPretty.register_uri(HTTPretty.GET, self.URL)
        client = Hammock(self.BASE)
        with mock.patch.object(client._session, "request", wraps=client._session.request) as m:
            # still uses httpretty, but check url passed
            client("/sample/path/to/resource").GET(params={"foo": "bar"})
            # httpretty path includes querystring
            self.assertTrue(HTTPretty.last_request.path.startswith(self.PATH))
            self.assertEqual(HTTPretty.last_request.querystring, {"foo": ["bar"]})

    def test_pr16_leading_slash_stripped_via_spawn(self):
        # PR #16: remove leading slash from the name
        api = Hammock(self.BASE)
        # direct _spawn with leading slash
        child = api._spawn("/foo")
        self.assertEqual(child._name, "foo")
        self.assertEqual(str(child), f"{self.BASE}/foo")
        # trailing also stripped
        child2 = api._spawn("bar/")
        self.assertEqual(child2._name, "bar")
        # both
        child3 = api._spawn("/baz/")
        self.assertEqual(child3._name, "baz")
        # non-string still handled (int) - _chain converts to str before _spawn
        # but direct spawn with int would not be stripped (not str case)
        # ensure call interface strips correctly
        self.assertEqual(str(api("/foo")), f"{self.BASE}/foo")
        self.assertEqual(str(api("/foo/")), f"{self.BASE}/foo")


class TestRedirectVerbPreservation(unittest.TestCase):
    """Issue #21: redirect should not change POST to GET"""

    BASE = "http://localhost:8000"

    def test_post_preserved_on_302(self):
        api = Hammock(self.BASE)
        redirect_resp = mock.Mock(
            status_code=302,
            headers={"Location": f"{self.BASE}/redirected"},
            url=f"{self.BASE}/foo",
        )
        final_resp = mock.Mock(status_code=200, headers={}, url=f"{self.BASE}/redirected")
        with mock.patch.object(
            api._session, "request", side_effect=[redirect_resp, final_resp]
        ) as m:
            resp = api.foo.POST(json={"x": 1})
            self.assertEqual(resp, final_resp)
            self.assertEqual(m.call_count, 2)
            # first call POST to original url
            self.assertEqual(m.call_args_list[0][0][0], "post")
            self.assertEqual(m.call_args_list[0][0][1], f"{self.BASE}/foo")
            # second call should still be POST to redirected url
            self.assertEqual(m.call_args_list[1][0][0], "post")
            self.assertEqual(m.call_args_list[1][0][1], f"{self.BASE}/redirected")
            # json payload preserved
            self.assertEqual(m.call_args_list[1][1].get("json"), {"x": 1})

    def test_303_changes_to_get(self):
        api = Hammock(self.BASE)
        redirect_resp = mock.Mock(
            status_code=303,
            headers={"Location": f"{self.BASE}/other"},
            url=f"{self.BASE}/foo",
        )
        final_resp = mock.Mock(status_code=200, headers={}, url=f"{self.BASE}/other")
        with mock.patch.object(
            api._session, "request", side_effect=[redirect_resp, final_resp]
        ) as m:
            resp = api.foo.POST(json={"x": 1}, data="body")
            self.assertEqual(m.call_args_list[1][0][0], "get")
            # body should be dropped for 303
            self.assertNotIn("json", m.call_args_list[1][1])
            self.assertNotIn("data", m.call_args_list[1][1])

    def test_allow_redirects_false_no_follow(self):
        api = Hammock(self.BASE)
        redirect_resp = mock.Mock(
            status_code=302,
            headers={"Location": f"{self.BASE}/redirected"},
            url=f"{self.BASE}/foo",
        )
        with mock.patch.object(api._session, "request", return_value=redirect_resp) as m:
            resp = api.foo.POST(allow_redirects=False)
            m.assert_called_once()
            self.assertEqual(resp, redirect_resp)
            self.assertEqual(m.call_args[1].get("follow_redirects"), False)
        # also follow_redirects alias
        with mock.patch.object(api._session, "request", return_value=redirect_resp) as m:
            resp = api.foo.POST(follow_redirects=False)
            m.assert_called_once()
            self.assertEqual(m.call_args[1].get("follow_redirects"), False)

    def test_relative_redirect_resolved(self):
        api = Hammock(self.BASE)
        redirect_resp = mock.Mock(
            status_code=301,
            headers={"Location": "/new-path"},
            url=f"{self.BASE}/old",
        )
        final_resp = mock.Mock(status_code=200, headers={}, url=f"{self.BASE}/new-path")
        with mock.patch.object(
            api._session, "request", side_effect=[redirect_resp, final_resp]
        ) as m:
            api.foo.GET()
            self.assertEqual(m.call_args_list[1][0][1], f"{self.BASE}/new-path")


class TestHammockEdge(unittest.TestCase):
    BASE = "http://localhost:8000"

    def test_empty_base_url(self):
        h = Hammock("")
        self.assertEqual(str(h), "")
        # empty base is falsy so __iter__ skips it, chain is just "foo"
        self.assertEqual(str(h.foo), "foo")

    def test_numeric_and_bool_chain(self):
        h = Hammock(self.BASE)
        self.assertEqual(str(h(0, False, True)), f"{self.BASE}/0/False/True")


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
