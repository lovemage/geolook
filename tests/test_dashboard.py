import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import dashboard as D


class ResolveHostCase(unittest.TestCase):
    def test_prefers_tailscale_ipv4(self):
        result = mock.Mock(returncode=0, stdout="100.120.148.6\n")
        with mock.patch.object(D.subprocess, "run", return_value=result) as run:
            self.assertEqual(D._resolve_host(), "100.120.148.6")
        run.assert_called_once_with(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )

    def test_explicit_host_skips_tailscale_lookup(self):
        with mock.patch.object(D.subprocess, "run") as run:
            self.assertEqual(D._resolve_host("127.0.0.1"), "127.0.0.1")
        run.assert_not_called()

    def test_falls_back_when_tailscale_is_unavailable(self):
        with mock.patch.object(D.subprocess, "run", side_effect=FileNotFoundError):
            self.assertEqual(D._resolve_host(), "127.0.0.1")

    def test_falls_back_for_invalid_tailscale_output(self):
        result = mock.Mock(returncode=0, stdout="not-an-ip\n")
        with mock.patch.object(D.subprocess, "run", return_value=result):
            self.assertEqual(D._resolve_host(), "127.0.0.1")


class ShutdownEndpointCase(unittest.TestCase):
    def handler(self, body, headers=None):
        h = D.Handler.__new__(D.Handler)
        h.path = "/api/shutdown"
        h.headers = {"Content-Type": "application/json",
                     "Host": "127.0.0.1:8765", **(headers or {})}
        h._body = mock.Mock(return_value=body)
        h._json = mock.Mock()
        h._reject = mock.Mock()
        h.server = mock.Mock()
        return h

    def test_requires_explicit_confirmation(self):
        h = self.handler({})
        h.do_POST()
        h._json.assert_called_once_with(
            {"ok": False, "error": "需要明確確認關閉伺服器"}, 400
        )
        h.server.shutdown.assert_not_called()

    def test_sends_response_before_starting_shutdown_thread(self):
        h = self.handler({"confirm": True})
        thread = mock.Mock()
        with mock.patch.object(D.threading, "Thread", return_value=thread) as make_thread:
            h.do_POST()
        h._json.assert_called_once_with(
            {"ok": True, "message": "GeoLook 伺服器正在關閉"}
        )
        make_thread.assert_called_once_with(target=h.server.shutdown, daemon=True)
        thread.start.assert_called_once_with()


class TestWriteGuard(unittest.TestCase):
    """未设令牌时，写入端点仍要挡住浏览器里的跨源请求（review 0920 · findings 3）。"""

    def test_host_allowed_accepts_local_names_and_ip_literals(self):
        for host in ("127.0.0.1:8765", "localhost:8765", "[::1]:8765",
                     "100.120.148.6:8765", "nas.tail1234.ts.net:8765"):
            self.assertTrue(D.host_allowed(host), host)

    def test_host_allowed_rejects_unknown_domains(self):
        # DNS rebinding：攻击者把自己的域名解析到 127.0.0.1，Origin 与 Host 就会一致
        for host in ("evil.example.com:8765", "", None):
            self.assertFalse(D.host_allowed(host), host)

    def test_host_allowed_honours_explicit_allowlist(self):
        self.assertTrue(D.host_allowed("geo.internal:8765",
                                       frozenset({"geo.internal"})))

    def test_write_origin_accepts_same_origin_and_extensions(self):
        self.assertTrue(D.write_origin_ok("http://127.0.0.1:8765", "127.0.0.1:8765"))
        self.assertTrue(D.write_origin_ok("chrome-extension://abcdef", "127.0.0.1:8765"))
        self.assertTrue(D.write_origin_ok(None, "127.0.0.1:8765"))   # curl / CLI

    def test_write_origin_rejects_foreign_pages(self):
        self.assertFalse(D.write_origin_ok("https://evil.example.com", "127.0.0.1:8765"))
        self.assertFalse(D.write_origin_ok("http://127.0.0.1:9999", "127.0.0.1:8765"))
        self.assertFalse(D.write_origin_ok("null", "127.0.0.1:8765"))

    def _guarded(self, headers):
        h = D.Handler.__new__(D.Handler)
        h.path = "/api/shutdown"
        h.headers = headers
        h._reject = mock.Mock()
        h._json = mock.Mock()
        h._body = mock.Mock(return_value={"confirm": True})
        h.server = mock.Mock()
        return h

    def test_cross_origin_shutdown_is_refused(self):
        h = self._guarded({"Content-Type": "application/json",
                           "Host": "127.0.0.1:8765",
                           "Origin": "https://evil.example.com"})
        h.do_POST()
        h.server.shutdown.assert_not_called()
        self.assertEqual(h._reject.call_args[0][0], 403)

    def test_non_json_content_type_is_refused(self):
        h = self._guarded({"Content-Type": "text/plain", "Host": "127.0.0.1:8765"})
        h.do_POST()
        h.server.shutdown.assert_not_called()
        self.assertEqual(h._reject.call_args[0][0], 415)

    def test_rebinding_host_is_refused(self):
        h = self._guarded({"Content-Type": "application/json",
                           "Host": "evil.example.com:8765",
                           "Origin": "http://evil.example.com:8765"})
        h.do_POST()
        h.server.shutdown.assert_not_called()
        self.assertEqual(h._reject.call_args[0][0], 403)

    def test_allowed_hosts_includes_bound_address(self):
        with mock.patch.dict(D.os.environ, {"GEOLOOK_ALLOWED_HOSTS": "geo.internal"}, clear=True):
            allowed = D._allowed_hosts("100.120.148.6")
        self.assertIn("100.120.148.6", allowed)
        self.assertIn("geo.internal", allowed)
        self.assertIn("127.0.0.1", allowed)


