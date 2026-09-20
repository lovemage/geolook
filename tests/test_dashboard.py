import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import dashboard as D


class ShutdownEndpointCase(unittest.TestCase):
    def handler(self, body):
        h = D.Handler.__new__(D.Handler)
        h.path = "/api/shutdown"
        h.headers = {}
        h._body = mock.Mock(return_value=body)
        h._json = mock.Mock()
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
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import dashboard as D


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


if __name__ == "__main__":
    unittest.main()
