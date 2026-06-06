"""
湖湘文化数据集清洗脚本 v2.0：
兼容维基百科（较干净）和百度百科（噪声多）两种数据源。
输入：data/raw_html/*.txt
输出：data/clean_txt/*.txt（覆盖）
"""
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT_DIR / "data" / "raw_html"
OUT_DIR = ROOT_DIR / "data" / "clean_txt"

# 百度百科导航/页脚噪声关键词
HEADER_NOISE = [
    "网页新闻贴吧知道网盘图片视频地图文库资讯采购百科",
    "百度首页", "华文行楷卍", "消息", "商城", "设置",
    "进入词条全站搜索国际版帮助", "播报编辑讨论", "播报编辑收藏赞",
    "播报", "编辑", "讨论", "收藏赞", "上传视频",
    "首页", "历史上的今天", "百科冷知识", "图解百科", "秒懂百科",
    "懂啦", "秒懂本尊答", "秒懂大师说", "秒懂看瓦特", "秒懂五千年",
    "秒懂全视界", "特色百科", "动态百科", "数字博物馆", "非遗百科",
    "艺术百科", "科学百科", "知识专题", "加入百科", "新人成长",
    "进阶成长", "任务广场", "百科团队", "校园团", "分类达人团",
    "热词团", "繁星团", "蝌蚪团", "权威合作", "合作模式",
    "常见问题", "联系方式", "个人中心",
    "史记2025", "观千年", "中国航天", "食品百科", "云游博物馆",
    "数字文物守护计划",
]

# 视频标题/推荐内容
VIDEO_TITLES = [
    "如何游览", "走进中国", "千年学府", "实地探访", "保姆级详细攻略",
    "带您走进", "三湘大地", "圆梦湖南", "游览千年", "千年庭院",
    "千年岳麓", "名气虽大", "中国四大书院之", "打卡", "一砖一瓦",
    "查看全部", "点击体验", "订阅",
]

FOOTER_NOISE = [
    "词条统计", "浏览次数", "编辑次数", "历史版本", "最近更新",
    "突出贡献榜", "相关搜索", "新手上路", "成长任务", "编辑入门",
    "编辑规则", "本人编辑", "我有疑问", "内容质疑", "在线客服",
    "官方贴吧", "意见反馈", "投诉建议", "举报不良信息", "未通过词条申诉",
    "投诉侵权信息", "封禁查询与解封", "使用百度前必读", "百科协议",
    "隐私政策", "百度百科合作平台", "京ICP证", "京公网安备",
    "订阅词条", "可以前往个人中心", "当词条有内容变更时",
    "当词条有热门讨论时", "确认订阅", "是否取消订阅更新",
    "取消订阅后", "再想想", "展开全部", "分享你的世界查看更多",
    "人已订阅", "词条内容更新", "词条热门讨论",
]

# 视频标题/时长模式
VIDEO_PATTERN = re.compile(r"^\d{2}:\d{2}$")
# 图片说明
IMAGE_CAPTION_PATTERNS = [
    re.compile(r".*塑像$"), re.compile(r".*画像$"), re.compile(r".*照片$"),
    re.compile(r".*图片.*张"), re.compile(r".*概述图"),
    re.compile(r"圆梦.*走进"), re.compile(r"千年学府.*攻略"),
    re.compile(r"游览.*学府"), re.compile(r"走进.*学府"),
    re.compile(r"实地探访"), re.compile(r"保姆级详细攻略"),
    re.compile(r"带您走进"), re.compile(r"三湘大地.*原因"),
]
# 用户评论/作者标签
COMMENT_PATTERNS = [
    re.compile(r".*领域爱好者$"), re.compile(r".*领域创作者$"),
    re.compile(r".*期刊主编.*"), re.compile(r".*文史作家$"),
    re.compile(r".*优质.*创作者$"), re.compile(r"AI故事创作.*"),
]
# 拼音标注
PINYIN_PATTERN = re.compile(r"\[[a-züāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ\s]+\]")
# 引用标记
REF_PATTERN = re.compile(r"\[\d+\]")
# 参考文献行
REFERENCE_LINE = re.compile(r"^\d+.*[．.].*引用日期")


def detect_source(text: str) -> str:
    """检测数据来源：wikipedia 或 baike。"""
    baike_markers = ["播报", "编辑", "百度百科", "进入词条", "播报编辑讨论"]
    wiki_markers = ["维基百科", "Wikipedia", "===", "===="]
    baike_count = sum(1 for m in baike_markers if m in text[:2000])
    wiki_count = sum(1 for m in wiki_markers if m in text[:2000])
    if baike_count >= 2:
        return "baike"
    if wiki_count >= 1:
        return "wikipedia"
    # 默认按百度百科处理（更严格的清洗）
    return "baike"


