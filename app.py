"""Vercel 入口：导入 FastAPI app。

Vercel @vercel/python builder 期望入口文件在项目根目录，
本文件把 src/ 加入 sys.path 后导入 xhs_agent.web.app。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from xhs_agent.web import app  # noqa: E402