class TestInitNoSite(unittest.TestCase):
    """无自有网站的品牌也要能从网页入口建项目（review 0920 · findings 4）。"""

    def handler(self, body):
        h = D.Handler.__new__(D.Handler)
        h.path = "/api/init"
        h.headers = {"Content-Type": "application/json", "Host": "127.0.0.1:8765"}
        h._body = mock.Mock(return_value=body)
        h._json = mock.Mock()
        h._reject = mock.Mock()
        return h

    def test_no_site_requires_a_name(self):
        h = self.handler({"no_site": True, "url": "", "name": ""})
        h.do_POST()
        self.assertEqual(h._json.call_args[0][1], 400)

    def test_no_site_creates_project_without_url(self):
        h = self.handler({"no_site": True, "name": "示例商品", "market": "cn"})
        cfg = {"slug": "shi-li", "brand": {"name": "示例商品", "site": ""}}
        with mock.patch.object(D, "create_project", return_value=cfg) as create:
            h.do_POST()
        create.assert_called_once_with("", "示例商品", "", "cn", 25, no_site=True)
        h._json.assert_called_once_with({"ok": True, "slug": "shi-li", "no_site": True})

    def test_no_site_rejects_a_url(self):
        h = self.handler({"no_site": True, "name": "示例", "url": "https://x.com"})
        h.do_POST()
        self.assertEqual(h._json.call_args[0][1], 400)

    def test_site_mode_still_requires_url(self):
        h = self.handler({"name": "示例"})
        h.do_POST()
        self.assertEqual(h._json.call_args[0][1], 400)


class TestAuthOk(unittest.TestCase):
    TOKEN = "s3cret-token"

    def test_no_token_configured_allows_all(self):
        self.assertTrue(D.auth_ok(None, None))
        self.assertTrue(D.auth_ok("", "anything=1"))

    def test_query_token_matches(self):
        self.assertTrue(D.auth_ok(self.TOKEN, None, query_token=self.TOKEN))

    def test_header_token_matches(self):
        self.assertTrue(D.auth_ok(self.TOKEN, None, header_token=self.TOKEN))

    def test_cookie_digest_matches(self):
        cookie = f"other=1; {D.AUTH_COOKIE}={D._token_digest(self.TOKEN)}"
        self.assertTrue(D.auth_ok(self.TOKEN, cookie))

    def test_wrong_credentials_rejected(self):
        self.assertFalse(D.auth_ok(self.TOKEN, None))
        self.assertFalse(D.auth_ok(self.TOKEN, None, query_token="wrong"))
        self.assertFalse(D.auth_ok(self.TOKEN, f"{D.AUTH_COOKIE}=deadbeef"))
        # cookie 里放原始令牌不行——cookie 存的是摘要
        self.assertFalse(D.auth_ok(self.TOKEN, f"{D.AUTH_COOKIE}={self.TOKEN}"))


class TestPublicBindGuard(unittest.TestCase):
    def test_public_host_without_token_dies(self):
        with mock.patch.dict(D.os.environ, {}, clear=True), \
             self.assertRaises(SystemExit):
            D.run(port=0, open_browser=False, host="0.0.0.0", token=None)


class TestMergedStartup(unittest.TestCase):
    def test_detected_tailscale_requires_token(self):
        with mock.patch.dict(D.os.environ, {}, clear=True), \
             mock.patch.object(D, "_resolve_host", return_value="100.120.148.6"), \
             mock.patch.object(D, "ThreadingHTTPServer") as server, \
             self.assertRaises(SystemExit):
            D.run(open_browser=False)
        server.assert_not_called()

    def test_environment_host_and_token_are_used(self):
        with mock.patch.dict(D.os.environ, {"GEOLOOK_HOST": "127.0.0.1", "GEOLOOK_TOKEN": "test-token"}, clear=True), \
             mock.patch.object(D.Handler, "TOKEN", None), \
             mock.patch.object(D.subprocess, "run") as lookup, \
             mock.patch.object(D.J, "reap_orphans"), \
             mock.patch.object(D.threading, "Thread"), \
             mock.patch.object(D, "ThreadingHTTPServer") as server:
            D.run(port=9876, open_browser=False)
            server.assert_called_once_with(("127.0.0.1", 9876), D.Handler)
            self.assertEqual(D.Handler.TOKEN, "test-token")
            lookup.assert_not_called()

    def test_explicit_host_overrides_environment(self):
        with mock.patch.dict(D.os.environ, {"GEOLOOK_HOST": "0.0.0.0"}, clear=True), \
             mock.patch.object(D.Handler, "TOKEN", None), \
             mock.patch.object(D.J, "reap_orphans"), \
             mock.patch.object(D.threading, "Thread"), \
             mock.patch.object(D, "ThreadingHTTPServer") as server:
            D.run(host="127.0.0.1", open_browser=False)
            server.assert_called_once_with(("127.0.0.1", 8765), D.Handler)


if __name__ == "__main__":
    unittest.main()
