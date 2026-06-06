"""
湖湘文化 GraphRAG Web 界面 v3.0 —— Gemini 风格暗色主题。
左侧：智能对话面板 | 右侧：Plotly 交互式知识图谱关系图 + Cypher 查询
"""
import re
import sys
import time
from typing import Any, Generator

# 屏蔽 Windows 上浏览器断连时的 ConnectionResetError 噪音日志
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

try:
    import gradio as gr
    GRADIO_AVAILABLE = True
except ImportError:
    gr = None  # type: ignore
    GRADIO_AVAILABLE = False

import networkx as nx
import plotly.graph_objects as go

from rag_agent import GraphRAGExpert

# ---------------------------------------------------------------------------
# 视觉主题 — Gemini 暗色风格
# ---------------------------------------------------------------------------

CSS = """
/* ===== 全局 ===== */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

.gradio-container {
    max-width: 100% !important;
    font-family: "Inter", "Google Sans", "Segoe UI", "Microsoft YaHei", sans-serif !important;
    background: #131314 !important;
    color: #e8e8e8 !important;
}
footer { visibility: hidden }

body, .gradio-container {
    background: #131314 !important;
}

/* ===== 标题区域 ===== */
.main-title h1 {
    background: linear-gradient(135deg, #4a9ff5 0%, #9b6dff 40%, #e86cdc 100%) !important;
    -webkit-background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
    background-clip: text !important;
    font-size: 1.8em !important;
    font-weight: 600 !important;
    letter-spacing: -0.02em !important;
    text-align: left !important;
    margin-bottom: 4px !important;
}
.subtitle p {
    color: #9aa0a6 !important;
    font-size: 0.85em !important;
    font-weight: 400 !important;
    text-align: left !important;
}

/* ===== Chatbot 容器 ===== */
.chatbot-container {
    border-radius: 0 !important;
    border: none !important;
    background: transparent !important;
    min-height: 480px !important;
    overflow-y: auto !important;
    position: relative !important;
    z-index: 1 !important;
}
.chatbot-container > div {
    background: transparent !important;
}
.chatbot-container .bubble-wrap .bubble {
    border-radius: 18px !important;
    padding: 12px 18px !important;
    font-size: 0.925em !important;
    line-height: 1.55 !important;
    max-width: 85% !important;
}
.chatbot-container .bubble-wrap.user .bubble {
    background: #282a2d !important;
    color: #e8e8e8 !important;
    border: 1px solid #3c4043 !important;
    border-radius: 18px 18px 4px 18px !important;
}
.chatbot-container .bubble-wrap.bot .bubble {
    background: transparent !important;
    color: #e8e8e8 !important;
    border: none !important;
    border-radius: 4px 18px 18px 18px !important;
    padding-left: 0 !important;
}
.chatbot-container .avatar { display: none !important; }
.chatbot-container .message-row { margin-bottom: 16px !important; }

.chatbot-container ::-webkit-scrollbar { width: 6px; }
.chatbot-container ::-webkit-scrollbar-track { background: transparent; }
.chatbot-container ::-webkit-scrollbar-thumb { background: #3c4043; border-radius: 3px; }

/* ===== 输入区域 ===== */
.input-row { gap: 10px !important; align-items: center !important; }
.input-row input, .input-row textarea {
    background: #1e1f20 !important;
    border: 1px solid #3c4043 !important;
    border-radius: 24px !important;
    color: #e8e8e8 !important;
    padding: 12px 20px !important;
    font-size: 0.95em !important;
    transition: border-color 0.25s ease, box-shadow 0.25s ease !important;
    line-height: 1.4 !important;
}
.input-row input:focus, .input-row textarea:focus {
    border-color: #8ab4f8 !important;
    box-shadow: 0 0 0 2px rgba(138, 180, 248, 0.15) !important;
    outline: none !important;
}
.input-row input::placeholder, .input-row textarea::placeholder {
    color: #6b7280 !important;
}
.input-row button {
    background: #8ab4f8 !important;
    color: #131314 !important;
    border: none !important;
    border-radius: 50% !important;
    width: 42px !important;
    height: 42px !important;
    min-width: 42px !important;
    padding: 0 !important;
    font-weight: 600 !important;
    font-size: 1em !important;
    cursor: pointer !important;
    transition: background 0.2s ease, box-shadow 0.2s ease !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}
.input-row button:hover {
    background: #aecbfa !important;
    box-shadow: 0 0 14px rgba(138, 180, 248, 0.4) !important;
}

.secondary-row button {
    background: transparent !important;
    color: #9aa0a6 !important;
    border: 1px solid #3c4043 !important;
    border-radius: 20px !important;
    padding: 6px 18px !important;
    font-size: 0.8em !important;
    cursor: pointer !important;
    transition: background 0.2s ease !important;
}
.secondary-row button:hover { background: #282a2d !important; color: #e8e8e8 !important; }

/* ===== 建议卡片网格 ===== */
.suggestion-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin: 8px 0 16px 0;
}
.suggestion-card {
    background: #1e1f20;
    border: 1px solid #2d2f31;
    border-radius: 12px;
    padding: 14px 16px;
    cursor: pointer;
    transition: background 0.2s ease, border-color 0.2s ease;
    font-size: 0.85em;
    color: #e8e8e8;
    line-height: 1.4;
}
.suggestion-card:hover { background: #282a2d; border-color: #4a9ff5; }

/* ===== 右侧面板卡片 ===== */
.panel-card {
    background: #1e1f20;
    border: 1px solid #2d2f31;
    border-radius: 16px;
    padding: 20px;
    margin-bottom: 14px;
}
.panel-card h3 {
    color: #e8e8e8;
    font-size: 1em;
    font-weight: 500;
    margin: 0 0 12px 0;
    letter-spacing: -0.01em;
}

/* ===== 统计徽章 ===== */
.stat-badge {
    display: inline-block;
    padding: 5px 12px;
    border-radius: 16px;
    font-size: 0.78em;
    font-weight: 500;
    margin: 3px;
    letter-spacing: 0.01em;
}
.stat-entities { background: rgba(138, 180, 248, 0.15); color: #8ab4f8; }
.stat-relations { background: rgba(232, 108, 220, 0.12); color: #e86cdc; }
.stat-empty { background: rgba(154, 160, 166, 0.1); color: #9aa0a6; }

/* ===== Cypher 代码区 ===== */
.cypher-box { border-radius: 12px !important; overflow: hidden !important; }
.cypher-box textarea {
    font-family: "JetBrains Mono", "Fira Code", "Consolas", monospace !important;
    font-size: 12px !important;
    background: #0d0d0e !important;
    color: #c0caf5 !important;
    border: 1px solid #2d2f31 !important;
    border-radius: 10px !important;
    padding: 14px !important;
    line-height: 1.6 !important;
}

/* ===== Accordion ===== */
.accordion { background: transparent !important; border: none !important; }
.accordion > .label-wrap {
    background: #1e1f20 !important;
    border: 1px solid #2d2f31 !important;
    border-radius: 12px !important;
    padding: 12px 16px !important;
    color: #9aa0a6 !important;
    font-size: 0.85em !important;
    cursor: pointer !important;
    transition: background 0.2s ease !important;
}
.accordion > .label-wrap:hover { background: #282a2d !important; }

.panel-card .prose, .panel-card p { color: #9aa0a6 !important; font-size: 0.85em !important; line-height: 1.5 !important; }

/* ===== 功能标签 ===== */
.feature-tag {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    background: rgba(138, 180, 248, 0.1);
    color: #8ab4f8;
    font-size: 0.75em;
    font-weight: 500;
    margin-right: 6px;
    margin-bottom: 4px;
}

/* ===== 防止右面板覆盖左面板 ===== */
.gradio-container .gr-row {
    overflow: visible !important;
}
.gradio-container .gr-column {
    overflow: visible !important;
}

.footer-note {
    color: #5f6368;
    font-size: 0.72em;
    text-align: center;
    margin-top: 18px;
    padding-bottom: 12px;
}
"""

