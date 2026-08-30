#!/usr/bin/env python3
"""M9 锻造·批8·路8A：批2 素材经济门禁（verify_m9_b2）。

依据：
  - docs/m9_batch_plan.md 批8（路8A：verify_m9_b2~b7 各批门禁脚本）+ 批2（素材经济拆
    3 路：2A 素材两档+来源 / 2B 素材即进度+死锁扫描 / 2C 死锁报告+DEAD 途径）
  - qbot_rpg/core/forge_material.py（material_tier_of/material_source/
    combine_3to1_available/combine_instances/comb_synth_map）
  - qbot_rpg/core/forge_progress.py（material_holdings/shortfall/progress_line/
    forge_readiness）
  - qbot_rpg/core/forge_deadlock.py（deadlock_report/deadlock_scan_ok/deadlock_hint）

本脚本对齐 scripts/verify/verify_m9_smoke.py 门禁模式：真实 content/test_demo 经
loader build_pack（check_pack 零红拦）+ 纯函数断言 + exit 0/1。零 NoneBot import、
确定性、无定时器/睡眠调用、渲染输出无 emoji（仅 ✅/❌）、零落盘。

场景（真实 test_demo 数据）：
  a. 素材两档判定：火龙鳞 rare / 矿石 normal（items 元数据 material_tier）+ 行覆写仲裁
  b. 来源归一三态：source_override > items.source > 兜底「来源未知」
  c. 3:1 combine 可用性：SP-F2 解锁 → ok；未解锁 → sp_locked；关开关 → synth_disabled；
     combine_instances 实例发现 + comb_synth_map 映射（moon_grass → ghost_moss）
  d. 素材即进度：铁剑 矿石 持有/差量/进度行（满额 ✅）/forge_readiness 满链判定
  e. 死锁扫描：真实 9 素材途径数汇总（star_iron 3 途径达标 / fire_dragon_scale 孤儿）+
     deadlock_scan_ok（W 级不拦截）+ deadlock_hint 缺口建议

退出码：0 = 批2 素材经济门禁通过（打印「M9_B2 OK」）；1 = 有失败。
"""
from __future__ import annotations

import pathlib
import sys
import traceback
from typing import Optional, Any, Dict, List, Mapping, cast

_REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO))

from qbot_rpg.content.loader import build_pack  # noqa: E402
from qbot_rpg.core.forge_deadlock import (  # noqa: E402
    THRESHOLD_NORMAL,
    THRESHOLD_RARE,
    deadlock_hint,
    deadlock_report,
    deadlock_scan_ok,
)
from qbot_rpg.core.forge_material import (  # noqa: E402
    combine_3to1_available,
    combine_instances,
    comb_synth_map,
    material_source,
    material_tier_of,
)
from qbot_rpg.core.forge_progress import (  # noqa: E402
    forge_readiness,
    material_holdings,
    progress_line,
    shortfall,
)
from qbot_rpg.core.forge_tree import ForgeTreeEngine  # noqa: E402

PACK_DIR = _REPO / "content" / "test_demo"

N_IRON = "node_iron_sword"   # 铁剑（lv1 矿石×3）
N_IRON_1 = "node_iron_sword_1"

_FAILS: List[str] = []
_OK: List[str] = []


def out(msg: str = "") -> None:
    print(msg)


def check(name: str, fn) -> None:
    try:
        fn()
        _OK.append(name)
        out(f"  ✅ {name}")
    except AssertionError as e:
        _FAILS.append(f"{name}: {e}")
        out(f"  ❌ {name}: {e}")
    except Exception as e:  # noqa: BLE001
        _FAILS.append(f"{name}: {type(e).__name__}: {e}")
        out(f"  ❌ {name}: {type(e).__name__}: {e}")
        traceback.print_exc()


# ---------------------------------------------------------------------------
# 模块上下文（真实 content/test_demo + loader build_pack）
# ---------------------------------------------------------------------------

_MODULES: Mapping[str, Any] = {}


def modules() -> Mapping[str, Any]:
    global _MODULES
    if not _MODULES:
        pack, _ = build_pack(PACK_DIR)
        assert len(pack.report.errors) == 0, f"check_pack 红拦：{pack.report.errors}"
        _MODULES = pack.modules
    return _MODULES


def ctx_with(inventory: Mapping[str, int], player: Mapping[str, Any]) -> Dict[str, Any]:
    mods = modules()
    forge_raw = mods["forge"]
    items_raw = mods["items"]
    settings_raw = mods["settings"]
    forge_seg = dict(settings_raw.get("forge")) if isinstance(settings_raw.get("forge"), Mapping) else {}  # noqa: E501
    settings = {**settings_raw, "forge": forge_seg}
    eng = ForgeTreeEngine(forge=forge_raw, items=items_raw, settings=settings)
    return {
        "forge": forge_raw,
        "items": items_raw,
        "settings": settings,
        "forge_tree": eng,
        "inventory": dict(inventory),
        "player": player,
        "qid": "b2_u1",
        "now": 1000.0,
    }


