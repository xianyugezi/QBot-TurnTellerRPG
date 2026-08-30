#!/usr/bin/env python3
"""M9 锻造·批8·路8A：批4 /锻造 指令门禁（verify_m9_b4）。

依据：
  - docs/m9_batch_plan.md 批8（路8A：verify_m9_b2~b7 各批门禁脚本）+ 批4（/锻造 核心
    指令拆 4 路：4A 原子流程引擎守卫 GU-01~06 / 4B 直锻+预览双流+/确认 窗口 /
    4C 参数解析 P-01~06 / 4D 批量 *N+快照入档+图鉴点亮）
  - qbot_rpg/commands/forge_commands.py（cmd_forge/forge_atomic/parse_forge_target/
    cmd_confirm + PREVIEW_WINDOW_KEY）
  - qbot_rpg/commands/parsers.py（parse_command 真实词法）

本脚本对齐 scripts/verify/verify_m9_smoke.py 门禁模式：真实 ctx（forge 表注入 +
模拟背包/玩家）+ 直锻/守卫/预览/确认/参数解析断言 + exit 0/1。零 NoneBot import、
确定性、无定时器/睡眠调用（确认窗超时用 ctx now 比较）、渲染输出无 emoji
（仅 ✅/❌）、零落盘。

场景（真实 test_demo 数据）：
  a. 直锻成功：铁剑 扣素材/扣费/产装/熟练 +2/forge_instances 快照/图鉴点亮
  b. 守卫拒绝：素材不足零消耗 / 前置未锻 / 等级不足（还差 N 熟练）/ 红名失效
  c. 预览卡片 + /确认 窗口：成功 / 超时零副作用 / 无窗拒绝
  d. 参数解析：禁空格 / 罗马等价（炎剑Ⅱ≡炎剑2）/ *N 批量 / 未知节点
  e. 批量 *N：两次结算 / 素材不足中断

退出码：0 = 批4 指令门禁通过（打印「M9_B4 OK」）；1 = 有失败。
"""
from __future__ import annotations

import pathlib
import sys
import traceback
from typing import Any, Dict, List, Mapping

_REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO))

from qbot_rpg.commands.forge_commands import (  # noqa: E402
    PREVIEW_WINDOW_KEY,
    cmd_confirm,
    cmd_forge,
    forge_atomic,
    parse_forge_target,
)
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command  # noqa: E402
from qbot_rpg.content.loader import build_pack  # noqa: E402
from qbot_rpg.core.forge_job import configure_proficiency  # noqa: E402
from qbot_rpg.core.forge_king import king_eligible  # noqa: E402
from qbot_rpg.core.forge_tree import ForgeTreeEngine  # noqa: E402

PACK_DIR = _REPO / "content" / "test_demo"

N_IRON = "node_iron_sword"
N_IRON_1 = "node_iron_sword_1"
N_IRON_2 = "node_iron_sword_2"
N_FLAME = "node_flame_sword"
N_FLAME_2 = "node_flame_sword_2"

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


def build_base() -> Dict[str, Any]:
    """基座 ctx：真实 forge/items/settings + ForgeTreeEngine + registry + 空背包/玩家。"""
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
        "qid": "b4_u1",
        "now": 1000.0,
    }


def make_player(*, forge_level: int = 1, coins: int = 99999,
                forged: object = None) -> Dict[str, Any]:
    """玩家 dict（proficiency.forge.level + forged + currencies + title_state）。"""
    mods = modules()
    prof_raw = mods["proficiency"]
    settings_raw = mods["settings"]
    configure_proficiency(prof_raw, settings_raw)
    prof = {
        "forge": {
            "level": forge_level, "exp": 0, "sp_earned": 0, "sp_used": 0,
            "unlocks": {},
        }
    }
    forged_list = list(forged) if isinstance(forged, (list, tuple, set, frozenset)) else []
    return {
        "proficiency": prof,
        "forged": forged_list,
        "currencies": {"coins": coins},
        "title_state": {"owned": []},
    }


def fresh_ctx(inventory: Mapping[str, int], player: Mapping[str, Any],
              *, now: float = 1000.0) -> Dict[str, Any]:
    """按 build_base 基座派生新 ctx（每次独立 inventory/player，互不污染）。"""
    ctx = build_base()
    ctx["inventory"] = dict(inventory)
    ctx["player"] = player
    ctx["now"] = now
    ctx.pop(PREVIEW_WINDOW_KEY, None)
    return ctx


def parsed(raw: str):
    whitelist = set(DEFAULT_WHITELIST) | {"图纸"}
    return parse_command(raw, whitelist=whitelist)