# ---------------------------------------------------------------------------
# 配色映射 — 实体类型 → 颜色（暗色版）
# ---------------------------------------------------------------------------

TYPE_COLORS = {
    "人物": "#8ab4f8",
    "作品": "#fdd663",
    "地点": "#81c995",
    "事件": "#f28b82",
    "概念": "#c58af9",
    "时间": "#9aa0a6",
    "学派": "#f493b5",
    "官职": "#78d9ec",
}
FALLBACK_COLOR = "#6b7280"

# ---------------------------------------------------------------------------
# 后端封装
# ---------------------------------------------------------------------------

class WebUIBackend:
    """Web UI 后端封装，管理 GraphRAGExpert 实例。"""

    def __init__(self) -> None:
        self.expert: GraphRAGExpert | None = None

    def get_expert(self) -> GraphRAGExpert:
        if self.expert is None:
            self.expert = GraphRAGExpert()
        return self.expert

    def close(self) -> None:
        if self.expert:
            self.expert.close()
            self.expert = None


backend = WebUIBackend()


# ---------------------------------------------------------------------------
# 图谱可视化引擎 (Plotly 暗色版)
# ---------------------------------------------------------------------------

def _extract_node_info(node: Any) -> dict[str, str]:
    """从 Neo4j 节点对象/字典中提取 name 和 type 信息。"""
    if hasattr(node, "_properties"):
        props = node._properties
        labels = list(node.labels) if hasattr(node, "labels") else []
        return {
            "name": props.get("name", str(node)),
            "type": labels[0] if labels else props.get("type", "未知"),
        }
    if isinstance(node, dict):
        return {
            "name": node.get("name", str(node)),
            "type": node.get("type", ""),
        }
    return {"name": str(node), "type": ""}


