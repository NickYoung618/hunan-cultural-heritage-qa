"""
CodeGraph 知识图谱可视化工具
读取 .codegraph/codegraph.db，生成交互式 HTML 图谱。
"""
import sqlite3
from pathlib import Path
from typing import Optional

import networkx as nx
from pyvis.network import Network


# 节点类型 → 颜色映射
NODE_COLORS = {
    "class":    "#FF6B6B",  # 红色
    "function": "#4ECDC4",  # 青色
    "method":   "#45B7D1",  # 蓝色
    "variable": "#96CEB4",  # 绿色
    "import":   "#DDA0DD",  # 紫色
    "file":     "#FFD93D",  # 黄色
}

# 边类型 → 样式映射
EDGE_STYLES = {
    "contains":      {"color": "#999999", "dashes": True,  "width": 0.5},
    "calls":         {"color": "#FF6B6B", "dashes": False, "width": 1.5},
    "imports":       {"color": "#4ECDC4", "dashes": False, "width": 1.0},
    "instantiates":  {"color": "#FFD93D", "dashes": False, "width": 1.0},
}

DEFAULT_STYLE = {"color": "#CCCCCC", "dashes": False, "width": 0.5}


def load_graph(db_path: str = ".codegraph/codegraph.db") -> nx.DiGraph:
    """从 CodeGraph SQLite 数据库加载为 NetworkX 有向图。

    Args:
        db_path: codegraph.db 路径，默认为当前目录下的 .codegraph/codegraph.db

    Returns:
        包含所有节点和边的 NetworkX DiGraph
    """
    db = Path(db_path)
    if not db.exists():
        raise FileNotFoundError(f"数据库不存在: {db}")

    G = nx.DiGraph()
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 加载节点
    for row in c.execute("SELECT id, kind, name, file_path, start_line, signature, docstring FROM nodes"):
        G.add_node(
            row["id"],
            kind=row["kind"],
            name=row["name"],
            file=row["file_path"] or "",
            line=row["start_line"] or 0,
            signature=row["signature"] or "",
            docstring=(row["docstring"] or "")[:120],
        )

    # 加载边
    for row in c.execute("SELECT source, target, kind FROM edges"):
        if row["source"] in G and row["target"] in G:
            G.add_edge(row["source"], row["target"], kind=row["kind"])

    conn.close()
    return G


def render_interactive(
    G: nx.DiGraph,
    output_path: str = "codegraph_viz.html",
    *,
    title: str = "CodeGraph 知识图谱",
    height: str = "750px",
    max_nodes: Optional[int] = None,
) -> str:
    """将图渲染为交互式 HTML 文件（基于 PyVis）。

    Args:
        G: NetworkX 有向图
        output_path: 输出 HTML 路径
        title: 页面标题
        height: 画布高度
        max_nodes: 最大节点数，超过时按出入度取 top N

    Returns:
        生成的 HTML 文件绝对路径
    """
    if max_nodes and len(G) > max_nodes:
        # 按 degree 取最重要的节点
        top = sorted(G.degree(), key=lambda x: x[1], reverse=True)[:max_nodes]
        keep = {n for n, _ in top}
        G = G.subgraph(keep).copy()

    net = Network(height=height, directed=True, notebook=False, cdn_resources="in_line")
    net.set_options("""
    var options = {
      "nodes": {
        "font": { "size": 14, "face": "Microsoft YaHei" },
        "scaling": { "min": 10, "max": 50 }
      },
      "edges": {
        "arrows": { "to": { "enabled": true, "scaleFactor": 0.6 } },
        "smooth": { "type": "continuous" }
      },
      "physics": {
        "forceAtlas2Based": {
          "gravitationalConstant": -80,
          "centralGravity": 0.01,
          "springLength": 120,
          "springConstant": 0.08
        },
        "maxVelocity": 30,
        "solver": "forceAtlas2Based",
        "timestep": 0.35,
        "stabilization": { "iterations": 200 }
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 100,
        "navigationButtons": true,
        "keyboard": true
      }
    }
    """)

    # 添加节点
    for node_id, attrs in G.nodes(data=True):
        kind = attrs.get("kind", "unknown")
        color = NODE_COLORS.get(kind, "#AAAAAA")
        # tooltip 显示详细信息
        tooltip = (
            f"<b>{attrs.get('name', node_id)}</b><br>"
            f"类型: {kind}<br>"
            f"文件: {attrs.get('file', '')}:{attrs.get('line', '')}<br>"
            f"{attrs.get('signature', '')}<br>"
            f"<small>{attrs.get('docstring', '')}</small>"
        )
        net.add_node(
            node_id,
            label=attrs.get("name", node_id),
            title=tooltip,
            color=color,
            shape="dot" if kind != "file" else "square",
            size=max(G.degree(node_id) * 2 + 5, 8),
        )

    # 添加边
    for u, v, attrs in G.edges(data=True):
        style = EDGE_STYLES.get(attrs.get("kind", ""), DEFAULT_STYLE)
        net.add_edge(
            u, v,
            color=style["color"],
            width=style["width"],
            dashes=style["dashes"],
            title=attrs.get("kind", ""),
        )

    out = Path(output_path).resolve()
    # 手动写入 HTML，避免 pyvis 在 Windows 上用 GBK 编码导致乱码
    html = net.generate_html()
    out.write_text(html, encoding="utf-8")
    return str(out)


