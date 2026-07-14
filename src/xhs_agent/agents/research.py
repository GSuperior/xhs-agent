"""研究取证 Agent。

职责：搜索策略、证据提取、claim 组织。不写小红书文案。
输入：TopicBrief（含 research_questions）
输出：EvidencePack（claims 列表 + sources 列表 + uncertainties）

Phase 1A 行为：
- 优先用工具层 Fetcher 抓取网页。
- 如果无网络或抓取失败，用 LLM 自身知识生成（confidence 标注为 medium/low）。
"""

import time
from pathlib import Path
from typing import List, Optional

from ..schemas.content import TopicBrief
from ..schemas.evidence import EvidencePack, Source
from ..tools.fetch import Fetcher, FetchResult
from .base import BaseAgent


class ResearchAgent(BaseAgent):
    """研究取证 Agent，只负责收集事实，不写文案。"""

    def get_system_prompt(self) -> str:
        return """你是研究取证 Agent，只负责收集事实，不写小红书文案。

## 核心规则
1. evidence_pack 只包含外部 Claim，provenance 不含 creator（博主观点走 editorial_thesis）。
2. 每个 claim 必须有 epistemic_type/content_role/provenance。
3. 每个 claim 的 source_ids 中每个 source 必须有对应 evidence_snippet。
4. 官方功能 factual 只需1个一手来源；趋势 trend 至少2个独立来源（EVIDENCE_007）。
5. 证据不足时写入 uncertainties，不作为核心 Claim。
6. 博主观点不在这里生成。

## 枚举值（严格区分，不可混用）
- epistemic_type（这句话是什么性质）: factual（事实）/ interpretive（解读）/ projective（预测）/ experiential（体验）
  注意：trend 不是 epistemic_type，trend 是 content_role
- content_role（这句话在笔记中承担什么作用）: core（核心）/ background（背景）/ comparison（对比）/ limitation（局限）/ case（案例）/ trend（趋势）
- provenance（观点来自哪里）: official / media / community / user（不含 creator）
- source_type: primary / media / user / community
- confidence: high / medium / low

### 枚举值使用示例
- "OpenAI在2026年3月发布了Operator" → epistemic_type=factual, content_role=core, provenance=official
- "Agent产品化进入深水区" → epistemic_type=interpretive, content_role=trend, provenance=media
- "到2027年Agent将取代30%的重复劳动" → epistemic_type=projective, content_role=trend, provenance=media
- "用户反馈Agent经常忘记上下文" → epistemic_type=experiential, content_role=case, provenance=user

## 证据要求分级（EVIDENCE_007）
| 判断类型 | 证据要求 |
|---|---|
| 纯价值偏好 | 可以无引用 |
| 产品设计建议 | 建议关联至少1条事实依据 |
| 原因解释 | 至少关联1-2条支持 Claim |
| 趋势预测 | 外部 trend/projective Claim 至少2个独立来源；证据不足时写入 uncertainties |
| 行业结论 | 不得仅凭个人观点生成 |

## Source 结构要求
- source_id：唯一标识
- publisher：发布方
- url：来源链接
- published_at：发布时间（可为 null）
- updated_at：更新时间（可为 null）
- accessed_at：访问时间（必填，格式 YYYY-MM-DDTHH:MM:SS）
- version_or_commit：版本或 commit（可为 null）
- source_type：primary / media / user / community
- snapshot_ref：来源快照路径
- content_hash：内容哈希

## Claim 结构要求
- claim_id：唯一标识（如 c1, c2）
- claim：事实陈述
- epistemic_type / content_role / provenance：枚举值
- source_ids：引用的 source_id 列表（每个必须有对应 evidence_snippet）
- context_source_ids：背景来源（不要求 snippet）
- evidence_snippets：原文摘录列表（含 source_id/snippet/location）
- confidence：high/medium/low
- confidence_reason：置信度原因
- time_scope：时间范围（如"截至2026-07-13"）
- applicability：适用范围（如"仅适用于Pro版本"）

## 无网络时的行为
如果上下文中没有提供已抓取的来源（标记为 LLM_KNOWLEDGE_MODE），请用你自身的知识生成 EvidencePack：
- confidence 必须为 medium 或 low（不得为 high）
- source 的 url 填你已知的真实链接，publisher 填发布方
- snapshot_ref 填 "llm_knowledge"
- content_hash 填 "llm_knowledge:<source_id>"
- 在 uncertainties 中注明"基于模型知识生成，未经实时验证"

## 输出格式
输出 JSON，顶层为 EvidencePack 结构：
{
  "topic": "...",
  "event_time": "2026-07-13" 或 null,
  "claims": [...],
  "sources": [...],
  "uncertainties": [...],
  "content_opportunities": [...]
}

只输出 JSON，不要额外解释。"""

    def execute(
        self,
        run_id: str,
        topic_brief: TopicBrief,
        source_urls: Optional[List[str]] = None,
        fetcher: Optional[Fetcher] = None,
    ) -> EvidencePack:
        """根据 TopicBrief 收集证据，生成 EvidencePack。

        Args:
            run_id: Run ID。
            topic_brief: 选题简报，含 research_questions。
            source_urls: 额外参考链接（可选，如来自 SelectedTopic）。
            fetcher: 可选的 Fetcher 实例。为 None 时自动创建。
        """
        source_urls = source_urls or []
        snapshot_dir = str(Path(self.store.runs_dir) / run_id / "sources")
        fetcher = fetcher or Fetcher(snapshot_dir=snapshot_dir)

        fetched = self._fetch_sources(fetcher, topic_brief, source_urls)

        context = self._build_context(topic_brief, fetched)
        user_content = self._build_user_content(topic_brief, fetched)

        messages = self._build_messages(user_content, context)

        result, llm_resp = self.llm.chat_json(
            self.model, messages, EvidencePack
        )

        result = self._merge_fetched_sources(result, fetched)

        version = self.store.get_latest_version(run_id, "evidence_pack") + 1
        output_ref = self.store.save_artifact(
            run_id, "evidence_pack", result.model_dump(), version
        )

        warnings = []
        if not fetched:
            warnings.append("无网络抓取，基于LLM知识生成，confidence为medium/low")

        self._log(
            run_id=run_id,
            stage="RESEARCHING",
            agent_name="ResearchAgent",
            input_refs=["topic_brief"] + source_urls,
            output_ref=output_ref,
            llm_resp=llm_resp,
            decision=f"生成EvidencePack（{len(result.claims)}个claim，{len(result.sources)}个source）",
            reasons=[c.claim_id for c in result.claims],
            warnings=warnings or None,
        )

        return result

    def _fetch_sources(
        self,
        fetcher: Fetcher,
        topic_brief: TopicBrief,
        source_urls: List[str],
    ) -> List[FetchResult]:
        """尝试抓取来源。失败时返回空列表（由 LLM 知识兜底）。"""
        results: List[FetchResult] = []

        urls_to_fetch = list(source_urls)
        queries = self._build_search_queries(topic_brief)
        for q in queries:
            try:
                search_results = fetcher.search_web(q, max_results=3)
                for r in search_results:
                    url = r.get("url", "")
                    if url and url not in urls_to_fetch:
                        urls_to_fetch.append(url)
            except Exception:
                continue

        for url in urls_to_fetch[:5]:
            try:
                result = fetcher.fetch_url(url)
                results.append(result)
            except Exception:
                continue

        return results

    def _build_search_queries(self, topic_brief: TopicBrief) -> List[str]:
        queries = [topic_brief.topic]
        for q in topic_brief.research_questions[:3]:
            queries.append(f"{topic_brief.topic} {q}")
        return queries

    def _build_context(
        self, topic_brief: TopicBrief, fetched: List[FetchResult]
    ) -> str:
        brief_json = topic_brief.model_dump_json(indent=2)
        parts = [f"## TopicBrief\n{brief_json}"]

        if fetched:
            parts.append("## 已抓取的来源（请用这些 source_id 引用）")
            for fr in fetched:
                text_excerpt = fr.text[:1500] if fr.text else ""
                parts.append(
                    f"### source_id: {fr.source_id}\n"
                    f"- url: {fr.url}\n"
                    f"- title: {fr.title or ''}\n"
                    f"- published_at: {fr.published_at or ''}\n"
                    f"- accessed_at: {fr.accessed_at}\n"
                    f"- snapshot_ref: {fr.snapshot_ref}\n"
                    f"- content_hash: {fr.content_hash}\n"
                    f"- source_type: {fr.source_type}\n"
                    f"- 原文摘录:\n{text_excerpt}"
                )
        else:
            parts.append(
                "## LLM_KNOWLEDGE_MODE\n"
                "未抓取到任何外部来源（无网络或搜索失败）。"
                "请用你自身的知识生成 EvidencePack，confidence 必须为 medium 或 low，"
                "并在 uncertainties 中注明未经实时验证。"
            )

        return "\n\n".join(parts)

    def _build_user_content(
        self, topic_brief: TopicBrief, fetched: List[FetchResult]
    ) -> str:
        mode = "有已抓取来源模式" if fetched else "LLM知识兜底模式"
        questions = "\n".join(f"- {q}" for q in topic_brief.research_questions)
        return (
            f"请根据 TopicBrief 生成 EvidencePack（当前为{mode}）。\n\n"
            f"研究问题：\n{questions or '（未指定，请根据主题自行拟定）'}\n\n"
            f"{'请引用上下文中提供的 source_id，并为每个 source_ids 中的 source 生成 evidence_snippet。' if fetched else '请用你自身知识生成 sources 和 claims，confidence 为 medium/low。'}\n"
            f"趋势类 claim 至少2个独立来源；证据不足写入 uncertainties。"
        )

    def _merge_fetched_sources(
        self, evidence_pack: EvidencePack, fetched: List[FetchResult]
    ) -> EvidencePack:
        """用真实抓取数据覆盖 LLM 生成的 Source 字段。"""
        if not fetched:
            self._fill_llm_source_fields(evidence_pack)
            return evidence_pack

        fetched_map = {fr.source_id: fr for fr in fetched}
        new_sources: List[Source] = []
        for src in evidence_pack.sources:
            if src.source_id in fetched_map:
                fr = fetched_map[src.source_id]
                new_sources.append(
                    Source(
                        source_id=fr.source_id,
                        publisher=src.publisher or self._infer_publisher(fr),
                        url=fr.url,
                        published_at=fr.published_at,
                        updated_at=None,
                        accessed_at=fr.accessed_at,
                        version_or_commit=None,
                        source_type=fr.source_type,
                        snapshot_ref=fr.snapshot_ref,
                        content_hash=fr.content_hash,
                    )
                )
            else:
                new_sources.append(src)
        self._fill_llm_source_fields_for_list(new_sources)
        evidence_pack.sources = new_sources
        return evidence_pack

    def _infer_publisher(self, fr: FetchResult) -> str:
        if fr.title:
            return fr.title[:80]
        from urllib.parse import urlparse

        return urlparse(fr.url).netloc or fr.url

    def _fill_llm_source_fields(self, evidence_pack: EvidencePack) -> None:
        self._fill_llm_source_fields_for_list(evidence_pack.sources)

    def _fill_llm_source_fields_for_list(self, sources: List[Source]) -> None:
        for src in sources:
            if not src.snapshot_ref or src.snapshot_ref == "":
                src.snapshot_ref = "llm_knowledge"
            if not src.content_hash or src.content_hash == "":
                src.content_hash = "llm_knowledge:" + src.source_id
            if not src.accessed_at:
                src.accessed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