# ---------------------------------------------------------------------------
# 场景实现
# ---------------------------------------------------------------------------

def t_pack_zero_red() -> None:
    """loader build_pack：真实 test_demo check_pack 零红拦。"""
    pack, _ = build_pack(PACK_DIR)
    assert len(pack.report.errors) == 0, f"红拦：{pack.report.errors}"


def t_direct_forge_success() -> None:
    """a. 直锻成功：铁剑 扣素材/扣费/产装/熟练 +2/快照/forged/图鉴（TC-09 / 2c2b §1.2）。"""
    mods = modules()  # noqa: F841 (build_pack 副作用校验)
    player = make_player(forge_level=1)
    ctx = fresh_ctx({"ore": 3, "iron_sword": 0}, player)
    out_txt = cmd_forge(parsed("/锻造 铁剑"), ctx)
    assert "✅ 铁剑 锻造完成！" in out_txt, out_txt
    assert "攻击 12" in out_txt and "部位：武器" in out_txt
    # 扣素材 / 扣费（lv1×10）/ 产装
    assert ctx["inventory"]["ore"] == 0
    assert ctx["inventory"].get("iron_sword", 0) == 1
    assert player["currencies"]["coins"] == 99999 - 10
    # 熟练 +2（节点等级×2）
    assert player["proficiency"]["forge"]["exp"] == 2
    # forge_last 快照 + forged 追加
    assert N_IRON in player["forged"]
    last = player.get("forge_last")
    assert last is not None and last.get("node_id") == N_IRON
    assert last.get("item_id") == "iron_sword"
    assert last.get("stats", {}).get("atk") == 12
    # forge_instances 快照入档（批4 路4D）
    insts = player.get("forge_instances", [])
    assert len(insts) == 1 and insts[0]["node_id"] == N_IRON
    assert insts[0]["item_id"] == "iron_sword"
    # 图鉴点亮（king_eligible 口径：lit_count ≥1）
    lit = king_eligible(player, ctx)
    assert lit["lit_count"] >= 1, lit


def t_guard_rejects() -> None:
    """b. 守卫拒绝：素材不足零消耗 / 前置未锻 / 等级不足（还差 N 熟练）/ 红名失效。"""
    mods = modules()

    # b1 素材不足：铁剑 需矿石×3，仅 2 → 拒绝且零消耗
    player = make_player(forge_level=1)
    ctx = fresh_ctx({"ore": 2}, player)
    out_txt = cmd_forge(parsed("/锻造 铁剑"), ctx)
    assert "素材不足" in out_txt, out_txt
    assert ctx["inventory"]["ore"] == 2            # 零消耗
    assert player["currencies"]["coins"] == 99999   # 零扣费
    assert player["proficiency"]["forge"]["exp"] == 0  # 零经验
    assert N_IRON not in player["forged"]            # 零落档

    # b2 前置未锻：铁剑Ⅰ（lv2 需 铁剑 已锻）→ 拒绝
    player = make_player(forge_level=3)
    ctx = fresh_ctx({"ore": 5}, player)
    out_txt = cmd_forge(parsed("/锻造 铁剑Ⅰ"), ctx)
    assert "需先锻造" in out_txt and "铁剑" in out_txt, out_txt

    # b3 等级不足：炎剑（lv4）在 forge_level=1 且前置链已锻 → 需要 大师 级，含「还差 N 熟练」
    player = make_player(forge_level=1, forged=[N_IRON, N_IRON_1, N_IRON_2])
    ctx = fresh_ctx({"ore": 5, "fire_dragon_scale": 3}, player)
    out_txt = cmd_forge(parsed("/锻造 炎剑"), ctx)
    assert "需要" in out_txt and "当前" in out_txt, out_txt
    assert "还差" in out_txt and "熟练" in out_txt, out_txt
    # 等级不足拒绝零副作用
    assert ctx["inventory"]["ore"] == 5 and ctx["inventory"]["fire_dragon_scale"] == 3

    # b4 红名失效节点：级联删除标记 → 「已失效：物品已删除」（2c2a §五 V15）
    forge_raw = dict(mods["forge"])
    forge_raw = dict(forge_raw)
    trees = [dict(t) for t in forge_raw.get("trees", [])]
    for t in trees:
        if isinstance(t, Mapping):
            nodes = [dict(n) for n in t.get("nodes", [])]
            for n in nodes:
                if n.get("id") == N_IRON:
                    n["redflagged"] = True
            t["nodes"] = nodes
    forge_raw["trees"] = trees
    settings_raw = mods["settings"]
    forge_seg = dict(settings_raw.get("forge")) if isinstance(settings_raw.get("forge"), Mapping) else {}  # noqa: E501
    settings = {**settings_raw, "forge": forge_seg}
    red_eng = ForgeTreeEngine(forge=forge_raw, items=mods["items"], settings=settings)
    player = make_player(forge_level=1)
    ctx = fresh_ctx({"ore": 3}, player)
    ctx["forge"] = forge_raw
    ctx["forge_tree"] = red_eng
    out_txt = cmd_forge(parsed("/锻造 铁剑"), ctx)
    assert "已失效" in out_txt, out_txt
    assert ctx["inventory"]["ore"] == 3            # 零消耗
    assert N_IRON not in player["forged"]