def render_static(
    G: nx.DiGraph,
    output_path: str = "codegraph_viz.png",
    *,
    figsize: tuple = (24, 18),
    max_nodes: Optional[int] = None,
) -> str:
    """将图渲染为静态 PNG 图片（基于 matplotlib + networkx）。

    Args:
        G: NetworkX 有向图
        output_path: 输出图片路径
        figsize: 画布尺寸 (宽, 高)
        max_nodes: 最大节点数，超过时按出入度取 top N

    Returns:
        生成的图片文件绝对路径
    """
    import matplotlib.pyplot as plt

    if max_nodes and len(G) > max_nodes:
        top = sorted(G.degree(), key=lambda x: x[1], reverse=True)[:max_nodes]
        keep = {n for n, _ in top}
        G = G.subgraph(keep).copy()

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    _, ax = plt.subplots(figsize=figsize)

    # 按节点类型分组着色
    color_map = []
    for _, attrs in G.nodes(data=True):
        color_map.append(NODE_COLORS.get(attrs.get("kind", ""), "#AAAAAA"))

    # 使用 spring layout
    pos = nx.spring_layout(G, k=2.5, iterations=50, seed=42)

    # 按边类型分别绘制
    for kind, style in EDGE_STYLES.items():
        edges = [(u, v) for u, v, a in G.edges(data=True) if a.get("kind") == kind]
        if edges:
            nx.draw_networkx_edges(
                G, pos, edgelist=edges, ax=ax,
                edge_color=style["color"],
                style="dashed" if style["dashes"] else "solid",
                width=style["width"],
                alpha=0.4,
                arrows=True, arrowsize=8,
                connectionstyle="arc3,rad=0.1",
            )

    # 绘制节点
    node_sizes = [max(G.degree(n) * 80 + 200, 300) for n in G.nodes()]
    nx.draw_networkx_nodes(G, pos, ax=ax, node_color=color_map, node_size=node_sizes, alpha=0.9)

    # 只给重要节点加标签
    degrees = dict(G.degree())
    threshold = sorted(degrees.values(), reverse=True)[max(1, min(len(degrees) // 4, 30)) - 1] if degrees else 0
    labels = {n: attrs["name"] for n, attrs in G.nodes(data=True) if degrees.get(n, 0) >= threshold}
    nx.draw_networkx_labels(G, pos, labels, ax=ax, font_size=6, font_family="Microsoft YaHei")

    # 图例
    legend_handles = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=c, markersize=10, label=k)
        for k, c in NODE_COLORS.items()
    ]
    ax.legend(handles=legend_handles, loc="upper left", fontsize=8, title="节点类型")
    ax.set_title("CodeGraph 知识图谱", fontsize=16)
    ax.axis("off")

    out = Path(output_path).resolve()
    plt.savefig(str(out), dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()
    return str(out)


# --- 顶层便捷函数 ---

def visualize(
    db_path: str = ".codegraph/codegraph.db",
    output: str = "codegraph_viz.html",
    *,
    interactive: bool = True,
    max_nodes: Optional[int] = 200,
) -> str:
    """CodeGraph 知识图谱可视化 — 生成交互式 HTML 或静态图片。

    Args:
        db_path: codegraph.db 路径
        output: 输出文件路径（.html 或 .png）
        interactive: True = 交互式 HTML (pyvis), False = 静态 PNG (matplotlib)
        max_nodes: 最大节点数限制，None = 不限

    Returns:
        生成的文件绝对路径
    """
    print(f"[Load] Database: {db_path}")
    G = load_graph(db_path)
    print(f"  Nodes: {len(G.nodes())}  Edges: {len(G.edges())}")

    if interactive:
        out = render_interactive(G, output, max_nodes=max_nodes)
        print(f"[OK] Interactive graph saved: {out}")
    else:
        # 自动修正后缀
        if not output.endswith(".png"):
            output = output.rsplit(".", 1)[0] + ".png" if "." in output else output + ".png"
        out = render_static(G, output, max_nodes=max_nodes)
        print(f"[OK] Static graph saved: {out}")

    return out


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CodeGraph 知识图谱可视化")
    parser.add_argument("--db", default=".codegraph/codegraph.db", help="数据库路径")
    parser.add_argument("--output", default="codegraph_viz.html", help="输出文件")
    parser.add_argument("--static", action="store_true", help="生成静态 PNG 而非交互 HTML")
    parser.add_argument("--max-nodes", type=int, default=200, help="最大节点数")
    args = parser.parse_args()

    visualize(args.db, args.output, interactive=not args.static, max_nodes=args.max_nodes)
