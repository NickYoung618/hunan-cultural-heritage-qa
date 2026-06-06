"""
实体抽取引擎 v2.1：基于 Pydantic 结构化 Schema + DeepSeek JSON Mode，
新增 detail 原话摘抄能力，彻底淘汰脆弱的 json.loads 手动清洗方式。
"""
import json
import os
from typing import Optional
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError
from dotenv import load_dotenv

load_dotenv()


# --- Pydantic 数据模型 ---

class Entity(BaseModel):
    """图谱实体模型"""
    name: str = Field(..., description="实体名称。必须极度精简（2到10个字以内），绝对禁止将长句子作为名称！")
    type: str = Field(..., description="实体类型", examples=["人物", "地点", "作品", "事件", "核心思想/流派"])
    # 👇 给大模型下达死命令
    description: str = Field(
        default="",
        description="实体的详细释义。如果是【核心思想】或【概念】（如气一元论），你必须将原文中关于该思想的几百字解释、内涵，完整、一字不落地摘抄到这里！绝对不允许为空！"
    )


class Relationship(BaseModel):
    """图谱关系模型"""
    source: str = Field(..., description="关系起点实体名称")
    target: str = Field(..., description="关系终点实体名称")
    relation: str = Field(..., description="关系描述，如'隐居于'、'撰写'、'兄弟'")
    detail: str = Field(
        default="",
        description="关系的具体背景、评价的原文或详细论述摘抄。例如某人对某人的具体评价原话。若无具体内容，请填空字符串。"
    )


class GraphExtractionResult(BaseModel):
    """一次抽取的完整结果"""
    entities: list[Entity] = Field(default_factory=list, description="抽取到的实体列表")
    relationships: list[Relationship] = Field(default_factory=list, description="抽取到的关系列表")


# --- JSON Schema 模板（注入 System Prompt） ---

JSON_SCHEMA_DEFINITION = """
{
  "entities": [
    {"name": "王夫之", "type": "人物", "description": "明末清初著名的思想家、哲学家，字而农，号姜斋，学者称船山先生。湖南衡阳人。早年参加抗清斗争，失败后隐居石船山著书立说。其学说渊博精深，以气一元论为核心，批判程朱理学与陆王心学，开创了明清之际实学思潮的新方向。"},
    {"name": "气一元论", "type": "核心思想/流派", "description": "王夫之认为气是唯一实体，不是'心外无物'。天地间存在着的一切都是具体的实物，一般原理存在于具体事物之中，决不是具体事物依存于一般原理。物质是运动的，运动是有规律的。物质运动的原因在于物质内部，物质内部阴阳两种对立势力的互相斗争促使一切事物运动变化。静止里包含着运动。"},
    {"name": "理势合一", "type": "核心思想/流派", "description": "王夫之的历史哲学思想，认为历史发展有其内在的必然规律（理），这种规律通过具体的历史趋势（势）体现出来。理不离势，势中见理。任何朝代兴衰、制度变迁都有其客观必然性，而非天意或圣人偶然意志所决定。这一思想打破了传统天命史观，是古代历史哲学的最高成就之一。"},
    {"name": "石船山", "type": "地点", "description": ""}
  ],
  "relationships": [
    {
      "source": "曾国藩",
      "target": "王夫之",
      "relation": "评价",
      "detail": "独先生深閟固藏，追焉无与。平生痛诋党人标谤之习，不欲身隐而文著，来反唇之讪笑。用是，其身长遁，其名寂寂，其学亦竟不显于世。荒山敝榻，终岁孜孜，以求所谓育物之仁、经邦之礼。"
    }
  ]
}
"""

SYSTEM_PROMPT = f"""你是一个严谨的历史图谱抽取智能体。
请从用户提供的文本中，提取出所有的【实体】以及实体之间的【关系】。

【提取规则强化】：
1. 实体类型从以下类别中选择：人物、地点、作品、事件、概念/流派、时间、学派、官职。
2. ⚠️ 极其重要：在提取"关系 (relationships)"时，必须提供 `detail` 字段。如果原文包含具体的评价原话、历史背景细节，绝对不能丢弃，必须完整摘抄到 `detail` 字段中！若无，填空字符串 ""。
3. ⚠️ 极其重要：在提取"实体 (entities)"时，如果原文对该实体有详细解释、思想论述、生平概括或背景描述，必须摘抄原文写入 `description` 字段！尤其是哲学概念（如"气一元论""理气论"）、历史事件、人物核心思想，description 是唯一的原文存储位置，绝对不能丢弃。若无详细解释，填空字符串 ""。
4. ⛔ 噪音过滤：请忽略所有与现代影视剧、现代纪念邮票、现代演员（如陈昭荣、贺生伟）相关的流行文化内容，仅提取明清历史时期的实体与关系。
5. 🛑 绝对红线 — 防崩溃严打法则（违反即作废）：
   - `name`（实体名称）必须是专有名词，极度精简（2-10字）！如果你发现自己试图把超过15个字的句子放进 `name` 里，那你绝对做错了！
   - 所有的长篇大论、哲学解释、生平背景，必须且只能塞进 `Entity` 的 `description` 字段或 `Relationship` 的 `detail` 字段。`name` 绝不承载解释性内容。
   - 严禁将毫不相干的事件（如娶妻、画像、现代影视）与纯粹的哲学概念（如"气一元论""理势合一"）强行建立连线！只有原文明确提到某人与某概念的关联时，才能建立关系。

你必须严格返回一个 JSON 对象，包含 "entities" 和 "relationships" 两个数组。不要输出任何解释、注释或 Markdown 标记，只输出纯 JSON 对象。

JSON 结构示例：
{JSON_SCHEMA_DEFINITION}
"""


