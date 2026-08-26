"""副本安全区 /休息（M3 批次7·路S：M24 安全区 + M25 /休息 + M26 休息≠离开）。

依据：
  - 细化_2a3_副本两型流程.md §2（状态集 M15：安全区 /休息 ≠ 离开——位置/BOSS 血量/快照保留，
    S0/S1/S3 状态不变、rest_count+1；R16 安全区内可 /休息 恢复 + 冷却缩减 + 次数限制可配；
    R21 副本内 HP/MP 不恢复、唯一例外=安全区 /休息；R32 非战斗离开=重置、/休息 ≠ 离开）
  - m3_shared_contract §4.4（快照续玩/死亡/安全区 M24–M30：/休息 副本内语义（恢复/冷却缩减/
    次数限制）；≠ 离开副本（不重置、快照保留）；safe_zone 字段缺省=入口区；副本会话持久化
    含休息次数）
  - 规划_路2a_地图副本.md M24（安全区=入口区 + safe_zone 配置区域，缺省=[入口区]；/休息 可用性
    判定=当前位置∈安全区 且 非战斗 且 非 BOSS 房）+ M25（HP/MP 部分恢复默认各 20% 可配；冷却
    缩减 −N 回合；次数限制 rest_per_dungeon 每副本上限可配 0=不限；rest_auto 进入自动结算一次
    默认关）+ M26（休息不改变位置、不退出副本、不触发重置；副本进度/BOSS 血量/快照
    ai_state+combo_state 全程保留）
  - 衔接细化_2a1c_地图副本衔接 R3（入口区缺省即安全区）/ 细化_2a1d_地图字段扩展（maps 节点
    扩展标记，见补白 4）/ 细化_1b_效果系统契约（effect_cooldowns 冷却登记表，1b 冷却缩减作用面）

职责（world 层纯逻辑：零 NoneBot import、零 IO、纯函数，返回数据不落库、不改入参）：
  is_safe_zone           M24：当前地图是否安全区（入口区 / safe_zone 配置 / maps 节点标记）
  rest_in_dungeon        M25：/休息 副本内语义——HP/MP 恢复（全满或按百分比，缺省各 20%）、
                        技能/特效冷却缩减（−N 回合，缺省 1）、次数限制（rest_limit 每副本上限，
                        超限拒绝「休息次数已用完」）；rest_count 递增；仅安全区可休息
  rest_is_not_exit       M26：休息 ≠ 离开——保留位置/BOSS 血量/子任务进度/换区上下文
                        （chase_ctx 保留），不触发副本重置（与 M15 离开重置互斥）

工程补白（定稿/契约未明示处，显式标注，不冒充定稿）：
  1. 冷却缩减缺省值：规划 M25 定稿「当前冷却中技能/特效冷却 −N 回合默认 3」+ 验收
     TC-2a3-15（副本定稿 §2.1「默认 3」）→ 本模块 DEFAULT_COOLDOWN_REDUCTION = 3
     （审查_M3_批次4 P2-8 修复：此前取 1 偏离仓内唯一权威默认 3，可配
     cfg.cooldown_reduction 覆盖）。
  2. 次数限制口径：规划 M25 定稿含「每日 3 次/天随存档持久化」与「rest_per_dungeon 每副本
     上限」两套口径。本路 rest_limit 语义 = 每副本上限（rest_per_dungeon 对齐，0=不限）；
     副本定稿 rest_per_dungeon 缺省 = null（不限）→ 本模块 DEFAULT_REST_LIMIT = 0（不限）
     （审查_M3_批次4 P2-9 修复：此前默认 3 误把「每日 3 次」用到每副本上限，未配 rest_limit
     的 BOSS 副本第 4 次休息被拦，与定稿「不限」冲突）。每日口径/rest_auto 自动结算由批次
     接线（本模块不接每日重置）。
  3. safe_zone 配置形态：m3_shared_contract §4.1 / DungeonDef 为单字符串；规划 M24 提「safe_zone
     数组」多安全区。本路防御兼容 str / list 两形态，并按 M24 取并集语义：安全区集合 =
     {入口区} ∪ {safe_zone 配置} ∪ {maps 节点 safe_zone 标记}（core.dungeon._safe_zone 为单图
     快捷落位，供 enter/复活点使用；本路实现完整安全区集合判定，两者互补不冲突）。
  4. maps 节点标记：契约 2a1a 节点级 8 字段未列 safe_zone；本路支持节点原始条目扩展键
     `safe_zone: true`（工程约定，MapDef.raw 只读镜像可读），作安全区标记来源之一。
  5. HP/MP 满值来源：Player（data/player.py）无 max_hp/max_mp 字段（满值由属性三层 3b 计算管线
     产出）。本路按 cfg.max_hp/cfg.max_mp → ctx.max_hp/max_mp → player.max_hp/max_mp 顺序读取；
     满值不可解时恢复量取 0（不越权猜测属性管线）。
  6. rest_in_dungeon 只做语义计算（纯函数，返回恢复/缩减/计数结果与消息），不接线状态机
     M15 迁移（core.dungeon 的 rest 迁移已含 rest_count+1、状态不变），落库/状态机迁移由
     指令层接线；本路 rest_count 字段为投影值（成功=原值+1）。
  7. 冷却表读取源（1b 效果系统 effect_cooldowns: {effect_id: 剩余回合}）：player_ctx.battle_state
     .effect_cooldowns → player_ctx.effect_cooldowns → player.effect_cooldowns / player.cooldowns；
     纯函数返回缩减后新 dict（值向下取整到 0），不改入参。
  8. rest_in_dungeon 的 maps 入参经 cfg.maps 透传（签名固定无 maps 形参）；安全区信息亦可
     由 session 内嵌 dungeon_def / safe_zone 扩展键提供。

铁律：零 NoneBot import；纯函数无 IO；平台无关；每功能可追溯（m3 铁律 4/8）。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

__all__ = [
    "DEFAULT_HP_MP_PCT",
    "DEFAULT_COOLDOWN_REDUCTION",
    "DEFAULT_REST_LIMIT",
    "REST_MODE_FULL",
    "REST_MODE_PCT",
    "STATE_LEFT",
    "MESSAGE_REST_LIMIT",
    "MESSAGE_REST_NOT_SAFE",
    "is_safe_zone",
    "rest_in_dungeon",
    "rest_is_not_exit",
]

# -------------------------------------------------------------------------------------
# 常量（工程补白见模块 docstring）
# -------------------------------------------------------------------------------------

#: HP/MP 部分恢复比例缺省值（M25：各 20% 可配倾向百分比）。
DEFAULT_HP_MP_PCT: float = 0.2

#: 冷却缩减量缺省值（−N 回合；【补白 1】：M25 / TC-2a3-15 定稿默认 3，可配）。
DEFAULT_COOLDOWN_REDUCTION: int = 3

#: 每副本休息次数上限缺省值（rest_per_dungeon 对齐；0=不限；【补白 2】：副本定稿缺省=null 不限）。
DEFAULT_REST_LIMIT: int = 0

#: 恢复模式：全满（mode="full"）。
REST_MODE_FULL: str = "full"

#: 恢复模式：按百分比（mode="pct"，缺省；M25 各 20%）。
REST_MODE_PCT: str = "pct"

#: 离开态（副本重置）状态键（对齐 core.dungeon S7 = "LEFT" / world.chase_resume.STATE_LEFT；
#: world 层自持常量避免跨层依赖）。
STATE_LEFT: str = "LEFT"

#: 休息次数用完拒绝文案（M25 验收「每日第 4 次被拦 / rest_per_dungeon=1 时同副本第 2 次被拦」）。
MESSAGE_REST_LIMIT: str = "休息次数已用完"

#: 非安全区拒绝文案（2a3 R16 / TC-2a3-15：安全区 /休息 ≠ 离开）。
MESSAGE_REST_NOT_SAFE: str = "非安全区不可 /休息（2a3 R16 / TC-2a3-15：安全区 /休息 ≠ 离开）"

#: 冷却登记表键（1b 效果系统；BattleSnapshot.effect_cooldowns = {effect_id: 剩余回合}）。
_COOLDOWN_KEYS: Tuple[str, ...] = ("effect_cooldowns", "cooldowns")


# -------------------------------------------------------------------------------------
# 纯函数辅助（dict / dataclass / 数值校验，风格对齐 world.chase_resume / core.dungeon）
# -------------------------------------------------------------------------------------


def _num(value: Any) -> bool:
    """数值校验（排除 bool——bool 是 int 子类）。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _session_field(session: Any, key: str, default: Any = None) -> Any:
    """从副本会话（DungeonSession dataclass / dict 持久化形态）读取字段（对齐 chase_resume）。"""
    if session is None:
        return default
    if isinstance(session, Mapping):
        return session.get(key, default)
    return getattr(session, key, default)


