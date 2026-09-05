"""训练木桩指令：/木桩 /调整木桩（怪物模块 §十五：enemies.json tier=training 特例）。

文件名：dummy_commands.py
创建时间：2026-09-06
作者：Hermes 主代理（指令缺口补全批1路2）

功能描述：
  ① cmd_dummy（/木桩 [档位]）：无参 → 列出可挑战木桩档位（序号+名称+HP/防御摘要）；
     带参（序号/名称）→ 启动训练木桩战斗（BattleEngine battle_type="dummy"）。
  ② cmd_adjust_dummy（/调整木桩 [怪物名]）：带参 → 把指定怪物面板（def/元素抗性/
     弱点）覆盖到木桩（HP 仍木桩值；不复制攻击/行动——木桩不反击）；无参 → 重置。
  ③ 训练战特例（§15.2）：木桩不可反击（无 actions）、无掉落/经验（enemies 条目无
     rewards/drops——奖励结算读不到即零）、玩家战败无损（木桩不攻击不会发生）、
     不入图鉴（codex 已剔除 tier=training）。

依据：
  - /root/docs_archive/RPG框架项目/怪物模块设计定稿.md §十五（15.1 标记/15.2 特例
    规则/15.3 多档/15.4 入口 /木桩/15.4.1 /调整木桩）
  - /root/docs_archive/RPG框架项目/RPG回合制框架设计文档.md L1280（/木桩 指令登记）
  - qbot_rpg/commands/battle_launch_commands.py（复用 _enemy_combatant/
    _player_combatant/_battle_defs + 引擎启动 + session acquire 路径）

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查）：
  F-D1 dummy_override 落玩家 persistent_state["dummy_override"]（玩家级档位，随
       ctx player 全量落档——契约说「settings/世界状态（可配）」，玩家级实现满足
       「覆盖后下次 /木桩 生效 + 重启保留」且免 world_state 事务复杂度；dummy_log
       同区（data/player.py L93 约定 dummy_log 为玩家 persistent_state 键）。
  F-D2 木桩 HP 取 enemies.json stats.hp（veinborn 轻甲 3000/重甲 5000——「极大」
       相对斩杀测量足够且可打死结束战斗；契约 §15.1「防打死中断测量」语义在本仓
       无 /撤退 入口（2026-08-31 用户拍板删）下以可打死为界——打死=正常胜利结算）。
  F-D3 覆盖面板合并：dummy_override = {def_base?, elem_res?, weakness?, name}——
       木桩启动时把覆盖面板的 def_base→combatant dfn、elem_res/weakness 并入木桩
       entry（stats.hp 保持木桩原值）。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional

from qbot_rpg.commands.battle_launch_commands import (
    _battle_defs,
    _enemy_combatant,
    _player_combatant,
)
from qbot_rpg.core.templates import tpl_of

__all__ = [
    "DUMMY_CMD",
    "ADJUST_DUMMY_CMD",
    "cmd_dummy",
    "cmd_adjust_dummy",
    "register_dummy_commands",
    "launch_dummy_battle",
]

DUMMY_CMD = "木桩"
ADJUST_DUMMY_CMD = "调整木桩"

_DUMMY_OVERRIDE_KEY = "dummy_override"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _player_ps(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """玩家 persistent_state（dict 玩家直接读写；dataclass → asdict）。"""
    p = ctx.get("player")
    if isinstance(p, MutableMapping):
        ps = p.get("persistent_state")
        if isinstance(ps, MutableMapping):
            return ps
        ps = {}
        p["persistent_state"] = ps
        return ps
    if p is not None and hasattr(p, "persistent_state"):
        import dataclasses  # noqa: PLC0415

        d = dataclasses.asdict(p)
        ctx["player"] = d
        ps = d.get("persistent_state")
        if isinstance(ps, MutableMapping):
            return ps
        ps = {}
        d["persistent_state"] = ps
        return ps
    return {}


def _enemies_list(ctx: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """ctx enemies 表（Mapping[enemy_id → entry] / list[entry]）→ list[entry]。"""
    enemies = ctx.get("enemies")
    out: List[Mapping[str, Any]] = []
    if isinstance(enemies, Mapping):
        for v in enemies.values():
            if isinstance(v, Mapping):
                out.append(v)
    elif isinstance(enemies, list):
        for e in enemies:
            if isinstance(e, Mapping):
                out.append(e)
    return out


def _dummy_entries(ctx: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """木桩条目（tier=training 或 type=dummy）。"""
    return [e for e in _enemies_list(ctx)
            if e.get("tier") == "training" or e.get("type") == "dummy"]


def _find_enemy(ctx: Mapping[str, Any], name_or_id: str) -> Optional[Mapping[str, Any]]:
    for e in _enemies_list(ctx):
        if str(e.get("id") or "") == name_or_id or str(e.get("name") or "") == name_or_id:
            return e
    return None


def _display_dfn(entry: Mapping[str, Any]) -> int:
    st = entry.get("stats") or {}
    if isinstance(st, Mapping):
        return int(st.get("con", st.get("dfn", 0)) or 0)
    return 0


def _display_hp(entry: Mapping[str, Any]) -> int:
    st = entry.get("stats") or {}
    if isinstance(st, Mapping):
        return int(st.get("hp", 0) or 0)
    return 0


# ---------------------------------------------------------------------------
# 木桩启动（复用 PvE 引擎装配路径；async——session acquire）
# ---------------------------------------------------------------------------

async def launch_dummy_battle(
    ctx: MutableMapping[str, Any],
    dummy_ref: Any = None,
) -> Dict[str, Any]:
    """发起训练木桩战斗。

    入参 ctx（player/enemies/session_mgr/skills 等装配键）；dummy_ref: 序号/名/id。
    出参 {ok, message, battle_engine}（对齐 launch_pve_battle 契约）。
    覆盖面板（F-D1）：dummy_override 有值时把防御/抗性面板并到木桩 entry。
    """
    sm = ctx.get("session_mgr")
    if sm is None:
        return {"ok": False, "message": "会话管理器不可用", "battle_engine": None}
    qid = str(ctx.get("qid") or ctx.get("qq_id") or "")
    # 会话互斥（已有战斗/会话 → 拒绝）
    active = getattr(sm, "get_active", None)
    if callable(active):
        try:
            out = active(qid)
            import inspect  # noqa: PLC0415
            cur = await out if inspect.isawaitable(out) else out
        except Exception:  # noqa: BLE001
            cur = None
        if cur is not None:
            return {"ok": False, "message": tpl_of(ctx, "dummy_battle_lock"),
                    "battle_engine": None}

    # 解析木桩
    dummies = _dummy_entries(ctx)
    if not dummies:
        return {"ok": False, "message": tpl_of(ctx, "dummy_list_empty"),
                "battle_engine": None}
    entry: Optional[Mapping[str, Any]] = None
    if dummy_ref is None or str(dummy_ref) == "":
        entry = dummies[0]
    else:
        s = str(dummy_ref)
        if s.isdigit():
            idx = int(s)
            if 1 <= idx <= len(dummies):
                entry = dummies[idx - 1]
        else:
            entry = _find_enemy(ctx, s)
            if entry is not None and entry not in dummies:
                # 指定的是普通怪 → 用覆盖语义（若无 override 先建默认木桩+覆盖）
                pass
    if entry is None or not _is_dummy(entry):
        if entry is not None:
            # 指定普通怪：若已有 override 则应用到默认木桩
            ov = _get_override(ctx)
            if ov is not None and str(ov.get("name") or "") == str(entry.get("name") or ""):
                pass
        return {"ok": False,
                "message": tpl_of(ctx, "dummy_not_found", {"name": str(dummy_ref or "")}),
                "battle_engine": None}

    # 覆盖面板合并（F-D3）
    merged = _apply_override(entry, _get_override(ctx))

    # 装配引擎（对齐 launch_pve_battle ③）
    registry = ctx.get("registry")
    all_defs, _chains_map, ce = _battle_defs(registry) if registry is not None else ({}, {}, None)
    p_comb = _player_combatant(ctx)
    if not p_comb:
        return {"ok": False, "message": "❌ 玩家状态不可用", "battle_engine": None}
    e_comb = _enemy_combatant(merged)
    try:
        from qbot_rpg.core.battle import BattleEngine  # noqa: PLC0415
        eng = BattleEngine(defs=all_defs, registry=registry, combo_engine=ce,
                           enemy_def=merged)
        eng.start(p_comb, e_comb, random_seed=None, battle_type="dummy")
    except Exception as exc:  # noqa: BLE001 - 开战失败不崩
        return {"ok": False, "message": f"❌ 开战失败：{exc}", "battle_engine": None}

    # 快照落 session（对齐 launch_pve_battle ④）
    try:
        snap = eng.to_snapshot()
        await sm.acquire(qid, "battle", payload=snap)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"❌ 开战失败（存档）：{exc}", "battle_engine": None}

    e_name = str(e_comb.get("name") or "训练木桩")
    e_hp = int(e_comb.get("max_hp", 0))
    msg = tpl_of(ctx, "dummy_start", {"name": e_name, "hp": e_hp})
    return {"ok": True, "message": msg, "battle_engine": eng}


def _is_dummy(entry: Mapping[str, Any]) -> bool:
    return entry.get("tier") == "training" or entry.get("type") == "dummy"


def _get_override(ctx: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    ps = ctx.get("player")
    if isinstance(ps, MutableMapping):
        ov = ps.get("persistent_state", {}).get(_DUMMY_OVERRIDE_KEY)
    else:
        _pstate = getattr(ps, "persistent_state", {}) if ps is not None else {}
        ov = _pstate.get(_DUMMY_OVERRIDE_KEY) if isinstance(_pstate, Mapping) else None
    return ov if isinstance(ov, Mapping) else None


def _apply_override(entry: Mapping[str, Any],
                    override: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """木桩 entry + 覆盖面板 → 合并 entry（HP 保持木桩原值；def/抗性/弱点用覆盖）。"""
    out = dict(entry)
    if not override:
        return out
    st = dict(entry.get("stats") or {})
    if isinstance(override, Mapping):
        o_def = override.get("def_base")
        if isinstance(o_def, (int, float)):
            # def_base（怪物面板防御基准）→ con/dfn（combatant dfn 来源）
            st["con"] = int(o_def)
            st["dfn"] = int(o_def)
        o_elem = override.get("elem_res")
        if isinstance(o_elem, Mapping):
            out["elem_res"] = dict(o_elem)
        o_wk = override.get("weakness")
        if isinstance(o_wk, Mapping):
            out["weakness"] = dict(o_wk)
    out["stats"] = st
    # 覆盖怪物名显示（面板名）
    oname = str(override.get("name") or "") if isinstance(override, Mapping) else ""
    if oname:
        out["name"] = f"训练木桩·{oname}"
    return out


def _overlay_from_enemy(entry: Mapping[str, Any]) -> Dict[str, Any]:
    """普通怪 entry → dummy_override 面板（def_base/elem_res/weakness/name）。"""
    ov: Dict[str, Any] = {"name": str(entry.get("name") or entry.get("id") or "")}
    st = entry.get("stats") or {}
    if isinstance(st, Mapping):
        con = st.get("con", st.get("dfn", 0))
        if isinstance(con, (int, float)):
            ov["def_base"] = int(con)
    for k in ("elem_res", "weakness"):
        v = entry.get(k)
        if isinstance(v, Mapping):
            ov[k] = dict(v)
    return ov


# ---------------------------------------------------------------------------
# 指令 handler
# ---------------------------------------------------------------------------

def cmd_dummy(parsed: Any, ctx: MutableMapping[str, Any]) -> Any:
    """/木桩 [档位]：列表或进入训练战（async 启动 → 返回 dict）。"""
    p = ctx.get("player")
    if p is None or not ctx.get("registered", False):
        return tpl_of(ctx, "dummy_register_gate")
    args = list(getattr(parsed, "args", None) or [])
    dummies = _dummy_entries(ctx)
    if not dummies:
        return tpl_of(ctx, "dummy_list_empty")
    if not args:
        lines = [tpl_of(ctx, "dummy_list_header")]
        for i, de in enumerate(dummies, 1):
            lines.append(tpl_of(ctx, "dummy_list_row", {
                "idx": i, "name": str(de.get("name") or de.get("id") or "?"),
                "hp": _display_hp(de), "dfn": _display_dfn(de)}))
        lines.append(tpl_of(ctx, "dummy_list_tail"))
        return "\n".join(lines)
    ref = str(args[0])
    # 序号直接进；名字 → 木桩名或普通怪名（普通怪名 → 先建覆盖再进默认木桩）
    if not ref.isdigit():
        e = _find_enemy(ctx, ref)
        if e is not None and not _is_dummy(e):
            _set_override(ctx, _overlay_from_enemy(e))
            ref = ""  # 默认木桩 + 覆盖
    return launch_dummy_battle(ctx, ref or None)


def cmd_adjust_dummy(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/调整木桩 [怪物名]：覆盖面板（无参=重置）。"""
    p = ctx.get("player")
    if p is None or not ctx.get("registered", False):
        return tpl_of(ctx, "dummy_register_gate")
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        _set_override(ctx, None)
        return tpl_of(ctx, "dummy_adjust_reset")
    name = str(args[0])
    e = _find_enemy(ctx, name)
    if e is None:
        return tpl_of(ctx, "dummy_adjust_missing", {"name": name})
    _set_override(ctx, _overlay_from_enemy(e))
    return tpl_of(ctx, "dummy_adjust_ok",
                  {"name": str(e.get("name") or e.get("id") or "")})


