"""GEO 工具箱共用模块：路径、配置、HTTP、正文抽取。

依赖 requests / bs4 / lxml / OpenCC，不引入 yaml/jinja2。
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from opencc import OpenCC

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"

# 人類可讀輸出一律使用繁體中文（台灣）。OpenCC 負責完整的簡繁詞義轉換；
# 這份字形表仍與 UI 的離線 zh-TW 轉換表共用，並作為簡繁字形辨識依據。
ZHTW_FROM = "万与专业东丢两严个临为举么义习书买乱争于亏云产亿仅从仓们价众优会传伤体余侧储儿关兴内册写决况净准减凑几凭击划则刚创删别剥办务动势区协单占却厂历压参双发变叠台号后吗听启员响团园围国图场坏块声壳处备复够头夸宁宝实审对导将尔尸层属币师带帮干并库应开异弃张弹强归当录径忆态总恒悬惩惯愿戏战户托执扩扫扰抢护报担拟拥拦择挂挡挤损换据携撑数斗断无旧时显暂术机杀杂权杠条来极构栅标栏树样档检槛横残气汇汉没浅测浏涨满滤滥灭点状独环现画监盖盘着码础确礼离种积称稳竖竞笔筛签简类纠约级纪纯纲纳线组细织终经绑结给绝统继绪续维综缀编缘网罚联脑脚脱腾节范荐获营蓝虑补装见观规视览触计订认讨让议讯记讲许论设访证评识诉诊词译试诚话询该详语误说请诺读谁调谱负责败账质购贴费资赖赢趋踪车转轮软轻载较辑输边达过运还这进远连迟适选递逻邻采释里鉴钟钥钱钻铺链销锁锋错锚键长门闭问间闻阅阈队阳阵阶际险随隐难静页顶项顺须顾顿预领颈频题额风饰马驱验骗骤齐"
ZHTW_TO = "萬與專業東丟兩嚴個臨為舉麼義習書買亂爭於虧雲產億僅從倉們價眾優會傳傷體餘側儲兒關興內冊寫決況淨準減湊幾憑擊劃則剛創刪別剝辦務動勢區協單佔卻廠歷壓參雙發變疊臺號後嗎聽啟員響團園圍國圖場壞塊聲殼處備復夠頭誇寧寶實審對導將爾屍層屬幣師帶幫幹並庫應開異棄張彈強歸當錄徑憶態總恆懸懲慣願戲戰戶託執擴掃擾搶護報擔擬擁攔擇掛擋擠損換據攜撐數鬥斷無舊時顯暫術機殺雜權槓條來極構柵標欄樹樣檔檢檻橫殘氣匯漢沒淺測瀏漲滿濾濫滅點狀獨環現畫監蓋盤著碼礎確禮離種積稱穩豎競筆篩籤簡類糾約級紀純綱納線組細織終經綁結給絕統繼緒續維綜綴編緣網罰聯腦腳脫騰節範薦獲營藍慮補裝見觀規視覽觸計訂認討讓議訊記講許論設訪證評識訴診詞譯試誠話詢該詳語誤說請諾讀誰調譜負責敗賬質購貼費資賴贏趨蹤車轉輪軟輕載較輯輸邊達過運還這進遠連遲適選遞邏鄰採釋裡鑑鍾鑰錢鑽鋪鏈銷鎖鋒錯錨鍵長門閉問間聞閱閾隊陽陣階際險隨隱難靜頁頂項順須顧頓預領頸頻題額風飾馬驅驗騙驟齊"
ZHTW_TERMS = (
    ("箇", "個"), ("識別", "辨識"),
    ("生成式引擎優化平臺", "生成式引擎最佳化平台"), ("搜尋引擎優化", "搜尋引擎最佳化"),
    ("接入新品牌", "新增品牌"), ("接入引導", "新增品牌引導"), ("國內引擎", "中國引擎"),
    ("國內市場", "中國市場"), ("人工智能", "人工智慧"), ("文件夾", "資料夾"),
    ("手機號", "手機號碼"), ("源代碼", "原始碼"), ("工作臺", "工作台"),
    ("後臺", "後台"), ("平臺", "平台"), ("舞臺", "舞台"), ("數據", "資料"),
    ("信息", "資訊"), ("信源", "資訊來源"), ("陣地", "通路"), ("渠道", "通路"),
    ("設置", "設定"), ("配置", "設定"), ("項目", "專案"), ("保存", "儲存"),
    ("文件", "檔案"), ("網絡", "網路"), ("鏈接", "連結"), ("賬號", "帳號"),
    ("用戶", "使用者"), ("創建", "建立"), ("添加", "新增"), ("加載", "載入"),
    ("導入", "匯入"), ("導出", "匯出"), ("運行", "執行"), ("訪問", "存取"),
    ("代碼", "程式碼"), ("質量", "品質"), ("視頻", "影片"), ("反饋", "回饋"),
    ("服務器", "伺服器"), ("鼠標", "滑鼠"), ("日誌", "紀錄"), ("內存", "記憶體"),
    ("搜索", "搜尋"), ("點擊", "點選"), ("刷新", "重新整理"), ("優化", "最佳化"),
    ("接口", "介面"), ("字段", "欄位"), ("域名", "網域"), ("默認", "預設"),
    ("當前", "目前"), ("支持", "支援"), ("響應", "回應"), ("連接", "連線"),
    ("進程", "程序"), ("程序", "程式"), ("官網", "官方網站"), ("打印", "列印"),
    ("回歸", "迴歸"), ("定時器", "排程器"), ("取舍", "取捨"),
)
_OPENCC_S2TWP = OpenCC("s2twp")
_ZH_HANS_MARKERS = frozenset(ZHTW_FROM) - frozenset(ZHTW_TO)
_ZH_HANT_MARKERS = frozenset(ZHTW_TO) - frozenset(ZHTW_FROM)
_PROTECTED_TEXT = re.compile(
    r"(```.*?```|~~~.*?~~~|"
    r"<(?:pre|code|script|style)\b[^>]*>.*?</(?:pre|code|script|style)\s*>|"
    r"`[^`\r\n]+`|https?://[^\s<>\]\)\"'，。；！？、（）【】《》「」『』“”‘’]+|"
    r"^(?: {4}|\t).*?$)",
    re.IGNORECASE | re.DOTALL | re.MULTILINE,
)


def chinese_script_profile(text: str, lang_attr: str = "") -> dict:
    """辨識中文使用 zh-Hans 或 zh-Hant，並回傳可稽核的信心值與字形計數。"""
    value = str(text or "")
    hans = sum(c in _ZH_HANS_MARKERS for c in value)
    hant = sum(c in _ZH_HANT_MARKERS for c in value)
    total = hans + hant
    attr = (lang_attr or "").lower().replace("_", "-")
    hint = ("zh-Hans" if attr.startswith(("zh-cn", "zh-sg", "zh-hans")) else
            "zh-Hant" if attr.startswith(("zh-tw", "zh-hk", "zh-mo", "zh-hant")) else "zh")

    if total:
        confidence = round(max(hans, hant) / total, 3)
        if hans > hant:
            language = "zh-Hans"
        elif hant > hans:
            language = "zh-Hant"
        else:
            language = hint
            confidence = 0.5 if hint != "zh" else 0.0
    else:
        language = hint
        confidence = 0.55 if hint != "zh" else 0.0
    return {
        "language": language,
        "confidence": confidence,
        "hans_markers": hans,
        "hant_markers": hant,
    }


def _convert_zh_tw_plain(text: str) -> str:
    out = _OPENCC_S2TWP.convert(text)
    for source, target in sorted(ZHTW_TERMS, key=lambda pair: len(pair[0]), reverse=True):
        out = out.replace(source, target)
    return out


def load_env(path: Path | None = None):
    """读项目根目录的 .env（已 gitignore）。已存在的环境变量优先，不覆盖。"""
    p = path or (ROOT / ".env")
    if not p.exists():
        return
    for line in p.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


load_env()

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 geo-skill/1.0"
)
# 403/406 回退用：不带 geo-skill 标记的纯浏览器 UA。很多 WAF 规则只拦
# 「带工具标记的 UA」，回退能区分「拦工具」还是「拦 IP」，这本身是诊断信号。
UA_BROWSER = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------- 基础工具


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def slugify(text: str) -> str:
    text = re.sub(r"^https?://", "", (text or "").strip().lower())
    text = re.sub(r"[^a-z0-9一-鿿]+", "-", text).strip("-")
    return text[:48] or "project"


def die(msg: str, code: int = 1):
    print(f"[geo] 错误：{msg}", file=sys.stderr)
    sys.exit(code)


def info(msg: str):
    print(f"[geo] {msg}", file=sys.stderr)


def to_zh_tw(text: str) -> str:
    """轉成台灣繁體；程式碼、HTML 程式區塊、縮排程式碼與網址保持原樣。"""
    value = str(text)
    out = []
    pos = 0
    for match in _PROTECTED_TEXT.finditer(value):
        out.append(_convert_zh_tw_plain(value[pos:match.start()]))
        out.append(match.group(0))
        pos = match.end()
    out.append(_convert_zh_tw_plain(value[pos:]))
    return "".join(out)


# JSON-LD 的身分欄位是品牌事實（註冊名、別名、網址、代碼、日期），繁簡轉換會把它們
# 改寫成另一個不存在的名字，讓結構化資料與事實庫對不上。寫這類檔案時只翻譯描述欄位，
# 其餘一律保留原文；需要在地名稱時，靠 brand.aliases 另外登記經確認的繁體別名。
JSONLD_TRANSLATABLE_KEYS = frozenset({
    "description", "about", "abstract", "disambiguatingDescription", "text",
    "audienceType",
})


def _normalize_json_values(value, translate_keys=None, translate=True):
    """JSON key 屬於資料結構不可翻譯，只正規化人類可讀的字串值。

    translate_keys 是 None 時整份翻譯；給定集合時只翻譯該集合內的 key，
    其餘欄位（品牌名、別名、網址、代碼等事實）原樣保留，子結構一併繼承。
    """
    if isinstance(value, str):
        return to_zh_tw(value) if translate else value
    if isinstance(value, list):
        return [_normalize_json_values(item, translate_keys, translate) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_json_values(
                    item, translate_keys,
                    translate if translate_keys is None else key in translate_keys)
                for key, item in value.items()}
    return value


def atomic_write(path: Path, text: str):
    """同目錄唯一暫存檔 + os.replace()。

    PID 不足以區分同一程序裡的多個執行緒——看板是 ThreadingHTTPServer，兩個請求
    同時寫同一個檔就會共用暫存路徑，先完成的那個 rename 走檔案，另一個撞上
    FileNotFoundError。改用 mkstemp 取唯一名字，落盤後再 replace。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_document(path: Path, text: str, json_translate_keys=None):
    """以 UTF-8 原子寫入繁體中文人類可讀文件。

    json_translate_keys 只對 .json 生效：給定欄位集合時僅翻譯這些欄位，
    其餘保留原文（JSON-LD 等事實型結構化資料用）。
    """
    p = Path(path)
    rendered = to_zh_tw(text)
    if p.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            pass
        else:
            rendered = json.dumps(
                _normalize_json_values(payload, json_translate_keys),
                ensure_ascii=False, indent=2)
            if str(text).endswith("\n"):
                rendered += "\n"
    atomic_write(p, rendered)


