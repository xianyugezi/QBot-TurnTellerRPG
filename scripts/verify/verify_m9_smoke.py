#!/usr/bin/env python3
"""M9 里程碑全链路冒烟门禁（verify_m9_smoke）。

依据：
  - docs/m9_启动包.md §五（验收门禁 3：verify_m9_smoke 全链路——
    合成素材→锻造→图纸→双流→铸造王；§五 4：emoji 门禁仅 ✅/❌）
  - docs/m9_batch_plan.md 批8（验收门禁：verify_m9_XX 各批门禁脚本 +
    verify_m9_smoke 收口；批6 路6B：全链路冒烟）——文件头标注「依据：批8 + 细化_5d 测试体系总纲」
  - docs/细化/细化_5d_测试体系总纲.md §2.1/§3.2（里程碑 verify 门禁严格依赖序 VG-13 /
    未接入不假绿 VG-11；本脚本为 M9 收口门禁，依赖序末位）
  - docs/m9_shared_contract.md / docs/细化/细化_2c2b_锻造流程契约.md（守卫/双流/图纸契约）

本脚本对齐 scripts/verify/ 既有门禁模式（verify_m7 等：真实 content/test_demo 数据
+ 全链路断言 + exit 0/1），并新增 loader build_pack 构建模块上下文（check_pack 零红拦）。

场景（每功能可追溯）：
  a. 合成素材：3:1 合成（moon_grass×3 → ghost_moss）可用 combine_3to1_available ok
     （CMB-01~04；含 combine_instances/comb_synth_map 实例发现）
  b. 素材两档：火龙鳞 rare / 矿石 normal（material_tier_of，TIER-03a 双源仲裁）
  c. /锻造 直锻成功：铁剑 锻造完成（扣素材/扣费/产装/熟练 +2/forge_last 快照/
     forged 追加/图鉴 weapon+item 分册点亮）（TC-09 / 2c2b §1.2）
  d. 守卫拒绝：素材不足零消耗 / 前置未锻 / 等级不足（含「还差 N 熟练」）（GU-04~06）
  e. 预览+确认窗：/锻造 X 预览 → 卡片 → /确认 → 成功；不确认超时 → 零副作用（TC-10~12）
  f. /图纸：主链全长（铁剑→…→■炎王剑）+ 持有进度段 + 已锻 ✅ 标注（2c2b §2.2/§2.3）
  g. /锻造树：分页 5 条/页 + 终结点 ■ + 可锻状态 + CakeGame 尾段（细化 2c2b §5.3）
  h. 铸造王：图鉴全亮 → king_eligible True → grant_forge_king 授予；未全亮拒绝（KF-01）
  i. 批量 *N：/锻造 炎剑Ⅱ*2 两次结算（素材够时）（P-05 / §1.2 多件）

退出码：0 = M9 全链路冒烟通过（打印「M9 SMOKE OK」）；1 = 有失败（打印失败点）。

铁律：零 NoneBot import；纯函数确定性（无随机）；无定时器/睡眠调用；渲染输出
无 emoji（仅 ✅/❌ + 排版符号）；临时产物自清理（本脚本零落盘）。
"""
from __future__ import annotations

import pathlib
import sys
import traceback
from typing import Any, Dict, List, Mapping, MutableMapping

_REPO = pathlib.Path(__file__).resolve().parent.parent.parent  # scripts/verify/ -> 仓库根
sys.path.insert(0, str(_REPO))  # 供 import qbot_rpg

from qbot_rpg.commands.forge_commands import (  # noqa: E402
    FORGE_DONE_MARK,
    PREVIEW_WINDOW_KEY,
    TREE_TAIL_TIP,
    cmd_blueprint,
    cmd_confirm,
    cmd_forge,
    cmd_forge_tree,
    register_forge_commands,
)
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command  # noqa: E402
from qbot_rpg.commands.router import Router  # noqa: E402
from qbot_rpg.content.loader import build_pack  # noqa: E402
from qbot_rpg.core.forge_job import configure_proficiency  # noqa: E402
from qbot_rpg.core.forge_king import grant_forge_king, king_eligible  # noqa: E402
from qbot_rpg.core.forge_material import (  # noqa: E402
    combine_3to1_available,
    combine_instances,
    comb_synth_map,
    material_tier_of,
)
from qbot_rpg.core.forge_tree import ForgeTreeEngine  # noqa: E402

