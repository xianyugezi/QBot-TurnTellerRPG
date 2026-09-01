"""PVP 玩家互斗引擎（qbot_rpg/core/pvp.py · M11 批3 路3A）。

依据：
  - docs/细化/细化_4e_PVP决斗契约.md（CMD-05/06 复用指令 + MIR 战斗复用 + SET 结算
    + FR 防刷 + CFG 配置；决斗流程四态已删，仅保留 /锁定玩家 /攻击玩家 双原语）
  - 定稿 §3.19 L345-354（PVP 概念 = 其他玩家 = 野怪实例，复用 1v1 战斗引擎）
  - docs/m11_启动包.md §2.3（玩家互斗非镜像 + 偷袭语义 + 战斗复用）

【工程补白 · 显式标注】
  B-1  PVP = 玩家互斗非镜像（用户 2026-09-01 纠正）：/锁定玩家 锁定真实玩家档案，
       /攻击玩家 直接攻击锁定玩家——目标 = 活人玩家档案进 Battle 引擎敌方侧。
  B-2  偷袭：目标玩家战斗会话（session_mgr.get_active(target_qid) 且 session_type==
       "battle"）时仍可锁定并攻击——复用「战斗期间怪物被其他人杀死→提示怪物丢失」
       先例（定稿 L100）；PVP 开独立会话，原战斗丢失提示由既有机制触发。
  B-3  settings.pvp 段读取三态容错（对齐 fishing_cfg）：段缺失/非 Mapping → 全默认
       不报错；逐键类型容错（非法回落默认）。
  B-4  技能解析双形态：ctx["skills"] 映射 / ctx["resolve_skill"] callable；皆缺 →
       回落普攻（normal）。
  B-5  非回合制防守方离线 = 一直防御：对防守方注入 guard 行动，避免离线玩家被白打
       时仍自动反击（对齐定稿 L352「防守方不操作则一直防御」）。
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional

# ---------------------------------------------------------------------------
# settings.pvp 段配置（B-3：三态容错，对齐 fishing_cfg）
# ---------------------------------------------------------------------------
PVP_SETTINGS_KEYS: tuple = (
    "enabled", "mode", "level_gate", "kill_penalty",
    "loot", "daily_reward_limit", "pair_daily_limit", "exp_on_win",
)
PVP_SETTINGS_DEFAULTS: dict = {
    "enabled": False,
    "mode": "turn_based",       # turn_based 回合制 / free 非回合制
    "level_gate": 10,           # 等级门槛
    "kill_penalty": "none",     # 击杀惩罚 none / respawn 回城
    "loot": None,               # 战斗掉落（无/货币/物品；None=无）
    "daily_reward_limit": 5,    # 每日奖励上限（FR-R1）
    "pair_daily_limit": 3,      # 同对每日上限（FR-R2）
    "exp_on_win": False,        # 胜方是否获得经验
}


def pvp_cfg(ctx_or_settings: Any) -> dict:
    """settings.pvp 段读取（三态容错：全量 dict 含 pvp 键 / 段本身 / ctx 含 settings）。

    入参 ctx_or_settings: ctx dict（含 settings 键）或 settings dict 或 None。
    出参 dict: 9 键配置（逐键类型容错，非法回落默认）。
    """
    settings: Any = ctx_or_settings
    if isinstance(settings, Mapping) and "settings" in settings:
        settings = settings.get("settings")
    segment: Any = None
    if isinstance(settings, Mapping):
        segment = settings.get("pvp")
    cfg = dict(PVP_SETTINGS_DEFAULTS)
    if isinstance(segment, Mapping):
        for k in PVP_SETTINGS_KEYS:
            v = segment.get(k)
            if v is None:
                continue
            cfg[k] = v
    return cfg


# ---------------------------------------------------------------------------
# 目标玩家档案读取
# ---------------------------------------------------------------------------
def _player_by_qid(ctx: Mapping[str, Any], qid: str) -> Optional[Mapping[str, Any]]:
    """目标玩家档案（ctx["players"] 映射 / ctx["get_player"] callable；缺省 None）。"""
    players = ctx.get("players")
    if isinstance(players, Mapping):
        p = players.get(qid)
        if isinstance(p, Mapping):
            return p
    getter = ctx.get("get_player")
    if callable(getter):
        try:
            p = getter(qid)
            if isinstance(p, Mapping):
                return p
        except Exception:
            return None
    return None


def _combatant_of(player: Mapping[str, Any]) -> dict:
    """玩家档案 → BattleEngine combatant 映射（属性三层合成面板 + 装备摘要）。

    M11 批4 A3 P1-6 修复：鸭子兼容——生产 ctx["player"] 是 frozen dataclass
    Player（data/player.py L22-53，无 .get），测试/内嵌是 dict；统一
    _pf(player, key, default) 读取（Mapping.get 或 getattr）。属性合成 = 对齐
    player_attributes.calc_final_attr 语义（base×(1+pct)+temp_flat+cond 近似），
    缺省回落 _DEFAULT_STATS 系默认。
    """

    def _pf(p: Any, key: str, default: Any = None) -> Any:
        if isinstance(p, Mapping):
            return p.get(key, default)
        return getattr(p, key, default)

    name = str(_pf(player, "name") or _pf(player, "qid") or "玩家")
    raw_attrs = _pf(player, "attributes")
    attrs: Mapping[str, Any] = raw_attrs if isinstance(raw_attrs, Mapping) else {}
    level = int(_pf(player, "level") or 1)

    def _attr(key: str, default: int = 10) -> int:
        base = attrs.get("base") if isinstance(attrs.get("base"), Mapping) else {}
        bonus = attrs.get("bonus") if isinstance(attrs.get("bonus"), Mapping) else {}
        temp = attrs.get("temp") if isinstance(attrs.get("temp"), Mapping) else {}
        b = base.get(key, default) if isinstance(base, Mapping) else default
        bf = bonus.get("flat", 0) if isinstance(bonus, Mapping) else 0
        bp = bonus.get("pct", 0) if isinstance(bonus, Mapping) else 0
        tf = temp.get("flat", 0) if isinstance(temp, Mapping) else 0
        tp = temp.get("pct", 0) if isinstance(temp, Mapping) else 0
        v = (b + bf) * (1 + float(bp or 0)) + tf * (1 + float(tp or 0))
        return max(1, int(v))

    return {
        "id": str(_pf(player, "qid") or name),
        "name": name,
        "level": level,
        "hp": int(_pf(player, "hp") or 100),
        "max_hp": int(_pf(player, "max_hp") or 100),
        "mp": int(_pf(player, "mp") or 50),
        "max_mp": int(_pf(player, "max_mp") or 50),
        # M11 批4 A3 P2-1 修复：对齐 battle._DEFAULT_STATS 键全集（battle.py L184-189）——
        # 引擎伤害管线实读 dfn/foc/con/mag（L186/L1323-1405），原 def_ 是无效字段
        "atk": _attr("atk"),
        "dfn": _attr("def"),
        "mag": _attr("mag", 30),
        "spd": _attr("spd"),
        "foc": _attr("foc"),
        "con": _attr("con"),
        "int": _attr("int"),
        "lck": _attr("lck"),
    }


def _equipment_summary(player: Mapping[str, Any]) -> str:
    """装备摘要（槽位：物品名；空 → 无）。"""
    eq = player.get("equipment")
    if not isinstance(eq, Mapping) or not eq:
        return "无"
    parts = []
    for slot, item in eq.items():
        if isinstance(item, Mapping):
            nm = item.get("name") or item.get("id") or str(slot)
        else:
            nm = str(item)
        parts.append(f"{slot}:{nm}")
    return " ".join(parts) if parts else "无"


def _target_status(player: Mapping[str, Any]) -> dict:
    """目标状态卡（/锁定玩家 展示：等级/职业/血量/装备摘要）。"""
    return {
        "name": str(player.get("name") or player.get("qid") or "玩家"),
        "level": int(player.get("level") or 1),
        "job": str(player.get("job_id") or player.get("job") or "无"),
        "hp": int(player.get("hp") or 0),
        "max_hp": int(player.get("max_hp") or 0),
        "equipment_summary": _equipment_summary(player),
    }

# ---------------------------------------------------------------------------
# 会话互斥（偷袭判定）
# ---------------------------------------------------------------------------
def _active_session_type(ctx: Mapping[str, Any], qid: str) -> Optional[str]:
    """目标当前会话类型（无会话 → None）。

    M11 批4 A3 P0-4 修复：主通道 = 装配层注入的 ctx["active_sessions"] 映射
    （同步可读；SessionView 字段是 session_type 非 type——session.py L46）。
    session_mgr.get_active 为 async（session.py L139），引擎同步路径不可直接调
    （协程未 await 恒空 + 泄漏），由装配层把已解析的会话表注入 ctx。
    """
    sessions = ctx.get("active_sessions")
    if isinstance(sessions, Mapping):
        s = sessions.get(qid)
        if isinstance(s, Mapping):
            stype = s.get("session_type") or s.get("type") or ""
            return str(stype)
    # 异步兜底：session_mgr 由装配层在注入前 await 解析（本函数同步不 await）
    mgr = ctx.get("session_mgr")
    if mgr is not None:
        getter = getattr(mgr, "get_active", None)
        if callable(getter):
            try:
                sv = getter(qid)
                if sv is not None:
                    return str(getattr(sv, "session_type", "") or "")
            except Exception:
                return None
    return None


def sneak_attack_allowed(ctx: Mapping[str, Any], target_qid: str) -> bool:
    """偷袭判定（B-2）：目标战斗会话中 → True（可偷袭）。"""
    return _active_session_type(ctx, target_qid) == "battle"


# ---------------------------------------------------------------------------
# /锁定玩家
# ---------------------------------------------------------------------------
def pvp_lock(ctx: Mapping[str, Any], target_qid: str) -> dict:
    """锁定目标玩家（/锁定玩家 <QQ号>）。

    出参 dict: {ok, message, reason?, target?}——target 含 name/level/job/hp/max_hp/
    equipment_summary（/锁定玩家 展示用）。
    守卫链：目标非空 → 防锁自己 → PVP 开关 → 等级门槛 → 目标存在 → 目标在线。
    """
    qid = str(target_qid or "").strip()
    if not qid:
        return {"ok": False, "message": "请指定目标：/锁定玩家 <QQ号>"}
    me = ctx.get("qid")
    if me and str(me) == qid:
        return {"ok": False, "message": "不能锁定自己"}
    cfg = pvp_cfg(ctx)
    if not cfg["enabled"]:
        return {"ok": False, "message": "PVP 功能未开启"}
    if int(cfg["level_gate"] or 0) > 0:
        my_level = int(ctx.get("level") or 1)
        if my_level < int(cfg["level_gate"]):
            return {"ok": False, "message": f"等级不足：PVP 需 {cfg['level_gate']} 级"}
    target = _player_by_qid(ctx, qid)
    if target is None:
        return {"ok": False, "message": "目标玩家不存在"}
    # M11 批4 A3 P1-4 修复：FR-R3 双向等级门槛——目标也须达标（读目标档案等级）；
    # 目标在线校验（ctx["online_qids"] 集合，装配层注入在线层）
    if int(cfg["level_gate"] or 0) > 0:
        t_level = int(target.get("level") or 1)
        if t_level < int(cfg["level_gate"]):
            return {"ok": False, "message": f"目标等级不足：PVP 需 {cfg['level_gate']} 级"}
    online = ctx.get("online_qids")
    if isinstance(online, (set, list, tuple)) and qid not in online:
        return {"ok": False, "message": "目标不在线"}
    return {
        "ok": True,
        "message": "已锁定玩家",
        "target": _target_status(target),
    }


# ---------------------------------------------------------------------------
# /攻击玩家（战斗复用 + 偷袭 + 结算）
# ---------------------------------------------------------------------------
def pvp_attack(ctx: MutableMapping[str, Any], skill_id: str) -> dict:
    """攻击锁定玩家（/攻击玩家 <技能序号>）。

    出参 dict: {ok, message, result?}——result 含 name/damage/hp/max_hp/ended 等
    （回合结算或整场结算摘要）。
    流程：锁定目标解析 → 偷袭判定（战斗中可偷袭）→ 双方 combatant →
    BattleEngine.start(battle_type="pvp") → 回合制轮流 / 非回合制防守方一直防御 →
    pvp_settle（胜负结算 + 防刷）。
    """
    target_qid = ctx.get("pvp_target")
    if not isinstance(target_qid, str) or not target_qid:
        return {"ok": False, "message": "尚未锁定玩家：先 /锁定玩家 <QQ号>"}
    target = _player_by_qid(ctx, target_qid)
    if target is None:
        return {"ok": False, "message": "目标玩家不存在"}
    cfg = pvp_cfg(ctx)
    if not cfg["enabled"]:
        return {"ok": False, "message": "PVP 功能未开启"}

    # 偷袭判定（B-2）：目标战斗中仍可攻击
    sneak = sneak_attack_allowed(ctx, target_qid)

    try:
        from qbot_rpg.core.battle import BattleEngine
    except ImportError:
        return {"ok": False, "message": "战斗引擎未接线"}

    me = ctx.get("qid")
    my_player = ctx.get("player") if isinstance(ctx.get("player"), Mapping) else None
    attacker_comb = _combatant_of(my_player) if my_player else {"id": str(me or "me"), "name": "我"}
    defender_comb = _combatant_of(target)

    try:
        battle = BattleEngine()
        battle.start(attacker_comb, defender_comb, random_seed=ctx.get("rng"),
                     battle_type="pvp", config=ctx.get("battle_config"))
    except Exception:
        return {"ok": False, "message": "开战失败"}

    # 行动：技能解析（B-4 双形态兜底）
    action = _resolve_skill_action(ctx, skill_id, attacker_comb)

    # 回合制：单回合结算；非回合制：防守方一直防御（B-5），连续输出一轮
    # M11 批4 A3 P0-3 修复：行动字典键为 type（battle.py L1064 读 action_dict["type"]），
    # 原 {"action":"guard"} 键错恒「回合结算失败」；且不先于 player_act 调用
    # （player_act 内部会再触发一次防守方行动，避免双行动）
    mode = cfg.get("mode", "turn_based")
    try:
        if mode == "free":
            # 非回合制：进攻方连续输出，防守方本回合防御（在 player_act 之后注入）
            r = battle.player_act(action, params=ctx.get("params"))
            battle.enemy_act({"type": "guard"})
        else:
            r = battle.player_act(action, params=ctx.get("params"))
    except Exception:
        return {"ok": False, "message": "回合结算失败"}

    return pvp_settle(ctx, battle, r, target, sneak=sneak)


def _resolve_skill_action(ctx: Mapping[str, Any], skill_id: str,
                          combatant: dict) -> Any:
    """技能序号 → BattleEngine action（skills 映射 / resolve_skill；缺省普攻）。"""
    if not isinstance(skill_id, str) or not skill_id:
        return "normal"
    skills = ctx.get("skills")
    if isinstance(skills, Mapping):
        if skill_id in skills:
            return {"action": "skill", "skill_id": skill_id, "target": "enemy"}
        # 数字序号 → 配置序
        try:
            idx = int(skill_id)
            if 1 <= idx <= len(skills):
                sid = list(skills.keys())[idx - 1]
                return {"action": "skill", "skill_id": sid, "target": "enemy"}
        except (TypeError, ValueError):
            pass
    resolver = ctx.get("resolve_skill")
    if callable(resolver):
        try:
            sid = resolver(skill_id)
            if isinstance(sid, str) and sid:
                return {"action": "skill", "skill_id": sid, "target": "enemy"}
        except Exception:
            pass
    return "normal"


def pvp_settle(ctx: MutableMapping[str, Any], battle: Any, turn_result: Any,
               target: Mapping[str, Any], *, sneak: bool = False) -> dict:
    """胜负结算（SET-R01 + FR 防刷）。

    出参 dict: {ok, message, result?}——result 含 name/damage/hp/max_hp/ended/
    winner（胜方）/sneak（是否偷袭）。
    """
    # FR-R1 每日奖励上限 / FR-R2 同对日限：达上限 → 仍正常结算判胜负，仅掉落置 0
    # （M11 批4 A3 P1-1/P1-2 修复：原实现直接伪造「防守方胜」违约 TC-17；
    #  超限只是奖励封顶，胜负不变）
    cfg = pvp_cfg(ctx)
    daily_raw = ctx.get("pvp_daily")
    daily: MutableMapping[str, Any] = daily_raw if isinstance(daily_raw, MutableMapping) else {}
    reward_blocked = int(daily.get("rewards", 0) or 0) >= int(cfg["daily_reward_limit"] or 5)

    name = str(target.get("name") or "目标")
    try:
        state = battle.battle_state()
    except Exception:
        state = {}
    hp = 0
    max_hp = 1
    ended = False
    winner = None
    if isinstance(state, Mapping) and state:
        enemy_raw = state.get("enemy")
        enemy: Mapping[str, Any] = enemy_raw if isinstance(enemy_raw, Mapping) else {}
        hp = int(enemy.get("hp", 0) or 0)
        max_hp = int(enemy.get("max_hp", 1) or 1)
        # M11 批4 A3 P1-7 修复：终态判定对齐 battle 真实键——battle_state 深拷贝
        # _snap 无 "ended" 键，status 值为 win/lose/draw（battle.py L742-783）；
        # 敌方 hp<=0 = 进攻方胜；进攻方 hp<=0 = 防守方胜（双向，非单向）。
        status = str(state.get("status") or state.get("phase") or "")
        player_raw = state.get("player")
        player_st: Mapping[str, Any] = player_raw if isinstance(player_raw, Mapping) else {}
        player_hp = int(player_st.get("hp", 0) or 0)
        ended = str(status) in ("win", "lose", "draw", "ended", "settle", "lost") \
            or hp <= 0 or player_hp <= 0
        if ended:
            if hp <= 0:
                winner = "player"
            elif player_hp <= 0:
                winner = "defender"
            else:
                if str(status) == "draw":
                    winner = "draw"
                elif str(status) == "win":
                    winner = "player"
                else:
                    winner = "defender"
    # M11 批4 A3 P1-7 修复：伤害提取——TurnReport 无 damage 字段（battle.py L239-249），
    # 真实伤害在 turn_result.outcomes[].final_damage 聚合
    damage = 0
    if turn_result is not None:
        if isinstance(turn_result, Mapping):
            damage = int(turn_result.get("damage") or 0)
        else:
            damage = int(getattr(turn_result, "damage", 0) or 0)
        if damage == 0:
            if isinstance(turn_result, Mapping):
                outcomes = turn_result.get("outcomes")
            else:
                outcomes = getattr(turn_result, "outcomes", None)
            if isinstance(outcomes, (list, tuple)):
                damage = sum(
                    int(o.get("final_damage", 0) or 0)
                    for o in outcomes if isinstance(o, Mapping)
                )

    # 击杀惩罚（FR：respawn 回城钩子）+ 胜方掉落（FR-R4 仅胜方；loot 配置）
    # M11 批4 A3 P1-1 修复：掉落只给胜方（winner=="player" 时），超限 reward_blocked
    # → 掉落 0；配对计数 + 幂等 tx_id（FR-R2/R5）。
    if ended and hp <= 0:
        penalty = cfg.get("kill_penalty", "none")
        if penalty == "respawn":
            try:
                hook = ctx.get("respawn_hook")
                if callable(hook):
                    hook(ctx, str(target.get("qid") or ""))
            except Exception:
                pass
        loot = cfg.get("loot")
        if loot and isinstance(ctx, MutableMapping) and winner == "player" and not reward_blocked:
            try:
                from qbot_rpg.core.reward import dispatch_reward

                tx_key = f"pvp:{ctx.get('qid')}:{ctx.get('today', '')}:{daily.get('seq', 0)}"
                ctx["tx_id"] = tx_key
                ctx["ledger"] = ctx.get("ledger")
                dispatch_reward(loot, ctx)
                # 每日奖励计数 +1 + 同对计数（FR-R1/R2 落档由装配层 ps 保存）
                daily["rewards"] = int(daily.get("rewards", 0) or 0) + 1
                daily["seq"] = int(daily.get("seq", 0) or 0) + 1
                pairs_raw = daily.get("pairs")
                pairs: MutableMapping[str, Any]
                if isinstance(pairs_raw, MutableMapping):
                    pairs = pairs_raw
                else:
                    pairs = {}
                pair_key = f"{ctx.get('qid')}:{target.get('qid')}"
                pairs[pair_key] = int(pairs.get(pair_key, 0) or 0) + 1
                if not isinstance(pairs_raw, MutableMapping):
                    daily["pairs"] = pairs
            except Exception:
                pass

    result = {
        "name": name, "damage": damage, "hp": max(0, hp), "max_hp": max_hp,
        "ended": bool(ended), "winner": winner, "sneak": bool(sneak),
        "reward_blocked": bool(reward_blocked),
    }
    return {"ok": True, "message": "攻击结算", "result": result}