def make_player(*, forge_level: int = 1, sp: int = 0,
                unlocks: Optional[Mapping[str, int]] = None,
                forged: object = None,
            ) -> Dict[str, Any]:
    forged_list = list(forged) if isinstance(forged, (list, tuple, set, frozenset)) else []
    return {
        "proficiency": {
            "forge": {
                "level": forge_level, "exp": 0,
                "sp_earned": sp, "sp_used": 0,
                "unlocks": dict(unlocks or {}),
            }
        },
        "forged": forged_list,
        "currencies": {"coins": 99999},
        "title_state": {"owned": []},
    }


def _items_map() -> Dict[str, Mapping[str, Any]]:
    raw = modules()["items"]
    return {e["id"]: e for e in raw if isinstance(e, Mapping) and isinstance(e.get("id"), str)}


def _node(node_id: str):
    ctx = ctx_with({}, {})
    return ctx["forge_tree"].node(node_id)


# ---------------------------------------------------------------------------
# 场景实现
# ---------------------------------------------------------------------------

def t_pack_zero_red() -> None:
    """loader build_pack：真实 test_demo check_pack 零红拦。"""
    pack, _ = build_pack(PACK_DIR)
    assert len(pack.report.errors) == 0, f"红拦：{pack.report.errors}"
    assert pack.pack_id == "test_demo"
    assert "forge" in pack.modules and "items" in pack.modules and "settings" in pack.modules


def t_material_tier() -> None:
    """a. 素材两档：火龙鳞 rare / 矿石 normal + 行覆写仲裁（TIER-03a / M-03）。"""
    items = _items_map()
    # 火龙鳞：items 元数据 material_tier=rare → rare
    assert material_tier_of(items_def=items.get("fire_dragon_scale"), material_row=None) == "rare"
    # 矿石：items 元数据 material_tier=normal → normal
    assert material_tier_of(items_def=items.get("ore"), material_row=None) == "normal"
    # 行覆写 > items 元数据：normal 素材行带 tier=rare → rare（M-03 行覆写优先）
    assert material_tier_of(
        items_def=items.get("ore"),
        material_row={"item": "ore", "count": 3, "tier": "rare"},
    ) == "rare"
    # 双缺省 → 缺省档位 normal（确定性兜底）
    assert material_tier_of(items_def=None, material_row=None) == "normal"


def t_material_source() -> None:
    """b. 来源归一三态：source_override > items.source > 兜底（SOUR-00）。"""
    items = _items_map()
    # 火龙鳞：items.source=「火龙掉落/商店」
    assert material_source(
        items_def=items.get("fire_dragon_scale"), material_row=None,
    ) == "火龙掉落/商店"
    # 行覆写 source_override 优先
    assert material_source(
        items_def=items.get("fire_dragon_scale"),
        material_row={"item": "fire_dragon_scale", "count": 3,
                      "source_override": "熔火洞窟采集"},
    ) == "熔火洞窟采集"
    # 双缺省 → 兜底「来源未知」
    assert material_source(items_def=None, material_row=None) == "来源未知"


def t_combine_3to1() -> None:
    """c. 3:1 combine：SP-F2 解锁可用 / 未解锁 sp_locked / 关开关 synth_disabled。"""
    ctx = ctx_with({}, {})
    player_ok = make_player(forge_level=3, sp=5, unlocks={"unlock_combine_3to1": 1})
    res = combine_3to1_available(player_ok, settings=ctx["settings"])
    assert res.get("ok") is True, res
    res = combine_3to1_available(make_player(forge_level=3), settings=ctx["settings"])
    assert res.get("ok") is False and res.get("reason") == "sp_locked", res
    settings_off = {**ctx["settings"], "forge": {**ctx["settings"]["forge"], "synth_ratio_3to1": False}}  # noqa: E501
    res = combine_3to1_available(player_ok, settings=settings_off)
    assert res.get("ok") is False and res.get("reason") == "synth_disabled", res


def t_combine_instances_map() -> None:
    """c'. combine 实例发现 + comb_synth_map 映射（moon_grass → ghost_moss）。"""
    mods = modules()
    insts = combine_instances(mods)
    assert any(
        i.get("recipe_id") == "rcp_combine_3to1"
        and i.get("inputs") == [{"item": "moon_grass", "count": 3}]
        and i.get("output") == {"item": "ghost_moss", "count": 1}
        for i in insts
    ), f"combine 实例未发现：{insts}"
    synth = comb_synth_map(mods)
    assert synth.get("moon_grass") == "ghost_moss", synth


