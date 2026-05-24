from tools.extractor import HuxiangExtractor

text = """其三，气一元论，王夫之认为气是唯一实体，不是“心外无物”。王夫之还指出，天地间存在着的一切都是具体的实物，一般原理存在于具体事物之中，决不可说具体事物依存于一般原理。王夫之认为“形而上”与“形而下”虽有上下之名，但不意味着上下之间有界限可以分割开来。"""

print("🚀 正在呼叫大模型进行裸测...")
extractor = HuxiangExtractor()
result = extractor.extract(text)
print(result.model_dump_json(indent=2))