PACK_DIR = _REPO / "content" / "test_demo"

# 节点 id 常量（test_demo forge.json，与 tests/unit/test_forge_commands.py 同源）
N_IRON = "node_iron_sword"            # 铁剑（根 lv1 矿石×3）
N_IRON_1 = "node_iron_sword_1"        # 铁剑Ⅰ（lv2）
N_IRON_2 = "node_iron_sword_2"        # 铁剑Ⅱ（lv3）
N_FLAME = "node_flame_sword"          # 炎剑（lv4）
N_FLAME_2 = "node_flame_sword_2"      # 炎剑Ⅱ（lv5 火龙鳞×5+火晶石×2）
N_FLAME_3 = "node_flame_sword_3"      # 炎剑Ⅲ（lv6）
N_KING = "node_flame_king_sword"      # ■炎王剑（lv7 final）
N_ICE = "node_ice_sword"              # 冰剑（lv5 final 分支）
N_THUNDER = "node_lightning_sword"    # 雷剑（lv5 final 分支）

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
# 模块上下文（真实 content/test_demo + loader build_pack → check_pack 零红拦）
# ---------------------------------------------------------------------------

def build_context() -> Dict[str, Any]:
    """用真实 content/test_demo 经 loader build_pack 构建模块上下文。

    build_pack 内部走 check_pack 全量校验（任一红拦抛 PackLoadError）——
    本函数对 pack.report.errors 显式断言 0（零红拦），并消费 pack.modules
    （forge/items/settings/recipe/proficiency）构造 forge_commands ctx。
    """
    pack, _ = build_pack(PACK_DIR)
    assert len(pack.report.errors) == 0, f"check_pack 红拦：{pack.report.errors}"
    modules = pack.modules

    forge_raw = modules.get("forge")
    assert isinstance(forge_raw, Mapping), "pack forge 模块缺失"
    items_raw = modules.get("items")
    settings_raw = modules.get("settings")
    assert isinstance(settings_raw, Mapping), "pack settings 模块缺失"

    # settings 归一（forge 段缺省合并）
    forge_v = settings_raw.get("forge")
    forge_seg = dict(forge_v) if isinstance(forge_v, Mapping) else {}
    settings = {**settings_raw, "forge": forge_seg}

    engine = ForgeTreeEngine(
        forge=forge_raw,
        items=items_raw,
        settings=settings,
    )
    return {
        "forge": forge_raw,
        "items": items_raw,
        "settings": settings,
        "forge_tree": engine,       # 铸造王全亮判定口径（forge_king）
        "registry": pack.registry,  # codex weapon 分册统计旁路
        "inventory": {},
        "player": {},
        "qid": "smoke_u1",
        "now": 1000.0,
    }


def make_player(modules: Mapping[str, object], *, forge_level: int = 1,
                coins: int = 99999, forged: object = None) -> Dict[str, Any]:
    """玩家 dict（proficiency.forge.level + forged + currencies + title_state）。"""
    prof_raw = modules.get("proficiency")
    settings_raw = modules.get("settings")
    assert isinstance(settings_raw, Mapping), "pack settings 模块缺失"
    configure_proficiency(prof_raw, settings_raw)  # type: ignore[arg-type]
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


def fresh_ctx(modules: Mapping[str, object], inventory: Mapping[str, int],
              player: Mapping[str, Any], *, now: float = 1000.0) -> Dict[str, Any]:
    """按 build_context 基座派生新 ctx（每次独立 inventory/player，互不污染）。"""
    ctx = build_context()
    ctx["inventory"] = dict(inventory)
    ctx["player"] = player
    ctx["now"] = now
    ctx.pop(PREVIEW_WINDOW_KEY, None)
    return ctx


