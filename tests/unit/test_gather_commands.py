"""批36 · X2 `/采集` 指令壳 + 端到端单测（tests/unit/test_gather_commands.py）。

端到端口径：**临时内容根**（tmp_path 造探针包 → 真实 `build_pack` 装载 + 校验 →
真实 `/进入` 通道行走 → 真实 `/采集` → 产出进背包）。绝不写仓库 content/（批19.1 门禁）。

覆盖：
  · E2E 主线：进入 → 采集 → 背包前后对比（真数值）；二次采集走冷却（次数耗尽）；
  · 无限资源图（【总纲】L1280）连采不冷却；
  · 边界人话提示：无采集点 / 冷却中 / 时节门控 / 位置未知 / 带参；
  · 不满足条件 → 背包不变 + 冷却状态不变 + 无入包 hook 调用（写盘四断言之一）；
  · 入包走既有链路（ctx["add_item"] hook 优先，对齐 forge/alchemy 口径）；
  · 确定性（同种子同结果，不 flaky）；
  · 回归：钓鱼链路不受影响（同图 `/钓鱼` 行为不变）+ 注册装配。

依据：docs/采集挖掘_实现口径.md（§一 定稿原句 / §二 钓鱼对照 / §三 范围）；
细化_2a1d GP-01~GP-11 + TC-01~TC-04；【总纲】L1280/L1305；【时间天气】L204-207。
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.commands.explore_commands import cmd_enter
from qbot_rpg.commands.fishing_commands import cmd_fishing
from qbot_rpg.commands.gather_commands import (
    GATHER_CMD,
    RARITY_CN,
    cmd_gather,
    register_gather_commands,
)
from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.commands.router import Router
from qbot_rpg.content.loader import PackLoadError, build_pack

# ---------------------------------------------------------------------------
# 临时内容根：造探针包（真实装载 + 校验；不动仓库 content/）
# ---------------------------------------------------------------------------
_ITEMS = [
    {"id": "herb", "name": "灵草", "type": "material", "quality": "common"},
    {"id": "ore", "name": "矿石", "type": "material", "quality": "common"},
]
_ENEMIES = [{"id": "slime", "name": "史莱姆"}, {"id": "bat", "name": "蝙蝠"}]
_MAPS = [
    {"id": "m_field", "name": "野草地", "desc": "测试图",
     "monsters": [{"enemy": "slime", "count": 3, "respawn_minutes": 5}],
     "exits": {"down": {"to": "m_cave", "mode": "bidirectional"}},
     "gather_points": [
         {"id": "gp_herb", "item": "herb", "rate": 1.0, "rarity": "normal",
          "respawn_minutes": 10, "name": "草药丛"}]},
    {"id": "m_cave", "name": "无限矿洞",
     "monsters": [{"enemy": "bat", "count": 0, "respawn_minutes": 5}],
     "exits": {"up": {"to": "m_field", "mode": "bidirectional"}},
     "gather_points": [
         {"id": "gp_ore", "item": "ore", "rate": 1.0, "rarity": "gold", "name": "矿脉"}]},
    {"id": "m_empty", "name": "空地图", "monsters": [], "exits": {}},
    {"id": "m_night", "name": "夜之林",
     "monsters": [{"enemy": "slime", "count": 2, "respawn_minutes": 5}], "exits": {},
     "gather_points": [
         {"id": "gp_night", "item": "herb", "rate": 1.0, "periods": ["night"],
          "seasons": ["autumn"], "name": "夜光菇"}]},
]


def _write_pack(root: Path) -> Path:
    """把探针包写进临时内容根（唯一写盘点 = tmp_path）。"""
    pack = root / "content" / "gatherprobe"
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "manifest.json").write_text(json.dumps(
        {"name": "采集探针包", "version": "1.0.0", "schema_version": 1,
         "modules": ["maps", "items", "enemies"]}, ensure_ascii=False), encoding="utf-8")
    (pack / "items.json").write_text(json.dumps(_ITEMS, ensure_ascii=False), encoding="utf-8")
    (pack / "enemies.json").write_text(json.dumps(_ENEMIES, ensure_ascii=False),
                                       encoding="utf-8")
    (pack / "maps.json").write_text(json.dumps(_MAPS, ensure_ascii=False), encoding="utf-8")
    return pack


@pytest.fixture()
def probe(tmp_path: Path) -> Dict[str, Any]:
    """真实 build_pack 装载临时包 → registry 原始模块（loader + 校验全过）。"""
    pack_dir = _write_pack(tmp_path)
    try:
        built, _ = build_pack(pack_dir)
    except PackLoadError as exc:  # pragma: no cover - 探针包应零红拦
        raise AssertionError(f"探针包应零红拦：{exc.report.errors}") from exc
    assert built.report.ok
    return built.registry.modules_raw


def _ctx(probe: Dict[str, Any], *, location: str = "m_field", **over: Any) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "registered": True,
        "qid": "u1",
        "player": {"name": "测试勇士", "qid": "u1"},
        "map_id": location,
        "location": location,
        "persistent_state": {"location": location},
        "maps": probe["maps"],
        "items": {it["id"]: it for it in probe["items"]},
        "inventory": {},
        "templates": None,
        "season": "spring",
        "period": "noon",
        "weather": "clear",
        "rng": random.Random(42),
        "now": 1000.0,
    }
    ctx.update(over)
    return ctx


def _enter(ctx: Dict[str, Any], target: str) -> str:
    """/进入 <目标>（真实通道行走）；随后按装配层口径把位置刷回 ctx["location"]。"""
    out = cmd_enter(parse_command(f"进入 {target}"), ctx)
    text = out if isinstance(out, str) else str(out.get("message") or "")
    ctx["location"] = ctx["persistent_state"].get("location", ctx["location"])
    ctx["map_id"] = ctx["location"]
    return text


# =====================================================================================
# A · E2E 主线：进入 → 采集 → 产出真进背包（背包前后对比）
# =====================================================================================
def test_e2e_enter_then_gather_puts_item_into_inventory(probe) -> None:
    ctx = _ctx(probe)
    msg = _enter(ctx, "下")
    assert "无限矿洞" in msg                     # 真实通道行走成功
    assert ctx["location"] == "m_cave"

    before = dict(ctx["inventory"])
    out = cmd_gather(parse_command("采集"), ctx)
    after = dict(ctx["inventory"])
    # 贴数值：背包前后对比
    assert before == {}
    assert after == {"ore": 1}
    assert "✅ 采到 矿石（金色）" in out
    assert "本图资源无限" in out                  # 无限资源图提示（【总纲】L1280）


def test_e2e_finite_map_first_gather_then_cooling(probe) -> None:
    """有限图（怪物 count>0）：首次命中入包并进冷却；二次采集 = 次数耗尽 → 人话提示。"""
    ctx = _ctx(probe, location="m_field")
    before = dict(ctx["inventory"])
    first = cmd_gather(parse_command("采集"), ctx)
    assert "✅ 采到 灵草（普通）" in first
    assert ctx["inventory"] == {"herb": 1}
    assert before == {}
    st = dict(ctx["gather_state"])
    assert st == {"m_field:gp_herb": 1000.0 + 10 * 60}

    # 二次采集（同一时钟）：冷却中 → 人话提示；背包不变、冷却状态不变
    inv_before, st_before = dict(ctx["inventory"]), dict(ctx["gather_state"])
    second = cmd_gather(parse_command("采集"), ctx)
    assert "草药丛：采空了" in second and "10 分钟后恢复" in second
    assert ctx["inventory"] == inv_before == {"herb": 1}
    assert ctx["gather_state"] == st_before

    # 10 分钟后（注入 now）→ 恢复可采
    ctx["now"] = 1000.0 + 10 * 60
    third = cmd_gather(parse_command("采集"), ctx)
    assert "✅ 采到 灵草（普通）" in third
    assert ctx["inventory"] == {"herb": 2}


def test_e2e_unlimited_map_repeatable_without_cooldown(probe) -> None:
    ctx = _ctx(probe, location="m_cave")
    cmd_gather(parse_command("采集"), ctx)
    cmd_gather(parse_command("采集"), ctx)
    assert ctx["inventory"] == {"ore": 2}        # 连采两次都进包
    assert not ctx.get("gather_state")           # 无限资源图不产生冷却


# =====================================================================================
# B · 边界：人话提示 + 不满足条件时背包不变
# =====================================================================================
def test_no_gather_points_human_text_and_inventory_unchanged(probe) -> None:
    ctx = _ctx(probe, location="m_empty")
    out = cmd_gather(parse_command("采集"), ctx)
    assert out == "❌ 本图没有采集点\n发 地图 换个地方"
    assert ctx["inventory"] == {} and not ctx.get("gather_state")


def test_period_gate_human_text_and_inventory_unchanged(probe) -> None:
    ctx = _ctx(probe, location="m_night", period="noon", season="autumn")
    out = cmd_gather(parse_command("采集"), ctx)
    assert out == "【采集】夜之林\n夜光菇：当前夜不出"
    assert ctx["inventory"] == {} and not ctx.get("gather_state")
    # 命中时节 → 可采（证明门控是唯一差异）
    ctx["period"] = "night"
    ok = cmd_gather(parse_command("采集"), ctx)
    assert "✅ 采到 灵草（普通）" in ok
    assert ctx["inventory"] == {"herb": 1}


def test_season_gate_human_text(probe) -> None:
    """时段命中、季节不命中 → 如实报季节（不误报时段）。"""
    ctx = _ctx(probe, location="m_night", period="night", season="winter")
    out = cmd_gather(parse_command("采集"), ctx)
    assert out == "【采集】夜之林\n夜光菇：当前秋不出"
    assert ctx["inventory"] == {} and not ctx.get("gather_state")


def test_unknown_location_human_text(probe) -> None:
    ctx = _ctx(probe)
    ctx["location"] = "no_such_map"
    out = cmd_gather(parse_command("采集"), ctx)
    assert out == "❌ 位置未知\n发 位置 查看当前位置"
    assert ctx["inventory"] == {}


def test_extra_arg_usage_human_text(probe) -> None:
    ctx = _ctx(probe)
    out = cmd_gather(parse_command("采集 1"), ctx)
    assert out == "❌ 采集 不需要参数\n发 采集 直接采集"
    assert ctx["inventory"] == {}


def test_conditions_not_met_does_not_call_add_item_hook(probe) -> None:
    """写盘四断言之一：条件不满足 → 无入包 hook 调用、背包不变、冷却不变。"""
    calls: list = []
    ctx = _ctx(probe, location="m_night", period="noon",
               add_item=lambda item, count, bound: calls.append((item, count, bound)) or True)
    out = cmd_gather(parse_command("采集"), ctx)
    assert "不出" in out
    assert calls == []
    assert ctx["inventory"] == {} and not ctx.get("gather_state")


# =====================================================================================
# C · 入包链路（hook 优先）+ 确定性
# =====================================================================================
def test_add_item_hook_is_preferred_over_inventory(probe) -> None:
    calls: list = []

    def hook(item: str, count: int, bound: bool) -> bool:
        calls.append((item, count, bound))
        return True

    ctx = _ctx(probe, location="m_field", add_item=hook)
    cmd_gather(parse_command("采集"), ctx)
    assert calls == [("herb", 1, False)]         # 走既有入包 hook（装配层负责落盘）
    assert ctx["inventory"] == {}                # hook 路径不回写 inventory 兜底


def test_add_item_failure_does_not_consume_cooldown(probe) -> None:
    """入包失败（hook 返回 False）→ 不写冷却（G-2 防空耗）。"""
    ctx = _ctx(probe, location="m_field", add_item=lambda *a, **k: False)
    out = cmd_gather(parse_command("采集"), ctx)
    assert "入包失败" in out
    assert not ctx.get("gather_state")
    assert ctx["inventory"] == {}


def test_determinism_same_seed_same_message(probe) -> None:
    a = _ctx(probe, location="m_field", rng=random.Random(2026))
    b = _ctx(probe, location="m_field", rng=random.Random(2026))
    assert cmd_gather(parse_command("采集"), a) == cmd_gather(parse_command("采集"), b)
    assert a["inventory"] == b["inventory"]


# =====================================================================================
# D · 回归：钓鱼链路不受影响（同图 /钓鱼 行为不变）
# =====================================================================================
def test_fishing_chain_unaffected_on_gather_map(probe) -> None:
    """加了采集点字段后，/钓鱼 空态与行为不变（钓鱼读 gather_points 的引用路径未动）。"""
    ctx = _ctx(probe, location="m_field", fishing={"species": []})
    out = cmd_fishing(parse_command("钓鱼"), ctx)
    assert out == "【垂钓点】\n本图暂无可钓鱼点"
    assert ctx["inventory"] == {}
    # /采集 不新增任何钓鱼状态键（钓鱼链路互不干扰）
    keys_before = set(ctx)
    cmd_gather(parse_command("采集"), ctx)
    assert {k for k in set(ctx) - keys_before if k.startswith("fish")} == set()


# =====================================================================================
# E · 装配 + 常量
# =====================================================================================
def test_register_gather_commands() -> None:
    router = Router()
    register_gather_commands(router, make_context=lambda p: {})
    assert GATHER_CMD in router.names()
    assert router.get(GATHER_CMD).whitelisted is True


def test_register_gather_requires_make_context() -> None:
    router = Router()
    register_gather_commands(router, make_context=None)
    with pytest.raises(RuntimeError):
        router.get(GATHER_CMD).handler(parse_command("采集"))


def test_rarity_cn_covers_four_tiers() -> None:
    from qbot_rpg.core.gathering import rarity_tiers

    assert set(rarity_tiers()) == set(RARITY_CN)