def _extract_rel_info(rel: Any) -> str:
    """从 Neo4j 关系对象中提取关系类型名称。"""
    if hasattr(rel, "type"):
        return rel.type
    if isinstance(rel, dict):
        return rel.get("type", rel.get("relation", str(rel)))
    if isinstance(rel, str):
        return rel
    return "关联"


def build_evidence_graph(evidence: list[dict]) -> go.Figure | None:
    """将图谱检索证据转换为 Plotly 交互式关系图（暗色主题）。"""
    if not evidence or not isinstance(evidence, list):
        return None

    G = nx.Graph()
    node_set: dict[str, dict] = {}

    for record in evidence:
        if not isinstance(record, dict):
            continue

        # 👇 核心修复：精准识别新版 Cypher 的扁平化返回结构
        if "a_name" in record and "b_name" in record:
            a_info = {
                "name": record.get("a_name") or "未知",
                "type": record.get("a_type") or "未知"
            }
            b_info = {
                "name": record.get("b_name") or "未知",
                "type": record.get("b_type") or "未知"
            }
            rel_label = record.get("relation") or "关联"

        # 兼容 source/target 格式（GraphRetriever 返回）
        elif "source" in record and "target" in record:
            a_info = {
                "name": record.get("source") or "未知",
                "type": record.get("source_type") or "未知"
            }
            b_info = {
                "name": record.get("target") or "未知",
                "type": record.get("target_type") or "未知"
            }
            rel_label = record.get("relation") or "关联"

        # 兼容旧版的 (a, r, b) 节点对象返回结构
        elif "a" in record and "b" in record:
            a = record.get("a")
            r = record.get("r")
            b = record.get("b")
            a_info = _extract_node_info(a)
            b_info = _extract_node_info(b)
            rel_label = _extract_rel_info(r) if r else "关联"

        else:
            continue  # 结构不匹配则跳过

        # 获取节点名字
        node_a_id = a_info["name"]
        node_b_id = b_info["name"]

        # 排除把长文本误认为节点名（加上安全锁）
        if len(node_a_id) > 20 or len(node_b_id) > 20:
            continue

        node_set[node_a_id] = a_info
        node_set[node_b_id] = b_info
        G.add_edge(node_a_id, node_b_id, label=rel_label)

    if not G.nodes:
        return None

    # ... 下面保留原有的 pos = nx.spring_layout 绘图代码不变 ...

    pos = nx.spring_layout(G, k=2.5, iterations=50, seed=42)

    edge_traces = []
    edge_annotations = []
    for u, v, data in G.edges(data=True):
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_traces.append(
            go.Scatter(
                x=[x0, x1, None],
                y=[y0, y1, None],
                mode="lines",
                line=dict(width=1.0, color="#3c4043"),
                hoverinfo="none",
                showlegend=False,
            )
        )
        mid_x, mid_y = (x0 + x1) / 2, (y0 + y1) / 2
        edge_annotations.append(
            dict(
                x=mid_x, y=mid_y, xref="x", yref="y",
                text=data.get("label", ""),
                showarrow=False,
                font=dict(size=8, color="#9aa0a6"),
                bgcolor="rgba(30,31,32,0.9)",
                borderpad=2,
            )
        )

    node_x, node_y, node_text, node_hover, node_colors = [], [], [], [], []
    for node_id in G.nodes:
        info = node_set.get(node_id, {"name": node_id, "type": ""})
        x, y = pos[node_id]
        node_x.append(x)
        node_y.append(y)
        node_text.append(info["name"])
        node_hover.append(f"<b>{info['name']}</b><br>类型：{info['type']}")
        node_colors.append(TYPE_COLORS.get(info["type"], FALLBACK_COLOR))

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        text=node_text,
        textposition="top center",
        textfont=dict(size=10, color="#e8e8e8"),
        hovertext=node_hover,
        hoverinfo="text",
        marker=dict(size=20, color=node_colors, line=dict(width=1.5, color="#1e1f20")),
        showlegend=False,
    )

    fig = go.Figure(
        data=edge_traces + [node_trace],
        layout=go.Layout(
            title=None,
            paper_bgcolor="#1e1f20",
            plot_bgcolor="#1e1f20",
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            annotations=edge_annotations,
            dragmode="pan",
            height=440,
        ),
    )

    seen_types = set()
    for info in node_set.values():
        t = info["type"]
        if t and t not in seen_types:
            seen_types.add(t)
            fig.add_trace(
                go.Scatter(
                    x=[None], y=[None],
                    mode="markers",
                    marker=dict(size=10, color=TYPE_COLORS.get(t, FALLBACK_COLOR), line=dict(width=1, color="#1e1f20")),
                    name=t,
                    showlegend=True,
                )
            )

    fig.update_layout(
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="left", x=0,
            font=dict(size=10, color="#9aa0a6"),
            bgcolor="rgba(30,31,32,0.9)",
        ),
    )
    return fig