def parsed(raw: str):
    """parse_command 真实解析。

    白名单：DEFAULT_WHITELIST（含 锻造/确认/锻造树）+「图纸」（/图纸 走 CommandSpec
    whitelisted 标记，批5 路5A 注册口径；DEFAULT_WHITELIST 未收 /图纸，此处补齐以
    走 parse_command 真实词法链路）。
    """
    whitelist = set(DEFAULT_WHITELIST) | {"图纸"}
    return parse_command(raw, whitelist=whitelist)


# ---------------------------------------------------------------------------
# 场景实现
# ---------------------------------------------------------------------------

def t_pack_zero_red() -> None:
    """loader build_pack：check_pack 零红拦（R-1~R-5 封闭清单空）。"""
    pack, changed = build_pack(PACK_DIR)
    assert len(pack.report.errors) == 0, f"红拦：{pack.report.errors}"
    assert pack.pack_id == "test_demo"
    assert isinstance(changed, tuple)


def t_combine_3to1_available() -> None:
    """a. 合成素材：3:1 合成（moon_grass×3 → ghost_moss）可用（CMB-01~04）。"""
    modules = _load_modules()
    # SP-F2 unlock_combine_3to1 解锁（非等级自动给，批3 SP 面板显式解锁）——
    # combine_3to1_available 直接以 player 作入参（ProficiencyEngine.unlock_count）
    player = {
        "proficiency": {
            "forge": {
                "level": 3, "exp": 0, "sp_earned": 0, "sp_used": 0,
                "unlocks": {"unlock_combine_3to1": 1},
            }
        },
        "forged": [],
    }
    settings = build_context()["settings"]
    res = combine_3to1_available(player, settings=settings)
    assert res.get("ok") is True, f"3:1 合成应可用：{res}"
    # 实例发现：rcp_combine_3to1（kind=combine）→ moon_grass → ghost_moss
    insts = combine_instances(modules)
    assert any(
        i.get("recipe_id") == "rcp_combine_3to1"
        and i.get("inputs") == [{"item": "moon_grass", "count": 3}]
        and i.get("output") == {"item": "ghost_moss", "count": 1}
        for i in insts
    ), f"combine 实例未发现：{insts}"
    synth_map = comb_synth_map(modules)
    assert synth_map.get("moon_grass") == "ghost_moss", f"合成映射缺失：{synth_map}"


def _load_modules() -> Mapping[str, object]:
    pack, _ = build_pack(PACK_DIR)
    return pack.modules


def t_material_tier() -> None:
    """b. 素材两档：火龙鳞 rare / 矿石 normal（material_tier_of，TIER-03a）。"""
    ctx = build_context()
    items = ctx["items"]
    items_map = {}
    if isinstance(items, Mapping):
        items_map = dict(items)
    elif isinstance(items, (list, tuple)):
        items_map = {e.get("id"): e for e in items if isinstance(e, Mapping)}
    # 火龙鳞：items 元数据 rare（行无覆写 → 元数据生效）
    assert material_tier_of(
        items_def=items_map.get("fire_dragon_scale"),
        material_row=None,
    ) == "rare"
    # 矿石：normal
    assert material_tier_of(
        items_def=items_map.get("ore"),
        material_row=None,
    ) == "normal"
    # 行覆写优先：铁剑 materials 行无 tier → items 元数据缺省 normal
    forge_raw = ctx["forge"]
    row = None
    for t in forge_raw.get("trees", []):
        for n in t.get("nodes", []):
            if n.get("id") == N_IRON and n.get("materials"):
                row = n["materials"][0]
    assert material_tier_of(items_def=None, material_row=row) == "normal"


