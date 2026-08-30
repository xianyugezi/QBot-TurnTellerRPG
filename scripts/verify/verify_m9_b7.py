#!/usr/bin/env python3
"""M9 锻造·批8·路8A：批7 套装/客制门禁（verify_m9_b7）。

依据：
  - docs/m9_batch_plan.md 批8（路8A：verify_m9_b2~b7 各批门禁脚本）+ 批7（P1/P2 结构
    预留拆 3 路：7A 套装 forge_sets / 7B 客制 forge_augments / 7C /套装 /客制 查询骨架）
  - qbot_rpg/core/forge_sets.py（parse_sets/validate_sets/set_lookup/set_effects_contract）
  - qbot_rpg/core/forge_augments.py（parse_augments/validate_augments/limit_by_rarity/
    augment_eligible）
  - qbot_rpg/commands/forge_commands.py（cmd_sets/cmd_augments + SETS_LOCKED_MSG/
    AUGMENTS_LOCKED_MSG/SETS_EMPTY/AUGMENTS_EMPTY）

本脚本对齐 scripts/verify/verify_m9_smoke.py 门禁模式：真实 content/test_demo 经
loader build_pack + 纯函数断言 + exit 0/1。零 NoneBot import、确定性、无定时器/
睡眠调用、渲染输出无 emoji（仅 ✅/❌）、零落盘。

场景：
  a. forge_sets：真实 test_demo sets 段解析（空段 → []，合法）/ validate_sets
     （V1~V3 硬 + W1~W4 黄：空段 + sets_enabled=true → W3 黄，ok=True）/ 内存合成
     防具套装 fixture（真·过批0 V1~V3：beta 继承 alpha skills + set_lookup ready +
     set_effects_contract）
  b. forge_augments：真实 test_demo augments 解析（4 项）/ validate_augments（V4~V8/
     W2/W3 黄，ok=True）/ limit_by_rarity 次数表（epic×3 / legendary×2 / 终盘×1）/
     augment_eligible 资格（SP-F5 未解锁拒 / 宗师+最终强化武器+品质放行）
  c. /套装 /客制：SP-F4/F5 未解锁 → SETS_LOCKED_MSG / AUGMENTS_LOCKED_MSG 拒绝；
     解锁后查询渲染（套装 ready 行 / 客制面板 4 项）

退出码：0 = 批7 套装/客制门禁通过（打印「M9_B7 OK」）；1 = 有失败。
"""
from __future__ import annotations

import pathlib
import sys
import traceback
from typing import Optional, Any, Dict, List, Mapping, cast

_REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO))

from qbot_rpg.commands.forge_commands import (  # noqa: E402
    AUGMENTS_LOCKED_MSG,
    AUGMENTS_EMPTY,
    SETS_LOCKED_MSG,
    SETS_EMPTY,
    cmd_augments,
    cmd_sets,
)
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command  # noqa: E402
from qbot_rpg.content.loader import build_pack  # noqa: E402
from qbot_rpg.core.forge_augments import (  # noqa: E402
    AUGMENT_MASTER_LEVEL_MIN,
    AUGMENT_SP_PANEL_ID,
    augment_eligible,
    limit_by_rarity,
    parse_augments,
    validate_augments,
)
from qbot_rpg.core.forge_job import configure_proficiency  # noqa: E402
from qbot_rpg.core.forge_sets import (  # noqa: E402
    FULL_SET_PIECES,
    MIN_ACTIVATE_PIECES,
    parse_sets,
    set_effects_contract,
    set_lookup,
    validate_sets,
)
from qbot_rpg.core.forge_tree import ForgeTreeEngine  # noqa: E402

PACK_DIR = _REPO / "content" / "test_demo"

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
# 模块上下文
# ---------------------------------------------------------------------------

_MODULES: Mapping[str, Any] = {}


def modules() -> Mapping[str, Any]:
    global _MODULES
    if not _MODULES:
        pack, _ = build_pack(PACK_DIR)
        assert len(pack.report.errors) == 0, f"check_pack 红拦：{pack.report.errors}"
        _MODULES = pack.modules
    return _MODULES


def build_base() -> Dict[str, Any]:
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
        "inventory": {},
        "player": {},
        "qid": "b7_u1",
        "now": 1000.0,
    }


def make_player(*, forge_level: int = 1, sp: int = 0,
                unlocks: Optional[Mapping[str, int]] = None,
                equipped: object = None,
            ) -> Dict[str, Any]:
    mods = modules()
    configure_proficiency(mods["proficiency"], mods["settings"])
    eq_list = list(equipped) if isinstance(equipped, (list, tuple, set, frozenset)) else []
    return {
        "proficiency": {
            "forge": {
                "level": forge_level, "exp": 0,
                "sp_earned": sp, "sp_used": 0,
                "unlocks": dict(unlocks or {}),
            }
        },
        "forged": [],
        "equipped": eq_list,
        "currencies": {"coins": 99999},
        "title_state": {"owned": []},
    }