def clean_wikipedia(text: str) -> str:
    """清洗维基百科文本（本身较干净，只需轻度处理）。"""
    # 去除引用标记 [1] [a] 等
    text = re.sub(r"\[\d+(?:[-,—]\d+)*\]", "", text)
    text = re.sub(r"\[[a-z]\](?:\[[a-z]\])*", "", text)
    text = re.sub(r"\[\d*\s*\]", "", text)
    # 去除多余空白
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 去除空段落
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue
        cleaned.append(stripped)
    # 合并连续空行
    result = []
    prev_empty = False
    for line in cleaned:
        if line == "":
            if not prev_empty:
                result.append("")
                prev_empty = True
        else:
            result.append(line)
            prev_empty = False
    # 去首尾空行
    while result and result[0] == "":
        result.pop(0)
    while result and result[-1] == "":
        result.pop()
    return "\n".join(result)


def clean_baike_fragment(text: str) -> str:
    """清洗百度百科碎片文本（短内容，如岳麓书院、湘军等摘要）。"""
    # 去除百度百科特有标记
    text = re.sub(r"百度百科[]*", "", text)
    text = re.sub(r"[播报暂停]+", "", text)
    text = re.sub(r"播报", "", text)
    text = re.sub(r"暂停", "", text)
    text = re.sub(r"编辑", "", text)
    text = re.sub(r"讨论", "", text)
    text = re.sub(r"收藏赞", "", text)
    # 去除 "xxx-来源名" 格式的标题行噪声
    text = re.sub(r"^[^\n]{1,15}-(?:百度百科|湖南简况|官方书院简介)[^\n]*\n?", "", text)
    # 去除来源标注
    text = re.sub(r"(?:湖南省人民政府|中国关键词|百度知道)[^\n]*", "", text)
    # 去除引用标记
    text = re.sub(r"\[\d+\]", "", text)
    # 去除多余空白
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 去除过短的碎片行（<15字且不是段落开头）
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue
        # 保留有实质内容的行
        if len(stripped) >= 15 or re.match(r"^[（(（]", stripped):
            cleaned.append(stripped)
    # 去首尾空行
    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return "\n\n".join(cleaned)


def is_noise(line: str) -> bool:
    """判断一行是否为噪声。"""
    stripped = line.strip()
    if not stripped:
        return False  # 空行保留，后面统一处理

    # 导航噪声
    for kw in HEADER_NOISE:
        if stripped == kw or stripped.startswith(kw):
            return True

    # 页脚噪声
    for kw in FOOTER_NOISE:
        if kw in stripped:
            return True

    # 视频时长
    if VIDEO_PATTERN.match(stripped):
        return True

    # 图片说明
    for p in IMAGE_CAPTION_PATTERNS:
        if p.match(stripped):
            return True

    # 用户评论标签
    for p in COMMENT_PATTERNS:
        if p.match(stripped):
            return True

    # 参考文献行（保留但标记）
    # 不删，后面单独处理

    # 纯标点或极短无意义行
    if len(stripped) <= 1 and stripped in "。，、；：？！—…·＂″″媖":
        return True

    # 百度百科特有的杂项
    noise_exact = [
        "百度百科", "进入词条", "播报", "编辑",
        "次历史版本", "人已订阅", "目录",
        "订阅", "查看全部", "点击体验",
        "人物关系", "主要作品", "人物成就", "奇闻异事",
        "真理触手可及", "原文在线阅读",
    ]
    if stripped in noise_exact:
        return True

    # "展开X个同名词条" 类
    if re.match(r"^展开\d*个?同名词条$", stripped):
        return True

    # 视频推荐标题
    for kw in VIDEO_TITLES:
        if stripped.startswith(kw) and len(stripped) < 80:
            return True

    # 含 #标签 的视频标题行
    if "#" in stripped and len(stripped) < 80:
        return True

    # 含"！"的短宣传语（非正文）
    if "！" in stripped and len(stripped) < 40:
        return True

    # 纯数字行（点赞数、浏览数等）
    if re.match(r"^\d{1,7}$", stripped):
        return True

    # 极短的碎片（<5字，且不是年份/朝代开头）
    if len(stripped) < 5 and not re.match(r"^[元明清民国天崇顺康雍乾隆嘉道咸同光宣万隆永]", stripped):
        return True

    return False


