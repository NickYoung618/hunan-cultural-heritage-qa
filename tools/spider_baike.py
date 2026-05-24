"""
百度百科批量爬虫 v2.0：支持传入名单列表，自动爬取、清洗并归档。
输出路径：data/raw_html/（原始网页）、data/clean_txt/（纯净文本）
"""
import re
import time
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import quote

# --- 配置 ---
ROOT_DIR = Path(__file__).resolve().parent.parent
RAW_HTML_DIR = ROOT_DIR / "data" / "raw_html"
CLEAN_TXT_DIR = ROOT_DIR / "data" / "clean_txt"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

BAIKE_BASE = "https://baike.baidu.com/item/"


def build_url(name: str) -> str:
    """根据中文名构建百度百科 URL。"""
    return BAIKE_BASE + quote(name)


def fetch_html(url: str) -> str:
    """发起 GET 请求，返回 HTML 文本。"""
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    return resp.text


def extract_paragraphs(html: str) -> list[str]:
    """从百度百科页面中提取正文段落。"""
    soup = BeautifulSoup(html, "lxml")

    # 移除上标、引用、脚注标签
    for tag in soup.find_all(["sup", "span", "a"]):
        classes = tag.get("class") or []
        cls = " ".join(classes)
        if tag.name == "sup" or any(kw in cls for kw in ("sup", "reference", "footnote")):
            tag.decompose()

    paragraphs: list[str] = []
    seen: set[str] = set()

    selectors = [
        ".lemma-summary .para",
        ".lemma-summary",
        ".para",
        ".para_Markdown",
        ".lemma-content .para",
        "[class*='para']",
    ]

    for selector in selectors:
        for tag in soup.select(selector):
            text = tag.get_text(separator="\n", strip=True)
            if text and text not in seen:
                seen.add(text)
                paragraphs.append(text)

    # 回退策略：提取所有可见文本块
    if not paragraphs:
        for tag in soup.find_all(["p", "div"]):
            if tag.name == "div" and "para" not in " ".join(tag.get("class", [])):
                continue
            text = tag.get_text(separator="\n", strip=True)
            if text and len(text) > 30:
                paragraphs.append(text)

    return paragraphs


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
    text = text.strip()
    return text


def crawl_single(name: str, delay: float = 1.0) -> dict:
    """抓取单个词条，保存原始 HTML 和清洗后的纯文本。

    Args:
        name: 百度百科词条名称（中文）。
        delay: 请求间隔（秒），避免触发反爬。

    Returns:
        {"name": str, "status": "success"|"failed", "paragraphs": int, "error": str|None}
    """
    result: dict = {"name": name, "status": "failed", "paragraphs": 0, "error": None}
    url = build_url(name)
    safe_name = name.replace("/", "_").replace("\\", "_")

    try:
        print(f"  🌐 [{name}] 正在请求: {url}")
        html = fetch_html(url)
        print(f"  📥 [{name}] HTML 长度: {len(html)} 字符")

        # 保存原始 HTML
        RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
        raw_path = RAW_HTML_DIR / f"{safe_name}.html"
        raw_path.write_text(html, encoding="utf-8")
        print(f"  💾 [{name}] 原始 HTML → {raw_path}")

        # 提取并清洗段落
        paragraphs = extract_paragraphs(html)
        print(f"  📝 [{name}] 原始段落数: {len(paragraphs)}")

        cleaned = []
        for p in paragraphs:
            p = clean_text(p)
            if len(p) > 20:
                cleaned.append(p)

        # 保存清洗文本
        CLEAN_TXT_DIR.mkdir(parents=True, exist_ok=True)
        clean_path = CLEAN_TXT_DIR / f"{safe_name}.txt"
        clean_path.write_text("\n\n".join(cleaned), encoding="utf-8")
        print(f"  ✅ [{name}] 清洗文本 ({len(cleaned)} 段) → {clean_path}")

        result["status"] = "success"
        result["paragraphs"] = len(cleaned)

    except requests.HTTPError as e:
        result["error"] = f"HTTP {e.response.status_code if e.response else 'unknown'}"
        print(f"  ❌ [{name}] HTTP 错误: {result['error']}")
    except requests.RequestException as e:
        result["error"] = f"网络错误: {e}"
        print(f"  ❌ [{name}] 网络异常: {e}")
    except Exception as e:
        result["error"] = str(e)
        print(f"  ❌ [{name}] 未知错误: {e}")

    # 请求间隔，避免反爬
    if delay > 0:
        time.sleep(delay)

    return result


def crawl_batch(names: list[str], delay: float = 1.5) -> list[dict]:
    """批量抓取百度百科词条，返回汇总结果。

    Args:
        names: 词条名称列表，如 ["王夫之", "曾国藩", "周敦颐"]。
        delay: 每个请求之间的间隔（秒）。

    Returns:
        每个词条的抓取结果汇总列表。
    """
    print("=" * 60)
    print(f"🕷️  百度百科批量爬虫启动 | 目标: {len(names)} 个词条")
    print(f"📂 原始 HTML → {RAW_HTML_DIR}")
    print(f"📂 清洗文本 → {CLEAN_TXT_DIR}")
    print("=" * 60)

    results: list[dict] = []
    for i, name in enumerate(names, 1):
        print(f"\n[{i}/{len(names)}] 开始处理: {name}")
        result = crawl_single(name, delay=delay)
        results.append(result)

    # 汇总
    success_count = sum(1 for r in results if r["status"] == "success")
    total_paragraphs = sum(r["paragraphs"] for r in results)
    print("\n" + "=" * 60)
    print(f"🎉 批量抓取完成！成功: {success_count}/{len(names)}，共 {total_paragraphs} 段文本")
    print("=" * 60)

    for r in results:
        icon = "✅" if r["status"] == "success" else "❌"
        err = f" — {r['error']}" if r["error"] else ""
        print(f"  {icon} {r['name']}: {r['paragraphs']} 段{err}")

    return results


def main(names: list[str] | None = None) -> None:
    """主控函数：接受名单列表，自动完成抓取→清洗→归档全流程。

    Args:
        names: 词条名列表。若为 None，则使用默认的湖湘名人列表。
    """
    if names is None:
        names = ["王夫之", "王介之", "周敦颐", "曾国藩"]

    crawl_batch(names)


if __name__ == "__main__":
    # 默认名单：可直接修改此列表或通过 main() 传参调用
    default_names = ["王夫之", "王介之", "周敦颐", "曾国藩"]
    main(default_names)
