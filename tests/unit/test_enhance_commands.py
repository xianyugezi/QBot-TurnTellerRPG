"""/强化 /强化信息 /强化保护 指令壳单测（2c3b §六 TC-01~23 落地核心场景）。

文件：tests/unit/test_enhance_commands.py
创建：2026-09-06
作者：Hermes 主代理（指令缺口补全批1路1）

覆盖（对齐 2c3b §六 TC 矩阵 + 2c3a §6）：
  A 强化成功/失败（原子+分级）：TC-01 成功升+1 属性增量 / TC-02 带标消耗按目标档 /
     TC-03 低段失败不变材料照扣 / TC-04 高段失败掉级材料照扣
  B /强化信息：TC-07 只读结构 / TC-08 达顶 / TC-09 未找到零副作用
  C /强化保护：TC-10 成功不耗石 / TC-11 高段失败扣石免掉级 / TC-12 低段失败不耗 /
     TC-13 无保护石拒绝
  D 达顶：TC-14 已达上限零消耗
  E 原子/幂等（指令级无跨消息状态）：TC-19 过期带标拒绝
  F 参数解析：TC-21 禁批量 / TC-22 非法标记 / TC-23 歧义候选
  注册：三指令 CommandSpec 注册（白名单标记）。

风格对齐 tests/unit/test_use_commands.py（make_ctx + parse_command + 指令壳直调）。
文案断言用 enhance_tpl 默认模板（渲染走 tpl_of——ctx 无 templates 时回退默认表）。
"""
from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.commands.enhance_commands import (
    ENHANCE_CMD,
    ENHANCE_INFO_CMD,
    ENHANCE_PROTECT_CMD,
    cmd_enhance,
    cmd_enhance_info,
    cmd_enhance_protect,
    register_enhance_commands,
)
from qbot_rpg.commands.parsers import parse_command, ParsedCommand
from qbot_rpg.commands.router import Router

# 测试用 enhance raw（内容包形态；正常/精良/史诗/传说上限齐全）
_TEST_ENHANCE = {
    "settings": {
        "max_by_rarity": {"normal": 5, "fine": 8, "epic": 10, "legendary": 12},
        "fail_tier_split": 3,
        "shatter_mode": False,
        "luck_affects": False,
    },
    "cost": {
        "coin_per_level": 100,
        "stones_per_level": 1,
        "stone_tiers": [
            {"tier": "low", "item": "stone_low", "levels": [1, 2, 3]},
            {"tier": "mid", "item": "stone_mid", "levels": [4, 5, 6]},
            {"tier": "high", "item": "stone_high", "levels": [7, 8, 9, 10, 11, 12]},
        ],
    },
    "success_curve": [
        {"to": 1, "rate": 90}, {"to": 2, "rate": 85}, {"to": 3, "rate": 80},
        {"to": 4, "rate": 70}, {"to": 5, "rate": 60}, {"to": 6, "rate": 50},
        {"to": 7, "rate": 40}, {"to": 8, "rate": 35}, {"to": 9, "rate": 30},
        {"to": 10, "rate": 25}, {"to": 11, "rate": 20}, {"to": 12, "rate": 15},
    ],
    "values": {
        "weapon_atk_per_level": {"type": "flat", "value": 5, "stat_key": "atk"},
        "armor_def_per_level": {"type": "flat", "value": 3, "stat_key": "def"},
    },
    "protect_stone": "protect_stone",
}


def _item(item_id: str, name: str, slot: str = "weapon", quality: str = "normal",
           atk: float = 0.0, defv: float = 0.0, enhance_level: int = 0,
           count: int = 1) -> Dict[str, Any]:
    sb: Dict[str, float] = {}
    if atk:
        sb["atk"] = atk
    if defv:
        sb["def"] = defv
    return {
        "item_id": item_id, "name": name, "count": count, "quality": quality,
        "bound": False, "slot": slot, "stats_bonus": sb,
        "enhance_level": enhance_level, "traits": [],
    }