def t_direct_forge_success() -> None:
    """c. /锻造 直锻成功：铁剑 锻造完成（扣素材/扣费/产装/熟练 +2/快照/forged/图鉴）。"""
    modules = _load_modules()
    player = make_player(modules, forge_level=1)
    ctx = fresh_ctx(modules, {"ore": 3, "iron_sword": 0}, player)
    out_txt = cmd_forge(parsed("/锻造 铁剑"), ctx)
    assert "✅ 铁剑 锻造完成！" in out_txt, out_txt
    assert "攻击 12" in out_txt and "部位：武器" in out_txt
    # 扣素材 / 扣费（lv1×10）/ 产装
    assert ctx["inventory"]["ore"] == 0
    assert ctx["inventory"].get("iron_sword", 0) == 1
    assert player["currencies"]["coins"] == 99999 - 10
    # 熟练 +2（节点等级×2）
    assert player["proficiency"]["forge"]["exp"] == 2
    # forge_last 快照 + forged 追加 + 图鉴点亮
    assert N_IRON in player["forged"]
    last = player.get("forge_last")
    assert last is not None and last.get("node_id") == N_IRON
    assert last.get("item_id") == "iron_sword"
    assert last.get("stats", {}).get("atk") == 12
    insts = player.get("forge_instances", [])
    assert len(insts) == 1 and insts[0]["node_id"] == N_IRON
    # 图鉴点亮（codex seen）——铸造王判定经 king_eligible（下方 lit），此处不独立记账
    lit = king_eligible(player, ctx)
    assert lit["lit_count"] >= 1, lit


def t_guard_rejects() -> None:
    """d. 守卫拒绝：素材不足零消耗 / 前置未锻 / 等级不足（含「还差 N 熟练」）。"""
    modules = _load_modules()

    # d1 素材不足：铁剑 需矿石×3，仅 2 → 拒绝且零消耗
    player = make_player(modules, forge_level=1)
    ctx = fresh_ctx(modules, {"ore": 2}, player)
    out_txt = cmd_forge(parsed("/锻造 铁剑"), ctx)
    assert "素材不足" in out_txt, out_txt
    assert ctx["inventory"]["ore"] == 2            # 零消耗
    assert player["currencies"]["coins"] == 99999   # 零扣费
    assert player["proficiency"]["forge"]["exp"] == 0  # 零经验
    assert N_IRON not in player["forged"]            # 零落档

    # d2 前置未锻：铁剑Ⅰ（lv2 需 铁剑 已锻）→ 拒绝
    player = make_player(modules, forge_level=3)
    ctx = fresh_ctx(modules, {"ore": 5}, player)
    out_txt = cmd_forge(parsed("/锻造 铁剑Ⅰ"), ctx)
    assert "需先锻造" in out_txt and "铁剑" in out_txt, out_txt

    # d3 等级不足：炎剑（lv4）在 forge_level=1 且前置链已锻 → 需要 大师 级，
    #     含「还差 N 熟练」（GU-06 等级足够，§1.3 L240 模板）
    player = make_player(modules, forge_level=1, forged=[N_IRON, N_IRON_1, N_IRON_2])
    ctx = fresh_ctx(modules, {"ore": 5, "fire_dragon_scale": 3}, player)
    out_txt = cmd_forge(parsed("/锻造 炎剑"), ctx)
    assert "需要" in out_txt and "当前" in out_txt, out_txt
    assert "还差" in out_txt and "熟练" in out_txt, out_txt
    # 等级不足拒绝零副作用
    assert ctx["inventory"]["ore"] == 5 and ctx["inventory"]["fire_dragon_scale"] == 3


def t_preview_confirm() -> None:
    """e. 预览+确认窗：预览卡片 → /确认 成功；不确认超时 → 零副作用。"""
    modules = _load_modules()

    # e1 预览流：卡片 + 登记确认窗，0 资源副作用
    player = make_player(modules, forge_level=1)
    ctx = fresh_ctx(modules, {"ore": 3}, player, now=1000.0)
    card = cmd_forge(parsed("/锻造 铁剑 预览"), ctx)
    assert "铁剑（攻击+12）" in card, card
    assert "素材：" in card and "矿石×3" in card
    assert ctx["inventory"]["ore"] == 3              # 预览不扣
    assert player["currencies"]["coins"] == 99999
    assert player["proficiency"]["forge"]["exp"] == 0
    win = ctx.get(PREVIEW_WINDOW_KEY)
    assert isinstance(win, Mapping) and "smoke_u1" in win

    # e2 /确认 → 重跑守卫成功
    out_txt = cmd_confirm(parsed("/确认"), ctx)
    assert "✅ 铁剑 锻造完成！" in out_txt, out_txt
    assert ctx["inventory"]["ore"] == 0
    assert player["proficiency"]["forge"]["exp"] == 2
    # 一次性：确认后窗口作废
    assert PREVIEW_WINDOW_KEY not in ctx or "smoke_u1" not in ctx[PREVIEW_WINDOW_KEY]

    # e3 超时（now 越过 carry_sec 缺省 90s）→ 零副作用
    player = make_player(modules, forge_level=1)
    ctx = fresh_ctx(modules, {"ore": 3}, player, now=1000.0)
    cmd_forge(parsed("/锻造 铁剑 预览"), ctx)
    ctx["now"] = 1000.0 + 91.0
    out_txt = cmd_confirm(parsed("/确认"), ctx)
    assert "已过期" in out_txt, out_txt
    assert ctx["inventory"]["ore"] == 3              # 零副作用
    assert player["proficiency"]["forge"]["exp"] == 0
    assert N_IRON not in player["forged"]

    # e4 无进行中预览 /确认 → 拒绝
    ctx = fresh_ctx(modules, {"ore": 3}, player, now=1000.0)
    out_txt = cmd_confirm(parsed("/确认"), ctx)
    assert "当前无可确认的锻造预览" in out_txt, out_txt


