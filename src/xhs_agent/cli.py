"""xhs_agent CLI 命令入口。

用户交互的主要入口，用 typer + rich 实现美观的终端界面。
封装完整14态主链路：INIT → DISCOVERING → TOPIC_ANGLE_CONFIRMATION →
RESEARCHING → EVIDENCE_REVIEW → OUTLINING → OUTLINE_CONFIRMATION →
DRAFTING → CONTENT_REVIEW → VISUAL_PLANNING → LAYOUT_REVIEW →
RENDERING → RENDER_VALIDATION → FINAL_CONFIRMATION → COMPLETED。
"""

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown

from .config import Config
from .controller import Controller
from .agents import (
    DiscoveryAgent,
    DiscoveryCandidates,
    ResearchAgent,
    PlanningAgent,
    WritingAgent,
    VisualAgent,
    ReviewerAgent,
)
from .tools import (
    LLMClient,
    Renderer,
    SchemaValidator,
    ReferenceValidator,
    RenderValidator,
)
from .schemas.common import RunState, ReviewerMode, ReviewStatus, Severity
from .schemas.content import (
    AngleHypothesis,
    CardOutline,
    Draft,
    SelectedTopic,
    TopicBrief,
)
from .schemas.evidence import EvidencePack
from .schemas.visual import AvailableAssets, LayoutSpec, AssetManifest

app = typer.Typer(
    name="xhs-agent",
    help="小红书 AI 内容 Agent CLI — 从选题到终稿的产前闭环",
    no_args_is_help=True,
)
console = Console()


