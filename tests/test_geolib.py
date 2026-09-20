import json, tempfile, threading, unittest
from pathlib import Path
import sys; sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import geolib as G

class TestJsonIO(unittest.TestCase):
    def test_traditional_chinese_document_output(self):
        source = "诊断报告：当前项目支持导出文件，运行后打开链接。"
        expected = "診斷報告：目前專案支援匯出檔案，執行後開啟連結。"
        self.assertEqual(G.to_zh_tw(source), expected)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "report.md"
            G.write_document(p, source)
            self.assertEqual(p.read_text("utf-8"), expected)
            self.assertFalse(list(Path(d).glob("*.tmp")))

    def test_traditional_conversion_preserves_code_and_urls(self):
        source = (
            "运行下面代码：`print('简体代码')`\n"
            "```python\n标签 = '简体代码'\n```\n"
            "访问 https://example.com/简体路径。继续运行。"
        )
        converted = G.to_zh_tw(source)
        self.assertIn("執行下面程式碼", converted)
        self.assertIn("`print('简体代码')`", converted)
        self.assertIn("标签 = '简体代码'", converted)
        self.assertIn("https://example.com/简体路径", converted)
        self.assertIn("。繼續執行。", converted)

    def test_json_document_preserves_keys_and_normalizes_values(self):
        source = json.dumps({"简体键": "当前项目", "nested": ["打开链接"]}, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "asset.json"
            G.write_document(p, source)
            payload = json.loads(p.read_text("utf-8"))
        self.assertIn("简体键", payload)
        self.assertEqual(payload["简体键"], "目前專案")
        self.assertEqual(payload["nested"], ["開啟連結"])

    def test_write_json_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            G.write_json(p, {"a": 1})
            self.assertEqual(G.read_json(p), {"a": 1})
            self.assertFalse(list(Path(d).glob("*.tmp")))

    def test_concurrent_writers_in_one_process(self):
        """看板是 ThreadingHTTPServer：同 PID 的两个线程写同一个文件不能互相踩。

        暂存文件名曾用 PID 拼，两个线程会撞同一个路径——先完成的那个把它 rename
        走，另一个撞 FileNotFoundError（review 0920 · findings 1）。"""
        for writer in (G.write_json, lambda p2, v: G.write_document(p2, json.dumps(v))):
            with tempfile.TemporaryDirectory() as d:
                target = Path(d) / "shared.json"
                start = threading.Barrier(8)
                errors = []

                def run(i):
                    start.wait()
                    try:
                        writer(target, {"writer": i})
                    except Exception as e:      # noqa: BLE001 —— 要的就是它不该发生
                        errors.append(e)

                threads = [threading.Thread(target=run, args=(i,)) for i in range(8)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                self.assertEqual(errors, [], f"{writer} 并发写出错")
                self.assertIn("writer", G.read_json(target, {}))
                self.assertEqual(list(Path(d).iterdir()), [target])

    def test_jsonld_fact_fields_survive_traditional_conversion(self):
        """JSON-LD 的身分字段是品牌事实，不是文案：转换会把它改写成另一个牌子
        （review 0920 · findings 5）。"""
        payload = {
            "@type": "Organization",
            "name": "软件工厂",
            "alternateName": ["软件工厂科技", "Software Factory"],
            "url": "https://example.com/产品",
            "description": "面向当前项目的数据网络服务。",
            "parentOrganization": {"@type": "Organization", "name": "网络集团"},
        }
        with tempfile.TemporaryDirectory() as d:
            p2 = Path(d) / "organization.json"
            G.write_document(p2, json.dumps(payload, ensure_ascii=False),
                             json_translate_keys=G.JSONLD_TRANSLATABLE_KEYS)
            out = json.loads(p2.read_text("utf-8"))
        self.assertEqual(out["name"], "软件工厂")
        self.assertEqual(out["alternateName"], ["软件工厂科技", "Software Factory"])
        self.assertEqual(out["url"], "https://example.com/产品")
        self.assertEqual(out["parentOrganization"]["name"], "网络集团")
        self.assertEqual(out["description"], "面向目前專案的資料網路服務。")

    def test_read_json_corrupt_returns_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text("{broken", "utf-8")
            self.assertEqual(G.read_json(p, default={}), {})

    def test_project_dir_rejects_traversal(self):
        for bad in ("../x", "/etc", "a/b", ".."):
            with self.assertRaises(SystemExit):
                G.project_dir(bad)

    def test_project_dir_accepts_valid_slug(self):
        self.assertEqual(G.project_dir("aigclink"), G.WORK / "aigclink")

    def test_read_json_missing_returns_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "nope.json"
            self.assertEqual(G.read_json(p, default={"x": 1}), {"x": 1})
            self.assertIsNone(G.read_json(p))

    def test_main_text_single_article_stays_focused(self):
        soup = G.parse_html(
            "<main><nav>menu</nav><article>the post body</article></main>")
        self.assertEqual(G.main_text(soup), "the post body")

    def test_main_text_multiple_articles_takes_whole_main(self):
        soup = G.parse_html(
            "<main><article>intro section</article>"
            "<article>steps: 1 2 3</article>"
            "<article>faq answers</article></main>")
        text = G.main_text(soup)
        for piece in ("intro section", "steps: 1 2 3", "faq answers"):
            self.assertIn(piece, text)

    def test_jsonl_roundtrip_with_unicode_line_separators(self):
        """正文含 U+2028/U+2029/U+0085 时 JSONL 必须仍能读回。

        json.dumps 不转义这些字符，而 str.splitlines() 会在它们处断行，
        导致一条记录被劈成两半。真实触发场景：抓取的网页正文里带 U+2028。
        """
        rows = [
            {"url": "https://a.example/1", "text": "line one\u2028line two"},
            {"url": "https://a.example/2", "text": "para\u2029break"},
            {"url": "https://a.example/3", "text": "next\u0085line"},
            {"url": "https://a.example/4", "text": "vert\u000btab and form\u000cfeed"},
            {"url": "https://a.example/5", "text": "plain"},
        ]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pages.jsonl"
            G.write_jsonl(p, rows)
            # 前提确认：这些字符确实原样落盘了，否则本测试没有鉴别力
            self.assertIn("\u2028", p.read_text("utf-8"))
            self.assertEqual(G.read_jsonl(p), rows)
    def test_main_text_marks_code_boundaries(self):
        soup = G.parse_html(
            "<main><p>运行示例</p><pre><code>标签 = '简体代码'</code></pre>"
            "<p>使用 <code>简体变量</code> 完成</p></main>"
        )
        text = G.main_text(soup)
        self.assertIn("```text\n标签 = '简体代码'\n```", text)
        self.assertIn("`简体变量`", text)
        converted = G.to_zh_tw(text)
        self.assertIn("執行示例", converted)
        self.assertIn("标签 = '简体代码'", converted)
        self.assertIn("`简体变量`", converted)

    def test_project_lock_enter_exit(self):
        with tempfile.TemporaryDirectory() as d:
            slug = "locktest"
            orig_work = G.WORK
            G.WORK = Path(d)
            try:
                with G.project_lock(slug):
                    self.assertTrue((Path(d) / slug / ".lock").exists())
                self.assertTrue((Path(d) / slug / ".lock").exists())
            finally:
                G.WORK = orig_work

if __name__ == "__main__":
    unittest.main()


class TestNoSiteMode(unittest.TestCase):
    """无自有网站项目（电商商品/线下品牌/小程序）的判定与降级。"""

    def test_has_site(self):
        self.assertTrue(G.has_site({"brand": {"site": "https://a.com"}}))
        for empty in ({"brand": {"site": ""}}, {"brand": {"site": "   "}}, {"brand": {}}, {}):
            self.assertFalse(G.has_site(empty), empty)

    def test_no_site_metrics_are_none_not_zero(self):
        """无站点时「引用官网率」必须是 None（不适用），绝不能退化成 0——
        0 会被读成「一次都没被引用」，那是编数。"""
        import sample as S
        cfg = {"brand": {"name": "商品", "site": "", "aliases": []}, "competitors": [],
               "questions": [{"id": "q001", "text": "有哪些好用的绿茶", "group": "推荐"}]}
        rows = [{"platform": "deepseek", "market": "cn", "question_id": "q001",
                 "question": "有哪些好用的绿茶", "ok": True,
                 "analysis": {"brand_mentioned": False, "brand_rank": 0, "candidates": [],
                              "competitors_mentioned": [], "cited_domains": ["x.com"],
                              "own_domain_cited": False, "answer_chars": 100}}]
        agg = S.aggregate(rows, cfg)
        self.assertIsNone(agg["deepseek"]["own_domain_cite_rate"])
        self.assertEqual(agg["deepseek"]["mention_rate"], 0.0)   # 提及率照常可测

    def test_no_site_generates_no_site_tickets(self):
        import tasks as T
        cfg = {"brand": {"name": "商品", "site": ""}, "market": "cn"}
        self.assertEqual(T.from_audit({"no_site": True}, cfg, iter(["T-001"])), [])