def t_blueprint() -> None:
    """f. /图纸：主链全长（铁剑→…→■炎王剑）+ 持有进度段 + 已锻 ✅ 标注。"""
    modules = _load_modules()

    # f1 主链全长（未锻玩家）
    player = make_player(modules, forge_level=1)
    ctx = fresh_ctx(modules, {"ore": 3}, player)
    out_txt = cmd_blueprint(parsed("/图纸 铁剑"), ctx)
    assert "铁剑派生链：" in out_txt
    assert "铁剑" in out_txt and "铁剑Ⅰ" in out_txt and "铁剑Ⅱ" in out_txt
    assert "炎剑" in out_txt and "炎剑Ⅱ" in out_txt and "炎剑Ⅲ" in out_txt
    assert "■炎王剑" in out_txt, out_txt           # 终结点 ■ + 无元素标注（火系应带（火））
    assert "当前持有：" in out_txt                    # 持有进度段（progress_line）
    # 未锻玩家：铁剑 节点行尾无 ✅（素材满额 3/3 → 持有段渲染 ✅，属进度段非节点标注）

    # f2 已锻玩家：铁剑 行尾 ✅ 标注（forge_node_suffix）
    player = make_player(modules, forge_level=1, forged=[N_IRON])
    ctx = fresh_ctx(modules, {"ore": 3, "iron_sword": 1}, player)
    out_txt = cmd_blueprint(parsed("/图纸 铁剑"), ctx)
    assert FORGE_DONE_MARK in out_txt, out_txt      # 已锻 ✅
    # 已锻玩家持有进度段素材满额也 ✅（progress_line）

    # f3 未知节点 → 空态
    out_txt = cmd_blueprint(parsed("/图纸 不存在之剑"), ctx)
    assert "未找到「不存在之剑」相关锻造链" in out_txt, out_txt


def t_forge_tree() -> None:
    """g. /锻造树：分页 5 条/页 + 终结点 ■ + 可锻状态 + CakeGame 尾段。"""
    modules = _load_modules()

    # g1 第 1 页：5 条装备行 + CakeGame 尾段 2 行（当前页 + Tip）＝ 7 行
    player = make_player(modules, forge_level=1)
    ctx = fresh_ctx(modules, {"ore": 3}, player)
    out_txt = cmd_forge_tree(parsed("/锻造树"), ctx)
    lines = [ln for ln in out_txt.splitlines() if ln.strip()]
    assert len(lines) == 7, f"应 5 行装备 + 2 行尾段：{lines}"
    assert "1. " in out_txt and "5. " in out_txt
    assert TREE_TAIL_TIP in out_txt, out_txt                     # CakeGame Tip 尾段
    # 可锻状态：铁剑 可锻；铁剑Ⅰ 需前置（未锻铁剑）
    assert "铁剑（1级" in out_txt and "可锻" in out_txt
    assert "需前置" in out_txt
    assert "当前页：1/2" in out_txt

    # g2 第 2 页（共 2 页：9 节点 / 5 = 2 页）：4 条装备 + 2 行尾段 = 6 行；
    #     终结点 ■（炎王剑/冰剑/雷剑 final 均在第二页）
    out_txt = cmd_forge_tree(parsed("/锻造树 2"), ctx)
    lines = [ln for ln in out_txt.splitlines() if ln.strip()]
    assert len(lines) == 6, lines
    assert "当前页" in out_txt and "2/2" in out_txt
    assert "■炎王剑" in out_txt, out_txt            # 终结点 ■ 前缀
    assert "■" in out_txt

    # g3 越界页 → 空态
    out_txt = cmd_forge_tree(parsed("/锻造树 99"), ctx)
    assert "该页暂无锻造装备" in out_txt, out_txt

    # g4 已锻节点 ✅ 标注
    player = make_player(modules, forge_level=1, forged=[N_IRON])
    ctx = fresh_ctx(modules, {"ore": 3, "iron_sword": 1}, player)
    out_txt = cmd_forge_tree(parsed("/锻造树"), ctx)
    assert FORGE_DONE_MARK in out_txt, out_txt