class XHSAgent:
    """CLI 流程编排主类，封装完整14态主链路。"""

    def __init__(self):
        self.config = Config()
        self.llm = LLMClient()
        self.controller = Controller(self.llm)
        self.store = self.controller.store
        self.renderer = Renderer()
        self.schema_validator = SchemaValidator()
        self.reference_validator = ReferenceValidator()
        self.render_validator = RenderValidator()

        # 初始化6个 Agent，传入对应模型名
        self.topic_agent = DiscoveryAgent(
            self.llm, self.controller.logger, self.store,
            model=self.config.get_model_name("topic"),
        )
        self.research_agent = ResearchAgent(
            self.llm, self.controller.logger, self.store,
            model=self.config.get_model_name("research"),
        )
        self.planning_agent = PlanningAgent(
            self.llm, self.controller.logger, self.store,
            model=self.config.get_model_name("planning"),
        )
        self.writing_agent = WritingAgent(
            self.llm, self.controller.logger, self.store,
            model=self.config.get_model_name("writing"),
        )
        self.visual_agent = VisualAgent(
            self.llm, self.controller.logger, self.store,
            model=self.config.get_model_name("visual_planning"),
        )
        self.reviewer_agent = ReviewerAgent(
            self.llm, self.controller.logger, self.store,
            model=self.config.get_model_name("review"),
        )

    # ==================================================================
    # 状态持久化
    # ==================================================================

    def _save_state(self, run_id: str):
        """保存 Controller 状态到 run 目录的 state.json。"""
        state_info = self.controller.get_state_info()
        state_path = Path(self.store.runs_dir) / run_id / "state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(state_info, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_state(self, run_id: str) -> Optional[dict]:
        """从 run 目录加载 Controller 状态。"""
        state_path = Path(self.store.runs_dir) / run_id / "state.json"
        if not state_path.exists():
            return None
        return json.loads(state_path.read_text(encoding="utf-8"))

    def _restore_controller(self, run_id: str) -> Optional[dict]:
        """恢复 Controller 状态。"""
        state_info = self._load_state(run_id)
        if state_info:
            self.controller.run_id = run_id
            self.controller.state = RunState(state_info.get("state", "INIT"))
            self.controller.research_count = state_info.get("research_count", 0)
            self.controller.outline_revise_count = state_info.get("outline_revise_count", 0)
            self.controller.copy_revise_count = state_info.get("copy_revise_count", 0)
            self.controller.layout_revise_count = state_info.get("layout_revise_count", 0)
            self.controller.render_retry_count = state_info.get("render_retry_count", 0)
        return state_info

    # ==================================================================
    # Artifact 加载
    # ==================================================================

    def _load_artifact_model(self, run_id: str, name: str, model_class):
        """加载 artifact 并转为 Pydantic 模型。"""
        data = self.store.load_artifact(run_id, name)
        if data is None:
            return None
        return model_class.model_validate(data)

    def _save_artifact(self, run_id: str, name: str, data) -> str:
        """保存 artifact（Pydantic 模型或 dict）。"""
        version = self.store.get_latest_version(run_id, name) + 1
        if hasattr(data, "model_dump"):
            payload = data.model_dump()
        else:
            payload = data
        return self.store.save_artifact(run_id, name, payload, version)

    # ==================================================================
    # TopicBrief 构建
    # ==================================================================

    def _build_topic_brief(self, selected: SelectedTopic) -> TopicBrief:
        """从 SelectedTopic 构建 TopicBrief（确定性映射）。"""
        return TopicBrief(
            topic=selected.title,
            target_reader=selected.target_audience,
            reader_problem=selected.what_happened,
            one_sentence_value=selected.why_now,
            core_angle=selected.product_angle,
            content_type=selected.content_type,
            content_type_label=selected.content_type_label,
            topic_subtype=selected.topic_subtype,
            hook=selected.why_now,
            expected_takeaway=[],
            differentiation=selected.product_angle,
            avoid=[],
            research_questions=[],
            angle_hypothesis=AngleHypothesis(
                statement=selected.product_angle,
                questions_to_verify=[],
            ),
        )

    # ==================================================================
    # 显示辅助
    # ==================================================================

    def _display_candidates(self, result: DiscoveryCandidates):
        """用 rich 表格展示候选话题。"""
        table = Table(title="候选话题列表", show_lines=True)
        table.add_column("ID", style="cyan bold", width=6)
        table.add_column("标题", style="white", width=40)
        table.add_column("栏目", style="magenta", width=10)
        table.add_column("分享值", style="green", width=8)
        table.add_column("证据质量", style="yellow", width=8)
        table.add_column("生命周期", style="blue", width=10)

        for c in result.candidates:
            table.add_row(
                c.topic_id,
                c.title[:40],
                c.content_type_label,
                f"{c.shareability:.2f}",
                f"{c.evidence_quality:.2f}",
                c.lifecycle.value,
            )
        console.print(table)

    def _display_outline(self, outline: CardOutline):
        """展示卡片大纲。"""
        thesis = outline.editorial_thesis
        console.print(Panel(
            f"[bold]博主判断:[/] {thesis.statement}\n"
            f"[bold]置信度:[/] {thesis.certainty}\n"
            f"[bold]支撑claim:[/] {', '.join(thesis.supporting_claim_refs) or '无'}",
            title="Editorial Thesis",
            border_style="green",
        ))

        table = Table(title="卡片大纲", show_lines=True)
        table.add_column("卡片ID", style="cyan bold", width=10)
        table.add_column("用途", style="white", width=20)
        table.add_column("中心信息", style="yellow", width=50)
        table.add_column("视觉类型", style="magenta", width=15)

        for card in outline.cards:
            table.add_row(
                card.card_id,
                card.purpose,
                card.key_message[:50],
                card.visual_type,
            )
        console.print(table)

    def _display_draft(self, draft: Draft):
        """展示文案 Draft。"""
        # 标题候选
        if draft.post_title_candidates:
            titles = "\n".join(
                f"  {i+1}. {t.text}" for i, t in enumerate(draft.post_title_candidates)
            )
            console.print(Panel(titles, title="标题候选", border_style="cyan"))

        # 封面
        cover = draft.cover
        console.print(Panel(
            f"[bold]栏目前缀:[/] {cover.series_label}\n"
            f"[bold]主标题:[/] {cover.main_title}\n"
            f"[bold]副标题:[/] {cover.subtitle.text}",
            title="封面",
            border_style="magenta",
        ))

        # 卡片文案
        card_blocks = [b for b in draft.blocks if b.surface == "card"]
        if card_blocks:
            table = Table(title="卡片文案", show_lines=True)
            table.add_column("卡片ID", style="cyan", width=10)
            table.add_column("文案", style="white", width=80)
            for b in card_blocks:
                table.add_row(b.card_id or "", b.text[:80])
            console.print(table)

        # 正文摘要
        body_preview = draft.body_text[:200] + "..." if len(draft.body_text) > 200 else draft.body_text
        console.print(Panel(body_preview, title="正文摘要", border_style="blue"))

        # 标签
        if draft.tags:
            console.print(f"[bold]标签:[/] {' '.join(draft.tags)}")

    def _display_review_result(self, result):
        """展示审核结果。"""
        status_colors = {
            ReviewStatus.PASS: "green",
            ReviewStatus.REVISE: "yellow",
            ReviewStatus.BLOCKED: "red",
            ReviewStatus.FAILED: "bold red",
        }
        color = status_colors.get(result.status, "white")
        console.print(Panel(
            f"[{color}]状态: {result.status.value}[/{color}]\n"
            f"[bold]问题类型:[/] {result.issue_type.value if result.issue_type else '无'}\n"
            f"[bold]路由:[/] {result.route_to or '无'}\n"
            f"[bold]严重度:[/] {result.severity.value}",
            title=f"审核结果",
            border_style=color,
        ))

        if result.issues:
            table = Table(title="审核问题", show_lines=True)
            table.add_column("规则ID", style="cyan", width=15)
            table.add_column("位置", style="white", width=20)
            table.add_column("问题", style="yellow", width=40)
            table.add_column("严重度", style="red", width=10)
            table.add_column("建议", style="green", width=30)
            for issue in result.issues:
                table.add_row(
                    issue.rule_id,
                    issue.location[:20],
                    issue.problem[:40],
                    issue.severity.value,
                    issue.suggested_action[:30],
                )
            console.print(table)

    # ==================================================================
    # 用户交互
    # ==================================================================

    def _prompt_input(self, prompt: str) -> str:
        """安全读取用户输入，处理 EOFError。"""
        try:
            return input(prompt).strip()
        except EOFError:
            console.print("\n[yellow]输入结束（非交互环境），流程中止。[/]")
            raise typer.Exit(1)

    def _prompt_select(self, result: DiscoveryCandidates) -> SelectedTopic:
        """提示用户选择话题。"""
        console.print("\n[bold]请选择一个话题（输入 topic_id，如 t1）:[/]")
        while True:
            choice = self._prompt_input("topic_id> ")
            for c in result.candidates:
                if c.topic_id == choice:
                    selected = SelectedTopic(
                        topic_id=c.topic_id,
                        title=c.title,
                        source_urls=c.source_urls,
                        published_at=c.published_at,
                        what_happened=c.what_happened,
                        target_audience=c.target_audience,
                        product_angle=c.product_angle,
                        why_now=c.why_now,
                        lifecycle=c.lifecycle,
                        valid_until=c.valid_until,
                        content_type=c.content_type,
                        content_type_label=c.content_type_label,
                        topic_subtype=c.topic_subtype,
                    )
                    console.print(f"\n[green]已选择: {selected.title}[/]")
                    return selected
            console.print(f"[red]未找到 topic_id={choice}，请重试。[/]")

    def _prompt_confirm(self, stage_name: str) -> str:
        """提示用户确认。返回 'confirm' / 'revise' / 'abort'。"""
        console.print(f"\n[bold]请确认{stage_name}:[/]")
        console.print("  [green]confirm[/] — 确认通过，继续下一步")
        console.print("  [yellow]revise[/] — 需要修改（会重新生成）")
        console.print("  [red]abort[/]   — 终止流程")
        while True:
            choice = self._prompt_input("> ").lower()
            if choice in ("confirm", "revise", "abort"):
                return choice
            console.print("[red]请输入 confirm / revise / abort[/]")

    # ==================================================================
    # 审核流程
    # ==================================================================

    def _run_evidence_review(self, run_id: str, evidence_pack: EvidencePack):
        """运行证据审核：Schema + Reference + ReviewerAgent。"""
        # Schema 校验
        schema_result = self.schema_validator.validate_evidence(
            evidence_pack.model_dump()
        )
        if not schema_result:
            console.print("[red]Schema 校验失败:[/]")
            for err in schema_result.errors:
                console.print(f"  - {err[:120]}")
            return None

        # Reference 校验
        ref_result = self.reference_validator.validate_evidence_pack(evidence_pack)
        if not ref_result:
            console.print("[yellow]引用校验警告:[/]")
            for err in ref_result.errors:
                console.print(f"  - {err[:120]}")

        # ReviewerAgent (evidence 模式)
        review_result = self.reviewer_agent.execute(
            run_id, ReviewerMode.EVIDENCE, evidence_pack=evidence_pack
        )
        self._display_review_result(review_result)
        return review_result

    def _run_content_review(
        self, run_id: str, card_outline: CardOutline,
        evidence_pack: EvidencePack, draft: Draft,
    ):
        """运行内容审核：Schema + Reference + 软规则 + ReviewerAgent。"""
        schema_result = self.schema_validator.validate_draft(draft.model_dump())
        if not schema_result:
            console.print("[red]Schema 校验失败:[/]")
            for err in schema_result.errors:
                console.print(f"  - {err[:120]}")
            return None

        ref_result = self.reference_validator.validate_draft(draft, evidence_pack)
        if not ref_result:
            console.print("[yellow]引用校验警告:[/]")
            for err in ref_result.errors:
                console.print(f"  - {err[:120]}")

        # 软规则校验：不阻断，但提示 Reviewer 重点关注
        enhanced_result = self.schema_validator.validate_draft_enhanced(
            draft, card_outline
        )
        if not enhanced_result:
            console.print("[yellow]内容软规则校验警告（请 Reviewer 重点关注）:[/]")
            for err in enhanced_result.errors:
                console.print(f"  - {err[:120]}")

        review_result = self.reviewer_agent.execute(
            run_id, ReviewerMode.CONTENT,
            evidence_pack=evidence_pack,
            card_outline=card_outline,
            draft=draft,
        )
        self._display_review_result(review_result)
        return review_result

    def _run_layout_review(
        self, run_id: str, layout_spec: LayoutSpec, draft: Draft,
    ):
        """运行布局审核：ReviewerAgent (layout 模式)。"""
        review_result = self.reviewer_agent.execute(
            run_id, ReviewerMode.LAYOUT,
            layout_spec=layout_spec,
            draft=draft,
        )
        self._display_review_result(review_result)
        return review_result

    def _handle_review_failure(self, run_id: str, result, stage_name: str) -> bool:
        """处理审核未通过的情况。返回 True 表示可继续，False 表示中止。"""
        if result.status == ReviewStatus.PASS:
            return True
        elif result.status == ReviewStatus.REVISE:
            console.print(f"[yellow]{stage_name}审核需返工: route_to={result.route_to}[/]")
            console.print("[yellow]将重新生成产物...[/]")
            return False
        elif result.status == ReviewStatus.BLOCKED:
            console.print(f"[red]{stage_name}审核被阻断，需人工介入。[/]")
            return False
        elif result.status == ReviewStatus.FAILED:
            console.print(f"[bold red]{stage_name}审核失败（不可恢复），流程终止。[/]")
            self.controller.transition(RunState.FAILED)
            self._save_state(run_id)
            return False
        return False

    # ==================================================================
    # 主流程：create
    # ==================================================================

    def create(self, topic: str):
        """创建新笔记流程（完整14态主链路）。"""
        # INIT → DISCOVERING
        run_id = self.controller.start(topic)
        self._save_state(run_id)
        console.print(Panel(
            f"[bold green]Run 创建成功[/]\nRun ID: [cyan]{run_id}[/]\n主题: [white]{topic}[/]",
            title="开始创建", border_style="green",
        ))

        # === DISCOVERING: 调用 TopicAgent ===
        console.print("\n[bold blue]═══ 阶段1: 选题发现 ═══[/]")
        try:
            candidates_result = self.topic_agent.execute(run_id, topic=topic)
        except Exception as e:
            console.print(f"[red]选题发现失败: {e}[/]")
            self.controller.transition(RunState.FAILED)
            self._save_state(run_id)
            return
        self._display_candidates(candidates_result)

        # === TOPIC_ANGLE_CONFIRMATION: 等待用户 select ===
        self.controller.transition(RunState.TOPIC_ANGLE_CONFIRMATION)
        self._save_state(run_id)
        selected = self._prompt_select(candidates_result)

        # 保存 selected_topic + topic_brief
        self._save_artifact(run_id, "selected_topic", selected)
        topic_brief = self._build_topic_brief(selected)
        self._save_artifact(run_id, "topic_brief", topic_brief)

        # 继续后续流程
        self._run_research_to_outline(run_id, topic_brief, selected.source_urls)

    def _run_research_to_outline(
        self, run_id: str, topic_brief: TopicBrief, source_urls: list = None,
    ):
        """运行 RESEARCHING → EVIDENCE_REVIEW → OUTLINING → OUTLINE_CONFIRMATION。"""
        source_urls = source_urls or []

        # === RESEARCHING: 调用 ResearchAgent ===
        self.controller.transition(RunState.RESEARCHING)
        self._save_state(run_id)
        console.print("\n[bold blue]═══ 阶段2: 研究取证 ═══[/]")
        try:
            evidence_pack = self.research_agent.execute(
                run_id, topic_brief, source_urls=source_urls
            )
        except Exception as e:
            console.print(f"[red]研究取证失败: {e}[/]")
            self.controller.transition(RunState.FAILED)
            self._save_state(run_id)
            return

        console.print(Panel(
            f"Claims: {len(evidence_pack.claims)} 个\n"
            f"Sources: {len(evidence_pack.sources)} 个\n"
            f"Uncertainties: {len(evidence_pack.uncertainties)} 条",
            title="EvidencePack 摘要", border_style="blue",
        ))

        # === EVIDENCE_REVIEW: Schema + Reference + ReviewerAgent ===
        self.controller.transition(RunState.EVIDENCE_REVIEW)
        self._save_state(run_id)
        console.print("\n[bold blue]═══ 阶段3: 证据审核 ═══[/]")
        review_result = self._run_evidence_review(run_id, evidence_pack)

        if review_result is None or not self._handle_review_failure(
            run_id, review_result, "证据"
        ):
            if review_result and review_result.status == ReviewStatus.REVISE:
                if self.controller.can_research():
                    console.print("[yellow]重新研究取证...[/]")
                    evidence_pack = self.research_agent.execute(
                        run_id, topic_brief, source_urls=source_urls
                    )
                    review_result = self._run_evidence_review(run_id, evidence_pack)
                    if not self._handle_review_failure(run_id, review_result, "证据(重试)"):
                        return
                else:
                    console.print("[red]研究重试预算耗尽，进入人工审核。[/]")
                    self.controller.transition(RunState.HUMAN_REVIEW)
                    self._save_state(run_id)
                    return
            else:
                return

        # === OUTLINING: 调用 PlanningAgent ===
        self.controller.transition(RunState.OUTLINING)
        self._save_state(run_id)
        console.print("\n[bold blue]═══ 阶段4: 内容规划 ═══[/]")
        try:
            card_outline = self.planning_agent.execute(
                run_id, topic_brief, evidence_pack
            )
        except Exception as e:
            console.print(f"[red]内容规划失败: {e}[/]")
            self.controller.transition(RunState.FAILED)
            self._save_state(run_id)
            return
        self._display_outline(card_outline)

        # === OUTLINE_CONFIRMATION: 等待用户确认 ===
        self.controller.transition(RunState.OUTLINE_CONFIRMATION)
        self._save_state(run_id)
        action = self._prompt_confirm("大纲")
        if action == "abort":
            console.print("[red]流程已中止。[/]")
            self.controller.transition(RunState.FAILED)
            self._save_state(run_id)
            return
        elif action == "revise":
            if self.controller.can_revise_outline():
                console.print("[yellow]重新生成大纲...[/]")
                card_outline = self.planning_agent.execute(
                    run_id, topic_brief, evidence_pack
                )
                self._display_outline(card_outline)
            else:
                console.print("[yellow]大纲修改预算耗尽，继续下一步。[/]")

        # 继续后续流程
        self._run_draft_to_final(run_id, topic_brief, evidence_pack, card_outline)

    def _run_draft_to_final(
        self, run_id: str, topic_brief: TopicBrief,
        evidence_pack: EvidencePack, card_outline: CardOutline,
    ):
        """运行 DRAFTING → CONTENT_REVIEW → VISUAL_PLANNING → LAYOUT_REVIEW →
        RENDERING → RENDER_VALIDATION → FINAL_CONFIRMATION → COMPLETED。"""

        # === DRAFTING: 调用 WritingAgent ===
        self.controller.transition(RunState.DRAFTING)
        self._save_state(run_id)
        console.print("\n[bold blue]═══ 阶段5: 文案撰写 ═══[/]")
        try:
            draft = self.writing_agent.execute(
                run_id, card_outline, evidence_pack, topic_brief
            )
        except Exception as e:
            console.print(f"[red]文案撰写失败: {e}[/]")
            self.controller.transition(RunState.FAILED)
            self._save_state(run_id)
            return
        self._display_draft(draft)

        # === CONTENT_REVIEW: Schema + Reference + ReviewerAgent ===
        self.controller.transition(RunState.CONTENT_REVIEW)
        self._save_state(run_id)
        console.print("\n[bold blue]═══ 阶段6: 内容审核 ═══[/]")
        review_result = self._run_content_review(
            run_id, card_outline, evidence_pack, draft
        )

        if review_result is None or not self._handle_review_failure(
            run_id, review_result, "内容"
        ):
            if review_result and review_result.status == ReviewStatus.REVISE:
                if self.controller.can_revise_copy():
                    console.print("[yellow]重新撰写文案...[/]")
                    draft = self.writing_agent.execute(
                        run_id, card_outline, evidence_pack, topic_brief
                    )
                    self._display_draft(draft)
                    review_result = self._run_content_review(
                        run_id, card_outline, evidence_pack, draft
                    )
                    if not self._handle_review_failure(run_id, review_result, "内容(重试)"):
                        return
                else:
                    console.print("[red]文案修改预算耗尽，进入人工审核。[/]")
                    self.controller.transition(RunState.HUMAN_REVIEW)
                    self._save_state(run_id)
                    return
            else:
                return

        # === VISUAL_PLANNING: 调用 VisualAgent ===
        self.controller.transition(RunState.VISUAL_PLANNING)
        self._save_state(run_id)
        console.print("\n[bold blue]═══ 阶段7: 视觉规划 ═══[/]")
        available_assets = AvailableAssets(available_assets=[])
        try:
            visual_plan = self.visual_agent.execute(
                run_id, card_outline, draft,
                available_assets, self.config.design_token,
            )
        except Exception as e:
            console.print(f"[red]视觉规划失败: {e}[/]")
            self.controller.transition(RunState.FAILED)
            self._save_state(run_id)
            return
        console.print(Panel(
            f"模板: {visual_plan.layout_spec.template}\n"
            f"卡片数: {len(visual_plan.layout_spec.cards)}\n"
            f"素材数: {len(visual_plan.asset_manifest.assets)}",
            title="VisualPlan 摘要", border_style="magenta",
        ))

        # === LAYOUT_REVIEW: ReviewerAgent (layout 模式) ===
        self.controller.transition(RunState.LAYOUT_REVIEW)
        self._save_state(run_id)
        console.print("\n[bold blue]═══ 阶段8: 布局审核 ═══[/]")
        review_result = self._run_layout_review(
            run_id, visual_plan.layout_spec, draft
        )

        if review_result is None or not self._handle_review_failure(
            run_id, review_result, "布局"
        ):
            if review_result and review_result.status == ReviewStatus.REVISE:
                if self.controller.can_revise_layout():
                    console.print("[yellow]重新视觉规划...[/]")
                    visual_plan = self.visual_agent.execute(
                        run_id, card_outline, draft,
                        available_assets, self.config.design_token,
                    )
                    review_result = self._run_layout_review(
                        run_id, visual_plan.layout_spec, draft
                    )
                    if not self._handle_review_failure(run_id, review_result, "布局(重试)"):
                        return
                else:
                    console.print("[red]布局修改预算耗尽，进入人工审核。[/]")
                    self.controller.transition(RunState.HUMAN_REVIEW)
                    self._save_state(run_id)
                    return
            else:
                return

        # === RENDERING: 调用 Renderer ===
        self.controller.transition(RunState.RENDERING)
        self._save_state(run_id)
        console.print("\n[bold blue]═══ 阶段9: 渲染 ═══[/]")
        try:
            html_content = self.renderer.render_html(
                visual_plan.layout_spec, draft,
                visual_plan.asset_manifest, self.config.design_token,
            )
            # 保存 HTML 到 output 目录
            run_dir = Path(self.store.runs_dir) / run_id
            html_path = run_dir / "output" / "note.html"
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(html_content, encoding="utf-8")
            console.print(f"[green]HTML 已保存: {html_path}[/]")
        except Exception as e:
            console.print(f"[red]渲染失败: {e}[/]")
            self.controller.transition(RunState.FAILED)
            self._save_state(run_id)
            return

        # === RENDER_VALIDATION: RenderValidator ===
        self.controller.transition(RunState.RENDER_VALIDATION)
        self._save_state(run_id)
        console.print("\n[bold blue]═══ 阶段10: 渲染校验 ═══[/]")
        render_result = self.render_validator.validate_html(
            html_content, self.config.design_token
        )
        if render_result:
            console.print("[green]渲染校验通过。[/]")
        else:
            console.print("[yellow]渲染校验警告:[/]")
            for err in render_result.errors:
                console.print(f"  - {err[:120]}")
            if self.controller.can_render():
                console.print("[yellow]继续流程（渲染警告不阻断）。[/]")
            else:
                console.print("[red]渲染重试预算耗尽。[/]")

        # === FINAL_CONFIRMATION: 等待用户确认 ===
        self.controller.transition(RunState.FINAL_CONFIRMATION)
        self._save_state(run_id)
        console.print(f"\n[bold]HTML 产物路径: [cyan]{html_path}[/][/]")
        action = self._prompt_confirm("终稿")
        if action == "abort":
            console.print("[red]流程已中止。[/]")
            self.controller.transition(RunState.FAILED)
            self._save_state(run_id)
            return

        # === COMPLETED ===
        self.controller.transition(RunState.COMPLETED)
        self._save_state(run_id)
        console.print(Panel(
            f"[bold green]✓ 流程完成！[/]\n"
            f"Run ID: [cyan]{run_id}[/]\n"
            f"HTML: [white]{html_path}[/]",
            title="完成", border_style="green",
        ))

    # ==================================================================
    # daily
    # ==================================================================

    def daily(self):
        """每日热点发现（输出5个候选，不自动生成完整笔记）。"""
        run_id = self.controller.start("daily_hot_discovery")
        self._save_state(run_id)
        console.print(Panel(
            f"[bold green]每日热点发现[/]\nRun ID: [cyan]{run_id}[/]",
            border_style="green",
        ))

        console.print("\n[bold blue]═══ 选题发现（热点模式）═══[/]")
        try:
            candidates_result = self.topic_agent.execute(run_id, topic="")
        except Exception as e:
            console.print(f"[red]选题发现失败: {e}[/]")
            self.controller.transition(RunState.FAILED)
            self._save_state(run_id)
            return
        self._display_candidates(candidates_result)

        # 进入 TOPIC_ANGLE_CONFIRMATION，等待用户 select
        self.controller.transition(RunState.TOPIC_ANGLE_CONFIRMATION)
        self._save_state(run_id)
        console.print(Panel(
            f"使用以下命令选择话题继续:\n"
            f"  [cyan]xhs-agent select {run_id} <topic_id>[/]",
            title="下一步", border_style="blue",
        ))

    # ==================================================================
    # select
    # ==================================================================

    def select(self, run_id: str, topic_id: str):
        """选中候选话题，然后继续后续流程。"""
        state_info = self._restore_controller(run_id)

        # 状态检查：只有 TOPIC_ANGLE_CONFIRMATION 允许选择话题。
        # 例外：state.json 不存在（首次 select）时允许放行，由后续流程自行报错。
        if state_info is not None:
            current_state = RunState(state_info.get("state", "INIT"))
            if current_state != RunState.TOPIC_ANGLE_CONFIRMATION:
                console.print(
                    f"[red]当前状态为 {current_state.value}，不允许选择话题。"
                    f"请从 daily 命令开始新流程。[/]"
                )
                return

        # 加载 discovery_candidates
        data = self.store.load_artifact(run_id, "discovery_candidates")
        if data is None:
            console.print(f"[red]Run {run_id} 未找到 discovery_candidates。[/]")
            return
        candidates_result = DiscoveryCandidates.model_validate(data)

        # 查找选中话题
        selected_candidate = None
        for c in candidates_result.candidates:
            if c.topic_id == topic_id:
                selected_candidate = c
                break
        if selected_candidate is None:
            console.print(f"[red]未找到 topic_id={topic_id}。[/]")
            console.print(f"[yellow]可用 topic_id: "
                         f"{', '.join(c.topic_id for c in candidates_result.candidates)}[/]")
            return

        # 转换为 SelectedTopic
        selected = SelectedTopic(
            topic_id=selected_candidate.topic_id,
            title=selected_candidate.title,
            source_urls=selected_candidate.source_urls,
            published_at=selected_candidate.published_at,
            what_happened=selected_candidate.what_happened,
            target_audience=selected_candidate.target_audience,
            product_angle=selected_candidate.product_angle,
            why_now=selected_candidate.why_now,
            lifecycle=selected_candidate.lifecycle,
            valid_until=selected_candidate.valid_until,
            content_type=selected_candidate.content_type,
            content_type_label=selected_candidate.content_type_label,
            topic_subtype=selected_candidate.topic_subtype,
        )
        self._save_artifact(run_id, "selected_topic", selected)

        # 构建 TopicBrief
        topic_brief = self._build_topic_brief(selected)
        self._save_artifact(run_id, "topic_brief", topic_brief)

        console.print(Panel(
            f"[green]已选择: {selected.title}[/]\n"
            f"栏目: {selected.content_type_label}",
            border_style="green",
        ))

        # 继续后续流程
        self._run_research_to_outline(run_id, topic_brief, selected.source_urls)

    # ==================================================================
    # confirm
    # ==================================================================

    def confirm(self, run_id: str):
        """确认当前节点（选题/大纲/终稿），继续流程。"""
        state_info = self._restore_controller(run_id)
        if state_info is None:
            console.print(f"[red]Run {run_id} 未找到状态文件。[/]")
            return

        current_state = RunState(state_info.get("state", "INIT"))
        console.print(f"[bold]当前状态: [cyan]{current_state.value}[/][/")

        if current_state == RunState.TOPIC_ANGLE_CONFIRMATION:
            console.print("[yellow]请使用 'xhs-agent select <run_id> <topic_id>' 选择话题。[/]")
            return

        if current_state == RunState.OUTLINE_CONFIRMATION:
            # 加载 artifacts 继续流程
            topic_brief = self._load_artifact_model(run_id, "topic_brief", TopicBrief)
            evidence_pack = self._load_artifact_model(run_id, "evidence_pack", EvidencePack)
            card_outline = self._load_artifact_model(run_id, "card_outline", CardOutline)
            if not all([topic_brief, evidence_pack, card_outline]):
                console.print("[red]缺少必要的 artifact，无法继续。[/]")
                return
            self._run_draft_to_final(run_id, topic_brief, evidence_pack, card_outline)
            return

        if current_state == RunState.FINAL_CONFIRMATION:
            # 直接标记完成
            self.controller.transition(RunState.COMPLETED)
            self._save_state(run_id)
            console.print("[green]终稿已确认，流程完成！[/]")
            html_path = Path(self.store.runs_dir) / run_id / "output" / "note.html"
            if html_path.exists():
                console.print(f"HTML 产物: [cyan]{html_path}[/]")
            return

        if current_state in (RunState.COMPLETED, RunState.FAILED):
            console.print(f"[yellow]流程已结束: {current_state.value}[/]")
            return

        console.print(f"[yellow]当前状态 {current_state.value} 不需要确认操作。[/]")

    # ==================================================================
    # revise
    # ==================================================================

    def revise(self, run_id: str, instruction: str):
        """用户修改指令，重新生成对应产物。"""
        state_info = self._restore_controller(run_id)
        if state_info is None:
            console.print(f"[red]Run {run_id} 未找到状态文件。[/]")
            return

        current_state = RunState(state_info.get("state", "INIT"))
        console.print(f"[bold]当前状态: [cyan]{current_state.value}[/][/]")
        console.print(f"[bold]修改指令: [yellow]{instruction}[//]")

        if current_state == RunState.OUTLINE_CONFIRMATION:
            # 重新生成大纲
            topic_brief = self._load_artifact_model(run_id, "topic_brief", TopicBrief)
            evidence_pack = self._load_artifact_model(run_id, "evidence_pack", EvidencePack)
            if not all([topic_brief, evidence_pack]):
                console.print("[red]缺少 topic_brief 或 evidence_pack。[/]")
                return
            if not self.controller.can_revise_outline():
                console.print("[red]大纲修改预算耗尽。[/]")
                return
            self.controller.outline_revise_count += 1
            console.print("[yellow]重新生成大纲...[/]")
            card_outline = self.planning_agent.execute(
                run_id, topic_brief, evidence_pack
            )
            self._display_outline(card_outline)
            self._save_state(run_id)
            console.print("[green]大纲已重新生成，使用 'xhs-agent confirm' 继续。[/]")

        elif current_state == RunState.FINAL_CONFIRMATION:
            # 重新生成文案
            topic_brief = self._load_artifact_model(run_id, "topic_brief", TopicBrief)
            evidence_pack = self._load_artifact_model(run_id, "evidence_pack", EvidencePack)
            card_outline = self._load_artifact_model(run_id, "card_outline", CardOutline)
            if not all([topic_brief, evidence_pack, card_outline]):
                console.print("[red]缺少必要的 artifact。[/]")
                return
            if not self.controller.can_revise_copy():
                console.print("[red]文案修改预算耗尽。[/]")
                return
            self.controller.copy_revise_count += 1
            console.print("[yellow]重新撰写文案...[/]")
            draft = self.writing_agent.execute(
                run_id, card_outline, evidence_pack, topic_brief
            )
            self._display_draft(draft)
            self._save_state(run_id)
            console.print("[green]文案已重新生成。[/]")

            # 重新渲染
            console.print("[yellow]重新渲染...[/]")
            available_assets = AvailableAssets(available_assets=[])
            visual_plan = self.visual_agent.execute(
                run_id, card_outline, draft,
                available_assets, self.config.design_token,
            )
            html_content = self.renderer.render_html(
                visual_plan.layout_spec, draft,
                visual_plan.asset_manifest, self.config.design_token,
            )
            run_dir = Path(self.store.runs_dir) / run_id
            html_path = run_dir / "output" / "note.html"
            html_path.write_text(html_content, encoding="utf-8")
            console.print(f"[green]HTML 已更新: {html_path}[/]")
            console.print("[green]使用 'xhs-agent confirm' 确认终稿。[/]")

        else:
            console.print(
                f"[yellow]当前状态 {current_state.value} 不支持 revise。"
                f"支持的状态: OUTLINE_CONFIRMATION, FINAL_CONFIRMATION[/]"
            )

    # ==================================================================
    # show
    # ==================================================================

    def show(self, run_id: str):
        """展示当前 Run 的产物和状态。"""
        run_dir = Path(self.store.runs_dir) / run_id
        if not run_dir.exists():
            console.print(f"[red]Run {run_id} 不存在。[/]")
            return

        # 加载状态
        state_info = self._load_state(run_id)
        if state_info:
            console.print(Panel(
                f"Run ID: [cyan]{state_info.get('run_id', run_id)}[/]\n"
                f"状态: [bold]{state_info.get('state', 'unknown')}[/]\n"
                f"研究次数: {state_info.get('research_count', 0)}\n"
                f"大纲修改: {state_info.get('outline_revise_count', 0)}\n"
                f"文案修改: {state_info.get('copy_revise_count', 0)}\n"
                f"布局修改: {state_info.get('layout_revise_count', 0)}\n"
                f"渲染重试: {state_info.get('render_retry_count', 0)}",
                title="Run 状态", border_style="cyan",
            ))
        else:
            console.print("[yellow]未找到 state.json[/]")

        # 列出 artifacts
        art_dir = run_dir / "artifacts"
        if art_dir.exists():
            table = Table(title="Artifacts", show_lines=True)
            table.add_column("名称", style="cyan", width=25)
            table.add_column("版本", style="green", width=10)
            table.add_column("路径", style="white", width=60)
            for sub in sorted(art_dir.iterdir()):
                if sub.is_dir():
                    versions = sorted(sub.glob("v*.json"),
                                    key=lambda p: int(p.stem[1:]))
                    if versions:
                        latest = versions[-1]
                        table.add_row(
                            sub.name,
                            latest.stem,
                            str(latest),
                        )
            console.print(table)

        # 显示 HTML 产物路径
        html_path = run_dir / "output" / "note.html"
        if html_path.exists():
            console.print(f"\n[green]HTML 产物: [cyan]{html_path}[/]")

    # ==================================================================
    # log
    # ==================================================================

    def log(self, run_id: str):
        """查看 Run 的决策日志。"""
        log_path = Path(self.store.runs_dir) / run_id / "run_log.jsonl"
        if not log_path.exists():
            console.print(f"[red]Run {run_id} 未找到决策日志。[/]")
            return

        table = Table(title=f"决策日志 — {run_id}", show_lines=True)
        table.add_column("时间", style="dim", width=20)
        table.add_column("阶段", style="cyan", width=20)
        table.add_column("Agent", style="magenta", width=16)
        table.add_column("决策", style="white", width=40)
        table.add_column("耗时(ms)", style="green", width=10)

        for line in log_path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            entry = json.loads(line)
            table.add_row(
                entry.get("timestamp", ""),
                entry.get("stage", ""),
                entry.get("agent", ""),
                entry.get("decision", "")[:40],
                str(entry.get("duration_ms", "")),
            )
        console.print(table)


