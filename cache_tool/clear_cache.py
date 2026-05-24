"""清理湖湘文化 GraphRAG 项目的所有缓存数据。"""
import shutil
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
CACHE_DIR = PROJECT_DIR / ".cache"


def _safe_delete(path: Path) -> bool:
    """安全删除文件或目录，返回是否成功。"""
    try:
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        return True
    except PermissionError:
        return False


def clear_qa_cache() -> None:
    """清理语义问答缓存（qa_cache.json）。"""
    cache_file = CACHE_DIR / "qa_cache.json"
    if not cache_file.exists():
        print("  问答缓存不存在，跳过")
        return
    if _safe_delete(cache_file):
        print(f"  已删除: {cache_file}")
    else:
        print(f"  删除失败（文件被占用）: {cache_file}")


def clear_json_cache() -> None:
    """清理 JSON 缓存目录。"""
    json_dir = PROJECT_DIR / "data" / "json_cache"
    if not json_dir.exists():
        print("  JSON 缓存目录不存在，跳过")
        return
    skipped = 0
    deleted = 0
    for f in sorted(json_dir.iterdir()):
        if _safe_delete(f):
            deleted += 1
        else:
            skipped += 1
            print(f"    跳过（被占用）: {f.name}")
    if skipped == 0 and deleted > 0:
        json_dir.rmdir()
        print(f"  已清空: {json_dir}")
    else:
        print(f"  已清理 {deleted} 个文件，{skipped} 个被跳过")


def clear_pycache() -> None:
    """清理 Python 字节码缓存（__pycache__ 目录）。"""
    deleted = 0
    skipped = 0
    for pycache in sorted(PROJECT_DIR.rglob("__pycache__")):
        if _safe_delete(pycache):
            deleted += 1
        else:
            skipped += 1
            print(f"    跳过（被占用）: {pycache}")
    if deleted:
        print(f"  已清理 {deleted} 个 __pycache__ 目录")
    if skipped:
        print(f"  {skipped} 个 __pycache__ 目录被跳过")
    if deleted == 0 and skipped == 0:
        print("  无 __pycache__ 目录")


def main() -> None:
    print("清空湖湘文化 GraphRAG 缓存\n")
    clear_qa_cache()
    clear_json_cache()
    clear_pycache()
    print("\n缓存清理完毕。")


if __name__ == "__main__":
    main()