# ---------------------------------------------------------------------------
# 问答处理（流式）
# ---------------------------------------------------------------------------

def chat_stream(
    message: str,
) -> Generator[tuple[str, str, go.Figure, str], None, None]:
    """流式问答生成器：逐个 yield (answer_so_far, cypher, fig, stats_html)。"""
    if not message or not message.strip():
        yield "请输入问题。", "", _empty_graph(), _empty_stats()
        return

    expert = backend.get_expert()

    # ---- 路径查询（非流式，一次返回） ----
    path_match = re.match(
        r"shortest\s*\(\s*(.+?)\s*,\s*(.+?)\s*\)", message.strip(), re.IGNORECASE
    )
    if path_match:
        t_start = time.time()
        name1 = path_match.group(1).strip()
        name2 = path_match.group(2).strip()
        answer = expert.query_shortest_path(name1, name2)
        path_data = expert.analytics.shortest_path(name1, name2)
        fig = _path_to_graph(path_data)
        stats = _summarize_evidence(fig)
        elapsed = round(time.time() - t_start, 2)
        answer += f"\n\n> ⏱️ 耗时 {elapsed} 秒"
        yield answer, "（路径查询，非 Cypher 生成）", fig, stats
        return

    # ---- 图谱报告（非流式，一次返回） ----
    if message.strip().lower() in ("/report", "/分析", "/analytics"):
        t_start = time.time()
        report = expert.analytics.full_report()
        report_text = _format_report(report)
        fig = _report_to_graph(report)
        stats = _summarize_evidence(fig)
        elapsed = round(time.time() - t_start, 2)
        report_text += f"\n\n> ⏱️ 耗时 {elapsed} 秒"
        yield report_text, "（图谱分析报告，非问答生成）", fig, stats
        return

    # ---- 自然语言问答（流式打字机效果） ----
    answer_so_far = ""
    cypher = ""
    fig = _empty_graph()
    stats = _empty_stats()
    elapsed_seconds = 0.0

    for event in expert.ask_stream(user_question=message.strip()):
        if event["type"] == "cypher":
            cypher = event["data"]
        elif event["type"] == "evidence":
            evidence = event["data"]
            fig = build_evidence_graph(evidence) or _empty_graph()
            stats = _summarize_evidence(fig)
        elif event["type"] == "token":
            answer_so_far += event["data"]
            yield answer_so_far, cypher, fig, stats
        elif event["type"] == "done":
            elapsed_seconds = event.get("elapsed_seconds", 0)

    if answer_so_far:
        answer_so_far += f"\n\n> ⏱️ 耗时 {elapsed_seconds} 秒"
        yield answer_so_far, cypher, fig, stats
    else:
        yield "抱歉，系统暂未生成有效回答。", cypher, fig, stats