def t_material_progress() -> None:
    """d. 素材即进度：铁剑 持有/差量/进度行 ✅/满链判定（PROG-01~05）。"""
    ctx = ctx_with({"ore": 3}, make_player(forge_level=1))
    holdings = material_holdings(ctx, _node(N_IRON))
    assert holdings["ore"]["need"] == 3 and holdings["ore"]["have"] == 3
    assert holdings["ore"]["name"] == "矿石"
    assert holdings["ore"]["source"] == "挖掘点/商店"
    # 差量：持有 1 → 缺 2
    ctx2 = ctx_with({"ore": 1}, make_player(forge_level=1))
    short = shortfall(material_holdings(ctx2, _node(N_IRON)))
    assert short["items"] == [("矿石", 2, "挖掘点/商店")], short
    assert short["coins"] == 0 and short["gem"] == 0
    # 进度行：满额 ✅
    line_full = progress_line(material_holdings(ctx, _node(N_IRON)))
    assert (line_full.startswith("当前持有：") and "矿石 3/3" in line_full
            and "✅" in line_full), line_full
    # 进度行：未满不标 ✅
    line_part = progress_line(material_holdings(ctx2, _node(N_IRON)))
    assert "矿石 1/3" in line_part and "✅" not in line_part, line_part
    # 进度行：已锻前置名后 ✅
    line_pre = progress_line(material_holdings(ctx, _node(N_IRON_1)),
                             forged_prefix_names=["铁剑"])
    assert "铁剑 ✅" in line_pre and "矿石 3/5" in line_pre, line_pre
    # 满链推进度：素材满额 + 根节点 → ready
    ready = forge_readiness(ctx, make_player(forge_level=1), _node(N_IRON), tree=ctx["forge_tree"])
    assert ready["ready"] is True and ready["message"] == "可锻造", ready
    # 缺口：铁剑Ⅰ 需前置 + 素材不足
    ctx3 = ctx_with({"ore": 2}, make_player(forge_level=1))
    not_ready = forge_readiness(ctx3, make_player(forge_level=1), _node(N_IRON_1),
                                tree=ctx3["forge_tree"])
    assert not_ready["ready"] is False, not_ready
    gaps = not_ready.get("gaps", [])
    assert any("需先锻造" in g and "铁剑" in g for g in gaps), gaps
    assert any("缺 矿石" in g for g in gaps), gaps


def t_deadlock_scan() -> None:
    """e. 死锁扫描：真实 test_demo 全素材途径数 + 达标判定 + 缺口建议（DEAD-04/06/07）。"""
    mods = modules()
    report = deadlock_report(mods)
    items = {it["item_id"]: it for it in cast(list, report["items"])
             if isinstance(it, Mapping) and isinstance(it.get("item_id"), str)}
    assert set(items) == {
        "alch_ember_crystal", "alch_fire_essence", "alch_frost_crystal", "ash_core",
        "fire_dragon_scale", "ice_crystal_ore", "ore", "star_iron", "thunder_beast_fang",
    }, f"forge 引用素材应全量扫描：{sorted(items)}"
    # 达标：星铁矿石 normal 3 途径（drop+shop+gather）→ 无 gap
    star = items["star_iron"]
    assert star["tier"] == "normal" and star["threshold"] == THRESHOLD_NORMAL
    assert star["source_count"] == 3 and star["gap"] is False, star
    # 孤儿：火龙鳞 rare 0 途径（仅 items.source 标签，无产出表）→ gap + orphan
    fds = items["fire_dragon_scale"]
    assert fds["tier"] == "rare" and fds["threshold"] == THRESHOLD_RARE
    assert fds["source_count"] == 0 and fds["gap"] is True and fds["orphan"] is True, fds
    # 普通孤儿：矿石 0 途径 → gap（低于下限 3）
    ore = items["ore"]
    assert ore["tier"] == "normal" and ore["source_count"] == 0 and ore["gap"] is True, ore
    # 达标判定：存在 gap → scan_ok False（W 级不拦截，仅提示）
    assert report["ok"] is False
    assert deadlock_scan_ok(report) is False
    # 缺口建议：gap 素材给替代途径文案；达标素材空
    hint = deadlock_hint("fire_dragon_scale", report)
    assert "建议补" in hint and "3:1 合成" in hint, hint
    assert deadlock_hint("star_iron", report) == ""
    # 确定性：重复调用结果一致
    assert report == deadlock_report(mods)


def main() -> int:
    out("=" * 60)
    out("M9 批2 素材经济门禁 verify_m9_b2（依据 m9_batch_plan.md 批8）")
    out("=" * 60)
    check("pack: build_pack 零红拦（真实 test_demo）", t_pack_zero_red)
    check("a. 素材两档（火龙鳞 rare / 矿石 normal + 行覆写）", t_material_tier)
    check("b. 来源归一三态（source_override > items.source > 兜底）", t_material_source)
    check("c. 3:1 combine 可用性（解锁/sp_locked/关开关）", t_combine_3to1)
    check("c'. combine 实例发现 + comb_synth_map 映射", t_combine_instances_map)
    check("d. 素材即进度（持有/差量/进度行 ✅/满链判定）", t_material_progress)
    check("e. 死锁扫描（途径数/达标判定/缺口建议）", t_deadlock_scan)
    out("=" * 60)
    if _FAILS:
        out(f"❌ M9_B2 FAILED：{len(_FAILS)} 个断言失败")
        for f in _FAILS:
            out(f"  - {f}")
        return 1
    out(f"M9_B2 OK（{len(_OK)} 项全绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