# ---------------------------------------------------------------- 项目目录

SLUG_OK = re.compile(r"^[a-z0-9一-鿿][a-z0-9一-鿿-]{0,47}$")


def project_dir(slug: str) -> Path:
    if not SLUG_OK.match(slug or ""):
        die(f"非法项目标识：{slug!r}")
    return WORK / slug


@contextmanager
def project_lock(slug: str):
    """项目级跨进程锁：load-modify-write 操作必须走它。"""
    d = project_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    with (d / ".lock").open("w") as fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)


def load_config(slug: str) -> dict:
    p = project_dir(slug) / "geo.json"
    if not p.exists():
        die(f"找不到项目配置 {p}，先运行：python3 scripts/geo.py init --url <网址>")
    return json.loads(p.read_text("utf-8"))


def has_site(cfg: dict) -> bool:
    """项目有没有自有网站。无站点项目（电商商品、线下品牌、小程序等）同样能做 GEO：
    抓取/体检/站内资产这几步不适用，但采样、竞品、阵地、内容、验收全都照常。
    判据只看 brand.site 是否为空——不引入第二个真相源。"""
    return bool((cfg.get("brand") or {}).get("site", "").strip())


def save_config(slug: str, cfg: dict):
    """写配置前先备份。geo.json 里是一期的人工投入（问题库、竞品、口径），
    被误覆盖的代价远大于留几个备份文件。"""
    p = project_dir(slug) / "geo.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        bak = p.parent / ".geo.bak"
        bak.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (bak / f"geo-{stamp}.json").write_text(p.read_text("utf-8"), "utf-8")
        old = sorted(bak.glob("geo-*.json"))
        for f in old[:-10]:
            f.unlink()
    atomic_write(p, json.dumps(cfg, ensure_ascii=False, indent=2))


