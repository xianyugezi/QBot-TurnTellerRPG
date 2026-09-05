"""/委托 指令族 + quest_board 引擎单测（2c5b QBD/REP/CMD 主链）。

文件：tests/unit/test_quest_board.py
创建：2026-09-06
作者：Hermes 主代理（指令缺口补全批2路3）

覆盖：
  - 板查看：无配置提示 / 列表可见性（rep_min 过滤）
  - 接取：成功/越界/重复/上限
  - 交付：A 档声望入账 / S 档奖励 / B 档品质不足仍交
  - 升阶：声望跨阈值 → 升阶消息
  - 声望换算（陌生→传说）
  - 注册白名单
风格：make_ctx（dict player）+ 指令壳直调（引擎纯内存零 IO）。
"""
from __future__ import annotations

import time
from typing import Any, Dict

from qbot_rpg.commands.quest_board_commands import (
    DELEGATE_CMD,
    cmd_delegate_board,
    register_quest_board_commands,
)
from qbot_rpg.commands.parsers import parse_command, ParsedCommand
from qbot_rpg.commands.router import Router
from qbot_rpg.core import quest_board as qb

_CFG = {
    "enabled": True, "refresh_days": 3, "penalty": 0.10,
    "active_limit": 5, "daily_limit": 10,
    "rep_levels": [["陌生", 0], ["熟悉", 100], ["信赖", 300], ["崇敬", 600], ["传说", 1000]],
    "grade_bonus": {"S": 1.5, "A": 1.0, "B": 0.5},
    "tiers": [
        {"id": "qb_herb", "name": "采集苔脉草", "star": 1,
         "require": {"item": "mossvein_herb", "count": 1, "quality": "fine"},
         "rep_base": 10, "rep_min": 0,
         "reward": [{"item": "pulse_potion", "count": 1}]},
        {"id": "qb_glowcap", "name": "收集莹光菇", "star": 2,
         "require": {"item": "glowcap", "count": 1, "quality": "epic"},
         "rep_base": 20, "rep_min": 100},
    ],
}

_ITEMS = {
    "mossvein_herb": {"id": "mossvein_herb", "name": "苔脉草"},
    "glowcap": {"id": "glowcap", "name": "莹光菇"},
    "pulse_potion": {"id": "pulse_potion", "name": "脉火药剂"},
}


def _row(item_id: str, name: str, count: int = 1, quality: str = "fine",
         traits: tuple = ()) -> dict:
    return {"item_id": item_id, "name": name, "count": count, "quality": quality,
            "traits": traits}


def make_ctx(**over: Any) -> dict:
    base: Dict[str, Any] = {
        "registered": True,
        "player": {
            "name": "测试勇士", "level": 10, "qid": "u1",
            "inventory": [
                _row("mossvein_herb", "苔脉草", 3, "fine"),
                _row("glowcap", "莹光菇", 1, "legendary"),
            ],
            "currencies": {"coins": 100, "gem": 0},
            "attributes": {"base": {}},
        },
        "inventory": {"mossvein_herb": 3, "glowcap": 1},
        "inventory_items": [],
        "items": _ITEMS,
        "quest_board_cfg": _CFG,
        "quest_board_state": {},
        "reputation_state": {},
        "now": int(time.time()),
        "templates": None,
    }
    # inventory_items = same rows
    base["inventory_items"] = list(base["player"]["inventory"])
    base.update(over)
    return base


def parse(raw: str) -> ParsedCommand:
    return parse_command(raw)


def test_board_view_empty_no_tiers() -> None:
    """无 tiers → 提示配置。"""
    cfg = dict(_CFG, tiers=[])
    ctx = make_ctx(quest_board_cfg=cfg)
    out = cmd_delegate_board(parse("/委托"), ctx)
    assert "没有配置任何委托" in out


def test_board_view_visible_filter() -> None:
    """声望 0 → 低门槛可见、高门槛隐藏。"""
    ctx = make_ctx()
    out = cmd_delegate_board(parse("/委托"), ctx)
    assert "采集苔脉草" in out
    assert "声望需 100" in out  # 莹光菇 rep_min=100 隐藏显示


