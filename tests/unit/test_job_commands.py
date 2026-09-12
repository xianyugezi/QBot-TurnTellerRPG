"""M13 /转职 指令单测（tests/unit/test_job_commands.py · M13 批14 路14A）。

覆盖：
  - /转职 无参 → 职业列表（含推荐角标）
  - /转职 <职业名> 成功（player job_id 更新 + 技能位重排落档）
  - /转职 <序号> 成功
  - /转职 未知职业 → 友好提示
  - 模板占位符白名单

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠。
"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.commands.job_commands import cmd_job


def _jobs() -> Dict[str, Dict[str, Any]]:
    return {
        "berserker": {"name": "狂战士", "recommended_newbie": False},
        "alchemy": {"name": "炼金术师", "recommended_newbie": True},
        "forge": {"name": "锻造师", "recommended_newbie": True},
    }


def _ctx(**over: Any) -> Dict[str, Any]:
    c: Dict[str, Any] = {
        "jobs": _jobs(),
        "job_id": "berserker",
        "job_name": "狂战士",
        "player": {"job_id": "berserker", "persistent_state": {}},
        "persistent_state": {},
        "now": 12345,
        "skills": {},
    }
    c.update(over)
    return c


class _Parsed:
    def __init__(self, args: list, error: str = "", raw: str = "") -> None:
        self.args = args
        self.error = error
        self.raw = raw


def test_no_args_job_list() -> None:
    """无参 → 职业列表（含推荐角标）。"""
    out = cmd_job(_Parsed([]), _ctx())
    assert "狂战士" in out and "炼金术师" in out and "锻造师" in out
    assert "（推荐）" in out  # 推荐角标


def test_job_switch_by_name() -> None:
    """/转职 炼金术师 → 成功 + job_id 更新。"""
    ctx = _ctx()
    out = cmd_job(_Parsed(["炼金术师"]), ctx)
    assert "炼金术师" in out and "成功" in out
    assert ctx["player"]["job_id"] == "alchemy"
    assert ctx["job_id"] == "alchemy"


def test_job_switch_by_index() -> None:
    """/转职 2 → 第 2 个职业（alchemy）。"""
    ctx = _ctx()
    out = cmd_job(_Parsed(["2"]), ctx)
    assert "炼金术师" in out and "成功" in out
    assert ctx["player"]["job_id"] == "alchemy"


def test_job_not_found() -> None:
    """未知职业 → 友好提示 + 可用列表。"""
    out = cmd_job(_Parsed(["不存在职业"]), _ctx())
    assert "不存在职业" in out and "可用" in out


def test_parsed_error() -> None:
    """解析错误 → 错误模板（不崩）。"""
    p = _Parsed([], error="err", raw="/转职")
    out = cmd_job(p, _ctx())
    assert isinstance(out, str) and out


def test_switch_saves_slot_snapshot() -> None:
    """转职后 skill_slots 快照更新（14C 联动）。"""
    ctx = _ctx()
    cmd_job(_Parsed(["锻造师"]), ctx)
    assert ctx.get("skill_slots") is not None, "转职应产出新装配快照"
    assert "job_slots" in ctx["persistent_state"], "转职快照段应落档"


def test_templates_registered() -> None:
    """job 8 键已迁全量表（分区默认表清空）+ 派生白名单与占位符一一对应。

    2026-09-12 批11·路A：job_tpl 分区默认表/白名单清空，断言改走 TABLE_TEMPLATES
    （对齐 test_pvp_commands / test_investigate_commands 同款口径）。
    """
    import re

    import qbot_rpg.core.templates.job_tpl as _job_partition
    from qbot_rpg.core.templates import DEFAULT_TEMPLATES, PLACEHOLDER_WHITELIST, TABLE_TEMPLATES

    # 分区默认表/白名单已清空（8 键全部迁全量表；空壳保留 import 兼容）
    assert not _job_partition.DEFAULT_TEMPLATES
    assert not _job_partition.PLACEHOLDER_WHITELIST
    job_keys = {k for k in TABLE_TEMPLATES if k.startswith("job_")}
    assert job_keys == {
        "job_list", "job_list_tip", "job_not_found", "job_switch_success",
        "job_detail_usage", "job_detail_header", "job_detail_rec", "job_detail_line",
    }
    pat = re.compile(r"\{([a-zA-Z0-9_]+)\}")
    for key in sorted(job_keys):
        tpl = TABLE_TEMPLATES[key]
        assert DEFAULT_TEMPLATES[key] == tpl, f"聚合未走表：{key}"
        assert PLACEHOLDER_WHITELIST[key] == set(pat.findall(tpl)), f"白名单不一致：{key}"
    # 占位符逐键核对（信息要素不丢字段）
    assert PLACEHOLDER_WHITELIST["job_list"] == {"list"}
    assert PLACEHOLDER_WHITELIST["job_not_found"] == {"job", "list"}
    assert PLACEHOLDER_WHITELIST["job_switch_success"] == {"job", "rec"}
    assert PLACEHOLDER_WHITELIST["job_detail_header"] == {"name"}
    assert PLACEHOLDER_WHITELIST["job_detail_line"] == {"k", "v"}
    assert PLACEHOLDER_WHITELIST["job_list_tip"] == set()
    assert PLACEHOLDER_WHITELIST["job_detail_usage"] == set()
    assert PLACEHOLDER_WHITELIST["job_detail_rec"] == set()


def test_job_list_empty() -> None:
    """jobs 表空 → 提示。"""
    out = cmd_job(_Parsed([]), _ctx(jobs={}))
    assert "无可转职业" in out or "未配置" in out
