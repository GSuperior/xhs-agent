from typing import List, Optional

from pydantic import BaseModel

from .common import AssetSource, AssetType


# ---------------------------------------------------------------------------
# 可用素材清单（VISUAL_PLANNING 输入）
# ---------------------------------------------------------------------------

class AvailableAsset(BaseModel):
    """轻量可用素材条目。只含 asset_id/type/source/local_ref。"""
    asset_id: str
    type: AssetType
    source: AssetSource
    local_ref: str


class AvailableAssets(BaseModel):
    """available_assets.json：可用素材清单。"""
    available_assets: List[AvailableAsset]


# ---------------------------------------------------------------------------
# 视觉规划选中的素材清单（asset_manifest.json）
# ---------------------------------------------------------------------------

class AssetManifestEntry(BaseModel):
    """asset_manifest 中的素材条目。Phase 1A 限制 source 只能为
    user_provided / library / generated（不含 official 远程下载）。
    """
    asset_id: str
    type: AssetType
    source: AssetSource
    source_url: Optional[str] = None
    local_ref: str
    license_note: Optional[str] = None
    used_in_cards: List[str] = []


class AssetManifest(BaseModel):
    """asset_manifest.json：视觉规划 Agent 选中的素材清单。"""
    assets: List[AssetManifestEntry]


# ---------------------------------------------------------------------------
# 布局规划（layout_spec.json）
# ---------------------------------------------------------------------------

class LayoutSpecItem(BaseModel):
    """单张卡片的布局规格。"""
    card_id: str
    template: str
    layout: str
    hierarchy: List[str] = []
    emphasis: List[str] = []
    icon_keys: List[str] = []


class LayoutSpec(BaseModel):
    """整体布局规格。template 为整体模板名。"""
    template: str
    cards: List[LayoutSpecItem]
    design_token_ref: str