def _cfg_int(cfg: Mapping[str, Any], key: str, default: int) -> int:
    """配置整型读取（非法/缺失 → 默认；bool 排除）。"""
    v = cfg.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else default


def _cfg_float(cfg: Mapping[str, Any], key: str, default: float) -> float:
    """配置浮点读取（非法/缺失 → 默认；bool 排除）。"""
    v = cfg.get(key)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        f = float(v)
        return f if f >= 0 else default
    return default


def _as_str_set(value: Any) -> set:
    """安全区配置归一：str → {str}；list/tuple/set/frozenset → 元素字符串集；其余 → 空集。"""
    if isinstance(value, str):
        return {value} if value else set()
    if isinstance(value, (list, tuple, set, frozenset)):
        return {str(x) for x in value if isinstance(x, str) and x}
    return set()


# -------------------------------------------------------------------------------------
# 安全区判定（M24）—— 入口区 / safe_zone 配置 / maps 节点标记 并集
# -------------------------------------------------------------------------------------


def _read_current_map(session: Any) -> Optional[str]:
    """当前地图 ID：session.current_map（顶层权威）→ session.map_id 兜底。"""
    cur = _session_field(session, "current_map")
    if isinstance(cur, str) and cur:
        return cur
    cur2 = _session_field(session, "map_id")
    return cur2 if isinstance(cur2, str) and cur2 else None


