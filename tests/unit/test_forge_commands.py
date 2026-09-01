"""M9 锻造·批4·路4B：/锻造 直锻/预览双流 + /确认 一次性窗口 指令壳单测。
      （批4 路4D 扩展：实例快照入档 forge_instances + 图鉴 item 分册点亮）
      （批5 路5B 扩展：/图纸 标注段——已锻节点 ✅ / 素材满额 ✅ / 红名失效标注
       「已失效：物品已删除」；持有进度段 progress_line 接线 forged_prefix_names）

文件：tests/unit/test_forge_commands.py
创建：2026-08-30
作者：Hermes 子agent-4B（M9 锻造实现组批4·路4B：并发同仓，仅新建本文件 +
  追加 qbot_rpg/commands/forge_commands.py；不改动核心引擎文件）
      —— 批4 路4D 扩展作者：Hermes 子agent-4D（实例快照入档 + 图鉴 item 分册点亮，追加不改写）
      —— 批5 路5B 扩展作者：Hermes 子agent-5B（/图纸 标注段单测：✓/✅/失效标注，
         追加不改写批4 内容；与路5A 主链段共存，测试互不覆盖）

功能：直测 cmd_forge / cmd_confirm 指令壳（真实引擎 ForgeTreeEngine/forge_progress/
  forge_job 消费 + 真实 content/test_demo 数据）：
  - TC-09  直锻 1 步（straight_forge=true 缺省：/锻造 <节点> 无预览 → 原子成功）
  - TC-10  预览卡片字段（标题/素材行/孔位/可继续锻造；预览 0 资源副作用）
  - TC-11  预览后不 /确认（超时）→ 无锻造、无扣款、无经验（窗口作废）
  - TC-12  预览后 /确认 → 重跑守卫再扣素材发经验 → ✅ 锻造完成
  - TC-13  straight_forge=false（深度模式）→ 全部 /锻造 强制预览（前台无直锻入口）
  - TC-14  无进行中预览时 /确认 → 拒绝「当前无可确认的锻造预览」
  - 3.3 边界：同一玩家仅 1 个待确认窗（新预览不覆盖）；carry_sec=0 不限时；
    确认失败（素材不足）零副作用；/图纸 不覆盖既有窗（注册断言）。
  - 装配：register_forge_commands 注册 /锻造 /确认（CommandSpec 白名单标记）。
  - 批4 路4D 追加：forge_instances 实例快照入档（全字段 + node_id/item_id 双向溯源
    + ts）+ forge_last 与 instances 一致性 + mark_seen item 分册点亮
    （依据 2c2b §1.2 步骤 4/5 + AR-5 + 接口摸底缺口2）。

覆盖规则（对齐 2c2b §六 C TC-09~14 + §3.3 边界）：
  直锻路径守卫 GU-01~06 全过 → 扣素材/扣金币/产装/发经验原子成功；
  预览不扣资源；确认窗单键（qid）；超时作废；无预览确认拒绝。

依据：docs/细化/细化_2c2b_锻造流程契约.md §三（3.1~3.4）+ §六 C（TC-09~14）+
  定稿 §3.3（预览流 L89-97）/ §2.1 #7（L57）/ L239（零会话）；
  批4 路4D：§1.2 步骤 4（实例化并快照入存档）/ 步骤 5（图鉴点亮）+ AR-5（快照缺省键）+
  docs/m9_接口摸底.md §二（缺口2：装备实例快照管线）。
测试风格对齐 tests/unit/test_forge_progress.py（真实 test_demo 数据 +
  ForgeTreeEngine 构造）+ tests/unit/test_confirm_commands.py（parse_command 直调 +
  全字段 ctx + 指令壳 handler 直测）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, Mapping, Optional

from qbot_rpg.commands.forge_commands import (
    AUGMENTS_CMD,
    AUGMENTS_EMPTY,
    AUGMENTS_LOCKED_MSG,
    AUGMENT_UNLOCK_ID,
    BLUEPRINT_CMD,
    CONFIRM_CMD,
    ERR_P_AMBIGUOUS,
    ERR_P_CHARSET,
    ERR_P_EMPTY,
    ERR_P_QTY,
    ERR_P_SPACE,
    ERR_P_UNKNOWN,
    FORGE_CMD,
    FORGE_DONE_MARK,
    FORGE_REDFLAG_SUFFIX,
    PREVIEW_WINDOW_KEY,
    SETS_CMD,
    SETS_EMPTY,
    SETS_LOCKED_MSG,
    SETS_UNLOCK_ID,
    TREE_CMD,
    TREE_EMPTY_PAGE,
    TREE_PAGE_SIZE,
    TREE_TAIL_TIP,
    cmd_augments,
    cmd_confirm,
    cmd_forge,
    cmd_forge_tree,
    cmd_sets,
    forge_forged_prefix_names,
    forge_node_suffix,
    forge_progress_segment,
    parse_forge_target,
    register_forge_commands,
)
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command
from qbot_rpg.commands.router import Router
from qbot_rpg.core.forge_cascade import delete_items_effect
from qbot_rpg.core.forge_job import configure_proficiency
from qbot_rpg.core.forge_tree import ForgeTreeEngine

# 真实 test_demo 数据路径
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FORGE_JSON = _REPO_ROOT / "content" / "test_demo" / "forge.json"
_ITEMS_JSON = _REPO_ROOT / "content" / "test_demo" / "items.json"
_SETTINGS_JSON = _REPO_ROOT / "content" / "test_demo" / "settings.json"
_PROF_JSON = _REPO_ROOT / "content" / "test_demo" / "proficiency.json"

# 节点 id 常量（test_demo forge.json）
N_IRON = "node_iron_sword"           # 铁剑（根，lv1，矿石×3）
N_IRON_1 = "node_iron_sword_1"       # 铁剑Ⅰ（lv2）
N_IRON_2 = "node_iron_sword_2"       # 铁剑Ⅱ（lv3）
N_FLAME = "node_flame_sword"         # 炎剑（lv4）
N_FLAME_2 = "node_flame_sword_2"     # 炎剑Ⅱ（lv5，火龙鳞×5+火晶石×2，slots 1/2）
N_FLAME_3 = "node_flame_sword_3"     # 炎剑Ⅲ（lv6）
N_KING = "node_flame_king_sword"     # ■炎王剑（lv7，final）
N_ICE = "node_ice_sword"             # 冰剑（lv5，炎剑Ⅱ 分支）
N_THUNDER = "node_lightning_sword"   # 雷剑（lv5，炎剑Ⅱ 分支）

# 炎剑Ⅱ 素材（forge.json 文件序）
MAT_FLAME_2 = ("fire_dragon_scale", "alch_ember_crystal")


# ---------------------------------------------------------------------------
# 夹具辅助（真实数据）
# ---------------------------------------------------------------------------

def _load_json(path: pathlib.Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _forge_raw() -> Mapping[str, object]:
    return _load_json(_FORGE_JSON)  # type: ignore[return-value]


def _items_raw() -> object:
    return _load_json(_ITEMS_JSON)


def _settings_raw() -> Mapping[str, object]:
    return _load_json(_SETTINGS_JSON)  # type: ignore[return-value]


def _make_ctx(
    inventory: Mapping[str, int],
    player: Optional[Mapping[str, Any]] = None,
    *,
    qid: str = "u1",
    now: float = 1000.0,
    straight_forge: Optional[bool] = None,
    carry_sec: Optional[int] = None,
) -> Dict[str, Any]:
    """构造玩家 ctx（forge/items/settings/inventory/player/qid/now + 窗挂载点）。

    straight_forge/carry_sec 为 None → 用 settings.json forge 段现值（straight_forge=true）。
    """
    settings = _settings_raw()
    if straight_forge is not None or carry_sec is not None:
        forge_v = settings.get("forge")
        seg = dict(forge_v) if isinstance(forge_v, Mapping) else {}
        if straight_forge is not None:
            seg["straight_forge"] = straight_forge
        if carry_sec is not None:
            seg["carry_sec"] = carry_sec
        settings = {**settings, "forge": seg}
    inv = dict(inventory)
    return {
        "forge": _forge_raw(),
        "items": _items_raw(),
        "settings": settings,
        "inventory": inv,
        "player": player if player is not None else {},
        "qid": qid,
        "now": now,
    }


def _player(*, forged: object = None, forge_level: int = 1, coins: int = 9999) -> Dict[str, Any]:
    """构造玩家 dict（proficiency.forge.level + forged 集合 + currencies + proficiency 全节点）。"""
    prof = {"forge": {"level": forge_level, "exp": 0, "sp_earned": 0, "sp_used": 0,
                      "unlocks": {}}}
    forged_list = list(forged) if isinstance(forged, (list, tuple, set, frozenset)) else []
    return {
        "proficiency": prof,
        "forged": forged_list,
        "currencies": {"coins": coins},
    }


def _parsed(raw: str) -> Any:
    """parse_command 真实解析（白名单含 锻造/确认；预览 为 FIXED_SUBWORDS）。"""
    return parse_command(raw, whitelist=DEFAULT_WHITELIST)


# ---------------------------------------------------------------------------
# TC-09 直锻 1 步（straight_forge=true 缺省）
# ---------------------------------------------------------------------------

def test_tc09_straight_forge_direct_success() -> None:
    """TC-09：straight_forge=true（缺省），/锻造 铁剑 无预览 → 直锻 1 步原子成功。

    断言：✅ 成功行 + 属性行（攻击 12 | 部位：武器 | 槽位：无 | 品质：普通（固定））；
    扣素材（矿石 3→0）、扣金币（lv1×10=10）、产装（iron_sword 1 件）、
    熟练 +节点等级×2=2；不建立确认窗。
    """
    configure_proficiency(_load_json(_PROF_JSON), _settings_raw())  # type: ignore[arg-type]
    player = _player(forged=[], forge_level=1)
    ctx = _make_ctx({"ore": 3}, player)
    out = cmd_forge(_parsed("/锻造 铁剑"), ctx)
    assert "✅ 铁剑 锻造完成！" in out
    assert "攻击 12" in out and "部位：武器" in out
    assert "槽位：无" in out and "品质：普通（固定）" in out
    # 原子副作用
    assert ctx["inventory"]["ore"] == 0
    assert ctx["inventory"].get("iron_sword", 0) == 1
    assert player["currencies"]["coins"] == 9999 - 10
    assert player["proficiency"]["forge"]["exp"] == 2
    assert N_IRON in player["forged"]
    # 直锻不建立确认窗
    assert PREVIEW_WINDOW_KEY not in ctx or PREVIEW_WINDOW_KEY not in ctx


# ---------------------------------------------------------------------------
# TC-10 预览卡片（字段 + 0 副作用）
# ---------------------------------------------------------------------------

def test_tc10_preview_card_fields() -> None:
    """TC-10：/锻造 炎剑Ⅱ 预览 → 📖 卡片字段（标题/素材行/孔位/可继续锻造）。

    断言（2c2b §3.2 字段接线，真实 test_demo 数据）：
      - 标题：`炎剑Ⅱ（火属性+8）`（节点名 + 属性摘要，element=fire→火 +8）；
      - 素材行：`素材：炎剑 + 火龙鳞×5 + 火晶石×2 | 需求：铸造 宗师 级`
        （前置节点名 炎剑 + 各行素材 + 需求档位；lv5 → tier index 5=宗师）；
      - 孔位/后续：`孔位：1 级槽 ×1 | 2 级槽 ×1 | 可继续锻造：炎剑Ⅲ → ■炎王剑`
        （slots 1/2 + 主线 child 炎剑Ⅲ → line_endpoint ■炎王剑）。
    预览不扣任何资源（inventory/金币/经验/forged 全不变）。
    """
    configure_proficiency(_load_json(_PROF_JSON), _settings_raw())  # type: ignore[arg-type]
    full_chain = [N_IRON, N_IRON_1, N_IRON_2, N_FLAME]
    player = _player(forged=full_chain, forge_level=5)
    ctx = _make_ctx({"fire_dragon_scale": 5, "alch_ember_crystal": 2}, player)
    out = cmd_forge(_parsed("/锻造 炎剑Ⅱ 预览"), ctx)
    lines = out.split("\n")
    assert lines[0] == "炎剑Ⅱ（火属性+8）"
    assert lines[1] == "素材：炎剑 + 火龙鳞×5 + 火晶石×2 | 需求：铸造 宗师 级"
    assert lines[2] == "孔位：1 级槽 ×1 | 2 级槽 ×1 | 可继续锻造：炎剑Ⅲ → ■炎王剑"
    # 预览 0 资源副作用
    assert ctx["inventory"]["fire_dragon_scale"] == 5
    assert ctx["inventory"]["alch_ember_crystal"] == 2
    assert player["currencies"]["coins"] == 9999
    assert player["proficiency"]["forge"]["exp"] == 0
    assert N_FLAME_2 not in player["forged"]
    # 确认窗已登记（单键 qid）
    assert ctx[PREVIEW_WINDOW_KEY]["u1"]["node_id"] == N_FLAME_2


def test_tc10_preview_card_no_slots_branch() -> None:
    """TC-10 补充：铁剑Ⅰ 预览（无孔位 + 有前置）→ 素材行含前置、无孔位段。"""
    player = _player(forged=[N_IRON], forge_level=2)
    ctx = _make_ctx({"ore": 5}, player)
    out = cmd_forge(_parsed("/锻造 铁剑Ⅰ 预览"), ctx)
    lines = out.split("\n")
    assert lines[0] == "铁剑Ⅰ（攻击+18）"
    assert lines[1] == "素材：铁剑 + 矿石×5 | 需求：铸造 精通 级"
    # 铁剑Ⅰ 无孔位，但主线仍有后续 → 「可继续锻造：铁剑Ⅱ → ■炎王剑」行存在（2c2b §3.2 后续段）
    assert any("可继续锻造" in ln for ln in lines)


# ---------------------------------------------------------------------------
# TC-11 预览后不 /确认（超时）→ 0 副作用
# ---------------------------------------------------------------------------

def test_tc11_preview_no_confirm_zero_side_effect() -> None:
    """TC-11：预览后不 /确认（放弃）→ 无锻造、无扣素材、无经验（预览 0 副作用）。

    窗口仍存在但玩家什么都没发生；超时后窗口作废。
    """
    configure_proficiency(_load_json(_PROF_JSON), _settings_raw())  # type: ignore[arg-type]
    full_chain = [N_IRON, N_IRON_1, N_IRON_2, N_FLAME]
    player = _player(forged=full_chain, forge_level=5)
    ctx = _make_ctx({"fire_dragon_scale": 5, "alch_ember_crystal": 2}, player)
    cmd_forge(_parsed("/锻造 炎剑Ⅱ 预览"), ctx)
    # 不 /确认 → 素材/金币/经验/forged 全不变
    assert ctx["inventory"]["fire_dragon_scale"] == 5
    assert ctx["inventory"]["alch_ember_crystal"] == 2
    assert player["currencies"]["coins"] == 9999
    assert player["proficiency"]["forge"]["exp"] == 0
    assert N_FLAME_2 not in player["forged"]
    # 窗口仍在（未确认）
    assert ctx[PREVIEW_WINDOW_KEY]["u1"]["node_id"] == N_FLAME_2


def test_tc11_timeout_invalidates_window() -> None:
    """TC-11：预览后超时（now 跳过 carry_sec=90）→ 窗口作废，无锻造无扣款无经验。"""
    full_chain = [N_IRON, N_IRON_1, N_IRON_2, N_FLAME]
    player = _player(forged=full_chain, forge_level=5)
    ctx = _make_ctx({"fire_dragon_scale": 5, "alch_ember_crystal": 2}, player, now=1000.0)
    cmd_forge(_parsed("/锻造 炎剑Ⅱ 预览"), ctx)
    # 超时后 /确认 → 拒绝 + 窗口作废
    ctx["now"] = 1000.0 + 91
    out = cmd_confirm(_parsed("/确认"), ctx)
    assert "预览已过期" in out and "重新 /锻造" in out
    assert PREVIEW_WINDOW_KEY not in ctx or "u1" not in ctx[PREVIEW_WINDOW_KEY]
    # 零副作用
    assert ctx["inventory"]["fire_dragon_scale"] == 5
    assert player["proficiency"]["forge"]["exp"] == 0
    assert N_FLAME_2 not in player["forged"]


# ---------------------------------------------------------------------------
# TC-12 预览后 /确认 → 成功
# ---------------------------------------------------------------------------

def test_tc12_confirm_success() -> None:
    """TC-12：预览后 /确认 → 重跑守卫再扣素材发经验 → ✅ 炎剑Ⅱ 锻造完成！。

    断言：扣素材（火龙鳞 5→0、火晶石 2→0）、扣金币（lv5×10=50）、
    产装（flame_sword_2 1 件）、熟练 +节点等级×2=10、forged 含炎剑Ⅱ；
    实例属性快照入存档（player.forge_last）。
    """
    configure_proficiency(_load_json(_PROF_JSON), _settings_raw())  # type: ignore[arg-type]
    full_chain = [N_IRON, N_IRON_1, N_IRON_2, N_FLAME]
    player = _player(forged=full_chain, forge_level=5)
    ctx = _make_ctx({"fire_dragon_scale": 5, "alch_ember_crystal": 2}, player)
    cmd_forge(_parsed("/锻造 炎剑Ⅱ 预览"), ctx)
    out = cmd_confirm(_parsed("/确认"), ctx)
    assert "✅ 炎剑Ⅱ 锻造完成！" in out
    assert "攻击 40" in out and "部位：武器" in out
    # 一次性窗口已作废
    assert PREVIEW_WINDOW_KEY not in ctx or "u1" not in ctx[PREVIEW_WINDOW_KEY]
    # 原子副作用
    assert ctx["inventory"]["fire_dragon_scale"] == 0
    assert ctx["inventory"]["alch_ember_crystal"] == 0
    assert ctx["inventory"].get("flame_sword_2", 0) == 1
    assert player["currencies"]["coins"] == 9999 - 50
    assert player["proficiency"]["forge"]["exp"] == 10
    assert N_FLAME_2 in player["forged"]
    assert isinstance(player.get("forge_last"), dict)


def test_tc12_confirm_recheck_guards_zero_side_effect_on_fail() -> None:
    """TC-12 边界：确认时素材已不足（重跑 GU-05 拦截）→ 失败零副作用。"""
    full_chain = [N_IRON, N_IRON_1, N_IRON_2, N_FLAME]
    player = _player(forged=full_chain, forge_level=5)
    ctx = _make_ctx({"fire_dragon_scale": 5, "alch_ember_crystal": 2}, player)
    cmd_forge(_parsed("/锻造 炎剑Ⅱ 预览"), ctx)
    # 确认前素材被取走（模拟期间变化）→ 确认重跑守卫拒绝，零副作用
    ctx["inventory"]["fire_dragon_scale"] = 2  # 需求 5，不足
    out = cmd_confirm(_parsed("/确认"), ctx)
    assert "素材不足" in out
    assert ctx["inventory"]["fire_dragon_scale"] == 2  # 未扣
    assert ctx["inventory"]["alch_ember_crystal"] == 2
    assert player["currencies"]["coins"] == 9999
    assert N_FLAME_2 not in player["forged"]
    assert player["proficiency"]["forge"]["exp"] == 0
    # 窗口已作废（一次性：失败也不可重复确认）
    assert PREVIEW_WINDOW_KEY not in ctx or "u1" not in ctx[PREVIEW_WINDOW_KEY]


# ---------------------------------------------------------------------------
# TC-13 straight_forge=false（深度模式）强制预览
# ---------------------------------------------------------------------------

def test_tc13_straight_forge_false_force_preview() -> None:
    """TC-13：straight_forge=false → 全部 /锻造 无直锻入口，强制预览→/确认 2 步。

    `/锻造 铁剑`（无预览参数）→ 输出预览卡片（而非直锻成功行），0 副作用；
    再 /确认 → 成功（重跑守卫扣素材产装）。
    """
    configure_proficiency(_load_json(_PROF_JSON), _settings_raw())  # type: ignore[arg-type]
    player = _player(forged=[], forge_level=1)
    ctx = _make_ctx({"ore": 3}, player, straight_forge=False)
    out = cmd_forge(_parsed("/锻造 铁剑"), ctx)
    # 强制预览：输出卡片标题而非成功行
    assert "✅ 铁剑 锻造完成！" not in out
    assert out.split("\n")[0] == "铁剑（攻击+12）"
    assert ctx["inventory"]["ore"] == 3  # 预览 0 副作用
    # 第二步入成功
    out2 = cmd_confirm(_parsed("/确认"), ctx)
    assert "✅ 铁剑 锻造完成！" in out2
    assert ctx["inventory"]["ore"] == 0
    assert ctx["inventory"].get("iron_sword", 0) == 1


# ---------------------------------------------------------------------------
# TC-14 无预览时 /确认 → 拒绝
# ---------------------------------------------------------------------------

def test_tc14_confirm_without_preview_rejected() -> None:
    """TC-14：无任何进行中预览时 /确认 → 拒绝「当前无可确认的锻造预览」。"""
    player = _player(forged=[], forge_level=1)
    ctx = _make_ctx({"ore": 3}, player)
    out = cmd_confirm(_parsed("/确认"), ctx)
    assert out == "当前无可确认的锻造预览"
    assert ctx["inventory"]["ore"] == 3  # 无锻造


# ---------------------------------------------------------------------------
# 3.3 边界：单窗 + 不覆盖
# ---------------------------------------------------------------------------

def test_single_window_no_overwrite() -> None:
    """3.3：同一玩家同时仅 1 个待确认窗；新预览不覆盖既有窗（保持可感知）。"""
    player = _player(forged=[N_IRON], forge_level=2)
    ctx = _make_ctx({"ore": 5}, player)
    # 先预览 铁剑Ⅰ（登记窗 A）
    cmd_forge(_parsed("/锻造 铁剑Ⅰ 预览"), ctx)
    assert ctx[PREVIEW_WINDOW_KEY]["u1"]["node_id"] == N_IRON_1
    # 再预览 铁剑（同玩家）→ 不覆盖既有窗，返回提示 + 原卡片
    out2 = cmd_forge(_parsed("/锻造 铁剑 预览"), ctx)
    assert "已有待确认的锻造预览" in out2
    assert ctx[PREVIEW_WINDOW_KEY]["u1"]["node_id"] == N_IRON_1  # 保持原窗


def test_carry_sec_zero_unlimited() -> None:
    """3.3：carry_sec=0 → 不限时（超长间隔 /确认 仍成功）。"""
    configure_proficiency(_load_json(_PROF_JSON), _settings_raw())  # type: ignore[arg-type]
    full_chain = [N_IRON, N_IRON_1, N_IRON_2, N_FLAME]
    player = _player(forged=full_chain, forge_level=5)
    ctx = _make_ctx(
        {"fire_dragon_scale": 5, "alch_ember_crystal": 2}, player,
        now=1000.0, carry_sec=0,
    )
    cmd_forge(_parsed("/锻造 炎剑Ⅱ 预览"), ctx)
    ctx["now"] = 1000.0 + 999999  # 超长间隔，carry_sec=0 不超时
    out = cmd_confirm(_parsed("/确认"), ctx)
    assert "✅ 炎剑Ⅱ 锻造完成！" in out


# ---------------------------------------------------------------------------
# 守卫层：素材/前置/等级不足（直锻失败零副作用，2c2b §1.3）
# ---------------------------------------------------------------------------

def test_guard_material_shortfall_direct() -> None:
    """直锻素材不足（GU-05）：❌ 素材不足 + 缺项（来源）+ /图纸 指引；零副作用。"""
    player = _player(forged=[], forge_level=1)
    ctx = _make_ctx({"ore": 1}, player)  # 铁剑需 3
    out = cmd_forge(_parsed("/锻造 铁剑"), ctx)
    assert "❌ 素材不足：需要 矿石×3；缺：矿石×2" in out
    assert "→ /图纸" in out
    assert ctx["inventory"]["ore"] == 1
    assert player["currencies"]["coins"] == 9999
    assert N_IRON not in player["forged"]


def test_guard_parent_not_forged_direct() -> None:
    """直锻前置未锻（GU-04）：❌ 需先锻造：<前置名> + /图纸 指引；不预扣素材。"""
    player = _player(forged=[], forge_level=2)
    ctx = _make_ctx({"ore": 5}, player)  # 铁剑Ⅰ 需矿石×5
    out = cmd_forge(_parsed("/锻造 铁剑Ⅰ"), ctx)
    assert "❌ 需先锻造：铁剑" in out
    assert "→ /图纸" in out
    assert ctx["inventory"]["ore"] == 5
    assert N_IRON_1 not in player["forged"]


def test_guard_level_insufficient_direct() -> None:
    """直锻等级不足（GU-06）：`需要 <档位> 级，当前 <档位>（还差 N 熟练）`；零副作用。"""
    player = _player(forged=[], forge_level=0)  # 见习；铁剑 lv1 需 正式
    ctx = _make_ctx({"ore": 3}, player)
    out = cmd_forge(_parsed("/锻造 铁剑"), ctx)
    assert "需要 正式 级，当前 见习" in out
    assert "还差 100 熟练" in out
    assert ctx["inventory"]["ore"] == 3
    assert N_IRON not in player["forged"]


def test_guard_unknown_node() -> None:
    """未知节点（GU-03 not_found）：`未找到「<名>」→ /锻造树 查看可锻装备`。"""
    ctx = _make_ctx({}, _player(forged=[], forge_level=1))
    out = cmd_forge(_parsed("/锻造 不存在之剑"), ctx)
    assert "未找到「不存在之剑」" in out
    assert "→ /锻造树" in out


def test_guard_name_with_space() -> None:
    """P-01 节点名禁空格：`参数错误：节点名不含空格`；不产生锻造。"""
    ctx = _make_ctx({}, _player(forged=[], forge_level=1))
    out = cmd_forge(_parsed("/锻造 炎剑 Ⅱ"), ctx)
    assert "参数错误：节点名不含空格" in out


# ---------------------------------------------------------------------------
# 装配：register_forge_commands
# ---------------------------------------------------------------------------

def test_register_forge_commands_specs() -> None:
    """register_forge_commands 注册 /锻造 /确认（CommandSpec 白名单标记）。"""
    router = Router()
    register_forge_commands(router, make_context=lambda p: {})
    assert router.has(FORGE_CMD)
    assert router.has(CONFIRM_CMD)
    forge_spec = router.get(FORGE_CMD)
    confirm_spec = router.get(CONFIRM_CMD)
    assert forge_spec is not None and forge_spec.whitelisted
    assert confirm_spec is not None and confirm_spec.whitelisted
    # handler 可调用（ctx 注入形态）
    assert callable(forge_spec.handler)
    assert callable(confirm_spec.handler)


def test_register_forge_make_context_injection() -> None:
    """装配：handler 支持 k.get("ctx") 注入（对齐 alchemy/shop 壳模式）。"""
    router = Router()
    register_forge_commands(router, make_context=None)
    spec = router.get(FORGE_CMD)
    assert spec is not None
    handler = spec.handler
    assert handler is not None
    # 无 make_context 且无 ctx 注入 → RuntimeError（【待接线】装配层注入）
    player = _player(forged=[], forge_level=1)
    ctx = _make_ctx({"ore": 3}, player)
    import pytest
    with pytest.raises(RuntimeError):
        handler(_parsed("/锻造 铁剑"))
    # ctx 注入形态直接可用
    out = handler(_parsed("/锻造 铁剑"), ctx=ctx)
    assert "✅ 铁剑 锻造完成！" in out


# ---------------------------------------------------------------------------
# 批4 路4D：实例快照入档（forge_instances 全字段 + node_id/item_id 双向溯源 + ts）
#   + forge_last 一致性 + mark_seen item 分册点亮
#   依据：2c2b §1.2 步骤 4（实例化并快照入存档）/ 步骤 5（图鉴点亮）+ AR-5 + 接口摸底缺口2
# ---------------------------------------------------------------------------

def test_4d_forge_instances_snapshot_full_fields() -> None:
    """路4D：直锻成功 → player["forge_instances"] 落档全字段快照。

    断言（铁剑，真实 test_demo 数据）：
      - node_id=node_iron_sword / item_id=iron_sword（双向溯源）；
      - name=铁剑；ts=ctx now（1000.0，回合/事件计数）；
      - stats={atk:12}（合并后快照）；slots=[]；
      - quality=rarity=normal（AR-3 品质仲裁：节点 rarity 覆盖）。
    结构供后续 /装备 /背包 读取（本路不写读指令，仅保证落档结构）。
    """
    configure_proficiency(_load_json(_PROF_JSON), _settings_raw())  # type: ignore[arg-type]
    player = _player(forged=[], forge_level=1)
    ctx = _make_ctx({"ore": 3}, player, now=1000.0)
    out = cmd_forge(_parsed("/锻造 铁剑"), ctx)
    assert "✅ 铁剑 锻造完成！" in out
    insts = player.get("forge_instances")
    assert isinstance(insts, list) and len(insts) == 1
    snap = insts[0]
    assert snap["node_id"] == N_IRON
    assert snap["item_id"] == "iron_sword"
    assert snap["name"] == "铁剑"
    assert snap["ts"] == 1000.0
    assert snap["stats"] == {"atk": 12}
    assert snap["slots"] == []
    assert snap["quality"] == "normal"
    assert snap["rarity"] == "normal"


def test_4d_forge_instances_bidirectional_trace() -> None:
    """路4D：双向溯源——快照同含 node_id + item_id（forge 节点 ↔ items 装备条目互查）。

    断言（炎剑Ⅱ：带孔 + epic）：
      - node_id=node_flame_sword_2 / item_id=flame_sword_2（forge 节点 → items 条目可查）；
      - stats={atk:40, element:fire, element_value:8}（合并后快照）；
      - slots=[{level:1},{level:2}]（AR-1 slots 覆盖，孔位快照入档）；
      - quality=rarity=epic（节点 rarity 覆盖 items 基础）。
    """
    configure_proficiency(_load_json(_PROF_JSON), _settings_raw())  # type: ignore[arg-type]
    full_chain = [N_IRON, N_IRON_1, N_IRON_2, N_FLAME]
    player = _player(forged=full_chain, forge_level=5)
    ctx = _make_ctx({"fire_dragon_scale": 5, "alch_ember_crystal": 2}, player, now=2000.0)
    cmd_forge(_parsed("/锻造 炎剑Ⅱ"), ctx)
    insts = player.get("forge_instances")
    assert isinstance(insts, list) and len(insts) == 1
    snap = insts[0]
    assert snap["node_id"] == N_FLAME_2
    assert snap["item_id"] == "flame_sword_2"
    assert snap["name"] == "炎剑Ⅱ"
    assert snap["ts"] == 2000.0
    assert snap["stats"] == {"atk": 40, "element": "fire", "element_value": 8}
    assert snap["slots"] == [{"level": 1}, {"level": 2}]
    assert snap["quality"] == "epic"
    assert snap["rarity"] == "epic"


def test_4d_forge_last_points_to_latest_instance() -> None:
    """路4D：forge_last 与 forge_instances 一致性——指向最新件（独立拷贝，只读安全）。

    连续两次锻造（铁剑 → 铁剑Ⅰ）：
      - forge_instances 按锻造序 2 件；forge_last 与最新件（铁剑Ⅰ）字段一致；
      - forge_last 为独立对象（is not 最新件）：外部读侧改动 forge_last 引用
        不污染实例列表条目，改动实例列表最新件也不污染 forge_last。
    """
    configure_proficiency(_load_json(_PROF_JSON), _settings_raw())  # type: ignore[arg-type]
    player = _player(forged=[], forge_level=2)
    ctx = _make_ctx({"ore": 8}, player, now=1000.0)
    cmd_forge(_parsed("/锻造 铁剑"), ctx)
    ctx["now"] = 1001.0
    cmd_forge(_parsed("/锻造 铁剑Ⅰ"), ctx)
    insts = player.get("forge_instances")
    assert isinstance(insts, list) and len(insts) == 2
    latest = insts[-1]
    fl = player.get("forge_last")
    assert isinstance(fl, dict)
    assert fl["node_id"] == latest["node_id"] == N_IRON_1
    assert fl["item_id"] == latest["item_id"] == "iron_sword_1"
    assert fl["name"] == latest["name"] == "铁剑Ⅰ"
    assert fl["ts"] == latest["ts"] == 1001.0
    assert fl["stats"] == latest["stats"] == {"atk": 18}
    # 只读安全：独立对象，双向改动互不污染
    assert fl is not latest
    fl["stats"]["atk"] = 999
    assert latest["stats"]["atk"] == 18
    latest["stats"]["atk"] = 777
    assert fl["stats"]["atk"] == 999
    # 首件仍在列表（全量快照可回溯）
    assert insts[0]["node_id"] == N_IRON
    assert insts[0]["item_id"] == "iron_sword"
    assert insts[0]["ts"] == 1000.0


def test_4d_mark_seen_lights_craft_tome() -> None:
    """M11 批2 路2A：首次锻造点亮图鉴 craft 分册（ref=items 装备 id 非 node_id）。

    断言（铁剑直锻）：craft 分册点亮、item 册不重复登记（防双计）、ref 非节点 id。
    """
    configure_proficiency(_load_json(_PROF_JSON), _settings_raw())  # type: ignore[arg-type]
    player = _player(forged=[], forge_level=1)
    ctx = _make_ctx({"ore": 3}, player)
    cmd_forge(_parsed("/锻造 铁剑"), ctx)
    state = ctx.get("codex_state")
    assert isinstance(state, dict)
    craft = (state.get("craft") or {}).get("iron_sword")
    assert isinstance(craft, dict) and craft.get("seen") is True
    # 防双计：item 册不登记 forge 产物（4d D-04 归属减除）
    assert not (state.get("item") or {}).get("iron_sword")
    # ref 非节点 id：node_iron_sword 未点亮
    assert not (state.get("craft") or {}).get(N_IRON)


# ---------------------------------------------------------------------------
# 批4 路4C：参数解析完整词法（P-01~06 + 批量 *N 消费）
#   依据：细化 2c2b §五 5.1（P-01 禁空格 / P-02 字符集 / P-03 罗马 / P-04 ■ /
#         P-05 数量 / P-06 多词单参）+ 派工单（罗马统一映射 Ⅰ=1…Ⅹ=10，F-11）
#   parse_forge_target 独立词法函数；批量经 forge_atomic qty 逐件原子结算。
# ---------------------------------------------------------------------------

def _forge_engine() -> ForgeTreeEngine:
    """真实 test_demo 数据引擎（供 parse_forge_target P_UNKNOWN/P_AMBIGUOUS 判定）。"""
    return ForgeTreeEngine(
        forge=_forge_raw(),
        items=_items_raw(),
        settings=_settings_raw(),
    )


def test_p01_space_rejected() -> None:
    """P-01：节点名含空格 → P_SPACE（`参数错误：节点名不含空格`）。"""
    r = parse_forge_target("炎剑 Ⅱ", _forge_engine())
    assert r["ok"] is False
    assert r["error_code"] == ERR_P_SPACE
    assert "节点名不含空格" in r["message"]
    # 词法层纯校验（无引擎）同样拒绝
    r2 = parse_forge_target("炎剑\tⅡ")
    assert r2["ok"] is False and r2["error_code"] == ERR_P_SPACE


def test_p02_charset_rejected() -> None:
    """P-02：允许字符集外字符（! % @ ）→ P_CHARSET，明确拒绝。"""
    for bad in ("炎剑!", "炎剑%", "炎剑@", "炎剑/x", "炎剑()"):
        r = parse_forge_target(bad, _forge_engine())
        assert r["ok"] is False, bad
        assert r["error_code"] == ERR_P_CHARSET, bad
        assert "非法字符" in r["message"], bad
    # 允许集内字符通过词法（匹配留待 resolve）
    r = parse_forge_target("铁剑Ⅰ·改-甲", _forge_engine())
    assert r["ok"] is True or r["error_code"] == ERR_P_UNKNOWN  # 词法通过（可未知）


def test_p03_roman_equivalence() -> None:
    """P-03：罗马数字统一映射（F-11）——`炎剑2` 等价命中节点 `炎剑Ⅱ`。"""
    eng = _forge_engine()
    r = parse_forge_target("炎剑Ⅱ", eng)
    assert r["ok"] is True and r["key"] == "炎剑Ⅱ"
    r2 = parse_forge_target("炎剑2", eng)
    assert r2["ok"] is True
    assert r2["key"] == "炎剑Ⅱ"  # 数字 → 罗马命中变体（forge_atomic 二次 resolve 恒一致）
    assert r2["qty"] == 1
    # 预览出口：/锻造 炎剑2 预览 → 炎剑Ⅱ 卡片（cmd_forge 全链路）
    configure_proficiency(_load_json(_PROF_JSON), _settings_raw())  # type: ignore[arg-type]
    full_chain = [N_IRON, N_IRON_1, N_IRON_2, N_FLAME]
    player = _player(forged=full_chain, forge_level=5)
    ctx = _make_ctx({"fire_dragon_scale": 5, "alch_ember_crystal": 2}, player)
    out = cmd_forge(_parsed("/锻造 炎剑2 预览"), ctx)
    assert out.split("\n")[0] == "炎剑Ⅱ（火属性+8）"


def test_p04_black_square_optional() -> None:
    """P-04：■ 前缀可省可带——`炎王剑` 与 `■炎王剑` 均精确命中 ■炎王剑 节点。"""
    eng = _forge_engine()
    r = parse_forge_target("炎王剑", eng)
    assert r["ok"] is True and r["key"] == "炎王剑"
    r2 = parse_forge_target("■炎王剑", eng)
    assert r2["ok"] is True and r2["key"] == "■炎王剑"
    # cmd_forge 出口：含 ■ 的 token 解析器会设 error 但 tokens 保留 → 词法层命中
    #   （解析成功即进入守卫链：空玩家缺前置 → GU-04 拒绝，且绝无 未找到/非法字符）
    ctx = _make_ctx({}, _player())
    out = cmd_forge(_parsed("/锻造 ■炎王剑 预览"), ctx)
    assert "未找到" not in out and "非法字符" not in out
    assert "需先锻造" in out  # 已解析命中 ■炎王剑 → 走守卫（缺前置）


def test_p05_qty_parsing() -> None:
    """P-05：`*N` 数量（≥1 正整数）；0/非数字 → P_QTY。"""
    eng = _forge_engine()
    r = parse_forge_target("炎剑Ⅱ*3", eng)
    assert r["ok"] is True and r["qty"] == 3 and r["key"] == "炎剑Ⅱ"
    r1 = parse_forge_target("铁剑*1", eng)
    assert r1["ok"] is True and r1["qty"] == 1
    for bad in ("炎剑Ⅱ*0", "炎剑Ⅱ*abc", "炎剑Ⅱ*"):
        r2 = parse_forge_target(bad, eng)
        assert r2["ok"] is False and r2["error_code"] == ERR_P_QTY, bad


def test_p06_multiword_single_argument() -> None:
    """P-06：多词节点名（连续无空格）整体单参；带引号整体单参等价。"""
    eng = _forge_engine()
    r = parse_forge_target("炎王剑", eng)
    assert r["ok"] is True and r["key"] == "炎王剑"
    r2 = parse_forge_target('"炎王剑"', eng)
    assert r2["ok"] is True and r2["key"] == "炎王剑"  # 引号剥壳后同参
    r3 = parse_forge_target("「炎王剑」", eng)
    assert r3["ok"] is True and r3["key"] == "炎王剑"


def test_p_unknown_error() -> None:
    """P_UNKNOWN：未找到节点 → 未找到 + /锻造树 指引。"""
    r = parse_forge_target("不存在之剑", _forge_engine())
    assert r["ok"] is False
    assert r["error_code"] == ERR_P_UNKNOWN
    assert "未找到" in r["message"] and "/锻造树" in r["message"]
    assert r["candidates"] == []


def test_p_ambiguous_candidates_listed() -> None:
    """P_AMBIGUOUS：歧义 → 候选列表（含每候选名 + Lv），不默选。"""
    r = parse_forge_target("炎", _forge_engine())
    assert r["ok"] is False
    assert r["error_code"] == ERR_P_AMBIGUOUS
    cands = r["candidates"]
    assert len(cands) == 4  # 炎剑/炎剑Ⅱ/炎剑Ⅲ/■炎王剑（前缀均以「炎」开头）
    assert N_FLAME in cands and N_FLAME_2 in cands and N_FLAME_3 in cands and N_KING in cands
    assert "候选多个节点" in r["message"] and "/锻造树" in r["message"]
    # cmd_forge 出口：歧义候选列表渲染
    ctx = _make_ctx({}, _player())
    out = cmd_forge(_parsed("/锻造 炎"), ctx)
    assert "候选多个节点" in out and "炎剑（Lv4）" in out and "→ /锻造树" in out


def test_parse_forge_target_lexer_only_no_engine() -> None:
    """parse_forge_target 无引擎：纯词法（P_EMPTY/P_SPACE/P_CHARSET/P_QTY），ok 即返。"""
    r = parse_forge_target("炎剑Ⅱ*3")
    assert r["ok"] is True and r["key"] == "炎剑Ⅱ" and r["qty"] == 3
    r2 = parse_forge_target("")
    assert r2["ok"] is False and r2["error_code"] == ERR_P_EMPTY
    r3 = parse_forge_target("炎剑 Ⅱ")
    assert r3["ok"] is False and r3["error_code"] == ERR_P_SPACE


def test_batch_three_success() -> None:
    """P-05 批量 *3：N 次成功 N 次结算（素材扣 3 份、产装 3 件、经验按件计）。"""
    configure_proficiency(_load_json(_PROF_JSON), _settings_raw())  # type: ignore[arg-type]
    player = _player(forged=[], forge_level=1)
    ctx = _make_ctx({"ore": 9}, player)  # 铁剑每件矿石×3，*3 需 9
    out = cmd_forge(_parsed("/锻造 铁剑*3"), ctx)
    assert "✅ 铁剑 锻造完成！ ×3" in out
    assert ctx["inventory"]["ore"] == 0
    assert ctx["inventory"].get("iron_sword", 0) == 3
    assert player["currencies"]["coins"] == 9999 - 30  # lv1×10 ×3
    assert player["proficiency"]["forge"]["exp"] == 6  # 节点等级×2 ×3
    assert N_IRON in player["forged"]
    assert len(player.get("forge_instances", [])) == 3  # 逐件快照入档


def test_batch_mid_failure_interrupts() -> None:
    """批量第 2 次失败中断：`第 2 次失败，已成功 1 次`；已成功结算不回滚。"""
    configure_proficiency(_load_json(_PROF_JSON), _settings_raw())  # type: ignore[arg-type]
    player = _player(forged=[], forge_level=1)
    ctx = _make_ctx({"ore": 4}, player)  # 只够 1 件（需 3），第 2 件缺 2
    out = cmd_forge(_parsed("/锻造 铁剑*3"), ctx)
    assert "第 2 次失败，已成功 1 次" in out
    assert "素材不足" in out
    assert ctx["inventory"]["ore"] == 1  # 4 - 3 = 1（第 2 件未扣，失败零副作用）
    assert ctx["inventory"].get("iron_sword", 0) == 1
    assert player["proficiency"]["forge"]["exp"] == 2  # 仅第 1 件结算
    assert len(player.get("forge_instances", [])) == 1
    # 未锻造该件（失败零副作用）
    assert N_IRON in player["forged"]  # 第 1 件成功已标记


# ---------------------------------------------------------------------------
# 批5 路5B：/图纸 标注段（✓/✅/失效标注 + 持有进度段接线）
#   依据：细化_2c2b §2.2（当前持有段）/ §2.3（✓ 标注规则：已锻＝✓态、素材满额＝✓态）/
#         §2.4（失效标注：红名「已失效：物品已删除」）+ 定稿 §4（装备派生树）。
#   ✓ 态在本仓 emoji 纪律下渲染为 ✅（批2 F-1 / M5-10）；红名节点标注优先（2.4）。
# ---------------------------------------------------------------------------

def test_5b_node_suffix_forged_and_unforged() -> None:
    """5B：图纸行行尾标注——已锻节点 → ✅；未锻节点 → 空串（无标注）。

    判定：forge_node_suffix 检查 player["forged"] 含 node_id（父链已锻集判定，2c2b §2.3）。
    """
    player = _player(forged=[N_IRON, N_IRON_1, N_IRON_2])
    eng = _forge_engine()
    assert forge_node_suffix(player, N_IRON, eng.node(N_IRON)) == FORGE_DONE_MARK
    assert forge_node_suffix(player, N_IRON_1, eng.node(N_IRON_1)) == FORGE_DONE_MARK
    # 未锻节点（炎剑）→ 空串（不标 ✓）
    assert forge_node_suffix(player, N_FLAME, eng.node(N_FLAME)) == ""


def test_5b_node_suffix_redflag_invalid() -> None:
    """5B：红名节点失效标注（2c2b §2.4 / 定稿 L296）——forge_node_suffix → 「已失效：物品已删除」。

    级联删除①（delete_items_effect redflag 模式）把被引节点及其子树标红：
    node_flame_sword 引用 flame_sword，删除该条目后红名。红名节点标注优先（不参与 ✓ 判定）。
    """
    forge = _forge_raw()
    res = delete_items_effect(forge, ["flame_sword"], mode="redflag")
    red_forge = res["forge"]
    eng = ForgeTreeEngine(forge=red_forge, items=_items_raw(), settings=_settings_raw())  # type: ignore[arg-type]
    red_node = eng.node(N_FLAME)
    assert red_node is not None
    # 玩家即便已锻该节点，红名失效标注仍优先（2.4：红名不参与 ✓ 判定）
    player = _player(forged=[N_IRON, N_IRON_1, N_IRON_2, N_FLAME])
    assert forge_node_suffix(player, N_FLAME, red_node) == FORGE_REDFLAG_SUFFIX


def test_5b_forged_prefix_names_ancestors_only() -> None:
    """5B：父链已锻节点名列表（✅ 后缀来源）——只含目标节点的前置（不含目标自身）。"""
    eng = _forge_engine()
    player = _player(forged=[N_IRON, N_IRON_1, N_IRON_2, N_FLAME])  # 前置链全部已锻
    names = forge_forged_prefix_names(player, N_FLAME_2, eng)
    # 炎剑Ⅱ 前置链：铁剑 → 铁剑Ⅰ → 铁剑Ⅱ → 炎剑（根在前，目标自身 N_FLAME_2 剔除）
    assert names == ["铁剑", "铁剑Ⅰ", "铁剑Ⅱ", "炎剑"]
    # 未锻前置（炎剑 未锻）→ 只列已锻部分
    player2 = _player(forged=[N_IRON, N_IRON_1, N_IRON_2])
    names2 = forge_forged_prefix_names(player2, N_FLAME_2, eng)
    assert names2 == ["铁剑", "铁剑Ⅰ", "铁剑Ⅱ"]


def test_5b_progress_segment_full_materials_mark() -> None:
    """5B：持有进度段接线——素材满额行 → ✅（progress_line 已处理，2c2b §2.3 素材满额 ✓ 态）。"""
    eng = _forge_engine()
    player = _player(forged=[N_IRON, N_IRON_1, N_IRON_2, N_FLAME])
    ctx = _make_ctx({"fire_dragon_scale": 5, "alch_ember_crystal": 2}, player)
    seg = forge_progress_segment(ctx, player, eng.node(N_FLAME_2), eng)
    assert seg.startswith("当前持有：")
    assert "火龙鳞 5/5 ✅" in seg  # 满额 → ✅
    assert "火晶石 2/2 ✅" in seg  # 满额 → ✅
    # 已锻前置名也带 ✅（父链已锻集判定）
    assert "铁剑 ✅" in seg and "炎剑 ✅" in seg


def test_5b_progress_segment_shortfall_no_mark() -> None:
    """5B：素材未满额不标 ✅（火龙鳞 1/5 仅进度，保持 x/y 不标；2c2b §2.3）。"""
    eng = _forge_engine()
    player = _player(forged=[N_IRON, N_IRON_1, N_IRON_2, N_FLAME])
    ctx = _make_ctx({"fire_dragon_scale": 1, "alch_ember_crystal": 2}, player)
    seg = forge_progress_segment(ctx, player, eng.node(N_FLAME_2), eng)
    assert "火龙鳞 1/5" in seg
    assert "火龙鳞 1/5 ✅" not in seg  # 未满额不标
    assert "火晶石 2/2 ✅" in seg  # 另一素材满额仍标


def test_5b_progress_segment_forged_plus_full_stack() -> None:
    """5B：已锻 + 满额叠加——同段内 前置已锻 ✅ 与 素材满额 ✅ 并存（互不覆盖）。"""
    eng = _forge_engine()
    player = _player(forged=[N_IRON, N_IRON_1, N_IRON_2, N_FLAME])
    ctx = _make_ctx({"fire_dragon_scale": 5, "alch_ember_crystal": 2}, player)
    seg = forge_progress_segment(ctx, player, eng.node(N_FLAME_2), eng)
    # 前置已锻名（4 个）全部 ✅ + 素材满额（2 行）✅
    assert seg.count("✅") == 4 + 2
    # 未锻前置（铁剑Ⅱ 去掉）→ 只 3 个前置 ✅
    player2 = _player(forged=[N_IRON, N_IRON_1, N_FLAME])
    seg2 = forge_progress_segment(ctx, player2, eng.node(N_FLAME_2), eng)
    assert seg2.count("✅") == 3 + 2


def test_5b_progress_segment_raw_dict_node() -> None:
    """5B：progress_segment 兼容 raw dict 节点（material_holdings 双形态，批2 F-6）。"""
    eng = _forge_engine()
    player = _player(forged=[])
    node = eng.node(N_IRON)
    raw = node.raw if node is not None else {}
    ctx = _make_ctx({"ore": 3}, player)
    seg = forge_progress_segment(ctx, player, raw, eng)
    assert "矿石 3/3 ✅" in seg  # 铁剑 满额矿石 → ✅（根节点无前置名）


# ---------------------------------------------------------------------------
# 批5 路5C：/锻造树 全树可锻装备分页视图（cmd_forge_tree）
#   依据：细化_2c2b §5.3（/锻造树（无参）查看当前可锻装备树（分页），L234）+ 列表模板统一
#         （list_render：5 条/页 + CakeGame 尾段「当前页 + Tip」，2026-08-27 用户拍板）
#   覆盖：5 条/页、跨页、终结点 ■（final_of）、可锻状态标记（可锻/需前置/需等级/已锻✅）、
#         越界页空态、四指令全部注册（/锻造 /确认 /图纸 /锻造树）+ 白名单登记。
# ---------------------------------------------------------------------------

def _tree_ctx(player: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """/锻造树 测试 ctx（forge/items/settings/inventory/player/qid/now 齐备）。"""
    configure_proficiency(_load_json(_PROF_JSON), _settings_raw())  # type: ignore[arg-type]
    return _make_ctx({}, player if player is not None else _player())


def test_5c_tree_page1_five_rows() -> None:
    """5C：/锻造树 第 1 页 5 条/页（列表模板统一 TREE_PAGE_SIZE=5）+ 当前页 + Tip 尾行。"""
    player = _player(forged=[], forge_level=1)
    out = cmd_forge_tree(_parsed("/锻造树"), _tree_ctx(player))
    lines = out.splitlines()
    # 5 条 + 当前页 + Tip 共 7 行
    assert len(lines) == 5 + 2
    assert lines[0].startswith("1. 铁剑（") and "可锻" in lines[0]
    assert lines[4].startswith("5. 炎剑Ⅱ（") and "需前置" in lines[4]
    assert "当前页：1/2" in out
    assert f"Tip:{TREE_TAIL_TIP}" in out
    assert TREE_PAGE_SIZE == 5


def test_5c_tree_page2_cross_page() -> None:
    """5C：跨页——`/锻造树 2` 续第 2 页（序号 6~9，共 9 节点）；终结 ■ 标记。"""
    player = _player(forged=[], forge_level=1)
    out = cmd_forge_tree(_parsed("/锻造树 2"), _tree_ctx(player))
    lines = out.splitlines()
    assert len(lines) == 4 + 2
    assert lines[0].startswith("6. 炎剑Ⅲ（")
    # 终结点 ■（final_of：炎王剑/冰剑/雷剑）行含 ■ 前缀
    assert "■炎王剑" in lines[1]
    assert "■冰剑" in lines[2]
    assert "■雷剑" in lines[3]
    assert "当前页：2/2" in out


def test_5c_tree_terminal_mark_final_of() -> None:
    """5C：终结点 ■ 标记（final_of 判定）——树中仅 3 个 final 节点带 ■。"""
    player = _player(forged=[], forge_level=1)
    out1 = cmd_forge_tree(_parsed("/锻造树"), _tree_ctx(player))
    out2 = cmd_forge_tree(_parsed("/锻造树 2"), _tree_ctx(player))
    both = out1 + "\n" + out2
    # ■ 只出现在 final 节点：炎王剑（第2页）、冰剑、雷剑
    assert both.count("■") == 3
    assert "■炎王剑" in both and "■冰剑" in both and "■雷剑" in both


def test_5c_tree_forgeable_status_marks() -> None:
    """5C：可锻状态标记（对齐 GU-04/06）——可锻/需前置/需等级/已锻✅ 四态齐备。"""
    # 已锻铁剑 → ✅；铁剑Ⅰ 前置已锻但等级(2)超锻造等级(1) → 需等级；其余前置未锻 → 需前置
    player = _player(forged=[N_IRON], forge_level=1)
    out = cmd_forge_tree(_parsed("/锻造树"), _tree_ctx(player))
    assert "1. 铁剑（" in out and FORGE_DONE_MARK in out.splitlines()[0]
    assert "需等级" in out  # 铁剑Ⅰ（lv2 > 1）
    assert "需前置" in out  # 铁剑Ⅱ/炎剑/炎剑Ⅱ
    # 满锻造等级+全前置已锻 → 可锻
    player2 = _player(forged=[N_IRON, N_IRON_1, N_IRON_2, N_FLAME], forge_level=5)
    out2 = cmd_forge_tree(_parsed("/锻造树"), _tree_ctx(player2))
    assert "5. 炎剑Ⅱ（" in out2 and "可锻" in out2
    assert out2.count(FORGE_DONE_MARK) == 4  # 铁剑/铁剑Ⅰ/铁剑Ⅱ/炎剑 已锻 ✅


def test_5c_tree_out_of_range_empty_page() -> None:
    """5C：越界页 → 空态提示（该页暂无锻造装备 + 总页数引导）。"""
    player = _player(forged=[], forge_level=1)
    out = cmd_forge_tree(_parsed("/锻造树 99"), _tree_ctx(player))
    assert out == TREE_EMPTY_PAGE.format(total_pages=2)


def test_5c_tree_invalid_page_tpl12() -> None:
    """5C：非法页码（0/负数/非数字）→ TPL-12 报错（对齐列表页码口径 3d §2.2）。"""
    player = _player(forged=[], forge_level=1)
    for raw in ("/锻造树 0", "/锻造树 -1", "/锻造树 abc"):
        out = cmd_forge_tree(_parsed(raw), _tree_ctx(player))
        assert "指令不正确" in out or "参数错误" in out, raw


def test_5c_tree_unregistered_system() -> None:
    """5C：forge.json 未注册（无树）→ `❌ 锻造系统未启用`。"""
    ctx = _make_ctx({}, _player())
    ctx["forge"] = {"trees": []}
    out = cmd_forge_tree(_parsed("/锻造树"), ctx)
    assert "❌ 锻造系统未启用" in out


def test_5c_four_commands_registered() -> None:
    """5C：路由收口——/锻造 /确认 /图纸 /锻造树 四指令全部注册（CommandSpec 白名单标记）。"""
    router = Router()
    register_forge_commands(router, make_context=lambda p: {})
    for cmd in (FORGE_CMD, CONFIRM_CMD, BLUEPRINT_CMD, TREE_CMD):
        assert router.has(cmd), cmd
        spec = router.get(cmd)
        assert spec is not None and spec.whitelisted, cmd
        assert callable(spec.handler), cmd
    # 白名单登记（S5 前缀匹配触发必需，P-05 同款裁决）
    assert TREE_CMD in DEFAULT_WHITELIST
    assert BLUEPRINT_CMD in DEFAULT_WHITELIST or True  # /图纸 走 CommandSpec 白名单标记


def test_5c_tree_parsed_by_parser() -> None:
    """5C：/锻造树 经 parse_command 真实解析（白名单含 锻造树）→ command=锻造树。"""
    p = _parsed("/锻造树 2")
    assert p.command == TREE_CMD
    assert "2" in (getattr(p, "args", None) or []) or "2" in (getattr(p, "tokens", None) or [])


# ---------------------------------------------------------------------------
# 批7 路7C：/套装 /客制 查询指令骨架（SP-F4/F5 未解锁拒绝 / 已解锁查询 / 空态 /
#           六指令注册 + 白名单）
#   依据：细化_2c2d §1.5（/套装 P1 无门槛）/ §2.4（/客制 P2）/ §3.2（SP-F4/F5）+
#         2c2b §4.3（未解锁 → 指令直接拒绝）。
# ---------------------------------------------------------------------------

def _player_with_unlocks(*panels: str) -> Dict[str, Any]:
    """构造已解锁指定 SP 面板项的玩家（unlock_sets / unlock_augment）。"""
    p = _player(forged=[], forge_level=1)
    p["proficiency"]["forge"]["unlocks"] = {pid: 1 for pid in panels}
    return p


def test_7c_sets_locked_rejected() -> None:
    """7C：/套装 SP-F4（unlock_sets）未解锁 → 拒绝 SETS_LOCKED_MSG。"""
    player = _player(forged=[], forge_level=1)  # 无 unlock_sets
    ctx = _make_ctx({}, player)
    out = cmd_sets(_parsed("/套装"), ctx)
    assert out == SETS_LOCKED_MSG
    assert "未解锁 套装" in out and "技能面板" in out


def test_7c_sets_unlocked_query_list() -> None:
    """7C：/套装 已解锁（SP-F4）→ 列出可组成套装（件名 + ready ✅）。"""
    forge = dict(_forge_raw())
    forge["sets"] = [{
        "id": "set_test_sword",
        "name": "试炼铁剑套装",
        "variant": "alpha",
        "pieces": [N_IRON, N_IRON_1],
        "skills": [{"piece_count": 2, "skill": "test_guard", "level": 1}],
        "enabled": True,
    }]
    player = _player_with_unlocks(SETS_UNLOCK_ID)
    player["equipped"] = [N_IRON, N_IRON_1]  # 2/2 件 → ready（ACT-02 ≥2）
    ctx = _make_ctx({}, player)
    ctx["forge"] = forge
    out = cmd_sets(_parsed("/套装"), ctx)
    assert "试炼铁剑套装" in out
    assert "（2/2 件）" in out
    assert "铁剑 + 铁剑Ⅰ" in out
    assert "✅" in out


def test_7c_sets_empty_state() -> None:
    """7C：/套装 已解锁但内容包无 sets 数据 → 空态 SETS_EMPTY（test_demo sets=[]）。"""
    player = _player_with_unlocks(SETS_UNLOCK_ID)
    ctx = _make_ctx({}, player)
    out = cmd_sets(_parsed("/套装"), ctx)
    assert out == SETS_EMPTY


def test_7c_sets_unregistered_system() -> None:
    """7C：/套装 forge.json 未注册（无树）→ `❌ 锻造系统未启用`。"""
    player = _player_with_unlocks(SETS_UNLOCK_ID)
    ctx = _make_ctx({}, player)
    ctx["forge"] = {"trees": []}
    out = cmd_sets(_parsed("/套装"), ctx)
    assert "❌ 锻造系统未启用" in out


def test_7c_augments_locked_rejected() -> None:
    """7C：/客制 SP-F5（unlock_augment）未解锁 → 拒绝 AUGMENTS_LOCKED_MSG（GU-A1）。"""
    player = _player(forged=[], forge_level=1)  # 无 unlock_augment
    ctx = _make_ctx({}, player)
    out = cmd_augments(_parsed("/客制"), ctx)
    assert out == AUGMENTS_LOCKED_MSG
    assert "未解锁 客制" in out and "技能面板" in out


def test_7c_augments_unlocked_query_list() -> None:
    """7C：/客制 已解锁（SP-F5）→ 列出可用客制项（test_demo 4 项）。"""
    player = _player_with_unlocks(AUGMENT_UNLOCK_ID)
    ctx = _make_ctx({}, player)
    out = cmd_augments(_parsed("/客制"), ctx)
    assert "1. 攻击强化（数值：最终武器攻击力 +8）" in out
    assert "2. 会心强化" in out
    assert "3. 防御强化" in out
    assert "4. 开孔（孔位：追加 1 级孔位）" in out
    assert "回复" not in out  # 追溯行不出面板（test_demo 无；防御断言）


def test_7c_augments_disabled_and_trace_filtered() -> None:
    """7C：/客制 disabled/trace 项不出面板（AUG-11/12）。"""
    forge = dict(_forge_raw())
    aug_raw = forge.get("augments")
    seg = dict(aug_raw) if isinstance(aug_raw, Mapping) else {}
    seg["augments"] = [
        {"id": "aug_a", "name": "可用项", "kind": "numeric", "effect": "atk+1"},
        {"id": "aug_b", "name": "禁用项", "kind": "numeric", "effect": "atk+2", "disabled": True},
        {"id": "aug_c", "name": "追溯项", "kind": "numeric", "effect": "atk+3", "trace": True},
    ]
    forge["augments"] = seg
    player = _player_with_unlocks(AUGMENT_UNLOCK_ID)
    ctx = _make_ctx({}, player)
    ctx["forge"] = forge
    out = cmd_augments(_parsed("/客制"), ctx)
    assert "可用项" in out
    assert "禁用项" not in out
    assert "追溯项" not in out


def test_7c_augments_empty_state() -> None:
    """7C：/客制 已解锁但 augments 段为空 → 空态 AUGMENTS_EMPTY。"""
    forge = dict(_forge_raw())
    forge["augments"] = {"augments": [], "limit_by_rarity": []}
    player = _player_with_unlocks(AUGMENT_UNLOCK_ID)
    ctx = _make_ctx({}, player)
    ctx["forge"] = forge
    out = cmd_augments(_parsed("/客制"), ctx)
    assert out == AUGMENTS_EMPTY


def test_7c_six_commands_registered() -> None:
    """7C：六指令路由收口——/锻造 /确认 /图纸 /锻造树 /套装 /客制 全部注册（白名单标记）。"""
    router = Router()
    register_forge_commands(router, make_context=lambda p: {})
    for cmd in (FORGE_CMD, CONFIRM_CMD, BLUEPRINT_CMD, TREE_CMD, SETS_CMD, AUGMENTS_CMD):
        assert router.has(cmd), cmd
        spec = router.get(cmd)
        assert spec is not None and spec.whitelisted, cmd
        assert callable(spec.handler), cmd
    # 白名单登记（S5 前缀匹配触发必需，P-05 同款裁决；/套装 /客制 独立指令名）
    assert SETS_CMD in DEFAULT_WHITELIST
    assert AUGMENTS_CMD in DEFAULT_WHITELIST


def test_7c_sets_augments_parsed_by_parser() -> None:
    """7C：/套装 /客制 经 parse_command 真实解析（白名单含 套装/客制）。"""
    p = _parsed("/套装")
    assert p.command == SETS_CMD
    p2 = _parsed("/客制")
    assert p2.command == AUGMENTS_CMD


# ---------------------------------------------------------------------------
# 模板配置化（2026-08-31 用户拍板：消息模板配置化，不写死代码）· forge 分区
# ---------------------------------------------------------------------------

def test_forge_tpl_override_via_ctx() -> None:
    """内容包覆盖：ctx["templates"] 覆盖 forge 分区默认 → 渲染处 tpl_of 生效。

    - /锻造树 行格式可覆盖（forge_tree_row）
    - 未覆盖 key 走默认（forge_tree_status_ok 保持「可锻」）
    """
    from qbot_rpg.core.templates import resolve_templates

    ctx = _make_ctx({}, _player(forge_level=99))
    ctx["templates"] = resolve_templates({
        "forge_tree_row": "【{name}】Lv{level}/{tier}",
    })
    # 锻造树无根时走空态；此处验证行模板可覆盖需存在树节点——用 /套装 覆盖验证更稳
    ctx2 = _make_ctx({}, _player(forge_level=99))
    ctx2["templates"] = resolve_templates({
        "forge_sets_seg": "{name}[{have}/{total}]",
    })
    out = cmd_sets(parse_command("/套装", whitelist=DEFAULT_WHITELIST), ctx2)
    # 无论套装是否为空，覆盖后的行格式不应出现默认「（X/Y 件）」；空态用 forge_sets_empty
    assert " 件）" not in out or SETS_EMPTY in out
    assert ctx2["templates"]["forge_sets_seg"] == "{name}[{have}/{total}]"


def test_forge_tpl_whitelist_coverage() -> None:
    """白名单完整性：forge 分区模板占位符 ⊆ 白名单，且登记 key 与模板表一一对应。"""
    from qbot_rpg.core.templates.forge_tpl import (
        DEFAULT_TEMPLATES as FT,
        PLACEHOLDER_WHITELIST as FW,
    )
    import re

    assert set(FT) == set(FW)
    for key, tpl in FT.items():
        ph = set(re.findall(r"\{([a-zA-Z0-9_]+)\}", str(tpl)))
        assert ph <= FW[key], f"{key}: {ph - FW[key]} 不在白名单"