def _empty_stats() -> str:
    """空白统计占位 HTML。"""
    return '<span class="stat-badge stat-empty">暂无数据</span>'


def _empty_graph() -> go.Figure:
    """返回空白的占位图。"""
    return go.Figure(
        layout=go.Layout(
            paper_bgcolor="#1e1f20",
            plot_bgcolor="#1e1f20",
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            annotations=[dict(
                text="提问后将在此<br>展示知识图谱关系图",
                x=0.5, y=0.5, xref="paper", yref="paper",
                showarrow=False,
                font=dict(size=13, color="#5f6368"),
                xanchor="center",
            )],
            height=440,
        )
    )


def _path_to_graph(path_data: list[dict]) -> go.Figure:
    """将最短路径数据转换为关系图。"""
    if not path_data:
        return _empty_graph()

    G = nx.Graph()
    node_set: dict[str, dict] = {}

    for seg in path_data:
        a_info = seg.get("from", seg.get("a", {}))
        b_info = seg.get("to", seg.get("b", {}))
        rel = seg.get("relation", seg.get("r", "关联"))

        a_name = a_info.get("name", str(a_info)) if isinstance(a_info, dict) else str(a_info)
        b_name = b_info.get("name", str(b_info)) if isinstance(b_info, dict) else str(b_info)
        a_type = a_info.get("type", "") if isinstance(a_info, dict) else ""
        b_type = b_info.get("type", "") if isinstance(b_info, dict) else ""
        rel_label = rel.get("type", str(rel)) if isinstance(rel, dict) else str(rel)

        node_set[a_name] = {"name": a_name, "type": a_type}
        node_set[b_name] = {"name": b_name, "type": b_type}
        G.add_edge(a_name, b_name, label=rel_label)

    return _render_graph(G, node_set)


def _report_to_graph(report: dict) -> go.Figure:
    """将分析报告的 Top 实体可视化为放射状关系图。"""
    degree_top = report.get("degree_top10", [])
    if not degree_top:
        return _empty_graph()

    fig = go.Figure()
    center_x, center_y = 0, 0

    fig.add_trace(go.Scatter(
        x=[center_x], y=[center_y],
        mode="markers+text",
        text=["湖湘文化"],
        textposition="middle center",
        textfont=dict(size=12, color="#131314"),
        marker=dict(size=34, color="#8ab4f8", line=dict(width=2.5, color="#1e1f20")),
        hovertext="知识图谱核心",
        hoverinfo="text",
        showlegend=False,
    ))

    import math
    n = len(degree_top)
    for i, item in enumerate(degree_top):
        angle = 2 * math.pi * i / n
        r = 1.5
        x = center_x + r * math.cos(angle)
        y = center_y + r * math.sin(angle)
        entity_type = item.get("type", "")
        color = TYPE_COLORS.get(entity_type, FALLBACK_COLOR)

        fig.add_trace(go.Scatter(
            x=[center_x, x], y=[center_y, y],
            mode="lines",
            line=dict(width=0.8, color="#3c4043", dash="dot"),
            hoverinfo="none",
            showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=[x], y=[y],
            mode="markers+text",
            text=[item.get("name", "")],
            textposition="top center",
            textfont=dict(size=9, color="#e8e8e8"),
            marker=dict(
                size=12 + item.get("degree", 1) * 0.4,
                color=color,
                line=dict(width=1, color="#1e1f20"),
            ),
            hovertext=f"<b>{item.get('name')}</b><br>类型：{entity_type}<br>连接数：{item.get('degree', '-')}",
            hoverinfo="text",
            name=entity_type,
            showlegend=False,
        ))

    fig.update_layout(
        paper_bgcolor="#1e1f20",
        plot_bgcolor="#1e1f20",
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        height=440,
    )
    return fig


