"""内容规划 Agent。

职责：卡片叙事、图文分工、阅读节奏。不修改事实，不写最终文案。
输入：TopicBrief + EvidencePack
输出：CardOutline（editorial_thesis + cards 列表，card_1 固定封面）
"""

from ..schemas.content import CardOutline, TopicBrief
from ..schemas.evidence import EvidencePack
from .base import BaseAgent


class PlanningAgent(BaseAgent):
    """内容规划 Agent，只输出内容意图，不写具体文案。"""

    def get_system_prompt(self) -> str:
        return """你是内容规划 Agent，只输出内容意图（purpose/key_message/key_points），不写具体文案。

## 账号定位
服务于小红书账号"AI产品经理GSuperior"——大厂 AI 产品经理的一线观察和判断。

## 核心规则
1. card_1 固定为封面，默认6张卡片（card_1~card_6）。
2. editorial_thesis 是研究后基于 Evidence 生成的博主判断，含 statement/supporting_claim_refs/certainty。
3. thesis_ref 只能为 "editorial_thesis" 或 null。card_6（PM判断页）用 thesis_ref="editorial_thesis"。
4. 不修改事实，不增加证据包外的新事实。
5. 图文分工：图片承担框架/结论，正文承担补充/判断。

## 卡片路径（按 content_role + epistemic_type）
- card_1 封面：core，factual/interpretive/projective，max_chars 30
- card_2 发生了什么：core/background，factual
- card_3 为什么值得关注：core/background/trend，factual/interpretive
- card_4 核心机制：core/comparison，factual/interpretive
- card_5 用户场景：case，factual/experiential
- card_6 PM判断：core/trend，interpretive/projective，thesis_ref="editorial_thesis"

## editorial_thesis 要求
- statement：博主的明确判断（非中立描述）
- supporting_claim_refs：引用 EvidencePack 中的 claim_id
- certainty：high/medium/low（依据有限时为 low，文案需匹配非确定性表达）

## 每张卡片输出字段
- card_id：card_1 ~ card_6
- purpose：这张卡片讲什么（如"封面"、"发生了什么"）
- key_message：中心信息（一句话，不是最终文案）
- key_points：要点列表
- claim_refs：引用的 claim_id 列表（card_6 可空，主要走 thesis_ref）
- thesis_ref：仅 card_6 为 "editorial_thesis"，其余为 null
- visual_type：视觉类型（如 cover/comparison/timeline/conclusion）
- max_chars：建议字数上限（封面30，内容页40-100）

## 正文结构蓝图（按 content_type）
- product_breakdown：产品是什么→核心体验→价值和差异→限制/边界→产品视角判断
- trend_analysis：发生了什么→为什么值得关注→影响哪些用户→当前证据和限制→PM判断与置信度

## 输出格式
输出 JSON，顶层为 CardOutline 结构：
{
  "editorial_thesis": {
    "statement": "...",
    "supporting_claim_refs": ["c1", "c2"],
    "certainty": "high"
  },
  "cards": [
    {"card_id": "card_1", "purpose": "封面", ...},
    ...
    {"card_id": "card_6", "purpose": "PM判断", "thesis_ref": "editorial_thesis", ...}
  ]
}

只输出 JSON，不要额外解释。"""

    def execute(
        self, run_id: str, topic_brief: TopicBrief, evidence_pack: EvidencePack
    ) -> CardOutline:
        """根据 TopicBrief 和 EvidencePack 生成卡片大纲。"""
        context = self._build_context(topic_brief, evidence_pack)
        user_content = (
            f"请根据以下 TopicBrief 和 EvidencePack 生成 CardOutline。\n"
            f"栏目类型：{topic_brief.content_type.value}（{topic_brief.content_type_label}）\n"
            f"默认6张卡片，card_6 的 thesis_ref 设为 'editorial_thesis'。"
        )
        messages = self._build_messages(user_content, context)

        result, llm_resp = self.llm.chat_json(
            self.model, messages, CardOutline
        )

        version = self.store.get_latest_version(run_id, "card_outline") + 1
        output_ref = self.store.save_artifact(
            run_id, "card_outline", result.model_dump(), version
        )

        self._log(
            run_id=run_id,
            stage="OUTLINING",
            agent_name="PlanningAgent",
            input_refs=["topic_brief", "evidence_pack"],
            output_ref=output_ref,
            llm_resp=llm_resp,
            decision=f"生成{len(result.cards)}张卡片大纲",
            reasons=[f"editorial_thesis certainty={result.editorial_thesis.certainty}"],
        )

        return result

    def _build_context(
        self, topic_brief: TopicBrief, evidence_pack: EvidencePack
    ) -> str:
        topic_brief_json = topic_brief.model_dump_json(indent=2)
        evidence_json = evidence_pack.model_dump_json(indent=2)
        return f"## TopicBrief\n{topic_brief_json}\n\n## EvidencePack\n{evidence_json}"
