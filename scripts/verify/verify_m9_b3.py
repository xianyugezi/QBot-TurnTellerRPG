#!/usr/bin/env python3
"""M9 锻造·批8·路8A：批3 铸造职业层门禁（verify_m9_b3）。

依据：
  - docs/m9_batch_plan.md 批8（路8A：verify_m9_b2~b7 各批门禁脚本）+ 批3（铸造职业层
    拆 3 路：3A 铸造 7 级门槛+熟练计价 / 3B SP 面板 F1~F5 / 3C 铸造王）
  - qbot_rpg/core/forge_job.py（forge_level/level_gate_met/gain_forge_exp/
    exp_to_next/rank_name + configure_proficiency）
  - qbot_rpg/core/forge_sp.py（sp_available/sp_unlock/sp_locked/sp_panel_view +
    FORGE_SP_PANEL）
  - qbot_rpg/core/forge_king.py（codex_all_lit/king_eligible/grant_forge_king/
    king_only_nodes/king_bonus/forge_king_eligible_check）

本脚本对齐 scripts/verify/verify_m9_smoke.py 门禁模式：真实 content/test_demo 经
loader build_pack（check_pack 零红拦）+ proficiency.json forge 实例真实加载
（configure_proficiency）+ 纯函数断言 + exit 0/1。零 NoneBot import、确定性、
无定时器/睡眠调用、渲染输出无 emoji（仅 ✅/❌）、零落盘。

场景（真实 test_demo 数据）：
  a. 铸造 7 级门槛：proficiency.json forge 实例加载——forge_level / level_gate_met
     （越级拒，need/current/missing）/ forge_exp_for 熟练计价（节点等级×2）/
     exp_to_next 缺口（还差 N 熟练）/ rank_name 档位名
  b. SP 面板 F1~F5：sp_available / sp_unlock（成功+幂等 not_repeatable / SP 不足拒 /
     未识别面板拒）/ sp_locked / sp_panel_view 五项
  c. 铸造王：codex_all_lit（全亮判定）/ king_eligible（未全亮拒）/ grant_forge_king
     （未全亮拒 → 全链锻造后授予）/ king_only 守卫（king_title_required 拒 →
     获王后放行）/ king_bonus 称号加成

退出码：0 = 批3 铸造职业层门禁通过（打印「M9_B3 OK」）；1 = 有失败。
"""
from __future__ import annotations

import pathlib
import sys
import traceback
from typing import Optional, Any, Dict, List, Mapping, MutableMapping

_REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO))

from qbot_rpg.commands.forge_commands import cmd_forge  # noqa: E402
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command  # noqa: E402
from qbot_rpg.content.loader import build_pack  # noqa: E402
from qbot_rpg.core.forge_job import (  # noqa: E402
    configure_proficiency,
    exp_to_next,
    forge_exp_for,
    forge_level,
    gain_forge_exp,
    level_gate_met,
    rank_name,
)
from qbot_rpg.core.forge_king import (  # noqa: E402
    FORGE_KING_BONUS_DEFAULT,
    FORGE_KING_BONUS_KEY,
    KING_TITLE_ID,
    codex_all_lit,
    forge_king_eligible_check,
    grant_forge_king,
    king_bonus,
    king_eligible,
    king_only_nodes,
)
from qbot_rpg.core.forge_sp import (  # noqa: E402
    FORGE_SP_PANEL,
    sp_available,
    sp_locked,
    sp_panel_view,
    sp_unlock,
)
from qbot_rpg.core.forge_tree import ForgeTreeEngine  # noqa: E402

PACK_DIR = _REPO / "content" / "test_demo"

# 节点 id 常量（test_demo forge.json）
N_IRON = "node_iron_sword"
N_IRON_1 = "node_iron_sword_1"
N_IRON_2 = "node_iron_sword_2"
N_FLAME = "node_flame_sword"
N_FLAME_2 = "node_flame_sword_2"
N_FLAME_3 = "node_flame_sword_3"
N_KING = "node_flame_king_sword"
N_ICE = "node_ice_sword"
N_THUNDER = "node_lightning_sword"
ALL_NODES = [N_IRON, N_IRON_1, N_IRON_2, N_FLAME, N_FLAME_2, N_FLAME_3,
             N_KING, N_ICE, N_THUNDER]

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
# 模块上下文（真实 content/test_demo + proficiency.json forge 实例）
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
        "registry": None,
        "inventory": dict(inventory),
        "player": player,
        "qid": "b3_u1",
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


