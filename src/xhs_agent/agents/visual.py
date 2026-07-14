"""视觉规划 Agent。

职责：选择模板、生成 layout_spec。不自由生成 HTML 代码。
输入：CardOutline + Draft + available_assets + design_token
输出：LayoutSpec + AssetManifest（包装在 VisualPlan 中）
"""

import json
from typing import Optional

from pydantic import BaseModel

from ..schemas.content import CardOutline, Draft
from ..schemas.visual import AssetManifest, AvailableAssets, LayoutSpec
from .base import BaseAgent


class VisualPlan(BaseModel):
    """视觉规划输出：LayoutSpec + AssetManifest。"""

    layout_spec: LayoutSpec
    asset_manifest: AssetManifest


class VisualAgent(BaseAgent):
    """视觉规划 Agent，只输出 layout_spec，不写 HTML 代码。"""

    def get_system_prompt(self) -> str:
        return """你是视觉规划 Agent，只输出 layout_spec，不写 HTML 代码。

## 核心规则
1. 从 available_assets 中选择素材，不直接下载 URL。
2. 只引用 available_assets 中已存在的 asset_id。
3. 每张卡片输出：card_id/template/layout/hierarchy/emphasis/icon_keys。
4. 选择整体模板：product_breakdown 或 trend_analysis。
5. Phase 1A 限制：asset.source 只能为 user_provided / library / generated（不含 official 远程下载）。

## 视觉规范
- 画布 1080×1440 px，安全区 72px（VISUAL_001）。
- 字号以 Design Token 为唯一真源（VISUAL_002），全文统一 px。
- 正文最小字号 32px（VISUAL_003）。
- 每张图必须有非纯文本的信息组织元素（卡片/框架/对比/图标等，VISUAL_006）。
- 视觉素材必须通过 asset_manifest 管理（VISUAL_007）。

## 卡片视觉类型参考（STYLE_007）
- 产品拆解推荐：界面/Logo/流程
- 趋势判断推荐：时间线/箭头/关系图
- 对比评测推荐：矩阵/表格/双栏
- 封面默认黑白极简+产品Logo点缀（STYLE_006）
- 内容图默认米色底+粉色高亮

## LayoutSpecItem 字段
- card_id：对应 CardOutline 中的 card_id
- template：该卡片的模板名（如 cover/comparison/timeline/conclusion）
- layout：布局描述（如 "左文右图" / "上标题下对比" / "全幅时间线"）
- hierarchy：信息层级（从高到低的元素列表，如 ["main_title", "subtitle", "badge"]）
- emphasis：强调元素列表
- icon_keys：使用的图标 key 列表

## AssetManifestEntry 字段
- asset_id：必须来自 available_assets
- type：logo / screenshot / icon / illustration
- source：user_provided / library / generated
- source_url：来源URL（可为 null）
- local_ref：本地路径（来自 available_assets 的 local_ref）
- license_note：版权说明（可为 null）
- used_in_cards：该素材用于哪些卡片

## 输出格式
输出 JSON，顶层为 VisualPlan 结构：
{
  "layout_spec": {
    "template": "product_breakdown" 或 "trend_analysis",
    "cards": [
      {"card_id": "card_1", "template": "cover", "layout": "...", "hierarchy": [...], "emphasis": [...], "icon_keys": [...]}
    ],
    "design_token_ref": "config/design_token.json"
  },
  "asset_manifest": {
    "assets": [
      {"asset_id": "a1", "type": "logo", "source": "library", "source_url": null, "local_ref": "assets/a1.png", "license_note": null, "used_in_cards": ["card_1"]}
    ]
  }
}

只输出 JSON，不要额外解释。"""

    def execute(
        self,
        run_id: str,
        card_outline: CardOutline,
        draft: Draft,
        available_assets: AvailableAssets,
        design_token: Optional[dict] = None,
    ) -> VisualPlan:
        """根据 CardOutline 和 Draft 生成 LayoutSpec + AssetManifest。"""
        design_token = design_token or {}
        context = self._build_context(card_outline, draft, available_assets, design_token)
        user_content = (
            "请根据以下 CardOutline、Draft 和 available_assets 生成 VisualPlan（LayoutSpec + AssetManifest）。\n"
            "只引用 available_assets 中已存在的 asset_id，不直接下载 URL。"
        )
        messages = self._build_messages(user_content, context)

        result, llm_resp = self.llm.chat_json(
            self.model, messages, VisualPlan
        )

        ls_version = self.store.get_latest_version(run_id, "layout_spec") + 1
        ls_ref = self.store.save_artifact(
            run_id, "layout_spec", result.layout_spec.model_dump(), ls_version
        )
        am_version = self.store.get_latest_version(run_id, "asset_manifest") + 1
        am_ref = self.store.save_artifact(
            run_id, "asset_manifest", result.asset_manifest.model_dump(), am_version
        )

        self._log(
            run_id=run_id,
            stage="VISUAL_PLANNING",
            agent_name="VisualAgent",
            input_refs=["card_outline", "draft", "available_assets"],
            output_ref=f"{ls_ref} + {am_ref}",
            llm_resp=llm_resp,
            decision=f"生成LayoutSpec（{len(result.layout_spec.cards)}张卡片）+AssetManifest（{len(result.asset_manifest.assets)}个素材）",
            reasons=[f"整体模板：{result.layout_spec.template}"],
        )

        return result

    def _build_context(
        self,
        card_outline: CardOutline,
        draft: Draft,
        available_assets: AvailableAssets,
        design_token: dict,
    ) -> str:
        outline_json = card_outline.model_dump_json(indent=2)
        draft_json = draft.model_dump_json(indent=2)
        assets_json = available_assets.model_dump_json(indent=2)
        token_json = json.dumps(design_token, ensure_ascii=False, indent=2)
        return (
            f"## CardOutline\n{outline_json}\n\n"
            f"## Draft\n{draft_json}\n\n"
            f"## AvailableAssets\n{assets_json}\n\n"
            f"## DesignToken\n{token_json}"
        )