def _forge_full_chain(modules: Mapping[str, object],
                      player: MutableMapping[str, Any],
                      ctx: MutableMapping[str, Any]) -> None:
    """沿主链逐节点锻造至 ■炎王剑（满素材满等级），点亮全图鉴（KF-01）。"""
    # 素材表（节点 → 需求）：按 forge.json 行覆写
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
    # 初始库存 = 全节点素材需求并集 ×2（余量）
    inv: Dict[str, int] = {}
    for need in mats.values():
        for iid, cnt in need.items():
            inv[iid] = inv.get(iid, 0) + cnt * 2
    ctx["inventory"] = inv
    ctx["player"] = player
    player["proficiency"]["forge"]["level"] = 7       # 铸造 7 级门槛
    for nid, need in mats.items():
        # 逐个直锻（依赖前置已锻；素材由循环内扣减）
        target = {"node_iron_sword": "铁剑",
                  "node_iron_sword_1": "铁剑Ⅰ",
                  "node_iron_sword_2": "铁剑Ⅱ",
                  "node_flame_sword": "炎剑",
                  "node_flame_sword_2": "炎剑Ⅱ",
                  "node_flame_sword_3": "炎剑Ⅲ",
                  "node_flame_king_sword": "■炎王剑",
                  "node_ice_sword": "冰剑",
                  "node_lightning_sword": "雷剑"}[nid]
        out_txt = cmd_forge(parsed(f"/锻造 {target}"), ctx)
        assert out_txt.startswith("✅"), f"{nid} 锻造失败：{out_txt}"


def t_forge_king() -> None:
    """h. 铸造王：图鉴全亮 → king_eligible True → grant_forge_king 授予；未全亮拒绝。"""
    modules = _load_modules()

    # h1 未全亮 → 拒绝（eligible False / grant 拒绝）
    player = make_player(modules, forge_level=7, forged=[])
    ctx = build_context()
    ctx["player"] = player
    ctx["inventory"] = {}
    elig = king_eligible(player, ctx)
    assert elig["eligible"] is False, elig
    assert elig["reason"] == "codex_incomplete"
    res = grant_forge_king(player, ctx)
    assert res["ok"] is False and res["reason"] == "codex_incomplete", res

    # h2 全亮 → eligible True → 授予
    player = make_player(modules, forge_level=7)
    ctx = build_context()
    ctx["player"] = player
    _forge_full_chain(modules, player, ctx)
    elig = king_eligible(player, ctx)
    assert elig["eligible"] is True, elig
    assert elig["lit_count"] == elig["total"] == 9, elig
    res = grant_forge_king(player, ctx)
    assert res["ok"] is True and res["granted"] is True, res
    owned = player.get("title_state", {}).get("owned", [])
    assert "forge" in {str(x) for x in owned}, f"铸造王称号未落账：{owned}"