def _configure_proficiency() -> None:
    """proficiency.json 真实 forge 实例注入模块级引擎（装配期一次性，批3 门禁主配置）。"""
    mods = modules()
    configure_proficiency(mods["proficiency"], mods["settings"])


def parsed(raw: str):
    """parse_command 真实解析（白名单：DEFAULT_WHITELIST 含 锻造 + 图纸）。"""
    whitelist = set(DEFAULT_WHITELIST) | {"图纸"}
    return parse_command(raw, whitelist=whitelist)


# ---------------------------------------------------------------------------
# 场景实现
# ---------------------------------------------------------------------------

def t_pack_zero_red() -> None:
    """loader build_pack：真实 test_demo check_pack 零红拦 + proficiency 模块存在。"""
    pack, _ = build_pack(PACK_DIR)
    assert len(pack.report.errors) == 0, f"红拦：{pack.report.errors}"
    assert "proficiency" in pack.modules


def t_job_gate() -> None:
    """a. 铸造 7 级门槛：forge_level / level_gate_met 越级拒 / 熟练计价 /
    exp_to_next / rank_name。"""
    _configure_proficiency()
    # forge_level：真实读取 / 缺省 0
    assert forge_level(make_player(forge_level=5)) == 5
    assert forge_level(make_player(forge_level=0)) == 0
    assert forge_level({}) == 0
    # level_gate_met：节点等级 ≤ 职业等级 → 可锻；越级 → 拒（need/current/missing）
    gate_ok = level_gate_met(make_player(forge_level=2), 2)
    assert gate_ok["ok"] is True and gate_ok["missing"] == 0, gate_ok
    gate_ng = level_gate_met(make_player(forge_level=1), 7)   # 越级（炎王剑 lv7）
    assert gate_ng["ok"] is False and gate_ng["reason"] == "level_insufficient", gate_ng
    assert gate_ng["need"] == 7 and gate_ng["current"] == 1 and gate_ng["missing"] == 6, gate_ng
    # 熟练计价：节点等级×2（真实 settings exp_per_forge=「节点等级×2」）
    ctx = ctx_with({}, {})
    assert forge_exp_for(1, ctx["settings"]) == 2
    assert forge_exp_for(2, ctx["settings"]) == 4
    assert forge_exp_for(7, ctx["settings"]) == 14
    # gain_forge_exp：lv2 节点 → +4 熟练，仍在见习（阈值 100）
    player = make_player(forge_level=0)
    res = gain_forge_exp(player, 2, ctx["settings"])
    assert res["ok"] is True and res["exp_gained"] == 4, res
    assert player["proficiency"]["forge"]["exp"] == 4
    # exp_to_next：缺口 = cost − exp（还差 N 熟练）
    detail = exp_to_next(player)
    assert detail["level"] == 0 and detail["rank"] == "见习", detail
    assert detail["cost"] == 100 and detail["missing"] == 96, detail
    assert detail["maxed"] is False
    # rank_name：档位名随等级（见习→正式→…→王）
    assert rank_name(make_player(forge_level=0)) == "见习"
    assert rank_name(make_player(forge_level=1)) == "正式"
    assert rank_name(make_player(forge_level=4)) == "大师"
    assert rank_name(make_player(forge_level=6)) == "王"
    # 满级 exp_to_next → maxed
    maxed = exp_to_next(make_player(forge_level=6))
    assert maxed["maxed"] is True and maxed["missing"] == 0, maxed


