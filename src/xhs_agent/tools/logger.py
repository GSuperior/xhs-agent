"""决策级日志记录器。

每条决策日志记录一个 Agent 在某个 stage 的输入/输出引用、模型、耗时、token、
决策与原因。日志写入对应 run 目录的 run_log.jsonl，便于事后审计与回放。
"""

import json
import re
import time
from pathlib import Path
from typing import Optional


class DecisionLogger:
    def __init__(self, log_dir: str = "./logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        run_id: str,
        stage: str,
        agent: str,
        input_refs: list,
        output_ref: str,
        model: str,
        duration_ms: int,
        token_usage: dict,
        decision: str,
        decision_reasons: list,
        warnings: list = None,
        status: str = "success",
    ) -> dict:
        """记录一条决策日志到 run 目录的 run_log.jsonl"""
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "run_id": run_id,
            "stage": stage,
            "agent": agent,
            "input_refs": input_refs,
            "output_ref": output_ref,
            "model": model,
            "duration_ms": duration_ms,
            "token_usage": token_usage,
            "decision": decision,
            "decision_reasons": decision_reasons,
            "warnings": warnings or [],
            "status": status,
        }
        log_path = Path("./runs") / run_id / "run_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def redact_sensitive(self, text: str) -> str:
        """脱敏 API Key、Cookie 等敏感信息"""
        text = re.sub(r"sk-[a-zA-Z0-9]+", "sk-***REDACTED***", text)
        text = re.sub(
            r"cookie[:\s]*[^\s]+",
            "cookie: ***REDACTED***",
            text,
            flags=re.IGNORECASE,
        )
        return text
