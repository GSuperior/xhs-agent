"""配置加载器。

加载 models.yaml 和 design_token.json（注意：后者扩展名是 .json 但内容是 YAML 格式，
需要用 yaml.safe_load 加载）。同时替换 models.yaml 中的环境变量占位符。
"""

import os
import yaml
from pathlib import Path
from dotenv import load_dotenv
from typing import Dict, Any

load_dotenv()

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


class Config:
    """配置加载器，提供模型配置和 design token 访问。"""

    def __init__(self):
        self.models = self._load_models()
        self.design_token = self._load_design_token()
        self.supported_content_types = self.models.get(
            "supported_content_types", ["product_breakdown", "trend_analysis"]
        )

    def _load_models(self) -> Dict[str, Any]:
        path = CONFIG_DIR / "models.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        # 替换环境变量
        data_str = yaml.dump(data)
        data_str = data_str.replace(
            "${SENSENOVA_BASE_URL}", os.getenv("SENSENOVA_BASE_URL", "")
        )
        data_str = data_str.replace(
            "${SENSENOVA_API_KEY}", os.getenv("SENSENOVA_API_KEY", "")
        )
        return yaml.safe_load(data_str)

    def _load_design_token(self) -> Dict[str, Any]:
        path = CONFIG_DIR / "design_token.json"
        # 这个文件实际是 YAML 格式
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def get_model_name(self, role: str) -> str:
        """根据角色获取模型名，如 topic/research/planning/writing/visual_planning/review"""
        model_key = self.models["models"].get(role, "default_model")
        return self.models["model_endpoints"][model_key]["model"]

    def get_model_config(self, role: str) -> dict:
        model_key = self.models["models"].get(role, "default_model")
        return self.models["model_endpoints"][model_key]

    def is_content_type_supported(self, content_type: str) -> bool:
        return content_type in self.supported_content_types


config = Config()