def fresh_ctx(inventory: Mapping[str, int], player: Mapping[str, Any]) -> Dict[str, Any]:
    ctx = build_base()
    ctx["inventory"] = dict(inventory)
    ctx["player"] = player
    return ctx


def parsed(raw: str):
    whitelist = set(DEFAULT_WHITELIST) | {"图纸"}
    return parse_command(raw, whitelist=whitelist)


def _synthetic_armor_forge() -> Dict[str, object]:
    """内存合成「防具树 + 套装」fixture（真·过批0 V1~V3；不改写文件）。

    防具五部位取 armor_head 树 5 节点；alpha 5 件满配 + 单 skill 2→3→5 连续档位
    （批0 V3「档位须从 2 起连续」）；beta 缺 skills → parse_sets 继承 alpha（VAR-01）。
    """
    nodes = []
    for i in range(1, 6):
        nodes.append({
            "id": f"node_helm_{i}", "name": f"铁盔{i}", "item": f"iron_helm_{i}",
            "type": "armor_head", "level": i,
            "parent": None if i == 1 else f"node_helm_{i - 1}", "branch": [],
            "stats": {"def": 4 + i}, "slots": [],
            "materials": [{"item": "ore", "count": 2 + i}],
            "rarity": "normal", "final": (i == 5),
        })
    return {
        "schema_version": "1.0",
        "trees": [{
            "id": "tree_armor_head", "name": "头盔树", "type": "armor_head",
            "roots": ["node_helm_1"], "nodes": nodes,
        }],
        "sets": [
            {
                "id": "guard_set", "name": "守卫套装", "variant": "alpha",
                "pieces": [f"node_helm_{i}" for i in range(1, 6)],
                "skills": [
                    {"piece_count": 2, "skill": "guard_skill", "level": 1,
                     "effect_ref": "fx_guard_1"},
                    {"piece_count": 3, "skill": "guard_skill", "level": 2,
                     "effect_ref": "fx_guard_2"},
                    {"piece_count": 5, "skill": "guard_skill", "level": 3,
                     "effect_ref": "fx_guard_3"},
                ],
                "codex_group": "guard_set",
            },
            {
                "id": "guard_set", "name": "守卫套装", "variant": "beta",
                "pieces": ["node_helm_1", "node_helm_2"],
                # beta 缺 skills → parse_sets 继承同族 alpha（VAR-01 档位共享）
            },
        ],
        "settings": {"sets_enabled": True, "augments_enabled": True},
    }


# ---------------------------------------------------------------------------
# 场景实现
# ---------------------------------------------------------------------------

def t_pack_zero_red() -> None:
    """loader build_pack：真实 test_demo check_pack 零红拦。"""
    pack, _ = build_pack(PACK_DIR)
    assert len(pack.report.errors) == 0, f"红拦：{pack.report.errors}"


def t_sets_parse_validate() -> None:
    """a1. forge_sets：真实 test_demo sets 段解析（空段 → []）+ validate_sets 结构校验。"""
    mods = modules()
    # 真实 test_demo sets=[]：空段合法
    real_sets = parse_sets({"forge": mods["forge"]})
    assert real_sets == [], f"test_demo sets 空段应解析为 []：{real_sets}"
    # validate_sets：V1~V3 无硬错 → ok=True；空段 + sets_enabled=true → W3 黄
    real_v = validate_sets({"forge": mods["forge"]})
    assert real_v["ok"] is True, f"空 sets 段应无硬错：{real_v['errors']}"
    assert real_v["sets_count"] == 0
    rules = {w.get("rule") for w in cast(list, real_v["warnings"]) if isinstance(w, Mapping)}
    assert "sets_empty" in rules, f"空段+sets_enabled=true 应有 W3 黄：{real_v['warnings']}"