def t_sp_panel() -> None:
    """b. SP 面板 F1~F5：可用/解锁/幂等/SP 不足/未识别/锁定判定/面板视图。"""
    _configure_proficiency()
    panel_ids = [item["id"] for item in FORGE_SP_PANEL]
    assert panel_ids == [
        "unlock_branch_tree", "unlock_combine_3to1", "unlock_slot_tool",
        "unlock_sets", "unlock_augment",
    ], panel_ids
    # sp_available：sp_earned − sp_used
    player = make_player(forge_level=7, sp=5)
    assert sp_available(player) == 5
    assert sp_available(make_player(forge_level=7, sp=0)) == 0
    # sp_unlock 成功：sp_used +1 / unlocks 登记
    res = sp_unlock(player, "unlock_sets")
    assert res["ok"] is True and res["sp_used_delta"] == 1, res
    assert player["proficiency"]["forge"]["sp_used"] == 1
    assert player["proficiency"]["forge"]["unlocks"]["unlock_sets"] == 1
    assert sp_available(player) == 4
    # 幂等：repeatable=false 二次解锁 → not_repeatable，不重复扣点
    res2 = sp_unlock(player, "unlock_sets")
    assert res2["ok"] is False and res2["reason"] == "not_repeatable", res2
    assert player["proficiency"]["forge"]["sp_used"] == 1
    # SP 不足拒
    poor = make_player(forge_level=7, sp=0)
    res3 = sp_unlock(poor, "unlock_sets")
    assert res3["ok"] is False and res3["reason"] == "sp_insufficient", res3
    # 未识别面板拒
    res4 = sp_unlock(player, "nope")
    assert res4["ok"] is False and res4["reason"] == "panel_not_found", res4
    # sp_locked：未解锁 → True；已解锁 → False；未识别 → True
    assert sp_locked(make_player(forge_level=7), "unlock_sets") is True
    assert sp_locked(player, "unlock_sets") is False
    assert sp_locked(player, "unlock_combine_3to1") is True   # 未解锁
    assert sp_locked(player, "nope") is True                  # 保守锁定
    # sp_panel_view：5 项 + unlocked 状态
    view = sp_panel_view(player)
    assert len(view) == 5
    assert [v["id"] for v in view] == panel_ids
    by_id = {v["id"]: v for v in view}
    assert by_id["unlock_sets"]["unlocked"] is True
    assert by_id["unlock_augment"]["unlocked"] is False
    assert by_id["unlock_branch_tree"]["scope"] == "/图纸 /锻造树"


def _forge_full_chain(player: MutableMapping[str, Any]) -> None:
    """沿主链逐节点锻造至 ■炎王剑（满素材满等级），点亮全图鉴（KF-01）。"""
    mods = modules()  # noqa: F841 (build_pack 副作用校验)
    mats = {
        N_IRON: {"ore": 3},
        N_IRON_1: {"ore": 5},
        N_IRON_2: {"ore": 8, "star_iron": 2},
        N_FLAME: {"ore": 5, "fire_dragon_scale": 3},
        N_FLAME_2: {"fire_dragon_scale": 5, "alch_ember_crystal": 2},
        N_FLAME_3: {"fire_dragon_scale": 8, "alch_fire_essence": 1},
        N_KING: {"fire_dragon_scale": 10, "ash_core": 2},
        N_ICE: {"ice_crystal_ore": 6, "alch_frost_crystal": 2},
        N_THUNDER: {"thunder_beast_fang": 4, "star_iron": 2},
    }
    inv: Dict[str, int] = {}
    for need in mats.values():
        for iid, cnt in need.items():
            inv[iid] = inv.get(iid, 0) + cnt * 2
    ctx = ctx_with(inv, player)
    ctx["player"] = player
    player["proficiency"]["forge"]["level"] = 7       # 铸造 7 级门槛
    targets = {
        N_IRON: "铁剑", N_IRON_1: "铁剑Ⅰ", N_IRON_2: "铁剑Ⅱ", N_FLAME: "炎剑",
        N_FLAME_2: "炎剑Ⅱ", N_FLAME_3: "炎剑Ⅲ", N_KING: "■炎王剑",
        N_ICE: "冰剑", N_THUNDER: "雷剑",
    }
    for nid, target in targets.items():
        out_txt = cmd_forge(parsed(f"/锻造 {target}"), ctx)
        assert out_txt.startswith("✅"), f"{nid} 锻造失败：{out_txt}"


