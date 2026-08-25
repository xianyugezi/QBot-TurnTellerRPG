"""统一日志工具（通用规则 ⑪：强制日志——关键步骤/运行状态/报错信息落文件）。

设计（零 NoneBot、纯 stdlib logging）：
- ``get_logger(name)``：取 ``qbot_rpg.<name>`` 命名空间 logger；首次调用时幂等
  初始化（文件 handler + stderr handler），多次调用不重复加 handler。
- 日志文件默认 ``logs/qbot_rpg.log``（相对仓库根），可用环境变量
  ``QRP_LOG_DIR`` 覆盖目录；RotatingFileHandler 滚动防膨胀（1MB×3）。
- 格式：``时间 级别 模块名 消息``（含异常 traceback 由调用方 ``logger.exception`` 触发）。

规则 ⑫/⑬ 配合：核心逻辑 try…except 处调用 ``logger.exception`` 记完整堆栈，
随后返回兜底值/状态码，禁止裸崩溃。
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_LOGGER_NAME = "qbot_rpg"
_INITIALIZED = False
_DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s %(message)s"


def _default_log_dir() -> Path:
    env = os.environ.get("QRP_LOG_DIR")
    if env:
        return Path(env)
    # 仓库根 = 本文件 ../../（qbot_rpg/data/logging_utils.py → 仓库根）
    return Path(__file__).resolve().parents[2] / "logs"


def _ensure_initialized() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    root = logging.getLogger(_LOGGER_NAME)
    if not root.handlers:  # 防御：已有外部 handler 时不再重复配置
        root.setLevel(logging.DEBUG)
        fmt = logging.Formatter(_DEFAULT_FORMAT)

        log_dir = _default_log_dir()
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(
                log_dir / "qbot_rpg.log", maxBytes=1_048_576, backupCount=3,
                encoding="utf-8",
            )
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except OSError:  # 日志目录不可写时不阻断业务（规则 ⑬：兜底不崩）
            pass

        sh = logging.StreamHandler()
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt)
        root.addHandler(sh)
    _INITIALIZED = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """取统一命名空间 logger；name 省略 → ``qbot_rpg`` 根。

    首次调用自动初始化文件 + stderr handler（幂等）。
    """
    _ensure_initialized()
    if not name:
        return logging.getLogger(_LOGGER_NAME)
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")


__all__ = ["get_logger"]