def t_preview_confirm() -> None:
    """c. 预览卡片 + /确认 窗口：成功 / 超时零副作用 / 无窗拒绝（TC-10~14）。"""
    mods = modules()  # noqa: F841 (build_pack 副作用校验)

    # c1 预览流：卡片 + 登记确认窗，0 资源副作用
    player = make_player(forge_level=1)
    ctx = fresh_ctx({"ore": 3}, player, now=1000.0)
    card = cmd_forge(parsed("/锻造 铁剑 预览"), ctx)
    assert "铁剑（攻击+12）" in card, card
    assert "素材：" in card and "矿石×3" in card
    assert ctx["inventory"]["ore"] == 3              # 预览不扣
    assert player["currencies"]["coins"] == 99999
    assert player["proficiency"]["forge"]["exp"] == 0
    win = ctx.get(PREVIEW_WINDOW_KEY)
    assert isinstance(win, Mapping) and "b4_u1" in win

    # c2 /确认 → 重跑守卫成功
    out_txt = cmd_confirm(parsed("/确认"), ctx)
    assert "✅ 铁剑 锻造完成！" in out_txt, out_txt
    assert ctx["inventory"]["ore"] == 0
    assert player["proficiency"]["forge"]["exp"] == 2
    # 一次性：确认后窗口作废
    assert PREVIEW_WINDOW_KEY not in ctx or "b4_u1" not in ctx[PREVIEW_WINDOW_KEY]

    # c3 超时（now 越过 carry_sec 缺省 90s）→ 零副作用
    player = make_player(forge_level=1)
    ctx = fresh_ctx({"ore": 3}, player, now=1000.0)
    cmd_forge(parsed("/锻造 铁剑 预览"), ctx)
    ctx["now"] = 1000.0 + 91.0
    out_txt = cmd_confirm(parsed("/确认"), ctx)
    assert "已过期" in out_txt, out_txt
    assert ctx["inventory"]["ore"] == 3              # 零副作用
    assert player["proficiency"]["forge"]["exp"] == 0
    assert N_IRON not in player["forged"]

    # c4 无进行中预览 /确认 → 拒绝
    ctx = fresh_ctx({"ore": 3}, player, now=1000.0)
    out_txt = cmd_confirm(parsed("/确认"), ctx)
    assert "当前无可确认的锻造预览" in out_txt, out_txt


def t_param_lexing() -> None:
    """d. 参数解析：禁空格 / 罗马等价（炎剑Ⅱ≡炎剑2）/ *N 批量 / 未知节点。"""
    mods = modules()
    settings_raw = mods["settings"]
    forge_seg = dict(settings_raw.get("forge")) if isinstance(settings_raw.get("forge"), Mapping) else {}  # noqa: E501
    settings = {**settings_raw, "forge": forge_seg}
    eng = ForgeTreeEngine(forge=mods["forge"], items=mods["items"], settings=settings)

    # d1 禁空格（P-01）：节点名含空格 → 参数错误
    res_space = parse_forge_target("铁剑 Ⅰ", eng=eng)
    assert res_space["ok"] is False and res_space["error_code"] == "P_SPACE", res_space

    # d2 罗马等价（P-03 / F-11）：炎剑Ⅱ ≡ 炎剑2
    res_rom = parse_forge_target("炎剑2", eng=eng)
    assert res_rom["ok"] is True, res_rom
    assert res_rom["key"] in (N_FLAME_2, "炎剑Ⅱ", "炎剑2"), res_rom   # 罗马归一后命中
    res_rom2 = parse_forge_target("炎剑Ⅱ", eng=eng)
    assert res_rom2["ok"] is True, res_rom2

    # d3 未知节点（GU-03 not_found）
    res_unk = parse_forge_target("不存在之剑", eng=eng)
    assert res_unk["ok"] is False and res_unk["error_code"] == "P_UNKNOWN", res_unk

    # d4 词法通过（无引擎纯词法：P_EMPTY / P_QTY）
    assert parse_forge_target("", eng=None)["error_code"] == "P_EMPTY"
    assert parse_forge_target("铁剑*0", eng=None)["error_code"] == "P_QTY"
    assert parse_forge_target("铁剑*3", eng=None)["qty"] == 3
    assert parse_forge_target("铁剑", eng=None)["ok"] is True

    # d5 指令层禁空格：cmd_forge 直接拒绝
    player = make_player(forge_level=1)
    ctx = fresh_ctx({"ore": 3}, player)
    out_txt = cmd_forge(parsed("/锻造 铁剑 Ⅰ"), ctx)
    assert "参数错误：节点名不含空格" in out_txt, out_txt