def _iter_map_nodes(maps: Any) -> Iterable[Tuple[str, Mapping[str, Any]]]:
    """maps 入参 → (map_id, 节点原始条目) 迭代（零失败；形态异常 → 空）。

    接受：modules 容器（{"maps": [...]}）/ MapDef 列表 / 节点 dict 列表 / 单个 MapDef /
    单个节点 dict / None。节点原始条目：dict 直用；MapDef 取 .raw（BaseDef 只读镜像）。
    """
    if maps is None:
        return
    if isinstance(maps, Mapping):
        if "maps" in maps:  # modules 容器（content 装载形态）
            entries = maps.get("maps")
            if not isinstance(entries, list):
                return
            for e in entries:
                if not isinstance(e, Mapping):
                    continue
                mid = e.get("id")
                if isinstance(mid, str) and mid:
                    yield mid, e
            return
        if "id" in maps:  # 单个地图节点
            mid = maps.get("id")
            if isinstance(mid, str) and mid:
                yield mid, maps
            return
        # 其他 map 形态（键=id）：取键（无节点条目）
        for k in maps:
            if isinstance(k, str) and k:
                yield k, {}
        return
    if isinstance(maps, (list, tuple)):
        for e in maps:
            if isinstance(e, Mapping):
                mid = e.get("id")
                if isinstance(mid, str) and mid:
                    yield mid, e
            elif hasattr(e, "id") and hasattr(e, "raw"):
                mid = getattr(e, "id")
                raw = getattr(e, "raw")
                if isinstance(mid, str) and mid:
                    yield mid, raw if isinstance(raw, Mapping) else {}


def _session_safe_zone_config(session: Any) -> Optional[Any]:
    """session 内嵌安全区配置：session.safe_zone → session.dungeon_def.safe_zone（dict/dataclass）。"""
    sz = _session_field(session, "safe_zone")
    if sz is not None:
        return sz
    dd = _session_field(session, "dungeon_def")
    if isinstance(dd, Mapping):
        sz = dd.get("safe_zone")
    elif dd is not None:
        sz = getattr(dd, "safe_zone", None)
    return sz


def _session_dungeon_maps(session: Any) -> Tuple[str, ...]:
    """session 内嵌 dungeon_def.maps 列表（入口区缺省依据；str 元素归一）。"""
    dd = _session_field(session, "dungeon_def")
    if isinstance(dd, Mapping):
        ms = dd.get("maps")
    elif dd is not None:
        ms = getattr(dd, "maps", None)
    else:
        ms = None
    if isinstance(ms, (list, tuple)):
        return tuple(str(x) for x in ms if isinstance(x, str) and x)
    if isinstance(ms, (set, frozenset)):
        return ()  # 无序集合不可判入口区（首图）
    return ()