class HuxiangExtractor:
    """湖湘文化图谱实体抽取器（Pydantic 校验版）"""

    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=os.getenv("MIMO_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("MIMO_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL"),
            timeout=300.0,
        )
        self.model_name: str = os.getenv("MIMO_MODEL") or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    def extract(self, text: str, max_retries: int = 2) -> GraphExtractionResult:
        """从文本中抽取实体和关系，带重试与 Pydantic 校验。

        Args:
            text: 待抽取的自然语言文本。
            max_retries: JSON 解析失败时的最大重试次数。

        Returns:
            经过 Pydantic 校验的 GraphExtractionResult 对象。
        """
        last_error: Optional[str] = None

        for attempt in range(max_retries + 1):
            raw_output = self._call_api(text, last_error)
            result = self._parse_and_validate(raw_output)

            if result is not None:
                return result

            last_error = "JSON 解析或校验失败，将要求模型重新生成"
            if attempt < max_retries:
                print(f"  ⚠️ [抽取器] 第 {attempt + 1} 次解析失败，正在重试...")

        # 所有重试均失败，返回空结果
        print(f"  ❌ [抽取器] 全部 {max_retries + 1} 次尝试均失败，返回空结果")
        return GraphExtractionResult(entities=[], relationships=[])

    def _call_api(self, text: str, previous_error: Optional[str] = None) -> str:
        """调用 DeepSeek API，启用 JSON Mode。"""
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

        if previous_error:
            messages.append({
                "role": "user",
                "content": f"上一次输出格式有误（{previous_error}），请严格按照 JSON Schema 重新输出。",
            })

        messages.append({"role": "user", "content": text})

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content

    @staticmethod
    def _parse_and_validate(raw: str) -> Optional[GraphExtractionResult]:
        """清理 Markdown 标记 → JSON 解析 → Pydantic 校验。"""
        if not raw:
            return None

        # 剥离 Markdown 代码块标记
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return None

        try:
            return GraphExtractionResult(**data)
        except ValidationError:
            # 尝试逐个字段修复（容错机制：保留对的，丢弃错的）
            entities_raw = data.get("entities", []) if isinstance(data, dict) else []
            relationships_raw = data.get("relationships", []) if isinstance(data, dict) else []

            valid_entities = []
            for e in entities_raw:
                try:
                    valid_entities.append(Entity(**e))
                except ValidationError:
                    continue

            valid_relationships = []
            for r in relationships_raw:
                try:
                    valid_relationships.append(Relationship(**r))
                except ValidationError:
                    continue

            if valid_entities or valid_relationships:
                return GraphExtractionResult(
                    entities=valid_entities,
                    relationships=valid_relationships,
                )

            return None


# --- 顶层便捷函数（保持与旧版兼容） ---

def extract_entities(text: str) -> str:
    """从文本中抽取实体和关系，返回 JSON 字符串。

    保持与旧版 API 兼容，内部使用 Pydantic 校验。
    """
    extractor = HuxiangExtractor()
    result = extractor.extract(text)
    return result.model_dump_json(ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # 快速自测
    sample = """
    曾国藩在《王船山遗书》中作序评：独先生深閟固藏，追焉无与。
    2010年《南岳奇人王船山》，陈昭荣饰演王夫之。
    """

    extractor = HuxiangExtractor()
    result = extractor.extract(sample)
    print(f"实体数: {len(result.entities)}")
    print(f"关系数: {len(result.relationships)}")
    for e in result.entities:
        print(f"  🏷️ {e.name} ({e.type})")
    for r in result.relationships:
        print(f"  🔗 {r.source} —[{r.relation}]→ {r.target} (Detail: {r.detail[:20]}...)")