def t_sets_synthetic() -> None:
    """a2. forge_sets：合成防具套装 → parse_sets（beta 继承）/ validate_sets 真过 /
    set_lookup（可组成 ready）/ set_effects_contract。"""
    forge_raw = _synthetic_armor_forge()

    # parse_sets：2 条记录；beta 缺 skills 继承 alpha（VAR-01）
    sets = parse_sets({"forge": forge_raw})
    assert len(sets) == 2, sets
    alpha = next(s for s in sets if s.variant == "alpha")
    beta = next(s for s in sets if s.variant == "beta")
    assert alpha.id == beta.id == "guard_set"
    assert len(alpha.skill_defs()) == 3
    assert len(beta.skill_defs()) == 3, "beta 应继承同族 alpha skills（VAR-01）"
    assert beta.raw.get("_skills_inherited_from") == "guard_set:alpha"
    assert alpha.pieces == ("node_helm_1", "node_helm_2", "node_helm_3",
                            "node_helm_4", "node_helm_5")

    # validate_sets（合成 fixture）：批0 V1~V3 全过 → ok=True；W1 件数不足黄（beta 2 件 <5）
    v = validate_sets({"forge": forge_raw})
    assert v["ok"] is True, f"合成防具套装应通过 V1~V3：{v['errors']}"
    assert v["sets_count"] == 2 and v["families"] == ["guard_set"]
    w_rules = {w.get("rule") for w in cast(list, v["warnings"]) if isinstance(w, Mapping)}
    assert "set_pieces_under_5" in w_rules, f"件数不足应有 W1 黄：{v['warnings']}"

    # set_lookup：装配 2 件（族级件数 ≥2）→ ready True（ACT-02）
    player2 = make_player(forge_level=1, equipped=["node_helm_1", "node_helm_2"])
    rows = set_lookup(player2, sets)
    assert len(rows) == 2, rows
    assert all(r.get("ready") for r in rows), f"族级件数 2 应两记录都 ready：{rows}"
    alpha_row = next(r for r in rows if r.get("variant") == "alpha")
    assert alpha_row["pieces_have"] == 2 and alpha_row["pieces_total"] == 5
    assert alpha_row["family_pieces_have"] == 2
    assert alpha_row["family_pieces_total"] == 5          # α(5)∪β(2)=5 件
    assert alpha_row["name"] == "守卫套装"

    # set_lookup：仅 1 件 → 未达 MIN_ACTIVATE_PIECES → ready False
    player1 = make_player(forge_level=1, equipped=["node_helm_1"])
    rows1 = set_lookup(player1, sets)
    assert all(r.get("ready") is False for r in rows1), rows1

    # set_effects_contract：技能契约展开
    contract = set_effects_contract(alpha)
    assert contract["ok"] is True and contract["set_id"] == "guard_set"
    skills = [sk for sk in cast(list, contract["skills"]) if isinstance(sk, Mapping)]
    assert len(skills) == 3
    assert skills[0]["piece_count"] == 2 and skills[0]["skill_id"] == "guard_skill"
    assert "穿 2 件激活" in skills[0]["trigger"]
    assert "效果接线：fx_guard_1" in skills[0]["desc"]

    # 常量对齐（ACT-02：2 件最低激活 / 5 件满配）
    assert MIN_ACTIVATE_PIECES == 2 and FULL_SET_PIECES == 5


def t_augments() -> None:
    """b. forge_augments：真实 test_demo 解析/校验/次数表/资格判定。"""
    mods = modules()
    forge_raw = mods["forge"]

    # parse_augments：4 项（攻击/会心/防御/开孔）
    rows = parse_augments({"forge": forge_raw})
    assert [r.id for r in rows] == ["aug_atk", "aug_crit", "aug_def", "aug_slot"], rows
    aug_atk = rows[0]
    assert aug_atk.aug_kind == "numeric" and aug_atk.effect == "最终武器攻击力 +8"
    assert aug_atk.stat_key == "atk" and aug_atk.value.get("flat") == 8
    aug_slot = rows[3]
    assert aug_slot.aug_kind == "slot" and aug_slot.slot_level == 1

    # validate_augments：V4~V8 无硬错 → ok=True + present=True
    v = validate_augments({"forge": forge_raw})
    assert v["ok"] is True, f"真实 augments 段应通过校验：{v['errors']}"
    assert v["present"] is True

    # limit_by_rarity：次数表 {epic:3, legendary:2} + 终盘 {legendary:1}
    lim = limit_by_rarity({"forge": forge_raw})
    assert lim["table"] == {"epic": 3, "legendary": 2}, lim
    assert lim["final_only"] == {"legendary": 1}, lim
    assert len(lim["rows"]) == 3

    # augment_eligible：SP-F5 未解锁 → sp_not_unlocked
    player_locked = make_player(forge_level=AUGMENT_MASTER_LEVEL_MIN, sp=0)
    weapon_ok = {"final": True, "augmentable": True, "rarity": "epic", "type": "weapon"}
    res_locked = augment_eligible(player_locked, weapon_ok)
    assert res_locked["ok"] is False and res_locked["reason"] == "sp_not_unlocked", res_locked

    # SP-F5 解锁 + 宗师 + 最终强化武器 + epic → 放行
    player_ok = make_player(forge_level=AUGMENT_MASTER_LEVEL_MIN,
                            unlocks={AUGMENT_SP_PANEL_ID: 1})
    res_ok = augment_eligible(player_ok, weapon_ok)
    assert res_ok["ok"] is True, res_ok
    assert res_ok["gates"]["sp_unlocked"] is True
    assert res_ok["gates"]["master_rank"] is True
    assert res_ok["gates"]["final_weapon"] is True
    assert res_ok["gates"]["quality_ok"] is True
    assert res_ok["level"] == AUGMENT_MASTER_LEVEL_MIN

    # 非最终强化武器 → not_final_weapon
    res_nf = augment_eligible(player_ok, {"final": False, "augmentable": True,
                                          "rarity": "epic", "type": "weapon"})
    assert res_nf["ok"] is False and res_nf["reason"] == "not_final_weapon", res_nf

    # 品质不达标（fine 不参与客制 GRD-R04）→ quality_not_augmentable
    res_q = augment_eligible(player_ok, {"final": True, "augmentable": True,
                                         "rarity": "fine", "type": "weapon"})
    assert res_q["ok"] is False and res_q["reason"] == "quality_not_augmentable", res_q

    # 等级不足（未宗师）→ master_rank_insufficient
    res_m = augment_eligible(make_player(forge_level=1, unlocks={AUGMENT_SP_PANEL_ID: 1}),
                             weapon_ok)
    assert res_m["ok"] is False and res_m["reason"] == "master_rank_insufficient", res_m