def _render_graph(G: nx.Graph, node_set: dict[str, dict]) -> go.Figure:
    """通用：将 NetworkX 图渲染为 Plotly Figure（暗色主题）。"""
    if not G.nodes:
        return _empty_graph()

    pos = nx.spring_layout(G, k=2.5, iterations=50, seed=42)
    edge_traces, edge_annotations = [], []
    for u, v, data in G.edges(data=True):
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_traces.append(go.Scatter(
            x=[x0, x1, None], y=[y0, y1, None],
            mode="lines",
            line=dict(width=1.0, color="#3c4043"),
            hoverinfo="none",
            showlegend=False,
        ))
        mid_x, mid_y = (x0 + x1) / 2, (y0 + y1) / 2
        edge_annotations.append(dict(
            x=mid_x, y=mid_y, xref="x", yref="y",
            text=data.get("label", ""),
            showarrow=False,
            font=dict(size=8, color="#9aa0a6"),
            bgcolor="rgba(30,31,32,0.9)",
            borderpad=2,
        ))

    node_x, node_y, node_text, node_hover, node_colors = [], [], [], [], []
    for node_id in G.nodes:
        info = node_set.get(node_id, {"name": node_id, "type": ""})
        x, y = pos[node_id]
        node_x.append(x)
        node_y.append(y)
        node_text.append(info["name"])
        node_hover.append(f"<b>{info['name']}</b><br>类型：{info['type']}")
        node_colors.append(TYPE_COLORS.get(info["type"], FALLBACK_COLOR))

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        text=node_text,
        textposition="top center",
        textfont=dict(size=10, color="#e8e8e8"),
        hovertext=node_hover,
        hoverinfo="text",
        marker=dict(size=20, color=node_colors, line=dict(width=1.5, color="#1e1f20")),
        showlegend=False,
    )

    fig = go.Figure(
        data=edge_traces + [node_trace],
        layout=go.Layout(
            paper_bgcolor="#1e1f20",
            plot_bgcolor="#1e1f20",
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            annotations=edge_annotations,
            dragmode="pan",
            height=440,
        ),
    )

    seen_types = set()
    for info in node_set.values():
        t = info["type"]
        if t and t not in seen_types:
            seen_types.add(t)
            fig.add_trace(go.Scatter(
                x=[None], y=[None],
                mode="markers",
                marker=dict(size=10, color=TYPE_COLORS.get(t, FALLBACK_COLOR), line=dict(width=1, color="#1e1f20")),
                name=t,
                showlegend=True,
            ))
    fig.update_layout(
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="left", x=0,
            font=dict(size=10, color="#9aa0a6"),
            bgcolor="rgba(30,31,32,0.9)",
        ),
    )
    return fig


# ---------------------------------------------------------------------------
# 图谱报告格式化
# ---------------------------------------------------------------------------