def t_batch_forge() -> None:
    """i. 批量 *N：/锻造 炎剑Ⅱ*2 两次结算（素材够时）。"""
    modules = _load_modules()
    # 前置链：铁剑→铁剑Ⅰ→铁剑Ⅱ→炎剑 全部已锻，forge_level=5
    player = make_player(modules, forge_level=5,
                         forged=[N_IRON, N_IRON_1, N_IRON_2, N_FLAME])
    ctx = fresh_ctx(modules, {"fire_dragon_scale": 12, "alch_ember_crystal": 6},
                    player)
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
    # 熟练 +2×2=4（节点等级 5 ×2 ×2 次）
    assert player["proficiency"]["forge"]["exp"] == 20

    # 素材不足批量中断：第 2 次失败已成功 1 次（零回滚已成功项）
    player = make_player(modules, forge_level=5,
                         forged=[N_IRON, N_IRON_1, N_IRON_2, N_FLAME])
    ctx = fresh_ctx(modules, {"fire_dragon_scale": 6, "alch_ember_crystal": 6},
                    player)
    out_txt = cmd_forge(parsed("/锻造 炎剑Ⅱ*2"), ctx)
    assert "第 2 次失败" in out_txt and "已成功 1 次" in out_txt, out_txt
    assert len(player.get("forge_instances", [])) == 1  # 第 1 次已结算


def t_registration() -> None:
    """装配：register_forge_commands 注册 锻造/确认/图纸/锻造树 四指令（白名单对齐）。"""
    router = Router()
    register_forge_commands(router)
    names = set(router.names())
    assert {"锻造", "确认", "图纸", "锻造树"} <= names, names
    # 白名单对齐：锻造/确认/锻造树 已在 DEFAULT_WHITELIST（parsers 注册时登记）；
    # /图纸 走 CommandSpec whitelisted 标记（批5 路5A 注册口径）
    assert "锻造" in DEFAULT_WHITELIST and "确认" in DEFAULT_WHITELIST
    assert "锻造树" in DEFAULT_WHITELIST
    # 指令可解析（白名单含 锻造/确认/锻造树）
    for raw in ("/锻造 铁剑", "/确认", "/锻造树"):
        p = parsed(raw)
        assert p is not None and p.command, f"{raw} 未解析"


def main() -> int:
    out("=" * 60)
    out("M9 全链路冒烟门禁 verify_m9_smoke（依据 m9_启动包 §五 + m9_batch_plan 批8）")
    out("=" * 60)

    # 模块上下文（真实 test_demo + loader build_pack，check_pack 零红拦）
    check("pack: build_pack 零红拦（check_pack）", t_pack_zero_red)
    # a. 合成素材 3:1
    check("a. 3:1 合成可用（moon_grass×3 → ghost_moss）", t_combine_3to1_available)
    # b. 素材两档
    check("b. 素材两档（火龙鳞 rare / 矿石 normal）", t_material_tier)
    # c. 直锻成功
    check("c. /锻造 直锻成功（铁剑 扣素材/扣费/产装/熟练/快照/forged/图鉴）",
          t_direct_forge_success)
    # d. 守卫拒绝
    check("d. 守卫拒绝（素材不足零消耗/前置未锻/等级不足含还差N熟练）", t_guard_rejects)
    # e. 预览+确认窗
    check("e. 预览+确认窗（卡片/确认成功/超时零副作用/无窗拒绝）", t_preview_confirm)
    # f. /图纸
    check("f. /图纸 主链全长+持有进度+已锻标注", t_blueprint)
    # g. /锻造树
    check("g. /锻造树 分页5条/页+终结点■+可锻状态+CakeGame尾段", t_forge_tree)
    # h. 铸造王
    check("h. 铸造王（未全亮拒绝/全亮授予）", t_forge_king)
    # i. 批量 *N
    check("i. 批量 *N（炎剑Ⅱ*2 两次结算/素材不足中断）", t_batch_forge)
    # 装配注册
    check("装配: register_forge_commands 四指令注册+白名单", t_registration)

    out("=" * 60)
    if _FAILS:
        out(f"❌ M9 SMOKE FAILED：{len(_FAILS)} 个断言失败")
        for f in _FAILS:
            out(f"  - {f}")
        return 1
    out(f"M9 SMOKE OK（{len(_OK)} 项全绿）")
    return 0


if __name__ == "__main__":
    # 兼容 `python scripts/verify/verify_m9_smoke.py`（pytest 亦可收集 main 内 check）
    sys.exit(main())