def make_ctx(**over: Any) -> dict:
    """已注册 + 已穿戴武器/防具 ctx（luck_affects=false 简化成功率断言）。"""
    items_map = {
        "iron_sword": {"id": "iron_sword", "name": "铁剑", "slot": "weapon", "atk": 12},
        "iron_armor": {"id": "iron_armor", "name": "铁甲", "slot": "body", "def": 10},
        "stone_low": {"id": "stone_low", "name": "低级强化石"},
        "stone_mid": {"id": "stone_mid", "name": "中级强化石"},
        "stone_high": {"id": "stone_high", "name": "高级强化石"},
        "protect_stone": {"id": "protect_stone", "name": "保护石"},
    }
    inv = {
        "iron_sword": 1, "iron_armor": 1,
        "stone_low": 99, "stone_mid": 99, "stone_high": 99, "protect_stone": 1,
    }
    player = {
        "name": "测试勇士", "level": 20, "qid": "u1",
        "hp": 100, "mp": 30,
        "currencies": {"coins": 50000},
        "inventory": [
            _item("iron_sword", "铁剑", "weapon", "normal", atk=12.0),
            _item("iron_armor", "铁甲", "body", "normal", defv=10.0),
            _item("stone_low", "低级强化石", "", "normal", count=99),
            _item("stone_mid", "中级强化石", "", "normal", count=99),
            _item("stone_high", "高级强化石", "", "normal", count=99),
            _item("protect_stone", "保护石", "", "normal", count=1),
        ],
        "equipment": {
            "weapon": {"item_id": "iron_sword", "name": "铁剑", "slot_level": 0},
            "body": {"item_id": "iron_armor", "name": "铁甲", "slot_level": 0},
        },
        "attributes": {"base": {"atk": 20.0, "def": 10.0, "lck": 10.0}},
        "in_battle": False,
    }
    base: Dict[str, Any] = {
        "registered": True,
        "player": player,
        "items": items_map,
        "enhance": _TEST_ENHANCE,
        "inventory": inv,
        "slots": {},
        "templates": None,
        "rng": lambda: 0.0,  # 恒成功
    }

    def _count(item_id: str) -> int:
        return int(inv.get(item_id, 0))

    def _remove(item_id: str, count: int) -> bool:
        cur = int(inv.get(item_id, 0))
        if cur < count:
            return False
        if cur == count:
            inv.pop(item_id, None)
        else:
            inv[item_id] = cur - count
        return True

    base["count_item"] = _count
    base["remove_item"] = _remove
    base.update(over)
    return base



def _inv_count(ctx: dict, item_id: str) -> int:
    """player.inventory 行计数。"""
    for r in ctx["player"]["inventory"]:
        if r["item_id"] == item_id:
            return int(r.get("count", 0))
    return 0


def _inv_has(ctx: dict, item_id: str) -> bool:
    return any(r["item_id"] == item_id for r in ctx["player"]["inventory"])

def _equip_state(ctx: dict) -> Dict[str, Any]:
    return ctx["player"]["equipment"]["weapon"]


def parse(raw: str) -> ParsedCommand:
    return parse_command(raw)


# ---------- A 强化成功/失败 ----------

def test_enhance_success_atomic_tc01() -> None:
    """TC-01：/强化 铁剑（+0，roll 成功）→ 一条消息 +1、扣石扣币、等级提升。"""
    ctx = make_ctx()
    out = cmd_enhance(parse("/强化 铁剑"), ctx)
    assert "成功" in out
    assert "铁剑+1" in out
    assert _equip_state(ctx)["slot_level"] == 1
    # 材料照扣：低级石 99→98、金币 50000→49900
    assert _inv_count(ctx, "stone_low") == 98
    assert ctx["player"]["currencies"]["coins"] == 49900
    # 属性增量：atk 12 → 17（+5/级）
    sword_row = ctx["player"]["inventory"][0]
    assert sword_row["stats_bonus"]["atk"] == 17.0


def test_enhance_with_mark_level_consume_tc02() -> None:
    """TC-02：/强化 铁剑+5（实际 +5，精良上限 8）→ 按目标 +6 消耗中级石×6 + 金币600。"""
    ctx = make_ctx()
    # 预先提升到 +5（直接改槽+行；品质精良上限 8 允许 +6）
    p = ctx["player"]
    p["equipment"]["weapon"]["slot_level"] = 5
    p["inventory"][0]["enhance_level"] = 5
    p["inventory"][0]["quality"] = "fine"
    p["inventory"][0]["stats_bonus"]["atk"] = 12.0 + 5 * 5
    out = cmd_enhance(parse("/强化 铁剑+5"), ctx)
    assert "铁剑+6" in out
    assert _inv_count(ctx, "stone_mid") == 93  # 99-6
    assert p["currencies"]["coins"] == 49400  # 50000-600


