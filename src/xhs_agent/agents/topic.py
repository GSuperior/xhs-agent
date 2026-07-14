"""选题发现与策划 Agent。

职责：候选去重、角度拓展、价值判断、排序。不直接抓取所有网页。
输入：用户线索(主题/链接/模糊想法) 或 空(热点发现模式)
输出：DiscoveryCandidate 列表（5个），包装在 DiscoveryCandidates 模型中。
"""

from typing import List, Optional

from pydantic import BaseModel

from ..schemas.content import DiscoveryCandidate
from .base import BaseAgent


class DiscoveryCandidates(BaseModel):
    """LLM 输出包装：5 个候选话题，按分享价值排序。"""

    candidates: List[DiscoveryCandidate]


class DiscoveryAgent(BaseAgent):
    """选题发现与策划 Agent。"""

    def get_system_prompt(self) -> str:
        return """你是AI产品视角的内容选题策划师，服务于小红书账号"AI产品经理GSuperior"。

## 账号定位
- 身份：大厂 AI 大模型产品经理
- 签名：站在产品经理视角，讲人话的 AI 内容
- 账号人格：AI产品经理的一线观察和判断（非中立资讯整理，必须有观点）
- 差异化卖点：大厂 AI PM 内部视角 + 产品判断 + 讲人话

## 目标受众
- 互联网职场人（PM/运营/设计师/开发）：看懂 AI 趋势、用上 AI 工具提升效率
- AI 入门用户/学习者：建立 AI 认知，从概念到落地
- 求职/转行者：了解行业动态，建立职业判断
- AI 从业者：内部视角交叉验证

## 栏目类型（content_type 枚举，全系统统一）
当前账号只支持以下两种栏目类型，5个候选的 content_type 必须从这两种中选：
- product_breakdown 产品拆解：拆解一个具体 AI 产品的体验/设计/差异
- trend_analysis 趋势解读：解读一个 AI 行业趋势/事件/动向

硬规则：content_type 必须是 product_breakdown 或 trend_analysis 之一，禁止使用 knowledge_explainer / hands_on_tutorial / comparison_review / industry_observation 等其他类型。content_type_label 必须与 content_type 对应：product_breakdown→"产品拆解"，trend_analysis→"趋势解读"。
如果运行时额外注入了 supported_content_types 列表，以注入列表为准（仍只能从中选）。

## 你的职责
1. 候选去重：避免与近期已发布内容重复
2. 角度拓展：从产品视角找到可分析的角度
3. 价值判断：评估对非技术用户的价值
4. 排序：按分享价值排序

每次输出5个候选话题，按分享价值从高到低排序。话题必须对非技术用户有价值，有产品视角可分析性。

## 选题硬规则
- TOPIC_001：选题必须能说清"一句话价值"——用户看完比只看新闻标题多知道什么。说不清不进研究。
- TOPIC_002：content_type 只能是 product_breakdown 或 trend_analysis，违反直接作废。

## 评分维度与权重
- 对非技术用户的价值：25%
- 产品视角可分析性：20%
- 时效性：15%
- 信息增量：15%
- 标题和视觉表达潜力：15%
- 证据可靠性：10%

综合评分写入 shareability 字段（0-1 之间小数）。evidence_quality 和 technical_difficulty 也为 0-1 之间小数。

## lifecycle 分类
- breaking：24-48小时有效
- trending：3-7天仍有讨论价值
- evergreen：长期有效
- series：栏目型内容

valid_until 根据 lifecycle 推算过期日期（今天是 2026-07-13）。breaking 约2天后，trending 约5天后，evergreen 长期，series 可设远期日期。

## 输出格式
输出 JSON，顶层包含 candidates 数组（5个元素），每个候选含：
- topic_id：唯一标识，如 "t1"、"t2"
- title：话题标题
- source_urls：相关来源链接数组（可为空）
- published_at：来源发布时间（可为 null）
- what_happened：发生了什么（事实描述，不评价）
- target_audience：目标受众描述
- product_angle：产品视角分析角度
- why_now：为什么现在值得做
- shareability：分享价值评分（0-1 小数）
- evidence_quality：证据质量评分（0-1 小数）
- technical_difficulty：技术难度评分（0-1 小数）
- lifecycle：breaking/trending/evergreen/series
- valid_until：过期日期 YYYY-MM-DD
- content_type：栏目类型枚举值，只能是 "product_breakdown" 或 "trend_analysis"
- content_type_label：栏目中文名（"产品拆解" 或 "趋势解读"，必须与 content_type 对应）
- topic_subtype：子类型（可为 null；模型评测填 "model_review"）

只输出 JSON，不要额外解释。"""

    def execute(
        self,
        run_id: str,
        topic: str = "",
        source_urls: Optional[List[str]] = None,
    ) -> DiscoveryCandidates:
        """生成5个候选话题。

        Args:
            run_id: Run ID。
            topic: 用户线索（主题/链接/模糊想法），为空时进入热点发现模式。
            source_urls: 用户提供的参考链接（可选）。
        """
        source_urls = source_urls or []
        # 从 Config 注入 supported_content_types，加入提示词约束
        supported_content_types = self._get_supported_content_types()
        user_content = self._build_user_content(
            topic, source_urls, supported_content_types
        )
        messages = self._build_messages(user_content)

        result, llm_resp = self.llm.chat_json(
            self.model, messages, DiscoveryCandidates
        )

        version = self.store.get_latest_version(run_id, "discovery_candidates") + 1
        output_ref = self.store.save_artifact(
            run_id, "discovery_candidates", result.model_dump(), version
        )

        self._log(
            run_id=run_id,
            stage="DISCOVERING",
            agent_name="DiscoveryAgent",
            input_refs=source_urls if source_urls else ["hot_discovery"],
            output_ref=output_ref,
            llm_resp=llm_resp,
            decision=f"生成{len(result.candidates)}个候选话题",
            reasons=[c.title for c in result.candidates],
        )

        return result

    def _build_user_content(
        self,
        topic: str,
        source_urls: List[str],
        supported_content_types: Optional[List[str]] = None,
    ) -> str:
        parts = []
        if topic and topic.strip():
            parts.append(f"用户线索：{topic}")
        else:
            parts.append("用户未提供线索，进入热点发现模式，请基于近期 AI 产品/趋势生成候选。")
        if source_urls:
            parts.append("参考链接：\n" + "\n".join(f"- {u}" for u in source_urls))
        if supported_content_types:
            parts.append(
                "content_type 约束：5个候选的 content_type 必须从以下列表中选择，"
                f"不得使用列表外的值：{supported_content_types}"
            )
        parts.append("请输出5个候选话题的 JSON。")
        return "\n\n".join(parts)

    @staticmethod
    def _get_supported_content_types() -> List[str]:
        """从 Config 读取 supported_content_types，失败时回退到默认值。"""
        try:
            from ..config import config
            return list(config.supported_content_types)
        except Exception:
            return ["product_breakdown", "trend_analysis"]
