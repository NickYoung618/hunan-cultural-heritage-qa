"""
百科批量爬虫 v3.0：多源降级策略（维基百科 -> 百度搜索摘要 -> 百度百科）。
输出路径：data/raw_html/（原始网页）、data/clean_txt/（纯净文本）
"""
import re
import sys
import time
import random
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import quote

# Windows 控制台 UTF-8 输出
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# --- 配置 ---
ROOT_DIR = Path(__file__).resolve().parent.parent
RAW_HTML_DIR = ROOT_DIR / "data" / "raw_html"
CLEAN_TXT_DIR = ROOT_DIR / "data" / "clean_txt"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

WIKI_API = "https://zh.wikipedia.org/w/api.php"
BAIKE_BASE = "https://baike.baidu.com/item/"
BAIDU_SEARCH = "https://www.baidu.com/s"


def get_session() -> requests.Session:
    """创建带反爬配置的 Session。"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })
    return s


def clean_text(text: str) -> str:
    """清洗文本：去除引用标记、多余空白、HTML 残留。"""
    text = re.sub(r"\[\d+(?:[-,—]\d+)*\]", "", text)
    text = re.sub(r"\[[a-z]\](?:\[[a-z]\])*", "", text)
    text = re.sub(r"\[\d*\s*\]", "", text)
    text = re.sub(r"^\s*\]\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\[\d*\s*$", "", text, flags=re.MULTILINE)
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ============================================================
# 数据源 1：维基百科中文版
# ============================================================

def fetch_wikipedia(session: requests.Session, name: str) -> str | None:
    """通过维基百科 API 获取词条摘要。"""
    # 先搜索匹配的页面标题
    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": name,
        "srlimit": "3",
        "format": "json",
        "utf8": "1",
    }
    try:
        resp = session.get(WIKI_API, params=search_params, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        results = data.get("query", {}).get("search", [])
        if not results:
            return None

        # 找到最匹配的标题
        title = None
        for r in results:
            if name in r["title"]:
                title = r["title"]
                break
        if not title:
            title = results[0]["title"]

        # 获取摘要
        summary_params = {
            "action": "query",
            "titles": title,
            "prop": "extracts",
            "exintro": "true",
            "explaintext": "true",
            "exsectionformat": "plain",
            "format": "json",
            "utf8": "1",
        }
        resp = session.get(WIKI_API, params=summary_params, timeout=15)
        if resp.status_code != 200:
            return None
        pages = resp.json().get("query", {}).get("pages", {})
        for page_id, page_data in pages.items():
            extract = page_data.get("extract", "")
            if extract and len(extract) > 50:
                return extract
    except Exception as e:
        print(f"    [wiki] 异常: {e}")
    return None


def fetch_wikipedia_full(session: requests.Session, name: str) -> str | None:
    """通过维基百科 API 获取词条完整正文。"""
    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": name,
        "srlimit": "3",
        "format": "json",
        "utf8": "1",
    }
    try:
        resp = session.get(WIKI_API, params=search_params, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        results = data.get("query", {}).get("search", [])
        if not results:
            return None

        title = None
        for r in results:
            if name in r["title"]:
                title = r["title"]
                break
        if not title:
            title = results[0]["title"]

        # 获取完整正文
        params = {
            "action": "query",
            "titles": title,
            "prop": "extracts",
            "explaintext": "true",
            "exsectionformat": "plain",
            "format": "json",
            "utf8": "1",
        }
        resp = session.get(WIKI_API, params=params, timeout=15)
        if resp.status_code != 200:
            return None
        pages = resp.json().get("query", {}).get("pages", {})
        for page_id, page_data in pages.items():
            extract = page_data.get("extract", "")
            if extract and len(extract) > 100:
                return extract
    except Exception as e:
        print(f"    [wiki-full] 异常: {e}")
    return None


# ============================================================
# 数据源 2：百度搜索摘要
# ============================================================

def fetch_baidu_search(session: requests.Session, name: str) -> str | None:
    """从百度搜索结果中提取摘要文本。"""
    params = {"wd": name + " 百度百科", "rn": 5}
    try:
        time.sleep(random.uniform(1.0, 2.0))
        resp = session.get(BAIDU_SEARCH, params=params, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "lxml")

        # 提取搜索结果摘要
        abstracts = []
        for item in soup.select(".c-abstract, .c-span-last, .result"):
            text = item.get_text(strip=True)
            if text and len(text) > 30:
                abstracts.append(clean_text(text))

        if abstracts:
            return "\n\n".join(abstracts[:5])
    except Exception as e:
        print(f"    [baidu] 异常: {e}")
    return None


# ============================================================
# 数据源 3：百度百科（降级尝试）
# ============================================================

def fetch_baike(session: requests.Session, name: str) -> str | None:
    """尝试爬取百度百科页面。"""
    url = BAIKE_BASE + quote(name)
    try:
        time.sleep(random.uniform(2.0, 4.0))
        resp = session.get(url, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            return None
        html = resp.text
        if "百度安全验证" in html or "wappass.baidu.com" in html:
            return None

        soup = BeautifulSoup(html, "lxml")
        for tag in soup.find_all(["sup"]):
            tag.decompose()

        paragraphs = []
        seen = set()
        for selector in [".lemma-summary .para", ".lemma-summary", ".para", ".para_Markdown"]:
            for t in soup.select(selector):
                text = t.get_text(separator="\n", strip=True)
                if text and text not in seen:
                    seen.add(text)
                    paragraphs.append(clean_text(text))

        if paragraphs:
            return "\n\n".join(p for p in paragraphs if len(p) > 20)
    except Exception as e:
        print(f"    [baike] 异常: {e}")
    return None


# ============================================================
# 主流程
# ============================================================

def crawl_single(session: requests.Session, name: str, delay: float = 2.0) -> dict:
    """抓取单个词条，多源降级尝试。"""
    result: dict = {"name": name, "status": "failed", "paragraphs": 0, "error": None, "source": None}
    safe_name = name.replace("/", "_").replace("\\", "_")

    sources = [
        ("wikipedia-full", fetch_wikipedia_full),
        ("wikipedia", fetch_wikipedia),
        ("baike", fetch_baike),
        ("baidu-search", fetch_baidu_search),
    ]

    content = None
    used_source = None

    for source_name, fetcher in sources:
        print(f"  [{source_name}] [{name}] 尝试中...")
        text = fetcher(session, name)
        if text and len(text) > 50:
            content = text
            used_source = source_name
            print(f"  [{source_name}] [{name}] 成功! 长度: {len(text)} 字符")
            break
        else:
            print(f"  [{source_name}] [{name}] 未获取到内容")

    if not content:
        result["error"] = "所有数据源均失败"
        print(f"  [FAIL] [{name}] 所有数据源均失败")
        time.sleep(delay)
        return result

    # 清洗并保存
    cleaned = clean_text(content)
    if len(cleaned) < 20:
        result["error"] = "内容过短"
        print(f"  [FAIL] [{name}] 内容过短 ({len(cleaned)} 字)")
        time.sleep(delay)
        return result

    # 保存原始内容
    RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_HTML_DIR / f"{safe_name}.txt"
    raw_path.write_text(content, encoding="utf-8")

    # 保存清洗文本
    CLEAN_TXT_DIR.mkdir(parents=True, exist_ok=True)
    clean_path = CLEAN_TXT_DIR / f"{safe_name}.txt"
    clean_path.write_text(cleaned, encoding="utf-8")

    # 统计段落数
    para_count = len([p for p in cleaned.split("\n\n") if p.strip()])
    print(f"  [OK] [{name}] {para_count} 段 ({used_source}) -> {clean_path}")

    result["status"] = "success"
    result["paragraphs"] = para_count
    result["source"] = used_source

    time.sleep(delay)
    return result


def crawl_batch(names: list[str], delay: float = 2.0) -> list[dict]:
    """批量抓取词条，返回汇总结果。"""
    print("=" * 60)
    print(f"百科批量爬虫启动 | 目标: {len(names)} 个词条")
    print(f"原始内容 -> {RAW_HTML_DIR}")
    print(f"清洗文本 -> {CLEAN_TXT_DIR}")
    print("=" * 60)

    session = get_session()

    results: list[dict] = []
    for i, name in enumerate(names, 1):
        print(f"\n[{i}/{len(names)}] 开始处理: {name}")
        result = crawl_single(session, name, delay=delay)
        results.append(result)

    # 汇总
    success_count = sum(1 for r in results if r["status"] == "success")
    total_paragraphs = sum(r["paragraphs"] for r in results)
    print("\n" + "=" * 60)
    print(f"批量抓取完成! 成功: {success_count}/{len(names)}，共 {total_paragraphs} 段文本")
    print("=" * 60)

    for r in results:
        icon = "[OK]" if r["status"] == "success" else "[FAIL]"
        src = f" ({r['source']})" if r.get("source") else ""
        err = f" -- {r['error']}" if r["error"] else ""
        print(f"  {icon} {r['name']}: {r['paragraphs']} 段{src}{err}")

    return results


def main(names: list[str] | None = None) -> None:
    """主控函数。"""
    if names is None:
        names = ["王夫之", "王介之", "周敦颐", "曾国藩"]
    crawl_batch(names)


if __name__ == "__main__":
    default_names = [
        "王夫之", "周敦颐", "曾国藩", "左宗棠", "魏源",
        "谭嗣同", "黄兴", "蔡锷", "毛泽东",
        "岳麓书院", "湘军", "经世致用"
    ]
    main(default_names)