def write_json(path: Path, data):
    atomic_write(Path(path), json.dumps(data, ensure_ascii=False, indent=2))


def read_json(path: Path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text("utf-8"))
    except json.JSONDecodeError:
        info(f"警告：{p} 已损坏，使用默认值")
        return default


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: Path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    # 必须按 "\n" 切，不能用 splitlines()：后者还会在 U+2028/U+2029/U+0085/\v/\f
    # 处断行，而 json.dumps 不转义这些字符，抓到含 U+2028 的页面就会把一条记录
    # 劈成两半 → JSONDecodeError，整期体检中断。
    for line in p.read_text("utf-8").split("\n"):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


# ---------------------------------------------------------------- HTTP

MAX_BYTES = 4_000_000  # 单页最多读 4MB，防止一头扎进安装包/大文件把管线拖死

# 一看就不是网页的路径，直接跳过（安装包、媒体、静态资源等）
SKIP_EXT = re.compile(
    r"\.(zip|gz|tgz|bz2|7z|rar|dmg|pkg|exe|msi|apk|ipa|deb|rpm|bin|iso"
    r"|mp4|mov|avi|mkv|mp3|wav|flac|png|jpe?g|gif|webp|svg|ico|bmp|tiff"
    r"|woff2?|ttf|eot|css|js|csv|xlsx?|docx?|pptx?|pdf)(\?|$)",
    re.I,
)
SKIP_PATH = re.compile(r"/(downloads?|dl|releases?|assets|static|cdn)/", re.I)