# ======================================================================
# Typer 命令
# ======================================================================

@app.command()
def create(topic: str = typer.Argument(..., help="主题/线索")):
    """创建新笔记流程（从主题开始，走完整14态主链路）。"""
    agent = XHSAgent()
    agent.create(topic)


@app.command()
def daily():
    """每日热点发现（输出5个候选，不自动生成完整笔记）。"""
    agent = XHSAgent()
    agent.daily()


@app.command()
def select(
    run_id: str = typer.Argument(..., help="Run ID"),
    topic_id: str = typer.Argument(..., help="话题ID，如 t1"),
):
    """选中候选话题并继续流程。"""
    agent = XHSAgent()
    agent.select(run_id, topic_id)


@app.command()
def confirm(
    run_id: str = typer.Argument(..., help="Run ID"),
):
    """确认当前节点（选题/大纲/终稿），继续流程。"""
    agent = XHSAgent()
    agent.confirm(run_id)


@app.command()
def revise(
    run_id: str = typer.Argument(..., help="Run ID"),
    instruction: str = typer.Argument(..., help="修改指令，如 '第3页太技术'"),
):
    """用户修改指令，重新生成对应产物。"""
    agent = XHSAgent()
    agent.revise(run_id, instruction)


@app.command()
def show(
    run_id: str = typer.Argument(..., help="Run ID"),
):
    """展示当前 Run 的产物和状态。"""
    agent = XHSAgent()
    agent.show(run_id)


@app.command()
def log(
    run_id: str = typer.Argument(..., help="Run ID"),
):
    """查看 Run 的决策日志。"""
    agent = XHSAgent()
    agent.log(run_id)


if __name__ == "__main__":
    app()
