"""BOSS 换区追击装配（M3 批次6·路Q：M12 换区触发装配 + M13 追击行走与错失窗口）。

依据：
  - 细化_2a2_换区追击流程.md §1（换区触发 R1-R8：残血阈值百分比口径 R1/R2 / 击杀优先 R3 /
    未配置不换区 R4 / 必发流程行为 R6 / 提示语 R7 / 候选区随机选一 R8）+ §2（PV 恢复 R9-R11）
  - 细化_2a2_换区追击流程.md §4（玩家追随时序：走通道 R15 / 路径选择 R16-R17 /
    追错方向 R18 / 追到续战 R19-R21 / 原地等待 R22）+ §5（离开副本重置 R24：BOSS 满状态重打）
  - m3_shared_contract.md §3（zone_change 配置四字段 / 换区规则要点：触发、逃跑行为
    chasing:true 提示「XX 逃向了【候选区】」、候选区固定种子可复现、追击走通道、
    错失窗口、续战）+ §八 2（确定性：抽签/换区去向/追击路径固定种子可复现；随机一律注入 rng）

职责（world 层纯逻辑装配，零 NoneBot import、零 IO、纯函数）：
  chase_trigger        M12 换区触发装配：调 core/dungeon_boss.BossFlow.should_zone_change
                       （boss_flow 未注入 → 按契约 §3.2 本地实现判定，判定链同口径）；
                       triggered 时 pick_chase_target 从 targets 确定性选一
  pick_chase_target    M12 候选区确定性选一（注入 rng 优先；未注入固定种子，同状态同值）
  begin_chase          M13 追击态开启：session chasing:true + 提示「BOSS 逃向了【XX】」
                       （目标区显示名 = maps.name）
  pursue               M13 追击行走与错失窗口：/进入 <方向> 走通道（调 movement.resolve_move）；
                       到达 chase_ctx.target_map → 捕获 {caught: True}；未到达 →
                       {caught: False, missed} —— 连续走错 ≥ 错失上限（默认 3）或
                       走回起始区 → BOSS 回满/离开副本（chase_ctx.miss_count 递增）

【工程补白】（显式标注，不冒充定稿）：
  1. boss_flow 未注入时 _contract_should_zone_change 为契约 §3.2 / 2a2 §1.1 的本地实现，
     判定链与 BossFlow.should_zone_change 完全同口径（R1-R6：enabled/targets 非空/hp
     百分比 ≤ 阈值×100 / timing=phase_changed 需 phase_changed 标志）；注入时以注入实现为准。
  2. pick_chase_target 未注入 rng 时以 targets 稳定摘要（sha256）为固定种子——同候选集
     必同值（跨进程稳定，m3 §八 2）；注入 rng 时优先 rng.choice，无 choice 回退
     rng.random() 索引映射（对齐 ScriptedRng 形态）。
  3. begin_chase 落盘键 = session["chasing"]=True + session["chase_target"]=<目标图 id>
     （契约 §4.2 追击态标志 chasing:true；持久化落库由快照批次接线，本路只改传入 dict）。
  4. 错失窗口两条件（2a2 §4.4 R18 + §5.1 R24 工程解读）：连续走错次数 ≥ miss_limit
     （chase_ctx.miss_limit 可配，默认 3）或走回起始区（chase_ctx.start_map）→ 返回
     boss_reset 信号（BOSS 回满/离开副本由调用方按 R24 执行重置），本路不直改战斗资源。
  5. 走通道失败（死路/隐藏条件未满足/非法方向）不计入 miss_count（2a1b R11 / 2a2 §4.2：
     「此方向没有通道」不消耗行动资源）。
  6. pursue 捕获后可选续战准备：chase_ctx 携带 boss_flow（BossFlow 实例）时调
     on_chase_continue() 取续战标记（resume/hp_keep/pv_half/opening_skill，路O 已测）；
     未携带则只报捕获信号，续战接线由调用方自理（M14 续战）。
  7. pursue 走错分支附 reachable 信息位（map_graph.path_exists BFS，2a1b R5 捷径连通），
     仅信息性提示「当前图是否仍可达目标区」，不驱动错失判定（判定严格按补白 4 两条件）。

铁律：零 NoneBot import（m3 §八 4）；纯函数无 IO；确定性（随机一律注入 rng，m3 §八 2）；
平台无关；每功能可追溯（m3 §八 8）。
"""