def t_batch_forge() -> None:
    """e. 批量 *N：炎剑Ⅱ*2 两次结算 / 素材不足中断（P-05 / §1.2 多件）。"""
    mods = modules()  # noqa: F841 (build_pack 副作用校验)
    # 前置链：铁剑→铁剑Ⅰ→铁剑Ⅱ→炎剑 全部已锻，forge_level=5
    player = make_player(forge_level=5, forged=[N_IRON, N_IRON_1, N_IRON_2, N_FLAME])
    ctx = fresh_ctx({"fire_dragon_scale": 12, "alch_ember_crystal": 6}, player)
    out_txt = cmd_forge(parsed("/锻造 炎剑Ⅱ*2"), ctx)
    # 批量成功汇总：✅ 炎剑Ⅱ 锻造完成！ ×2
    assert "✅ 炎剑Ⅱ 锻造完成！" in out_txt, out_txt
    assert "×2" in out_txt, out_txt
    # 两次结算：火龙鳞 12-10=2；火晶石 6-4=2
    assert ctx["inventory"]["fire_dragon_scale"] == 2
    assert ctx["inventory"]["alch_ember_crystal"] == 2
    # 两件实例入档
    assert len(player.get("forge_instances", [])) == 2
    assert N_FLAME_2 in player["forged"]
    # 熟练 +2×2×5 = 20（节点等级 5 ×2 ×2 次）
    assert player["proficiency"]["forge"]["exp"] == 20

    # 素材不足批量中断：第 2 次失败已成功 1 次（零回滚已成功项）
    player = make_player(forge_level=5, forged=[N_IRON, N_IRON_1, N_IRON_2, N_FLAME])
    ctx = fresh_ctx({"fire_dragon_scale": 6, "alch_ember_crystal": 6}, player)
    out_txt = cmd_forge(parsed("/锻造 炎剑Ⅱ*2"), ctx)
    assert "第 2 次失败" in out_txt and "已成功 1 次" in out_txt, out_txt
    assert len(player.get("forge_instances", [])) == 1  # 第 1 次已结算

    # forge_atomic 直接调用（路4A 公开入口）单件成功
    player = make_player(forge_level=5, forged=[N_IRON, N_IRON_1, N_IRON_2, N_FLAME])
    ctx = fresh_ctx({"fire_dragon_scale": 5, "alch_ember_crystal": 2}, player)
    out_txt = forge_atomic(ctx, "炎剑Ⅱ", qty=1)
    assert "✅ 炎剑Ⅱ 锻造完成！" in out_txt, out_txt


def main() -> int:
    out("=" * 60)
    out("M9 批4 /锻造 指令门禁 verify_m9_b4（依据 m9_batch_plan.md 批8）")
    out("=" * 60)
    check("pack: build_pack 零红拦（真实 test_demo）", t_pack_zero_red)
    check("a. 直锻成功（扣素材/扣费/产装/熟练/快照/forged/图鉴）", t_direct_forge_success)
    check("b. 守卫拒绝（素材不足零消耗/前置未锻/等级不足/红名失效）", t_guard_rejects)
    check("c. 预览卡片+/确认 窗口（成功/超时零副作用/无窗拒绝）", t_preview_confirm)
    check("d. 参数解析（禁空格/罗马等价/未知节点/词法分类）", t_param_lexing)
    check("e. 批量 *N（两次结算/素材不足中断/forge_atomic）", t_batch_forge)
    out("=" * 60)
    if _FAILS:
        out(f"❌ M9_B4 FAILED：{len(_FAILS)} 个断言失败")
        for f in _FAILS:
            out(f"  - {f}")
        return 1
    out(f"M9_B4 OK（{len(_OK)} 项全绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