def t_sets_augments_commands() -> None:
    """c. /套装 /客制：SP-F4/F5 未解锁拒绝；解锁后查询渲染。"""
    # c1 SP 未解锁 → 拒绝文案
    locked = make_player(forge_level=1, sp=0)
    ctx = fresh_ctx({}, locked)
    assert cmd_sets(parsed("/套装"), ctx) == SETS_LOCKED_MSG
    assert cmd_augments(parsed("/客制"), ctx) == AUGMENTS_LOCKED_MSG

    # c2 真实 test_demo 无 sets 数据：/套装 解锁后 → 空态
    player_sets = make_player(forge_level=1, unlocks={"unlock_sets": 1})
    ctx = fresh_ctx({}, player_sets)
    assert cmd_sets(parsed("/套装"), ctx) == SETS_EMPTY

    # c3 合成防具套装：/套装 解锁 + 装配 2 件 → 渲染 ready 行
    forge_raw = _synthetic_armor_forge()
    mods = modules()
    settings_raw = mods["settings"]
    forge_seg = dict(settings_raw.get("forge")) if isinstance(settings_raw.get("forge"), Mapping) else {}  # noqa: E501
    settings = {**settings_raw, "forge": forge_seg}
    player_ready = make_player(forge_level=1, unlocks={"unlock_sets": 1},
                               equipped=["node_helm_1", "node_helm_2"])
    ctx = fresh_ctx({}, player_ready)
    ctx["forge"] = forge_raw
    ctx["forge_tree"] = ForgeTreeEngine(forge=forge_raw, items=mods["items"], settings=settings)
    out_txt = cmd_sets(parsed("/套装"), ctx)
    assert "守卫套装" in out_txt and "件" in out_txt, out_txt
    assert "✅" in out_txt, f"ready 套应标 ✅：{out_txt}"

    # c4 真实 test_demo augments：/客制 解锁 → 渲染 4 项面板
    player_aug = make_player(forge_level=1, unlocks={"unlock_augment": 1})
    ctx = fresh_ctx({}, player_aug)
    out_txt = cmd_augments(parsed("/客制"), ctx)
    assert AUGMENTS_EMPTY not in out_txt, out_txt
    for seg in ("攻击强化", "会心强化", "防御强化", "开孔"):
        assert seg in out_txt, f"/客制 面板缺 {seg}：{out_txt}"
    assert "数值" in out_txt and "孔位" in out_txt, out_txt


def main() -> int:
    out("=" * 60)
    out("M9 批7 套装/客制门禁 verify_m9_b7（依据 m9_batch_plan.md 批8）")
    out("=" * 60)
    check("pack: build_pack 零红拦（真实 test_demo）", t_pack_zero_red)
    check("a1. forge_sets 真实解析+校验（空段合法/W3 黄）", t_sets_parse_validate)
    check("a2. forge_sets 合成防具 fixture（beta 继承/set_lookup ready/技能契约）",
          t_sets_synthetic)
    check("b. forge_augments（解析/校验/次数表/资格判定）", t_augments)
    check("c. /套装 /客制（SP 未解锁拒绝/解锁查询渲染）", t_sets_augments_commands)
    out("=" * 60)
    if _FAILS:
        out(f"❌ M9_B7 FAILED：{len(_FAILS)} 个断言失败")
        for f in _FAILS:
            out(f"  - {f}")
        return 1
    out(f"M9_B7 OK（{len(_OK)} 项全绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
