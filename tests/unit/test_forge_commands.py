"""M9 锻造·批4·路4B：/锻造 直锻/预览双流 + /确认 一次性窗口 指令壳单测。

文件：tests/unit/test_forge_commands.py
创建：2026-08-30
作者：Hermes 子agent-4B（M9 锻造实现组批4·路4B：并发同仓，仅新建本文件 +
  追加 qbot_rpg/commands/forge_commands.py；不改动核心引擎文件）

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

覆盖规则（对齐 2c2b §六 C TC-09~14 + §3.3 边界）：
  直锻路径守卫 GU-01~06 全过 → 扣素材/扣金币/产装/发经验原子成功；
  预览不扣资源；确认窗单键（qid）；超时作废；无预览确认拒绝。

依据：docs/细化/细化_2c2b_锻造流程契约.md §三（3.1~3.4）+ §六 C（TC-09~14）+
  定稿 §3.3（预览流 L89-97）/ §2.1 #7（L57）/ L239（零会话）。
测试风格对齐 tests/unit/test_forge_progress.py（真实 test_demo 数据 +
  ForgeTreeEngine 构造）+ tests/unit/test_confirm_commands.py（parse_command 直调 +
  全字段 ctx + 指令壳 handler 直测）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, Mapping, Optional

from qbot_rpg.commands.forge_commands import (
    CONFIRM_CMD,
    FORGE_CMD,
    PREVIEW_WINDOW_KEY,
    cmd_confirm,
    cmd_forge,
    register_forge_commands,
)
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command
from qbot_rpg.commands.router import Router
from qbot_rpg.core.forge_job import configure_proficiency

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