def test_enhance_fail_low_tier_tc03() -> None:
    """TC-03：低段失败（+2→+3 roll 失败）→ 装备不变、材料照扣。"""
    ctx = make_ctx(rng=lambda: 0.999)  # 恒失败
    p = ctx["player"]
    p["equipment"]["weapon"]["slot_level"] = 2
    p["inventory"][0]["enhance_level"] = 2
    p["inventory"][0]["stats_bonus"]["atk"] = 12.0 + 2 * 5
    out = cmd_enhance(parse("/强化 铁剑+2"), ctx)
    assert "强化失败，装备保持不变" in out
    assert _equip_state(ctx)["slot_level"] == 2
    assert _inv_count(ctx, "stone_low") == 96  # 99-3
    assert p["currencies"]["coins"] == 49700  # 50000-300


def test_enhance_fail_high_tier_tc04() -> None:
    """TC-04：高段失败（+5→+6 roll 失败）→ 掉级 +4、材料照扣。"""
    ctx = make_ctx(rng=lambda: 0.999)
    p = ctx["player"]
    p["equipment"]["weapon"]["slot_level"] = 5
    p["inventory"][0]["enhance_level"] = 5
    p["inventory"][0]["quality"] = "fine"
    p["inventory"][0]["stats_bonus"]["atk"] = 12.0 + 5 * 5
    out = cmd_enhance(parse("/强化 铁剑+5"), ctx)
    assert "强化等级 -1" in out
    assert "铁剑+5 → 铁剑+4" in out
    assert _equip_state(ctx)["slot_level"] == 4
    assert _inv_count(ctx, "stone_mid") == 93  # 99-6
    assert p["currencies"]["coins"] == 49400


# ---------- B /强化信息 ----------

def test_enhance_info_readonly_tc07() -> None:
    """TC-07：/强化信息 铁剑 → 结构完整、零扣除。"""
    ctx = make_ctx()
    before = (_inv_count(ctx, "stone_low"), ctx["player"]["currencies"]["coins"])
    out = cmd_enhance_info(parse("/强化信息 铁剑"), ctx)
    assert "铁剑" in out and "强化上限 +5" in out
    assert "+1 成功率" in out and "90%" in out
    assert "低级强化石 ×1" in out
    after = (_inv_count(ctx, "stone_low"), ctx["player"]["currencies"]["coins"])
    assert before == after  # 零扣除


def test_enhance_info_at_max_tc08() -> None:
    """TC-08：已达上限 → 成功率/消耗行替换为已达上限。"""
    ctx = make_ctx()
    p = ctx["player"]
    p["equipment"]["weapon"]["slot_level"] = 5
    p["inventory"][0]["enhance_level"] = 5
    out = cmd_enhance_info(parse("/强化信息 铁剑"), ctx)
    assert "已达强化上限（+5）" in out
    assert "+1 成功率" not in out


def test_enhance_info_not_found_tc09() -> None:
    """TC-09：未持有 → 未找到「名」；零副作用。"""
    ctx = make_ctx()
    before = dict(ctx["player"]["currencies"])
    out = cmd_enhance_info(parse("/强化信息 神秘武器"), ctx)
    assert "未找到「神秘武器」" in out
    assert ctx["player"]["currencies"] == before


# ---------- C /强化保护 ----------

def test_enhance_protect_success_no_stone_tc10() -> None:
    """TC-10：/强化保护 成功 → 保护石不耗、等级 +1。"""
    ctx = make_ctx()
    out = cmd_enhance_protect(parse("/强化保护 铁剑"), ctx)
    assert "成功" in out
    assert _inv_count(ctx, "protect_stone") == 1  # 不耗
    assert _equip_state(ctx)["slot_level"] == 1


def test_enhance_protect_fail_high_saves_tc11() -> None:
    """TC-11：高段失败 → 扣 1 石免掉级、等级不变、材料照扣。"""
    ctx = make_ctx(rng=lambda: 0.999)
    p = ctx["player"]
    p["equipment"]["weapon"]["slot_level"] = 5
    p["inventory"][0]["enhance_level"] = 5
    p["inventory"][0]["quality"] = "fine"
    out = cmd_enhance_protect(parse("/强化保护 铁剑+5"), ctx)
    assert "保护石抵消掉级" in out
    assert _equip_state(ctx)["slot_level"] == 5  # 不掉
    assert _inv_count(ctx, "protect_stone") == 0  # 扣 1
    assert _inv_count(ctx, "stone_mid") == 93  # 材料照扣