def _set_override(ctx: MutableMapping[str, Any], ov: Optional[Mapping[str, Any]]) -> None:
    ps = _player_ps(ctx)
    if ov is None:
        ps.pop(_DUMMY_OVERRIDE_KEY, None)
    else:
        ps[_DUMMY_OVERRIDE_KEY] = dict(ov)


# ---------------------------------------------------------------------------
# 装配
# ---------------------------------------------------------------------------

def register_dummy_commands(
    router: Any,
    *,
    make_context: Optional[Callable[[Any], dict]] = None,
) -> Any:
    """把 /木桩 /调整木桩 注册进 Router。"""
    from qbot_rpg.commands.router import CommandSpec  # noqa: PLC0415

    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError("dummy_commands.register_dummy_commands 需要 make_context")
        return make_context(parsed)

    def _wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        def _h(parsed: Any, *a: Any, **k: Any) -> Any:
            injected = k.get("ctx") if isinstance(k, dict) else None
            if isinstance(injected, MutableMapping):
                return fn(parsed, injected)
            return fn(parsed, _ctx(parsed))
        return _h

    router.register(CommandSpec(DUMMY_CMD, handler=_wrap(cmd_dummy)))
    router.register(CommandSpec(ADJUST_DUMMY_CMD, handler=_wrap(cmd_adjust_dummy)))
    return router
