"""采样扩展的静态回归（review 0920 · findings 2）。

扩展没有 Python 侧逻辑，端到端跑真实 Chrome 的脚本在 extension/test/e2e.js，
只在 macOS 上手动跑。这里守住三件不该再回退的事：
所有请求走同一个带令牌的包装、界面有令牌输入、自定义服务器地址要申请 host 权限。
"""

import json
import unittest
from pathlib import Path

EXT = Path(__file__).parent.parent / "extension"


class SidePanelAuthCase(unittest.TestCase):
    def setUp(self):
        self.js = (EXT / "sidepanel.js").read_text("utf-8")
        self.html = (EXT / "sidepanel.html").read_text("utf-8")

    def test_panel_has_a_token_field(self):
        self.assertIn('id="token"', self.html)

    def test_requests_carry_the_token_header(self):
        self.assertIn('opt.headers["X-Geolook-Token"] = t;', self.js)

    def test_no_bare_fetch_outside_the_wrapper(self):
        # 只有 apiFetch 里那一处 fetch()；再出现第二处就说明又有请求绕过了令牌
        self.assertEqual(self.js.count("fetch("), 1, "有请求绕过 apiFetch 包装")

    def test_uploads_and_queue_go_through_the_wrapper(self):
        self.assertIn("await apiPost(`/api/collect/${slug()}`", self.js)
        self.assertIn("const apiGet = (path) => apiFetch(path);", self.js)

    def test_unauthorized_response_tells_the_user_what_to_do(self):
        self.assertIn("r.status === 401", self.js)
        self.assertIn("GEOLOOK_TOKEN", self.js)

    def test_custom_server_requests_host_permission(self):
        self.assertIn("chrome.permissions.request", self.js)
        self.assertIn("ensureAccess", self.js)


class ManifestCase(unittest.TestCase):
    def setUp(self):
        self.mf = json.loads((EXT / "manifest.json").read_text("utf-8"))

    def test_default_host_permissions_stay_local(self):
        self.assertEqual(self.mf["host_permissions"],
                         ["http://127.0.0.1:8765/*", "http://localhost:8765/*"])

    def test_other_servers_are_optional_not_granted(self):
        self.assertIn("optional_host_permissions", self.mf)
        self.assertIn("http://*/*", self.mf["optional_host_permissions"])


if __name__ == "__main__":
    unittest.main()