def is_fetchable(url: str) -> bool:
    if SKIP_EXT.search(url) or SKIP_PATH.search(url):
        return False
    tail = url.rstrip("/").rsplit("/", 1)[-1].lower()
    return tail not in {"download", "dl"}



def fetch(url: str, timeout: int = 12, retries: int = 1, ua: str | None = None) -> dict:
    """返回 {url, final_url, status, html, x_robots_tag, elapsed, error}。只读网页，且有体积上限。
    ua 可换成 AI 爬虫的 User-Agent 做差异探测（WAF/CDN 是否单独拦 AI 爬虫）。"""
    if not is_fetchable(url):
        return {"url": url, "final_url": url, "status": 0, "html": "", "content_type": "",
                "x_robots_tag": "", "elapsed": 0, "error": "跳过：不是网页（下载/媒体/静态资源）"}
    last = ""
    # 调用方没指定 UA 时，默认 UA 被 403/406 拦截后换纯浏览器 UA 再试一轮：
    # 站长在自己站上做诊断，绕过自家 WAF 的工具规则是合理的，且结果会标注出来
    ua_plan = [ua or UA] + ([UA_BROWSER] if ua is None else [])
    for ua_idx, cur_ua in enumerate(ua_plan):
      for attempt in range(retries + 1):
        try:
            t0 = time.time()
            headers = {"User-Agent": cur_ua, "Accept-Language": os.environ.get("GEO_ACCEPT_LANGUAGE", "zh-TW,zh-Hant;q=0.9,zh-CN;q=0.8,zh;q=0.7,en;q=0.6")}
            if ua_idx > 0:
                headers["Accept"] = ("text/html,application/xhtml+xml,application/xml;"
                                     "q=0.9,image/avif,image/webp,*/*;q=0.8")
            r = requests.get(
                url,
                timeout=timeout,
                headers=headers,
                allow_redirects=True,
                stream=True,
            )
            # 5xx / 429 多是临时故障（服务端抖动、限流），值得按异常同样的节奏重试
            if (r.status_code >= 500 or r.status_code == 429) and attempt < retries:
                r.close()
                time.sleep(1.5)
                continue
            # 默认 UA 被拦（403/406 是 WAF 的典型手势）→ 跳出内层，换浏览器 UA
            if r.status_code in (403, 406) and ua_idx + 1 < len(ua_plan):
                r.close()
                last = f"HTTP {r.status_code}（默认 UA 被拦）"
                break
            ctype = r.headers.get("Content-Type", "")
            xrobots = r.headers.get("X-Robots-Tag", "")
            if ctype and not any(k in ctype.lower() for k in ("html", "text/plain", "xml")):
                r.close()
                return {"url": url, "final_url": r.url, "status": r.status_code, "html": "",
                        "content_type": ctype, "x_robots_tag": xrobots,
                        "elapsed": round(time.time() - t0, 2),
                        "error": f"跳过非网页内容（{ctype.split(';')[0]}）"}
            chunks, size = [], 0
            for chunk in r.iter_content(65536):
                chunks.append(chunk)
                size += len(chunk)
                if size >= MAX_BYTES:
                    break
            r.close()
            raw = b"".join(chunks)
            enc = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else None
            if not enc:
                m = re.search(rb'charset=["\']?([\w\-]+)', raw[:4000], re.I)
                enc = m.group(1).decode("ascii", "ignore") if m else "utf-8"
            return {
                "url": url,
                "final_url": r.url,
                "status": r.status_code,
                "html": raw.decode(enc, "replace"),
                "content_type": ctype,
                "x_robots_tag": xrobots,
                "elapsed": round(time.time() - t0, 2),
                "error": None,
                "ua_fallback": ua_idx > 0,
            }
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            if attempt < retries:
                time.sleep(1.5)
    return {"url": url, "final_url": url, "status": 0, "html": "", "content_type": "",
            "x_robots_tag": "", "elapsed": 0, "error": last}


