"""支持 python -m xhs_agent 运行。

新增 `web` 子命令启动 FastAPI Web 端：
    python -m xhs_agent web
其它参数走原 Typer CLI（不修改 cli.py）。
"""

import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "web":
        # 移除 "web" 后转发给 web 模块
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        from .web import run_server
        run_server()
        return
    from .cli import app
    app()


if __name__ == "__main__":
    main()
