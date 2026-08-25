"""logging_utils 单测（通用规则 ⑪⑫⑬：强制日志/异常捕获/兜底处理落地验证）。"""
from __future__ import annotations

from qbot_rpg.data.logging_utils import _default_log_dir, get_logger


def test_get_logger_writes_to_file() -> None:
    """规则 ⑪：get_logger 记录的关键步骤/报错信息真实落入日志文件（默认 logs/ 目录）。"""
    logger = get_logger("test.file")
    logger.info("关键步骤：玩家上线 qid=123")
    logger.warning("报错信息：加载失败")
    # 触发一次异常日志（规则 ⑫⑬ 配套：logger.exception 记完整堆栈）
    try:
        raise ValueError("未预料数据")
    except ValueError:
        logger.exception("兜底处理前记录异常")

    log_file = _default_log_dir() / "qbot_rpg.log"
    assert log_file.exists(), "日志文件应被创建"
    text = log_file.read_text(encoding="utf-8")
    assert "关键步骤：玩家上线 qid=123" in text
    assert "报错信息：加载失败" in text
    assert "未预料数据" in text, "exception 日志应含异常 traceback 消息"


def test_get_logger_idempotent() -> None:
    """规则 ⑪：多次 get_logger 不重复添加 handler（幂等，防日志重复）。"""
    name = "qbot_rpg.test_idem"
    a = get_logger(name)
    b = get_logger(name)
    assert a is b, "同一命名空间应返回同一 logger 实例"
    n = len(a.handlers)
    get_logger(name)  # 再取一次
    assert len(get_logger(name).handlers) == n, "不应重复叠加 handler"