def _format_report(report: dict[str, Any]) -> str:
    """将图谱分析报告格式化为 Markdown 文本。"""
    lines = ["## 湖湘文化图谱分析报告\n"]
    lines.append("### 度中心性 Top 10\n")
    lines.append("| 类型 | 名称 | 连接数 |")
    lines.append("|------|------|--------|")
    for item in report.get("degree_top10", []):
        lines.append(f"| {item['type']} | {item['name']} | {item['degree']} |")

    lines.append("\n### PageRank Top 10\n")
    lines.append("| 类型 | 名称 | 分数 |")
    lines.append("|------|------|------|")
    for item in report.get("pagerank_top10", []):
        score_key = "pagerank" if "pagerank" in item else "pagerank_approx"
        lines.append(f"| {item['type']} | {item['name']} | {item[score_key]} |")

    lines.append("\n### 介数中心性 Top 10\n")
    lines.append("| 类型 | 名称 | 桥梁数 |")
    lines.append("|------|------|--------|")
    for item in report.get("betweenness_top10", []):
        lines.append(f"| {item['type']} | {item['name']} | {item['betweenness_approx']} |")

    gds_status = "可用" if report.get("gds_available") else "不可用（使用 Cypher 回退）"
    lines.append(f"\n> GDS 库状态：{gds_status}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 统计摘要
# ---------------------------------------------------------------------------

def _summarize_evidence(fig: go.Figure | None) -> str:
    """从关系图中提取统计摘要 HTML 徽章。"""
    if fig is None or not fig.data:
        return '<span class="stat-badge stat-empty">暂无数据</span>'

    node_count = 0
    edge_count = 0
    seen_types = set()

    for trace in fig.data:
        if trace.mode and "markers+text" in trace.mode and trace.x and any(x is not None for x in (trace.x or [])):
            node_count += len([x for x in trace.x if x is not None])
        if trace.mode == "lines" and trace.x:
            edge_count += len([x for x in trace.x if x is None])

    for trace in fig.data:
        if trace.showlegend and trace.name:
            seen_types.add(trace.name)

    return (
        f'<span class="stat-badge stat-entities">实体 {node_count}</span>'
        f'<span class="stat-badge stat-relations">关系 {edge_count}</span>'
    )


# ---------------------------------------------------------------------------
# Gradio 主题
# ---------------------------------------------------------------------------

THEME = gr.themes.Soft(
    primary_hue="blue",
    secondary_hue="gray",
    neutral_hue="slate",
).set(
    body_background_fill="#131314",
    body_background_fill_dark="#131314",
    block_background_fill="#131314",
    block_background_fill_dark="#131314",
    block_border_width="0px",
    block_title_text_color="#e8e8e8",
    body_text_color="#e8e8e8",
    body_text_color_dark="#e8e8e8",
    background_fill_primary="#1e1f20",
    background_fill_primary_dark="#1e1f20",
    background_fill_secondary="#282a2d",
    background_fill_secondary_dark="#282a2d",
    border_color_primary="#2d2f31",
    border_color_primary_dark="#2d2f31",
    button_primary_background_fill="#8ab4f8",
    button_primary_background_fill_dark="#8ab4f8",
    button_primary_text_color="#131314",
    button_primary_text_color_dark="#131314",
    button_secondary_background_fill="#282a2d",
    button_secondary_background_fill_dark="#282a2d",
    button_secondary_text_color="#9aa0a6",
    button_secondary_border_color="#3c4043",
    input_background_fill="#1e1f20",
    input_background_fill_dark="#1e1f20",
    input_border_color="#3c4043",
    input_placeholder_color="#6b7280",
    color_accent_soft="#8ab4f8",
    panel_background_fill="#1e1f20",
    panel_border_color="#2d2f31",
)


# ---------------------------------------------------------------------------
# UI 构建
# ---------------------------------------------------------------------------

def build_ui() -> "gr.Blocks":
    """构建 Gemini 风格 Gradio Web 界面 v3.0。"""
    if not GRADIO_AVAILABLE:
        raise ImportError("Gradio 未安装，请运行: pip install gradio")

    with gr.Blocks(title="湖湘文化 GraphRAG 问答系统") as demo:

        # ---- 顶部标题 ----
        with gr.Row():
            with gr.Column(scale=3, min_width=360):
                gr.Markdown(
                    '# 湖湘文化 · GraphRAG',
                    elem_classes=["main-title"],
                )
                gr.Markdown(
                    '基于 LangGraph + DeepSeek + Neo4j 的知识图谱智能问答',
                    elem_classes=["subtitle"],
                )

        with gr.Row(equal_height=False):
            # =================================================
            # 左侧：对话面板 (60%)
            # =================================================
            with gr.Column(scale=3, min_width=360):
                chatbot = gr.Chatbot(
                    label="",
                    height=480,
                    layout="bubble",
                    elem_classes=["chatbot-container"],
                    show_label=False,
                )

                with gr.Row(elem_classes=["input-row"]):
                    msg_input = gr.Textbox(
                        placeholder="输入您的问题...",
                        label="",
                        scale=10,
                        container=False,
                        show_label=False,
                    )
                    submit_btn = gr.Button(
                        "↑",
                        variant="primary",
                        scale=1,
                        min_width=42,
                    )

                with gr.Row(elem_classes=["secondary-row"]):
                    clear_btn = gr.Button("清空对话", variant="secondary", size="sm")

                gr.Markdown("""
                <div class="suggestion-grid">
                    <div class="suggestion-card">王夫之有哪些著作？</div>
                    <div class="suggestion-card">王夫之和曾国藩的关系？</div>
                    <div class="suggestion-card">湖湘学派有哪些代表人物？</div>
                    <div class="suggestion-card">shortest(周敦颐, 王夫之)</div>
                </div>
                """)

                gr.Markdown("""
                <span class="feature-tag">自然语言问答</span>
                <span class="feature-tag">关系路径查询</span>
                <span class="feature-tag">图谱分析报告</span>
                <span class="feature-tag">交互式可视化</span>
                """)

            # =================================================
            # 右侧：关系图 + Cypher (40%)
            # =================================================
            with gr.Column(scale=2, min_width=400):
                gr.HTML("""
                <div class="panel-card">
                    <h3>知识图谱关系图</h3>
                """)

                stats_html = gr.HTML(
                    value='<span class="stat-badge stat-empty">提问后将展示关系图</span>',
                )

                graph_plot = gr.Plot(
                    value=_empty_graph(),
                    label="",
                    show_label=False,
                )

                gr.HTML("""</div>""")

                with gr.Accordion("生成的 Cypher 查询", open=False, elem_classes=["accordion"]):
                    cypher_output = gr.Code(
                        label="",
                        lines=6,
                        elem_classes=["cypher-box"],
                    )

                gr.Markdown(
                    '<div class="footer-note">'
                    '湖湘文化 GraphRAG 多智能体问答系统 v3.0<br>'
                    '支持人物关系、历史事件、著作典籍等多维度知识查询'
                    '</div>',
                )

        # =====================================================
        # 事件处理
        # =====================================================

        def user_message_handler(message: str, history_in: list[dict]):
            """流式问答处理器：打字机效果输出回答内容。"""
            history = list(history_in) if history_in else []
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": "正在思考..."})

            # 第一帧立即显示，让用户知道系统在响应
            yield history, _empty_graph(), "", _empty_stats(), ""

            for answer_text, cypher, fig, stats in chat_stream(message):
                history[-1]["content"] = answer_text
                yield history, fig, cypher, stats, ""

        submit_btn.click(
            fn=user_message_handler,
            inputs=[msg_input, chatbot],
            outputs=[chatbot, graph_plot, cypher_output, stats_html, msg_input],
        )
        msg_input.submit(
            fn=user_message_handler,
            inputs=[msg_input, chatbot],
            outputs=[chatbot, graph_plot, cypher_output, stats_html, msg_input],
        )
        clear_btn.click(
            fn=lambda: ([], _empty_graph(), "", _empty_stats(), ""),
            outputs=[chatbot, graph_plot, cypher_output, stats_html, msg_input],
        )

    return demo


def _kill_port(port: int) -> None:
    """释放指定端口：查找并终止占用该端口的进程，避免启动时端口冲突。"""
    import subprocess
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                subprocess.run(
                    ["taskkill", "/F", "/PID", pid],
                    capture_output=True, timeout=10
                )
                print(f"已释放端口 {port}（原占用 PID: {pid}）")
                return
    except Exception:
        pass  # 静默失败，后续 launch 会正常报错


if __name__ == "__main__":
    _kill_port(7860)
    ui = build_ui()
    ui.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
        show_error=True,
        css=CSS,
        theme=THEME,
    )