def fetch_text(url: str, timeout: int = 8) -> str:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA})
        if r.status_code == 200:
            r.encoding = r.apparent_encoding or r.encoding
            return r.text
    except Exception:  # noqa: BLE001
        pass
    return ""


# ---------------------------------------------------------------- robots.txt
# 按 RFC 9309 语义解析，而不是逐行正则：三个最容易误判的点——
#   1. 多个 User-agent 行共享同一组规则（组内第一个 UA 后面的会被逐行正则漏掉）
#   2. 具体 UA 组存在时通配符组整组失效（specificity，不看先后顺序）
#   3. 规则按最长路径匹配定胜负，同长时 Allow 胜出；支持 * 与 $ 通配符
# 所以「User-agent: * / Disallow: /」会封掉所有没有专属组的 AI 爬虫，
# 而「User-agent: GPTBot / Allow: /」会让 GPTBot 无视通配符组里的任何 Disallow。


def robots_parse(txt: str) -> list[dict]:
    """解析成 [{agents: [ua...], rules: [(allow, path)]}]。空 Disallow 值 = 全放行，不算规则。"""
    groups: list[dict] = []
    cur = None
    last_was_agent = False
    for raw in (txt or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            if cur is None or not last_was_agent:
                cur = {"agents": [], "rules": []}
                groups.append(cur)
            cur["agents"].append(value.lower())
            last_was_agent = True
        elif field in ("allow", "disallow"):
            last_was_agent = False
            if cur is not None and value:
                cur["rules"].append((field == "allow", value))
        else:
            last_was_agent = False
    return groups


def _robots_rule_rx(pattern: str) -> re.Pattern:
    rx = re.escape(pattern).replace(r"\*", ".*")
    if rx.endswith(r"\$"):
        rx = rx[:-2] + "$"
    return re.compile("^" + rx)


def robots_decision(groups: list[dict], ua: str, path: str) -> tuple[bool, str | None]:
    """某个爬虫（产品名，如 'GPTBot'）能否抓某路径。返回 (允许?, 命中的规则文本)。"""
    ua_l = (ua or "").lower()
    specific, spec_len, wildcard = None, -1, None
    for g in groups:
        for a in g["agents"]:
            if a == "*":
                if wildcard is None:
                    wildcard = g
            elif a and (a in ua_l or ua_l in a) and len(a) > spec_len:
                specific, spec_len = g, len(a)
    g = specific or wildcard
    if not g:
        return True, None
    path = path or "/"
    match_len, allowed, rule = -1, True, None
    for allow, pat in g["rules"]:
        if _robots_rule_rx(pat).match(path):
            plen = len(pat)
            # 最长匹配优先；同长时 Allow 胜出
            if plen > match_len or (plen == match_len and allow and not allowed):
                match_len, allowed = plen, allow
                rule = ("Allow: " if allow else "Disallow: ") + pat
    return allowed, rule


def same_site(a: str, b: str) -> bool:
    ha, hb = urlparse(a).netloc.lower(), urlparse(b).netloc.lower()
    ha, hb = ha.removeprefix("www."), hb.removeprefix("www.")
    return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)