def _resolve_safe_zone_ids(session: Any, maps: Any) -> set:
    """安全区地图 ID 集合 = {入口区} ∪ {safe_zone 配置} ∪ {maps 节点 safe_zone 标记}（M24 并集）。

    入口区来源：session.dungeon_def.maps[0] → maps 入参集合首图（2a1c R3 缺省即安全区；
    【补白 3】）。maps 节点标记 = 节点原始条目 `safe_zone: true`（【补白 4】）。
    """
    ids: set = set()

    # 1) safe_zone 配置（session 内嵌，str / list 防御兼容【补白 3】）
    ids |= _as_str_set(_session_safe_zone_config(session))

    # 2) maps 节点级 safe_zone 标记（【补白 4】）
    for mid, node in _iter_map_nodes(maps):
        mark = node.get("safe_zone")
        if mark is True or mark in ("true", 1, "1"):
            ids.add(mid)

    # 3) 入口区（= 首图）：session.dungeon_def.maps[0] 权威；无内嵌则取 maps 入参首图
    dm = _session_dungeon_maps(session)
    if dm:
        ids.add(dm[0])
    else:
        for mid, _node in _iter_map_nodes(maps):
            ids.add(mid)
            break  # 仅首图
    return ids


def is_safe_zone(session: Any, maps: Any = None) -> bool:
    """当前地图是否安全区（M24 安全区定义与可用性判定）。

    Args:
        session: 副本会话（DungeonSession dataclass / dict 持久化形态）；dict 形态可内嵌
            safe_zone（str/list）或 dungeon_def（含 safe_zone / maps）扩展键（【补白 3/8】）。
        maps: 地图源（modules 容器 {"maps":[...]} / MapDef 列表 / 节点 dict 列表 / 单个节点）——
            提供节点级 `safe_zone: true` 标记与「入口区=首图」缺省（【补白 4】）。

    Returns:
        current_map ∈ 安全区集合 → True；current_map 缺失 / 集合为空 / 不在集合 → False。
    """
    cur = _read_current_map(session)
    if not cur:
        return False
    return cur in _resolve_safe_zone_ids(session, maps)


# -------------------------------------------------------------------------------------
# /休息 副本内语义（M25）—— 恢复 / 冷却缩减 / 次数限制
# -------------------------------------------------------------------------------------


def _read_current_resource(player_ctx: Mapping[str, Any], key: str) -> Optional[float]:
    """当前资源（hp/mp）：ctx[key] → ctx["player"][key]。非法/缺失 → None。"""
    v = player_ctx.get(key)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    player = player_ctx.get("player")
    if isinstance(player, Mapping):
        pv = player.get(key)
        if isinstance(pv, (int, float)) and not isinstance(pv, bool):
            return float(pv)
    return None


def _read_max_resource(player_ctx: Mapping[str, Any], cfg: Mapping[str, Any],
                       key: str) -> Optional[float]:
    """满值资源（max_hp/max_mp）：cfg[key] → ctx[key] → ctx["player"][key]（【补白 5】）。"""
    for src in (cfg, player_ctx):
        v = src.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    player = player_ctx.get("player")
    if isinstance(player, Mapping):
        pv = player.get(key)
        if isinstance(pv, (int, float)) and not isinstance(pv, bool):
            return float(pv)
    return None