def t_forge_king() -> None:
    """c. 铸造王：未全亮拒 / 全链锻造后全亮授予 / king_only 守卫 / 称号加成。"""
    _configure_proficiency()
    mods = modules()
    settings_raw = mods["settings"]
    forge_seg = dict(settings_raw.get("forge")) if isinstance(settings_raw.get("forge"), Mapping) else {}  # noqa: E501
    settings = {**settings_raw, "forge": forge_seg}

    # c1 未全亮 → eligible False / grant 拒（codex_incomplete）
    player0 = make_player(forge_level=7)
    ctx0 = ctx_with({}, player0)
    elig0 = king_eligible(player0, ctx0)
    assert elig0["eligible"] is False and elig0["reason"] == "codex_incomplete", elig0
    assert codex_all_lit(ctx0)["total"] == 9 and codex_all_lit(ctx0)["lit_count"] == 0
    res0 = grant_forge_king(player0, ctx0)
    assert res0["ok"] is False and res0["reason"] == "codex_incomplete", res0

    # c2 全链锻造（点亮全图鉴）→ eligible True → 授予
    player1 = make_player(forge_level=7)
    _forge_full_chain(player1)
    ctx1 = ctx_with({}, player1)
    elig1 = king_eligible(player1, ctx1)
    assert elig1["eligible"] is True, elig1
    assert elig1["lit_count"] == elig1["total"] == 9, elig1
    res1 = grant_forge_king(player1, ctx1)
    assert res1["ok"] is True and res1["granted"] is True, res1
    assert KING_TITLE_ID in {str(x) for x in player1.get("title_state", {}).get("owned", [])}
    # 幂等：已拥有 → granted False
    res1b = grant_forge_king(player1, ctx1)
    assert res1b["ok"] is True and res1b["granted"] is False, res1b

    # c3 king_only 守卫（KF-02 ①）：专属配方节点未获王拒 → 获王后放行
    king_only_id = "node_king_only_test"
    forge_raw = dict(mods["forge"])
    forge_raw["trees"] = [{
        "id": "tree_king", "name": "王专属树", "type": "weapon", "roots": [king_only_id],
        "nodes": [{
            "id": king_only_id, "name": "王剑", "item": "king_sword", "type": "weapon",
            "level": 7, "parent": None, "branch": [], "stats": {"atk": 90}, "slots": [],
            "materials": [{"item": "fire_dragon_scale", "count": 10}],
            "rarity": "legendary", "final": True, "king_only": True,
        }],
    }]
    king_eng = ForgeTreeEngine(forge=forge_raw, items=mods["items"], settings=settings)
    ctx_k = ctx_with({}, make_player(forge_level=7))
    ctx_k["forge"] = forge_raw
    ctx_k["forge_tree"] = king_eng
    assert king_only_nodes(forge_raw) == [king_only_id]
    guard = forge_king_eligible_check(player0, ctx_k, king_only_id)
    assert guard["ok"] is False and guard["reason"] == "king_title_required", guard
    assert guard["message"] == "未获铸造王" and guard["king_only"] is True, guard
    # 获王后放行
    guard_ok = forge_king_eligible_check(player1, ctx_k, king_only_id)
    assert guard_ok["ok"] is True and guard_ok["has_title"] is True, guard_ok
    # 非 king_only 节点守卫不适用
    guard_na = forge_king_eligible_check(player0, ctx0, N_IRON)
    assert guard_na["ok"] is True and guard_na["king_only"] is False, guard_na

    # c4 称号加成（KF-02 ②）：settings 缺省 5% / 可配键
    bonus = king_bonus(settings)
    assert bonus["key"] == FORGE_KING_BONUS_KEY
    assert bonus["percent"] == FORGE_KING_BONUS_DEFAULT and bonus["pct"] == 0.05
    assert bonus["enabled"] is True
    seg = dict(settings["forge"])
    seg[FORGE_KING_BONUS_KEY] = 10
    bonus10 = king_bonus({**settings, "forge": seg})
    assert bonus10["percent"] == 10.0 and bonus10["pct"] == 0.10, bonus10


def main() -> int:
    out("=" * 60)
    out("M9 批3 铸造职业层门禁 verify_m9_b3（依据 m9_batch_plan.md 批8）")
    out("=" * 60)
    check("pack: build_pack 零红拦（真实 test_demo）", t_pack_zero_red)
    check("a. 铸造 7 级门槛（level_gate_met/熟练计价/exp_to_next/rank_name）", t_job_gate)
    check("b. SP 面板 F1~F5（可用/解锁/幂等/不足拒/锁定/视图）", t_sp_panel)
    check("c. 铸造王（图鉴全亮/授予/king_only 守卫/称号加成）", t_forge_king)
    out("=" * 60)
    if _FAILS:
        out(f"❌ M9_B3 FAILED：{len(_FAILS)} 个断言失败")
        for f in _FAILS:
            out(f"  - {f}")
        return 1
    out(f"M9_B3 OK（{len(_OK)} 项全绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
