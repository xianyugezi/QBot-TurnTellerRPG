"""实机 PvE 战斗发起链路（battle_launch.py · G3 2026-09-02）。

契约：docs/指令清单_全量.md L35「/锁定 <序号> 锁定目标怪物进入战斗」；
框架设计文档 L1279 同口径（白名单已登记未接线 → 本模块接线）。

提供：
  - async launch_pve_battle(...)：当前地图活动怪物 → BattleEngine 装配 →
    to_snapshot → session_mgr.acquire(qid, "battle", payload) → 返回
    {ok, message, battle_engine}
  - make_start_battle_hook(...)：ctx["start_battle"] 可调用闭包
    （对齐 investigate_commands launch_hunt_battle 消费形态）
  - register_battle_launch_commands(router, make_context)：/锁定 /锁定怪物
    CommandSpec 注册（async handler，白名单 whitelisted=True）

铁律：零 NoneBot import；模板文案走 core/templates/battle_tpl.py（key 注册）；
零定时器/零睡眠；异常兜底不崩（返回友好提示）。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Mapping, Optional

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.combo import ComboEngine

_LOGGER = logging.getLogger(__name__)

# 指令名
LOCK_CMD = "锁定"
LOCK_MONSTER_CMD = "锁定怪物"

# 模板 key（注册到 core/templates/battle_tpl.py，见文件底部 key 注册表）
_TPL_LOCK_OK = "battle_lock_ok"
_TPL_NO_MONSTER = "battle_lock_no_monster"
_TPL_ALREADY_IN_BATTLE = "battle_lock_already_in_battle"
_TPL_HAS_OTHER_SESSION = "battle_lock_has_other_session"
_TPL_NO_MAP = "battle_lock_no_map"


# ---------------------------------------------------------------------------
# 引擎装配（对齐 scripts/verify_veinborn_smoke.py 金标准：绕 registry Def 坑）
# ---------------------------------------------------------------------------

def _battle_defs(registry: Any):
    """registry.modules_raw → (all_defs raw dict 表, ComboEngine 自定 resolver)。

    返回 (all_defs, chains_map, combo_engine)。registry 为 content Registry
    （build_pack/load_pack 产物）；modules_raw 只读。
    """
    raw = getattr(registry, "modules_raw", None)
    if not isinstance(raw, Mapping):
        return {}, {}, None
    skills_map = {s["id"]: s for s in raw.get("skills", []) if isinstance(s, Mapping)}
    actions_map = {a["id"]: a for a in raw.get("action", []) if isinstance(a, Mapping)}
    chains_map = {c["id"]: c for c in raw.get("skill_chains", []) if isinstance(c, Mapping)}
    all_defs: Dict[str, Any] = {**skills_map, **actions_map}

    def _resolver(id_: str, kind: str) -> Any:
        if kind == "skill_chain":
            return chains_map.get(id_)
        return all_defs.get(id_)

    ce = ComboEngine(defs={**all_defs, **chains_map}, resolver=_resolver)
    return all_defs, chains_map, ce


# ---------------------------------------------------------------------------
# combatant 构造
# ---------------------------------------------------------------------------

def _enemy_combatant(enemy_entry: Mapping[str, Any]) -> dict:
    """enemies.json 条目 → BattleEngine 敌方 combatant（stats 映射）。

    对齐 scripts/e2e_m6_smoke._enemy_combatant：hp/mp/str/int/agi/spr/luk/con/foc
    透传；引擎 _DEFAULT_STATS 合并补齐缺省键。
    """
    st = enemy_entry.get("stats") or {}
    return {
        "hp": int(st.get("hp", 100)),
        "max_hp": int(st.get("hp", 100)),
        "mp": int(st.get("mp", 0)),
        "str": int(st.get("str", 10)),
        "int": int(st.get("int", 10)),
        "agi": int(st.get("agi", 10)),
        "spr": int(st.get("spr", 10)),
        "lck": int(st.get("luk", st.get("lck", 10))),
        "con": int(st.get("con", 10)),
        "foc": int(st.get("foc", 10)),
        "name": str(enemy_entry.get("name") or enemy_entry.get("id") or "怪物"),
    }


def _player_combatant(ctx: Mapping[str, Any]) -> dict:
    """ctx 玩家档案 → combatant（对齐 core/pvp._combatant_of 鸭子读法）。"""
    from qbot_rpg.core.pvp import _combatant_of  # noqa: PLC0415

    player = ctx.get("player")
    if player is None:
        return {}
    return _combatant_of(player)


# ---------------------------------------------------------------------------
# 地图活动怪解析
# ---------------------------------------------------------------------------

def _current_map_monsters(ctx: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """当前地图活动怪列表（ctx.location + ctx.maps）。空 → []。"""
    loc = str(ctx.get("location") or "")
    maps = ctx.get("maps")
    rows: List[Mapping[str, Any]] = []
    if isinstance(maps, list):
        for m in maps:
            if not isinstance(m, Mapping):
                continue
            if str(m.get("id") or "") == loc or str(m.get("name") or "") == loc:
                ms = m.get("monsters")
                if isinstance(ms, list):
                    rows = [x for x in ms if isinstance(x, Mapping)]
                break
    elif isinstance(maps, Mapping):
        m = maps.get(loc) or maps.get(str(ctx.get("location_name") or ""))
        if isinstance(m, Mapping):
            ms = m.get("monsters")
            if isinstance(ms, list):
                rows = [x for x in ms if isinstance(x, Mapping)]
    return rows


def _resolve_monster_ref(
    ctx: Mapping[str, Any], monster_ref: Any
) -> Optional[Mapping[str, Any]]:
    """怪物引用解析：None/空 → 第一只；数字 → 序号（1 基）；名字/id → 匹配。"""
    rows = _current_map_monsters(ctx)
    if not rows:
        return None
    if monster_ref is None or str(monster_ref) == "":
        return rows[0]
    s = str(monster_ref)
    if s.isdigit():
        idx = int(s)
        if 1 <= idx <= len(rows):
            return rows[idx - 1]
        return None
    for r in rows:
        if str(r.get("enemy") or "") == s or str(r.get("name") or "") == s:
            return r
    return None


def _enemy_entry_of(ctx: Mapping[str, Any], row: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """怪物行 → enemies.json 条目（ctx.enemies 表）。"""
    enemies = ctx.get("enemies")
    eid = str(row.get("enemy") or "")
    if isinstance(enemies, Mapping):
        d = enemies.get(eid)
        if isinstance(d, Mapping):
            return d
        # Def 对象 → raw
        raw = getattr(d, "raw", None)
        if isinstance(raw, Mapping):
            return raw
    elif isinstance(enemies, list):
        for e in enemies:
            if isinstance(e, Mapping) and str(e.get("id") or "") == eid:
                return e
    return None


# ---------------------------------------------------------------------------
# 模板（battle_tpl 取词，key 缺省友好文案）
# ---------------------------------------------------------------------------

def _tpl(ctx: Mapping[str, Any], key: str, default: str) -> str:
    tpl_of = ctx.get("tpl_of")
    if callable(tpl_of):
        try:
            return str(tpl_of(ctx, key) or default)
        except Exception:  # noqa: BLE001 - 模板缺 key 兜底
            return default
    return default


# ---------------------------------------------------------------------------
# 主入口：发起 PvE 战斗
# ---------------------------------------------------------------------------

async def launch_pve_battle(
    ctx: Mapping[str, Any],
    monster_ref: Any = None,
) -> Dict[str, Any]:
    """发起一场 PvE 战斗（真实装配 + session 落档）。

    入参 ctx: 玩家上下文（需 player/location/maps/enemies/session_mgr/
    skills 等装配键——由 make_context 产物）；monster_ref: 怪物引用。
    出参 {ok, message, battle_engine}。
    """
    # 1. 会话互斥
    sm = ctx.get("session_mgr")
    if sm is None:
        return {"ok": False, "message": "会话管理器不可用", "battle_engine": None}
    try:
        from qbot_rpg.world.session import SessionConflictError  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        SessionConflictError = Exception  # type: ignore[assignment,misc]
    qid = str(ctx.get("qid") or ctx.get("qq_id") or "")
    active = getattr(sm, "get_active", None)
    cur = None
    if callable(active):
        try:
            out = active(qid)
            import inspect  # noqa: PLC0415

            cur = await out if inspect.isawaitable(out) else out
        except Exception:  # noqa: BLE001
            cur = None
    if cur is not None:
        stype = str(getattr(cur, "session_type", "") or (cur.get("session_type") if isinstance(cur, Mapping) else ""))
        if "battle" in stype:
            return {"ok": False,
                    "message": _tpl(ctx, _TPL_ALREADY_IN_BATTLE, "❌ 你已经在战斗中了"),
                    "battle_engine": None}
        return {"ok": False,
                "message": _tpl(ctx, _TPL_HAS_OTHER_SESSION, "❌ 你还有未结束的会话，请先完成"),
                "battle_engine": None}

    # 2. 解析怪物
    loc = str(ctx.get("location") or "")
    if not loc:
        return {"ok": False, "message": _tpl(ctx, _TPL_NO_MAP, "❌ 当前不在任何地图"), "battle_engine": None}
    row = _resolve_monster_ref(ctx, monster_ref)
    if row is None:
        return {"ok": False,
                "message": _tpl(ctx, _TPL_NO_MONSTER, "❌ 当前地图没有可战斗的怪物"),
                "battle_engine": None}
    enemy_entry = _enemy_entry_of(ctx, row)
    if enemy_entry is None:
        return {"ok": False,
                "message": _tpl(ctx, _TPL_NO_MONSTER, f"❌ 怪物 {row.get('enemy')} 不存在"),
                "battle_engine": None}

    # 3. 装配引擎
    registry = ctx.get("registry")
    all_defs, _chains_map, ce = _battle_defs(registry) if registry is not None else ({}, {}, None)
    p_comb = _player_combatant(ctx)
    if not p_comb:
        return {"ok": False, "message": "❌ 玩家状态不可用", "battle_engine": None}
    e_comb = _enemy_combatant(enemy_entry)
    try:
        eng = BattleEngine(
            defs=all_defs, registry=registry, combo_engine=ce, enemy_def=enemy_entry,
        )
        eng.start(p_comb, e_comb, random_seed=None)
    except Exception as exc:  # noqa: BLE001 - 开战失败不崩
        _LOGGER.warning("battle launch failed: %s", exc)
        return {"ok": False, "message": f"❌ 开战失败：{exc}", "battle_engine": None}

    # 4. 快照落 session
    try:
        snap = eng.to_snapshot()
        await sm.acquire(qid, "battle", payload=snap)
    except SessionConflictError:
        return {"ok": False,
                "message": _tpl(ctx, _TPL_ALREADY_IN_BATTLE, "❌ 你已经在战斗中了"),
                "battle_engine": None}
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("battle session acquire failed: %s", exc)
        return {"ok": False, "message": f"❌ 开战失败（存档）：{exc}", "battle_engine": None}

    e_name = str(e_comb.get("name") or "怪物")
    e_hp = int(e_comb.get("max_hp", 0))
    msg = f"⚔️ 与 {e_name}（HP {e_hp}）的战斗开始！发 /攻击 出战。"
    return {"ok": True, "message": msg, "battle_engine": eng}


def make_start_battle_hook(
    ctx_factory: Optional[Callable[[Any], Mapping[str, Any]]] = None,
) -> Callable[..., Any]:
    """ctx["start_battle"] hook 工厂（对齐 investigate launch_hunt_battle 消费）。

    返回 (ctx, boss_ref) -> dict 闭包；boss_ref 可为怪物 id/名/序号。
    供 investigate 的 hunt 结果接真实 BOSS 战；独立调用用 /锁定。
    """

    def _hook(ctx: Mapping[str, Any], boss_ref: Any = None) -> Dict[str, Any]:
        import asyncio  # noqa: PLC0415

        try:
            return asyncio.get_event_loop().run_until_complete(
                launch_pve_battle(ctx, boss_ref))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("start_battle hook failed: %s", exc)
            return {"ok": False, "message": f"❌ 开战失败：{exc}", "battle_engine": None}

    return _hook


# ---------------------------------------------------------------------------
# 指令 handler（/锁定 /锁定怪物）
# ---------------------------------------------------------------------------

def _make_lock_handler(make_context: Optional[Callable[[Any], Mapping[str, Any]]]) -> Callable:
    """/锁定 handler：无参 → 当前地图第一只活动怪；参数 → 序号/名字。"""

    def _handler(parsed: Any, **kw: Any) -> Any:
        ctx = kw.get("ctx")
        if ctx is None and make_context is not None:
            ctx = make_context(parsed)
        if ctx is None:
            return "❌ 上下文不可用"
        args = list(getattr(parsed, "args", None) or [])
        ref: Any = args[0] if args else None
        return launch_pve_battle(ctx, ref)

    return _handler


def register_battle_launch_commands(
    router: Any,
    *,
    make_context: Optional[Callable[[Any], Mapping[str, Any]]] = None,
) -> Any:
    """把 /锁定 /锁定怪物 注册进 Router（白名单 whitelisted=True）。"""
    from qbot_rpg.commands.router import CommandSpec  # noqa: PLC0415

    handler = _make_lock_handler(make_context)
    for name in (LOCK_CMD, LOCK_MONSTER_CMD):
        spec = CommandSpec(name, handler=handler, whitelisted=True)
        if name not in router.names():
            router.register(spec)
    return router