def _restore_amounts(player_ctx: Mapping[str, Any],
                     cfg: Mapping[str, Any]) -> Tuple[int, int, Optional[float], Optional[float]]:
    """HP/MP 恢复量计算（纯函数，不改入参；M25 各 20% / mode=full 全满）。

    返回 (hp_restored, mp_restored, hp_after, mp_after)。满值不可解 → 恢复量 0（【补白 5】）。
    百分比模式恢复量 = floor(max × pct)，上限封顶至满值；full 模式 = max - cur。
    """
    mode = cfg.get("mode")
    mode = mode if isinstance(mode, str) else REST_MODE_PCT
    shared_pct = _cfg_float(cfg, "hp_mp_pct", DEFAULT_HP_MP_PCT)
    hp_pct = _cfg_float(cfg, "hp_pct", shared_pct)
    mp_pct = _cfg_float(cfg, "mp_pct", shared_pct)

    results: Dict[str, Tuple[int, Optional[float]]] = {}
    for key, pct in (("hp", hp_pct), ("mp", mp_pct)):
        cur = _read_current_resource(player_ctx, key)
        maxv = _read_max_resource(player_ctx, cfg, "max_" + key)
        if cur is None or maxv is None or maxv <= cur:
            results[key] = (0, cur if cur is not None else maxv)
            continue
        # 此分支 cur/maxv 均为已解数值（非 None），pyright 窄化提示按防御处理
        if mode == REST_MODE_FULL:
            amount = float(maxv) - float(cur)
        else:
            amount = int(float(maxv) * pct)  # floor（对齐 2a2 向下取整口径）
        if amount < 0:
            amount = 0
        cap = float(maxv) - float(cur)
        amount = min(amount, cap)
        results[key] = (int(amount), float(cur) + amount)
    return (results["hp"][0], results["mp"][0], results["hp"][1], results["mp"][1])


def _read_cooldowns(player_ctx: Mapping[str, Any]) -> Optional[Dict[str, int]]:
    """冷却登记表（1b effect_cooldowns: {effect_id: 剩余回合}）读取（【补白 7】优先级）。"""
    bs = player_ctx.get("battle_state")
    if isinstance(bs, Mapping):
        for k in _COOLDOWN_KEYS:
            v = bs.get(k)
            if isinstance(v, Mapping):
                return dict(v)
    for k in _COOLDOWN_KEYS:
        v = player_ctx.get(k)
        if isinstance(v, Mapping):
            return dict(v)
    player = player_ctx.get("player")
    if isinstance(player, Mapping):
        for k in _COOLDOWN_KEYS:
            v = player.get(k)
            if isinstance(v, Mapping):
                return dict(v)
    return None


def _reduce_cooldowns(player_ctx: Mapping[str, Any], cfg: Mapping[str, Any],
                      reduction: int) -> Tuple[Tuple[str, ...], Dict[str, int]]:
    """冷却缩减（−N 回合）：对冷却表中剩余回合 > 0 的条目统一减 N，向下取整到 0。

    返回 (受影响的 effect_id 元组, 缩减后新表 dict)。纯函数：不改入参（返回新 dict）。
    """
    table = _read_cooldowns(player_ctx)
    if not table:
        return (), {}
    affected: list = []
    after: Dict[str, int] = {}
    for eid, rem in table.items():
        r = rem if isinstance(rem, int) and not isinstance(rem, bool) else 0
        nv = max(0, r - reduction)
        if r > 0:
            affected.append(str(eid))
        after[str(eid)] = nv
    return tuple(affected), after


