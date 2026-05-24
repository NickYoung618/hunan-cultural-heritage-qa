import os
import time
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from tools.extractor import extract_entities
from tools.graph_writer import save_to_neo4j
from concurrent.futures import ThreadPoolExecutor, as_completed  # 👈 新增：导入多线程控制模块


# --- 1. 状态与节点定义 ---
class HuxiangState(TypedDict):
    text: str
    json_result: str
    db_status: str
    chunk_index: int  # 记录当前处理的块索引


def extractor_node(state: HuxiangState):
    idx = state['chunk_index']
    print(f"  🕵️ [区块 {idx}] 抽取专家正在提炼实体...")
    max_retries = 3
    for attempt in range(max_retries):
        try:
            result = extract_entities(state["text"])

            if "抽取失败" in result or "Request timed out" in result:
                print(f"  ⚠️ [区块 {idx}] 抽取失败 (尝试 {attempt + 1}/{max_retries}): {result}")
                if attempt < max_retries - 1:
                    print(f"  ⏳ [区块 {idx}] 局部冷却 10 秒后重试...")
                    time.sleep(10)  # 👈 这里的休眠只会暂停当前线程，其他线程继续狂奔
                    continue
                else:
                    return {"json_result": result}

            return {"json_result": result}

        except Exception as e:
            print(f"  ⚠️ [区块 {idx}] 网络异常 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                print(f"  ⏳ [区块 {idx}] 局部冷却 10 秒后重试...")
                time.sleep(10)
            else:
                return {"json_result": f'{{"error": "{str(e)}"}}'}


def reviewer_node(state: HuxiangState):
    json_data = state.get("json_result", "")
    if "error" in json_data or json_data == "":
        print(f"  ❌ [审核驳回] 抛弃本块数据。")
        raise ValueError("数据审核未通过")
    return {}


def graph_writer_node(state: HuxiangState):
    idx = state['chunk_index']
    print(f"  🕸️ [区块 {idx}] 入库专家正在构建图谱...")
    status = save_to_neo4j(state["json_result"])
    print(f"  🏁 [区块 {idx}] {status}")
    return {"db_status": status}


# --- 2. 构建图谱应用 ---
workflow = StateGraph(HuxiangState)
workflow.add_node("extractor", extractor_node)
workflow.add_node("reviewer", reviewer_node)
workflow.add_node("graph_writer", graph_writer_node)
workflow.add_edge(START, "extractor")
workflow.add_edge("extractor", "reviewer")
workflow.add_edge("reviewer", "graph_writer")
workflow.add_edge("graph_writer", END)
app = workflow.compile()


# --- 3. 长文本切片引擎 ---
def chunk_text(text: str, max_length: int = 800) -> list:
    paragraphs = text.split('\n')
    chunks = []
    current_chunk = ""
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if len(current_chunk) + len(p) > max_length and current_chunk:
            chunks.append(current_chunk)
            current_chunk = p
        else:
            current_chunk += "\n" + p
    if current_chunk:
        chunks.append(current_chunk)
    return chunks


# --- 4. 核心改造：封装供多线程调用的独立工作单元 ---
def process_single_chunk(chunk_data, index):
    """这个函数将被线程池分配给不同的工人同时执行"""
    try:
        app.invoke({"text": chunk_data, "chunk_index": index})
    except Exception as e:
        print(f"  ⏭️ [区块 {index}] 彻底失败已跳过。原因: {e}")


# --- 5. 多线程并发调度中心 ---
if __name__ == "__main__":
    print("==============================================")
    print("🚀 湖湘文化 GraphRAG：多线程并发入库引擎启动")
    print("==============================================")

    base_dir = os.path.dirname(os.path.abspath(__file__))

    # 优先从 clean_txt 目录批量读取清洗文本
    clean_dir = os.path.join(base_dir, "data", "clean_txt")
    if os.path.isdir(clean_dir) and os.listdir(clean_dir):
        print(f"📂 检测到 clean_txt 目录，将合并处理其中所有 .txt 文件...")
        raw_text = ""
        for fname in sorted(os.listdir(clean_dir)):
            if fname.endswith(".txt"):
                fpath = os.path.join(clean_dir, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    raw_text += f"\n\n--- {fname} ---\n\n" + f.read()
                print(f"  📄 已加载: {fname}")
        if not raw_text:
            print("❌ clean_txt 目录中无有效 .txt 文件，请先运行 spider_baike.py 抓取数据。")
            exit()
    else:
        # 回退到旧版单文件路径
        file_path = os.path.join(base_dir, "data", "wangfuzhi_baike.txt")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_text = f.read()
        except Exception as e:
            print(f"读取文件失败: {e}")
            exit()

    text_chunks = chunk_text(raw_text, max_length=600)
    print(f"📄 原始长文已成功切分为 {len(text_chunks)} 个数据块。\n")

    # 重点：配置并发数量安全阀
    MAX_WORKERS = 3  # 最多同时向 API 发送 3 个请求

    start_time = time.time()  # 记录开始时间

    # 启动线程池
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for i, chunk in enumerate(text_chunks):
            print(f"▶️ 正在将第 {i + 1}/{len(text_chunks)} 块数据推入多线程列车...")
            # 将任务提交给线程池并行处理
            futures.append(executor.submit(process_single_chunk, chunk, i + 1))

            # 错峰发车：给每个并发请求一点极短的间隔，防止瞬间流量洪峰
            time.sleep(0.5)

            # 阻塞主线程，直到所有的子线程全部汇报完工
        for future in as_completed(futures):
            pass

    end_time = time.time()
    print("-" * 50)
    print(f"🎉 批量任务完美收官！全流程总耗时: {round(end_time - start_time, 2)} 秒")