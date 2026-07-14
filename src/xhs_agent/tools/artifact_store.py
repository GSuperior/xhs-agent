"""Artifact 版本化存储。

Run 目录结构:
    runs/{run_id}/
        artifacts/{name}/v{version}.json
        sources/{source_id}.txt
        assets/
        output/
        run_log.jsonl   (由 DecisionLogger 写入)
"""

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional


class ArtifactStore:
    def __init__(self, runs_dir: str = "./runs"):
        self.runs_dir = Path(runs_dir)

    def create_run(self, topic: str) -> str:
        """创建 Run 目录，格式: YYYYMMDD_HHMMSS_{topic_slug}_{random4}"""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        slug = "".join(c if c.isalnum() else "_" for c in topic)[:30]
        rand = uuid.uuid4().hex[:4]
        run_id = f"{timestamp}_{slug}_{rand}"
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "artifacts").mkdir(exist_ok=True)
        (run_dir / "sources").mkdir(exist_ok=True)
        (run_dir / "assets").mkdir(exist_ok=True)
        (run_dir / "output").mkdir(exist_ok=True)
        return run_id

    def save_artifact(
        self, run_id: str, name: str, data: Any, version: int = 1
    ) -> str:
        """保存版本化 artifact: artifacts/{name}/v{version}.json"""
        run_dir = self.runs_dir / run_id
        art_dir = run_dir / "artifacts" / name
        art_dir.mkdir(parents=True, exist_ok=True)
        path = art_dir / f"v{version}.json"
        if isinstance(data, (dict, list)):
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        else:
            path.write_text(str(data), encoding="utf-8")
        return str(path)

    def load_artifact(
        self, run_id: str, name: str, version: Optional[int] = None
    ) -> Any:
        """加载 artifact，version=None 时加载最新版本"""
        run_dir = self.runs_dir / run_id
        art_dir = run_dir / "artifacts" / name
        if not art_dir.exists():
            return None
        if version is None:
            versions = sorted(
                art_dir.glob("v*.json"), key=lambda p: int(p.stem[1:])
            )
            if not versions:
                return None
            path = versions[-1]
        else:
            path = art_dir / f"v{version}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def get_latest_version(self, run_id: str, name: str) -> int:
        run_dir = self.runs_dir / run_id
        art_dir = run_dir / "artifacts" / name
        if not art_dir.exists():
            return 0
        versions = sorted(
            art_dir.glob("v*.json"), key=lambda p: int(p.stem[1:])
        )
        return int(versions[-1].stem[1:]) if versions else 0

    def save_source_snapshot(
        self, run_id: str, source_id: str, text: str
    ) -> str:
        run_dir = self.runs_dir / run_id
        path = run_dir / "sources" / f"{source_id}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)