def rest_in_dungeon(session: Any, player_ctx: Mapping[str, Any],
                    cfg: Optional[Mapping[str, Any]] = None) -> dict:
    """/休息 副本内语义（M25：恢复 / 冷却缩减 / 次数限制；仅安全区可休息）。

    Args:
        session: 副本会话（DungeonSession / dict）；安全区判定来源见 is_safe_zone
            （dict 形态可内嵌 dungeon_def/safe_zone；maps 经 cfg.maps 透传【补白 8】）。
        player_ctx: 玩家上下文（hp/mp/max_hp/max_mp 读取；battle_state.effect_cooldowns
            冷却表，【补白 5/7】）。纯函数不改写入参。
        cfg: 配置（可空）——mode("full"|"pct"，缺省 pct) / hp_mp_pct(缺省 0.2) /
            hp_pct / mp_pct / cooldown_reduction(缺省 3，M25/TC-2a3-15) / rest_limit(缺省
            0=不限，副本定稿 rest_per_dungeon 缺省 null) / maps（安全区判定地图源）。

    Returns:
        成功：{rested: True, hp_restored, mp_restored, cooldown_reduction,
          cooldowns_affected, cooldowns_after, hp_after, mp_after,
          rest_count(投影=原值+1), limit_reached: False, state, current_map}
        非安全区拒绝：{rested: False, reason: "not_safe_zone", message, hp_restored: 0,
          mp_restored: 0, cooldown_reduction: 0, rest_count, limit_reached: False}
        次数超限拒绝：{rested: False, reason: "limit_reached", message: "休息次数已用完",
          hp_restored: 0, mp_restored: 0, cooldown_reduction: 0, rest_count, limit_reached: True}
    """
    c: Mapping[str, Any] = cfg if isinstance(cfg, Mapping) else {}
    cur_count = _session_field(session, "rest_count")
    cur_count = cur_count if isinstance(cur_count, int) and not isinstance(cur_count, bool) else 0

    if not is_safe_zone(session, maps=c.get("maps")):
        return {
            "rested": False,
            "reason": "not_safe_zone",
            "message": MESSAGE_REST_NOT_SAFE,
            "hp_restored": 0,
            "mp_restored": 0,
            "cooldown_reduction": 0,
            "rest_count": cur_count,
            "limit_reached": False,
        }

    rest_limit = _cfg_int(c, "rest_limit", DEFAULT_REST_LIMIT)
    if rest_limit > 0 and cur_count >= rest_limit:
        return {
            "rested": False,
            "reason": "limit_reached",
            "message": MESSAGE_REST_LIMIT,
            "hp_restored": 0,
            "mp_restored": 0,
            "cooldown_reduction": 0,
            "rest_count": cur_count,
            "limit_reached": True,
        }

    hp_restored, mp_restored, hp_after, mp_after = _restore_amounts(player_ctx, c)
    cd = _cfg_int(c, "cooldown_reduction", DEFAULT_COOLDOWN_REDUCTION)
    cd_affected, cd_after = _reduce_cooldowns(player_ctx, c, cd)

    return {
        "rested": True,
        "hp_restored": hp_restored,
        "mp_restored": mp_restored,
        "cooldown_reduction": cd,
        "cooldowns_affected": cd_affected,
        "cooldowns_after": cd_after,
        "hp_after": hp_after,
        "mp_after": mp_after,
        "rest_count": cur_count + 1,
        "limit_reached": False,
        "state": _session_field(session, "state"),
        "current_map": _session_field(session, "current_map"),
    }


# -------------------------------------------------------------------------------------
# 休息 ≠ 离开（M26）—— 保留位置/BOSS 血量/子任务进度/换区上下文，不触发重置
# -------------------------------------------------------------------------------------

#: 离开态集合（副本重置判定：S7 LEFT / 契约中文键兜底）。
_LEFT_STATES: Tuple[str, ...] = (STATE_LEFT, "LEFT", "S7")


def rest_is_not_exit(session: Any) -> dict:
    """休息 ≠ 离开副本（M26 / 细化_2a3 M15：位置/BOSS 血量/快照保留，不触发重置）。

    与 M15 离开重置（exit_dungeon_reset）互斥的验证谓词：休息后的会话应保持
      - 状态非 LEFT（休息不进入离开态）
      - current_map 保留（位置不改变）
      - boss_state / subquest_progress 保留（副本进度不因休息清空）
      - 换区上下文（chase_ctx 等顶层键）保留（【补白：chase_resume._ZONE_CHASE_KEYS 同源】）
    本函数只读判定，不触发任何重置副作用；会话缺失/形态非法 → kept: False。

    Returns:
        {kept, state, current_map, boss_state_preserved, subquest_progress_preserved,
         chase_ctx_preserved, reset_triggered: False}
    """
    state = _session_field(session, "state")
    current_map = _session_field(session, "current_map")
    boss_state = _session_field(session, "boss_state")
    subquest = _session_field(session, "subquest_progress")
    chase_ctx = _session_field(session, "chase_ctx")

    boss_preserved = isinstance(boss_state, Mapping) and bool(boss_state)
    subquest_preserved = isinstance(subquest, Mapping) and bool(subquest)
    chase_preserved = chase_ctx is not None  # 换区上下文键保留（可为空值）

    kept = (
        state not in _LEFT_STATES
        and isinstance(current_map, str) and bool(current_map)
        and boss_preserved
        and subquest_preserved
    )
    return {
        "kept": kept,
        "state": state,
        "current_map": current_map,
        "boss_state_preserved": boss_preserved,
        "subquest_progress_preserved": subquest_preserved,
        "chase_ctx_preserved": chase_preserved,
        "reset_triggered": False,
    }