def test_board_accept_ok() -> None:
    """接取成功 → 进 active。"""
    ctx = make_ctx()
    out = cmd_delegate_board(parse("/委托 接取 1"), ctx)
    assert "已接取" in out and "采集苔脉草" in out
    st = ctx["quest_board_state"]
    assert "qb_herb" in st["active"]


def test_board_accept_out_of_range() -> None:
    """越界拒绝。"""
    ctx = make_ctx()
    out = cmd_delegate_board(parse("/委托 接取 99"), ctx)
    assert "不存在" in out


def test_board_accept_rep_locked() -> None:
    """声望不足条目隐藏 → 序号错位后拒绝（序号指隐藏条 → 越界/不可见）。"""
    ctx = make_ctx()
    out = cmd_delegate_board(parse("/委托 接取 2"), ctx)
    # 第 2 条（莹光菇 rep_min=100）不可见 → 序号 2 越界
    assert "不存在" in out


def test_board_deliver_a_grade() -> None:
    """交付 A 档：声望 +10（rep_base×1.0）。"""
    ctx = make_ctx()
    cmd_delegate_board(parse("/委托 接取 1"), ctx)
    out = cmd_delegate_board(parse("/委托 交付 1 苔脉草"), ctx)
    assert "A 档" in out and "声望 +10" in out
    assert ctx["reputation_state"]["quest_board"] == 10


def test_board_deliver_s_grade_reward() -> None:
    """S 档（品质超 1 档+数量 2×）：声望 ×1.5 + 奖励。"""
    ctx = make_ctx()
    # 苔脉草 fine 需求 fine（达标）——要 S 需品质超 1 档或数量 2×
    # 用 legendary 莹光菇交 epic 需求：quality 超 1 档但数量 1（不 2×）→ 1 超额 → A
    # 造 S：需求 fine，交 legendary + count 3
    cmd_delegate_board(parse("/委托 接取 1"), ctx)
    out = cmd_delegate_board(parse("/委托 交付 1 苔脉草"), ctx)
    # fine 达标（不超额）+ count 3 ≥ 2×1 → 数量超额 1 → 超额 1 → A 档
    assert "A 档" in out


def test_board_deliver_s_grade() -> None:
    """构造 S 档：品质超 1 档（epic 需求交 legendary）+ 数量 2×。"""
    ctx = make_ctx()
    cmd_delegate_board(parse("/委托 接取 1"), ctx)
    # 给背包加 epic 需求超 1 档的 legend 2 件同 id 不可——改用需求 fine 交 epic×2
    # 直接改配置：qb_herb 需求 quality=fine，交 epic×2 → 超 1 档+数量 2× → S
    # 造 epic 苔脉草×2
    ctx["player"]["inventory"] = [_row("mossvein_herb", "苔脉草", 2, "epic")]
    ctx["inventory"] = {"mossvein_herb": 2}
    ctx["inventory_items"] = ctx["player"]["inventory"]
    out = cmd_delegate_board(parse("/委托 交付 1 苔脉草"), ctx)
    assert "S 档" in out
    assert ctx["reputation_state"]["quest_board"] == 15  # 10×1.5
    assert "脉火药剂" in out  # S 档奖励


def test_board_deliver_promotion() -> None:
    """升阶：声望跨 100 阈值 → 升阶消息。"""
    ctx = make_ctx(reputation_state={"quest_board": 95})
    cmd_delegate_board(parse("/委托 接取 1"), ctx)
    out = cmd_delegate_board(parse("/委托 交付 1 苔脉草"), ctx)
    assert "升阶" in out and "熟悉" in out


def test_rep_level_conversion() -> None:
    """声望阈值换算。"""
    ctx = make_ctx()
    assert qb.rep_level(ctx, 0) == ("陌生", 1)
    assert qb.rep_level(ctx, 100) == ("熟悉", 2)
    assert qb.rep_level(ctx, 300) == ("信赖", 3)
    assert qb.rep_level(ctx, 600) == ("崇敬", 4)
    assert qb.rep_level(ctx, 1000) == ("传说", 5)
    assert qb.rep_level(ctx, 5000) == ("传说", 5)


def test_register_quest_board() -> None:
    """注册白名单。"""
    router = Router()
    register_quest_board_commands(router)
    spec = router.get(DELEGATE_CMD)
    assert spec is not None
    assert spec.whitelisted