def test_enhance_protect_fail_low_no_stone_tc12() -> None:
    """TC-12：低段失败（无惩罚）→ 保护石不耗、等级不变、材料照扣。"""
    ctx = make_ctx(rng=lambda: 0.999)
    p = ctx["player"]
    p["equipment"]["weapon"]["slot_level"] = 2
    p["inventory"][0]["enhance_level"] = 2
    out = cmd_enhance_protect(parse("/强化保护 铁剑+2"), ctx)
    assert "强化失败，装备保持不变" in out
    assert _inv_count(ctx, "protect_stone") == 1  # 不耗
    assert _equip_state(ctx)["slot_level"] == 2


def test_enhance_protect_no_stone_reject_tc13() -> None:
    """TC-13：无保护石 → 拒绝 + 来源提示、零扣除。"""
    ctx = make_ctx()
    pl = ctx["player"]
    pl["inventory"] = [r for r in pl["inventory"] if r["item_id"] != "protect_stone"]
    out = cmd_enhance_protect(parse("/强化保护 铁剑"), ctx)
    assert "保护石" in out
    assert _equip_state(ctx)["slot_level"] == 0
    assert _inv_count(ctx, "stone_low") == 99  # 未扣


# ---------- D 达顶 ----------

def test_enhance_at_max_tc14() -> None:
    """TC-14：已达上限强化 → 已达强化上限、零消耗。"""
    ctx = make_ctx()
    p = ctx["player"]
    p["equipment"]["weapon"]["slot_level"] = 5
    p["inventory"][0]["enhance_level"] = 5
    before = (_inv_count(ctx, "stone_low"), ctx["player"]["currencies"]["coins"])
    out = cmd_enhance(parse("/强化 铁剑+5"), ctx)
    assert "已达强化上限（+5）" in out
    after = (_inv_count(ctx, "stone_low"), ctx["player"]["currencies"]["coins"])
    assert before == after


# ---------- E 原子/锚定 ----------

def test_enhance_stale_mark_reject_tc19() -> None:
    """TC-19：过期带标（实际 +3 发 +2）→ 拒绝并报实际等级、零扣除。"""
    ctx = make_ctx()
    p = ctx["player"]
    p["equipment"]["weapon"]["slot_level"] = 3
    p["inventory"][0]["enhance_level"] = 3
    before = (_inv_count(ctx, "stone_low"), ctx["player"]["currencies"]["coins"])
    out = cmd_enhance(parse("/强化 铁剑+2"), ctx)
    assert "当前 +3" in out
    after = (_inv_count(ctx, "stone_low"), ctx["player"]["currencies"]["coins"])
    assert before == after


# ---------- F 参数解析 ----------

def test_enhance_batch_rejected_tc21() -> None:
    """TC-21：含 * → 拒绝批量。"""
    ctx = make_ctx()
    out = cmd_enhance(parse("/强化 铁剑*2"), ctx)
    assert "不支持批量强化" in out


def test_enhance_bad_mark_tc22() -> None:
    """TC-22：非法标记族 → 参数错误、零副作用。"""
    ctx = make_ctx()
    for raw in ("/强化 铁剑+", "/强化 铁剑+abc", "/强化 铁剑++2"):
        before = (_inv_count(ctx, "stone_low"), ctx["player"]["currencies"]["coins"])
        out = cmd_enhance(parse(raw), ctx)
        assert "参数错误" in out, raw
        after = (_inv_count(ctx, "stone_low"), ctx["player"]["currencies"]["coins"])
        assert before == after, raw


def test_enhance_ambiguous_tc23() -> None:
    """TC-23：歧义前缀 → 候选列表、不自动强化。"""
    ctx = make_ctx()
    p = ctx["player"]
    # 加一件 铁剑·改（同前缀）
    p["inventory"].append(_item("iron_sword2", "铁剑·改", "weapon", "fine", atk=20.0))
    p["equipment"]["weapon2"] = {"item_id": "iron_sword2", "name": "铁剑·改", "slot_level": 0}
    out = cmd_enhance(parse("/强化 铁"), ctx)
    assert "候选" in out
    assert "铁剑·改" in out
    assert _equip_state(ctx)["slot_level"] == 0  # 未强化


# ---------- 注册 ----------

def test_register_enhance_commands() -> None:
    """三指令注册 + 白名单标记。"""
    router = Router()
    register_enhance_commands(router)
    for name in (ENHANCE_CMD, ENHANCE_INFO_CMD, ENHANCE_PROTECT_CMD):
        spec = router.get(name)
        assert spec is not None
        assert spec.whitelisted