def clean_text(text: str) -> str:
    """清洗单行文本。"""
    # 去拼音标注
    text = PINYIN_PATTERN.sub("", text)
    # 去引用标记 [1] [2] 等
    text = REF_PATTERN.sub("", text)
    # 去多余空白
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def clean_file(raw_path: Path) -> str:
    """清洗单个文件，返回清洗后的文本。"""
    lines = raw_path.read_text(encoding="utf-8").splitlines()

    # 第一步：去除头部噪声（前 N 行中找到正文开始位置）
    start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        # 找到词条标题行（通常是 "百度百科\n词条名\n进入词条" 之后）
        if stripped and not is_noise(line):
            # 额外检查：跳过纯标题行（词条名本身）
            if len(stripped) > 15 or (i > 0 and "播报" in lines[i - 1]):
                start = i
                break

    # 第二步：去除尾部噪声
    end = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped and not is_noise(lines[i]):
            # 找到最后一个非噪声行
            end = i + 1
            break

    # 第三步：逐行清洗
    cleaned = []
    seen = set()
    for line in lines[start:end]:
        if is_noise(line):
            continue
        text = clean_text(line)
        if not text:
            # 保留空行作为段落分隔
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue
        # 参考文献行：保留但精简
        if REFERENCE_LINE.match(text):
            if text not in seen:
                seen.add(text)
                cleaned.append(text)
            continue
        # 去重
        if text not in seen:
            seen.add(text)
            cleaned.append(text)

    # 第四步：合并碎片行（百度百科复制时链接文字被单独成行）
    merged = merge_fragments(cleaned)

    # 第五步：清理多余空行
    result = []
    prev_empty = False
    for line in merged:
        if line == "":
            if not prev_empty:
                result.append("")
                prev_empty = True
        else:
            result.append(line)
            prev_empty = False

    # 去掉首尾空行
    while result and result[0] == "":
        result.pop(0)
    while result and result[-1] == "":
        result.pop()

    return "\n".join(result)


def merge_fragments(lines: list[str]) -> list[str]:
    """合并被链接打断的碎片行。

    例如：
        "其父王朝聘50岁，母谭氏47岁。"
        "王夫之塑像"  <- 图片说明，删
        "天启"
        "二年（1622年）"  <- 应合并为 "天启二年（1622年）"
    """
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line:
            result.append(line)
            i += 1
            continue

        # 检查是否是碎片（短行 + 下一行是年份/时间开头）
        if i + 1 < len(lines) and lines[i + 1]:
            next_line = lines[i + 1]
            # 模式：上一行以朝代/年号结尾，下一行以"X年"开头
            if re.match(r"^(天启|崇祯|顺治|康熙|雍正|乾隆|嘉庆|道光|咸丰|同治|光绪|宣统|民国|万历|隆庆|永历)$", line.strip()):
                merged = line.strip() + next_line.strip()
                result.append(merged)
                i += 2
                continue
            # 模式：上一行是短文本（<10字），下一行是年份开头
            if len(line.strip()) < 10 and re.match(r"^[元明清民国天崇顺康雍乾隆嘉道咸同光宣].*年", next_line.strip()):
                merged = line.strip() + next_line.strip()
                result.append(merged)
                i += 2
                continue

        result.append(line)
        i += 1

    return result


def main():
    if not RAW_DIR.exists():
        print(f"原始数据目录不存在: {RAW_DIR}")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(RAW_DIR.glob("*.txt"))

    if not files:
        print(f"目录为空: {RAW_DIR}")
        return

    print("=" * 60)
    print(f"数据清洗 v2.0 | 共 {len(files)} 个文件")
    print(f"输入: {RAW_DIR}")
    print(f"输出: {OUT_DIR}")
    print("=" * 60)

    for f in files:
        raw_text = f.read_text(encoding="utf-8")
        raw_lines = len(raw_text.splitlines())

        # 检测数据源类型，选择清洗策略
        source = detect_source(raw_text)
        if source == "wikipedia":
            cleaned = clean_wikipedia(raw_text)
            method = "wiki轻洗"
        else:
            # 百度百科内容：短文件用碎片清洗，长文件用深度清洗
            if raw_lines <= 10:
                cleaned = clean_baike_fragment(raw_text)
                method = "baike碎片"
            else:
                cleaned = clean_file(f)
                method = "baike深洗"

        clean_lines = len(cleaned.splitlines())

        out_path = OUT_DIR / f.name
        out_path.write_text(cleaned, encoding="utf-8")

        ratio = (1 - clean_lines / raw_lines) * 100 if raw_lines else 0
        print(f"  [{method}] {f.name}: {raw_lines} -> {clean_lines} 行 (去除 {ratio:.0f}%)")

    print(f"\n完成! 清洗后文件 -> {OUT_DIR}")


if __name__ == "__main__":
    main()