from __future__ import annotations

import hashlib
import random
from typing import Any, List, Mapping, Optional, cast

from qbot_rpg.world.movement import resolve_move

__all__ = [
    "MISS_LIMIT_DEFAULT",
    "CHASE_HINT_TEMPLATE",
    "SESSION_CHASING_KEY",
    "SESSION_CHASE_TARGET_KEY",
    "chase_trigger",
    "pick_chase_target",
    "begin_chase",
    "pursue",
    "target_reachable",
]

# -------------------------------------------------------------------------------------
# 常量（工程补白见模块 docstring）
# -------------------------------------------------------------------------------------

#: 错失上限缺省值：连续走错次数 ≥ 3 → BOSS 回满/离开副本（工程补白 4）。
MISS_LIMIT_DEFAULT: int = 3

#: 追击态开启提示模板（契约 §3.2「提示 XX 逃向了【候选区】」，目标区名 = maps.name）。
CHASE_HINT_TEMPLATE: str = "BOSS 逃向了【{name}】"

#: session 追击态标志键（契约 §4.2 chasing:true）。
SESSION_CHASING_KEY: str = "chasing"

#: session 追击目标区键（工程补白 3）。
SESSION_CHASE_TARGET_KEY: str = "chase_target"

#: zone_change.timing 枚举键（对齐 dungeon_boss.ZC_TRIGGER_*）。
ZC_TRIGGER_AFTER_ACTION: str = "after_action"
ZC_TRIGGER_PHASE_CHANGED: str = "phase_changed"


# -------------------------------------------------------------------------------------
# 数据访问助手（兼容 dict / Mapping / 带 get 的 Def 对象）
# -------------------------------------------------------------------------------------


def _cfg_get(cfg: Any, key: str, default: Any = None) -> Any:
    """从 dict / Mapping / BaseDef（.get）等任意带 get 的对象读取配置值。"""
    if cfg is None:
        return default
    if isinstance(cfg, Mapping):
        return cfg.get(key, default)
    getter = getattr(cfg, "get", None)
    if callable(getter):
        return getter(key, default)
    return default


def _hp_pct(enemy_state: Any) -> Optional[float]:
    """从 enemy_state 读取血量百分比（0-100）。

    {hp, max_hp} → hp/max_hp×100；{hp_pct} → 百分比直读（2a2 §1.1 阈值口径统一为百分比）；
    不可解 → None（视为无法判定，不触发换区）。
    """
    if not isinstance(enemy_state, Mapping):
        return None
    hp = enemy_state.get("hp")
    max_hp = enemy_state.get("max_hp")
    if (
        isinstance(hp, (int, float))
        and not isinstance(hp, bool)
        and isinstance(max_hp, (int, float))
        and not isinstance(max_hp, bool)
        and max_hp > 0
    ):
        return hp / max_hp * 100.0
    pct = enemy_state.get("hp_pct")
    if isinstance(pct, (int, float)) and not isinstance(pct, bool):
        return float(pct)
    return None


def _targets_list(cfg: Any) -> List[str]:
    """zone_change.targets 归一 → list[str]（非 list/tuple → 空表 = 永不换区，R4）。"""
    raw = _cfg_get(cfg, "targets")
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(t) for t in raw if str(t)]


# -------------------------------------------------------------------------------------
# M12 触发判定：契约本地实现（boss_flow 未注入时的兜底，判定链同 BossFlow）
# -------------------------------------------------------------------------------------


def _contract_should_zone_change(enemy_state: Any, cfg: Any) -> bool:
    """契约 §3.2 / 2a2 §1.1 换区触发判定本地实现（工程补白 1，判定链同口径 R1-R6）：

      1. cfg 缺失 / enabled=False / targets 空 → 永不换区（R4）
      2. hp=0 → 击杀优先，不进换区（R3）
      3. hp_pct > hp_threshold×100 → 不触发（R1/R2，不残血不换区）
      4. timing=phase_changed 且本结算点无阶段切换 → 不触发（衔接 monster_phases）
      5. 其余 → 触发（条件满足即必换区，无概率博弈，R6）
    """
    if not isinstance(cfg, Mapping):
        return False
    if _cfg_get(cfg, "enabled", True) is False:
        return False
    if not _targets_list(cfg):
        return False  # 候选区缺失/为空 = 永不换区（R4）
    pct = _hp_pct(enemy_state)
    if pct is None:
        return False
    threshold = _cfg_get(cfg, "hp_threshold")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        return False
    threshold = float(threshold)
    if pct <= 0.0:
        return False  # hp=0 击杀优先（R3）
    if pct > threshold * 100.0:
        return False  # 不残血不触发（R1/R2）
    timing = _cfg_get(cfg, "timing", ZC_TRIGGER_AFTER_ACTION)
    if timing == ZC_TRIGGER_PHASE_CHANGED:
        if not isinstance(enemy_state, Mapping) or not enemy_state.get("phase_changed"):
            return False
    return True