# 跟踪参数：同一个页面挂不同参数会被当成多个 URL 重复抓，先剥掉
TRACKING_PARAMS = {"fbclid", "gclid", "dclid", "msclkid", "igshid", "mc_cid", "mc_eid",
                   "ref", "spm", "scm"}


def normalize_url(base: str, href: str) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    u = urljoin(base, href)
    u, _, _ = u.partition("#")
    parts = urlparse(u)
    if parts.query:
        qs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
              if not (k.lower().startswith("utm_") or k.lower() in TRACKING_PARAMS)]
        u = urlunparse(parts._replace(query=urlencode(qs)))
    return u


# ---------------------------------------------------------------- 正文抽取

_DROP_TAGS = ["script", "style", "noscript", "svg", "iframe", "form", "template"]
_BOILER = re.compile(r"(nav|header|footer|sidebar|menu|breadcrumb|cookie|banner|advert)", re.I)


def parse_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "lxml")


def main_text(soup: BeautifulSoup) -> str:
    # 恰好一个 <article> 才当正文容器；多个 <article>（列表页/分节页）时取 <main>
    # 整体，否则只保留第一节，数字/步骤/FAQ 全部丢失，正文评分被严重低估。
    articles = soup.find_all("article")
    body = (articles[0] if len(articles) == 1 else None) \
        or soup.find("main") or soup.body or soup
    clone = BeautifulSoup(str(body), "lxml")
    for t in clone(_DROP_TAGS):
        t.decompose()
    # 保留程式碼邊界，讓後續簡繁正規化能跳過程式碼內容。
    for t in clone.find_all("pre"):
        code = t.get_text("\n", strip=True)
        t.replace_with(f"\n```text\n{code}\n```\n")
    for t in clone.find_all("code"):
        code = t.get_text(" ", strip=True)
        t.replace_with(f"`{code}`")
    for t in clone.find_all(attrs={"class": _BOILER}):
        t.decompose()
    for t in clone.find_all(attrs={"id": _BOILER}):
        t.decompose()
    text = clone.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


CJK = re.compile(r"[一-鿿]")
KANA = re.compile(r"[぀-ヿ]")


def cjk_ratio(text: str) -> float:
    """中文字符占「中文字符 + 英文单词」的比例，用来判断这页到底是中文页还是英文页。"""
    cjk = len(CJK.findall(text))
    latin = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", text))
    total = cjk + latin
    return round(cjk / total, 3) if total else 0.0


def page_language(text: str, lang_attr: str = "") -> str:
    """返回 zh-Hans / zh-Hant / zh / ja / en / mixed / unknown。"""
    if len(text) < 80:
        la = (lang_attr or "").lower()
        kana = len(KANA.findall(text))
        return ("ja" if kana >= 2
                else chinese_script_profile(text, la)["language"]
                if la.startswith("zh") or CJK.search(text)
                else "en" if la.startswith("en")
                else "ja" if la.startswith("ja") else "unknown")
    # 日文：假名够多且占（假名 + 汉字）比例明显，避免把引用了一两个日语词的中文页判成 ja
    kana = len(KANA.findall(text))
    if kana >= 5 and kana / (kana + len(CJK.findall(text))) > 0.2:
        return "ja"
    r = cjk_ratio(text)
    return (chinese_script_profile(text, lang_attr)["language"] if r >= 0.5
            else "en" if r <= 0.1 else "mixed")


def word_count(text: str) -> int:
    """中英日混排统一折算成「词」：CJK 1.6 字算 1 词（接近中英信息密度比）。
    假名并入 CJK 统计：假名为主的日文页不算的话词数会被严重低估。"""
    cjk = len(CJK.findall(text)) + len(KANA.findall(text))
    latin = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", text))
    return int(cjk / 1.6 + latin)


def jsonld(soup: BeautifulSoup) -> list:
    out = []
    for tag in soup.find_all("script", type=lambda v: v and "ld+json" in v):
        try:
            data = json.loads(tag.string or "{}")
        except Exception:  # noqa: BLE001
            continue
        out.extend(data if isinstance(data, list) else [data])
    return out


def jsonld_types(blocks: list) -> list[str]:
    types = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        t = b.get("@type")
        if isinstance(t, list):
            types.extend(str(x) for x in t)
        elif t:
            types.append(str(t))
        for sub in b.get("@graph", []) or []:
            if isinstance(sub, dict) and sub.get("@type"):
                st = sub["@type"]
                types.extend(st if isinstance(st, list) else [st])
    return sorted(set(types))