# -------------------------------------------------------------------------------------
# M12 候选区确定性选一（R8：targets 随机选一，固定种子可复现）
# -------------------------------------------------------------------------------------


def _stable_seed(targets: List[str]) -> int:
    """targets 稳定摘要 → 固定种子（sha256，跨进程稳定；工程补白 2）。"""
    blob = "\x00".join(sorted(str(t) for t in targets))
    digest = hashlib.sha256(blob.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def pick_chase_target(cfg: Any, rng: Any = None) -> Optional[str]:
    """从 zone_change.targets 确定性选一（2a2 §1.4 R8 / m3 §八 2）。

    - 注入 rng：优先 rng.choice(seq)；无 choice 回退 rng.random() 索引映射
      （对齐 ScriptedRng 形态；求值异常 → 回退固定种子）。
    - 未注入 rng：以 targets 稳定摘要为固定种子（同候选集必同值，跨进程稳定）。
    - 候选区为空 → None（调用方保证触发前 targets 非空，R4）。

    Args:
        cfg: zone_change 配置子段（读 targets）。
        rng: 注入的确定性随机源（.choice / .random 任一即可）。
    """
    targets = _targets_list(cfg)
    if not targets:
        return None
    if rng is not None:
        choice = getattr(rng, "choice", None)
        if callable(choice):
            try:
                v = choice(list(targets))
                if v is not None:
                    return str(v)
            except Exception:
                pass
        rand = getattr(rng, "random", None)
        if callable(rand):
            try:
                r = float(cast(Any, rand)())
            except Exception:
                r = 0.0
            return targets[int(r * len(targets)) % len(targets)]
    return targets[random.Random(_stable_seed(targets)).randrange(len(targets))]


# -------------------------------------------------------------------------------------
# M12 换区触发装配（chase_trigger）
# -------------------------------------------------------------------------------------


def chase_trigger(
    enemy_state: Any,
    cfg: Any,
    boss_flow: Any = None,
    rng: Any = None,
) -> dict:
    """M12 换区触发装配（m3 §3.2 / 2a2 §1.1 + §1.4）。

    触发判定：boss_flow 注入时调 BossFlow.should_zone_change(enemy_state, cfg)（路O 已测
    实现优先）；未注入 → 契约本地实现 _contract_should_zone_change（判定链同口径）。
    触发时 pick_chase_target 从 targets 确定性选一（注入 rng / 固定种子）。

    Args:
        enemy_state: 怪物状态 {hp, max_hp} 或 {hp_pct}（百分比）；phase_changed 可选标志。
        cfg: enemies zone_change 配置子段（enabled/hp_threshold/targets/timing）。
        boss_flow: 注入 BossFlow（或带 should_zone_change 的对象）；None → 本地契约实现。
        rng: 注入确定性随机源（候选区选一用）。

    Returns:
        {"triggered": bool, "targets": list[str], "target": str|None}
        —— triggered=False 时 target 恒为 None（R4/R1/R3 任一不满足）。
    """
    targets = _targets_list(cfg)
    if boss_flow is not None and callable(getattr(boss_flow, "should_zone_change", None)):
        triggered = bool(boss_flow.should_zone_change(enemy_state, cfg))
    else:
        triggered = _contract_should_zone_change(enemy_state, cfg)
    target = pick_chase_target(cfg, rng=rng) if triggered else None
    return {"triggered": triggered, "targets": targets, "target": target}


# -------------------------------------------------------------------------------------
# M13 追击态开启（begin_chase）
# -------------------------------------------------------------------------------------


def _lookup_name_in_entries(entries: Any, map_id: str) -> Optional[str]:
    """地图条目列表（raw dict / MapDef 对象）→ map_id 的 name；未知 → None。"""
    for e in entries:
        if isinstance(e, Mapping):
            if e.get("id") == map_id:
                n = e.get("name")
                return n if isinstance(n, str) and n else None
        else:
            mid = getattr(e, "id", None)
            if mid == map_id:
                n = getattr(e, "name", None)
                return n if isinstance(n, str) and n else None
    return None


def _map_display_name(map_names: Any, map_id: str) -> Optional[str]:
    """map_names 入参归一 → 目标图显示名（maps.name，契约 §3.2 / 2a2 §1.3 R7）。

    接受：{map_id: name} 映射 / 地图条目列表（raw dict 或 MapDef）/ 单节点 /
    modules 容器（{"maps": [...]}）/ None。未知 → None（调用方回退 map_id）。
    """
    if not map_id:
        return None
    if isinstance(map_names, Mapping):
        if "maps" in map_names:  # modules 容器（content 装载形态）
            entries = map_names.get("maps")
            if isinstance(entries, (list, tuple)):
                return _lookup_name_in_entries(entries, map_id)
            return None
        v = map_names.get(map_id)
        if isinstance(v, str) and v:
            return v
        if map_names.get("id") == map_id:  # 单地图节点
            n = map_names.get("name")
            return n if isinstance(n, str) and n else None
        return None
    if isinstance(map_names, (list, tuple)):
        return _lookup_name_in_entries(map_names, map_id)
    return None


def begin_chase(session: Any, target_map: Any, map_names: Any = None) -> dict:
    """M13 追击态开启（契约 §3.2 逃跑行为 / §4.2 chasing:true / 2a2 §1.3 R7）。

    - session（dict）原地落盘追击态：session["chasing"]=True + session["chase_target"]=<id>
      （工程补白 3；存储层落库由快照批次接线）。
    - 返回 {chasing: True, target_map, target_name, hint}；hint = 「BOSS 逃向了【显示名】」
      （显示名 = maps.name；未知图回退 map_id）。

    Args:
        session: 副本会话（dict；原地写入 chasing 标志，非 dict 则仅返回不落盘）。
        target_map: 逃跑目标图 id。
        map_names: 地图名解析源（{map_id: name} / 地图列表 / 容器 / 单节点，见
            _map_display_name）；None → 显示名回退 map_id。
    """
    target = "" if target_map is None else str(target_map)
    name = _map_display_name(map_names, target) or target
    if isinstance(session, dict):
        session[SESSION_CHASING_KEY] = True
        session[SESSION_CHASE_TARGET_KEY] = target
    return {
        "chasing": True,
        "target_map": target,
        "target_name": name,
        "hint": CHASE_HINT_TEMPLATE.format(name=name),
    }


# -------------------------------------------------------------------------------------
# M13 追击行走与错失窗口（pursue）
# -------------------------------------------------------------------------------------


def target_reachable(
    from_map_id: Any,
    target_map: Any,
    maps: Any,
    conditions: Any = None,
) -> bool:
    """当前图能否沿通道到达目标图（map_graph.path_exists BFS，2a1b R5 捷径连通）。

    工程补白 7：pursue 走错分支的 reachable 信息位；仅信息性，不驱动错失判定。
    maps 须为 list/tuple（路J ctx 契约）；异常/未注入 → False（fail-safe）。
    """
    if not isinstance(maps, (list, tuple)):
        return False
    try:
        from qbot_rpg.core.map_graph import path_exists
    except Exception:
        return False
    ctx: dict = {"maps": list(maps)}
    if conditions is not None:
        ctx["conditions"] = conditions
    try:
        return bool(path_exists(str(from_map_id), str(target_map), ctx["maps"], ctx))
    except Exception:
        return False


def pursue(
    player_ctx: dict,
    direction: Any,
    chase_ctx: Any,
    maps: Any = None,
) -> dict:
    """M13 追击行走与错失窗口（2a2 §4.2 R15 / §4.4 R18 / §5.1 R24 / 契约 §3.2）。

    玩家 /进入 <方向> 走通道追击：调 movement.resolve_move（成功则原地更新
    player_ctx 位置）；到达 chase_ctx.target_map → {caught: True}（续战准备见补白 6）；
    未到达 → {caught: False, missed}：

      - 走通道失败（死路/隐藏未满足/非法方向）→ 不计错（补白 5，不消耗行动资源）；
      - 走错一步 → chase_ctx.miss_count 递增（原地写回）；
      - 错失窗口关闭：连续走错 ≥ chase_ctx.miss_limit（默认 3）或走回起始区
        chase_ctx.start_map → {missed: True, boss_reset: True}（BOSS 回满/离开副本
        信号，按 R24 由调用方执行重置；本路不直改战斗资源）。

    Args:
        player_ctx: 玩家上下文 {map_id, player:{map_id}, time_state?, maps?}（dict，原地改）。
        direction: 方向字面量（上/下/左/右 + 别名，movement.DIRECTION_ALIASES）。
        chase_ctx: 追击上下文 dict {target_map, start_map?, miss_count?, miss_limit?,
            chasing?, boss_flow?}；miss_count/miss_limit 原地递增写回。
        maps: 地图源（list / 容器 / None → player_ctx["maps"]）。

    Returns:
        捕获:   {"caught": True, "moved": True, "missed": False, "target_map",
                 "chase_over": True, "continue_data"?}
        走错:   {"caught": False, "moved": True, "missed": False, "miss_count",
                 "miss_limit", "reachable"?}
        错失:   {"caught": False, "moved": True, "missed": True, "miss_count",
                 "miss_limit", "boss_reset": True, "reason", "message"}
        移动失败: {"caught": False, "moved": False, "missed": False, "reason", "miss_count"}
    """
    if not isinstance(chase_ctx, dict):
        chase_ctx = {}  # 非 dict 注入：计数仅本地生效，无法回写（防御）
    target_map = str(chase_ctx.get("target_map") or "")
    start_raw = chase_ctx.get("start_map")
    start_map = str(start_raw) if start_raw else None
    try:
        miss_limit = int(chase_ctx.get("miss_limit", MISS_LIMIT_DEFAULT))
    except (TypeError, ValueError):
        miss_limit = MISS_LIMIT_DEFAULT
    if miss_limit < 1:
        miss_limit = MISS_LIMIT_DEFAULT
    try:
        miss_count = int(chase_ctx.get("miss_count", 0))
    except (TypeError, ValueError):
        miss_count = 0

    res = resolve_move(player_ctx, direction, maps=maps)
    if not res.get("ok"):
        # 通道不可走（死路/隐藏未满足/非法方向）：不消耗行动资源，不计错（补白 5）
        return {
            "caught": False,
            "moved": False,
            "missed": False,
            "reason": res.get("reason") or "移动失败",
            "miss_count": miss_count,
        }

    new_map = player_ctx.get("map_id")
    new_map = str(new_map) if new_map else None

    if target_map and new_map == target_map:
        # 到达目标图 → 捕获（M6 追到 → S4 决战准备；2a2 §4.5 R19）
        chase_ctx[SESSION_CHASING_KEY] = False
        out: dict = {
            "caught": True,
            "moved": True,
            "missed": False,
            "target_map": target_map,
            "chase_over": True,
        }
        bf = chase_ctx.get("boss_flow")
        if bf is not None and callable(getattr(bf, "on_chase_continue", None)):
            out["continue_data"] = bf.on_chase_continue()  # 续战准备（补白 6，M14 消费）
        return out

    # 未到达目标图：本次移动 = 走错一步（2a2 §4.4 R18），计数递增并回写
    miss_count += 1
    chase_ctx["miss_count"] = miss_count
    back_to_start = bool(start_map) and new_map == start_map
    over_limit = miss_count >= miss_limit
    missed = over_limit or back_to_start
    if missed:
        # 错失窗口关闭：BOSS 回满/离开副本（2a2 §5.1 R24；信号交付，资源重置调用方执行）
        chase_ctx[SESSION_CHASING_KEY] = False
        chase_ctx["boss_reset"] = True
        reason = "back_to_start" if back_to_start else "miss_limit"
        message = (
            "走回起始区，BOSS 回满并离开了副本"
            if back_to_start
            else f"连续走错已达上限（{miss_limit} 次），BOSS 回满并离开了副本"
        )
        return {
            "caught": False,
            "moved": True,
            "missed": True,
            "miss_count": miss_count,
            "miss_limit": miss_limit,
            "boss_reset": True,
            "reason": reason,
            "message": message,
        }

    out = {
        "caught": False,
        "moved": True,
        "missed": False,
        "miss_count": miss_count,
        "miss_limit": miss_limit,
    }
    if target_map:
        out["reachable"] = target_reachable(new_map, target_map, maps)  # 信息位（补白 7）
    return out
