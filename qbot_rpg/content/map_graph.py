"""地图通道判定（M3 批次3·路J：M02 双向通道判定 + M03 单向拦截 + M04 捷径/追击路径计算）。

依据：
  - 细化_2a1a_地图schema字段.md §2（exits 6 字段：direction / target / mode / shortcut /
    hidden / lore）
  - 细化_2a1b_通道规则与刷怪.md §一（通道规则 R1-R13：R2 未配置方向=死路、R3 双向、
    R4 单向（反方向拒绝）、R5 捷径=绕路连通（单向边+回程边布线）、R6-R7 隐藏通道条件打开）
  - m3_shared_contract §2.4（can_move / bidirectional_consistent / path_exists 接口签名）

本模块为**纯逻辑模块**：零 NoneBot import、零 IO（不读文件/不写状态）、无副作用；
地图数据经 ctx.maps 注入（raw dict 或 MapDef 均可，见 _entry_exits/_exit_fields），
隐藏通道条件求值由调用方经 ctx.conditions 注入。

【工程补白】显式标注（契约/细化未定死处的落地选择，不冒充定稿）：
  1. Warning 为 dict 形状（契约只给 list[Warning] 类型名，未定字段集）；字段集见
     bidirectional_consistent，与 validate_maps Y-8（rule=map_exit_bidirectional_asymmetry）
     同口径，方便收口时统一黄提示渲染。
  2. MoveResult 在契约 §2.4 核心字段（ok/to/mode/hidden_ok/blocked_reason?）之外补
     to_name / lore 两个提示字段：指令层 /进入 <方向> 提示目标图名（maps.name）与途经文本
     （细化_2a1a §2.6 lore / 2a1b R12 换区追击提示对位）。
  3. 隐藏通道条件求值 = ctx["conditions"](cond)->bool，由调用方注入；未注入或求值异常
     一律视为不满足（2a1b R7 双层拒绝：不显示 + 不可走）。
  4. 单向反方向拦截 = 玩家位于单向门目标端、目标图无回本图的边（该方向未配置/无对应边），
     与死路同用 blocked_reason="此路不通"（契约 §2.4 同文案）；单向门前向通行
     （源端→目标端，R4「只有一边」的可用一边）放行。
"""

from __future__ import annotations

from collections import deque
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

# -------------------------------------------------------------------------------------
# 类型别名（契约 §2.4：MoveResult / Warning 均为 dict 形状）
# -------------------------------------------------------------------------------------
MoveResult = Dict[str, Any]
Warning = Dict[str, Any]

# 权威文案（契约 §2.4 + 2a1b R2/R4/R7：拦截提示原文）
BLOCKED_NO_PASSAGE = "此路不通"  # 死路 / 单向反方向 / 目标悬空
BLOCKED_NO_CHANNEL = "此处无通道"  # 隐藏通道条件未满足（R7 双层拒绝）

# 双向一致性黄提示 rule 标识（与 validate_maps Y-8 同口径）
RULE_BIDIRECTIONAL_ASYMMETRY = "map_exit_bidirectional_asymmetry"

EXIT_DIRECTIONS: Tuple[str, ...] = ("up", "down", "left", "right")  # 4 方向键（2a1b R2）
EXIT_MODES: Tuple[str, ...] = ("bidirectional", "one_way", "hidden")  # 三枚举（契约 §2.2）


# =====================================================================================
# 数据访问助手（同时兼容 raw dict 条目 与 MapDef 对象条目，见 _entry_exits/_exit_fields）
# =====================================================================================
def _entry_id(entry: object) -> Optional[str]:
    """地图条目 → id（Mapping：raw["id"]；对象：.id）。非字符串 → None。"""
    if isinstance(entry, Mapping):
        v = entry.get("id")
        return v if isinstance(v, str) else None
    v = getattr(entry, "id", None)
    return v if isinstance(v, str) else None


def _entry_exits(entry: object) -> Mapping[str, object]:
    """地图条目 → {direction: exit}（raw dict / MapDef.exits 属性；非映射 → 空表）。"""
    if isinstance(entry, Mapping):
        raw = entry.get("exits")
        return raw if isinstance(raw, Mapping) else {}
    ex = getattr(entry, "exits", None)
    return ex if isinstance(ex, Mapping) else {}


def _exit_fields(ex: object) -> Tuple[Optional[str], Optional[str], object]:
    """单条通道 → (to, mode, condition)。兼容 raw dict 与 ExitDef 对象。"""
    if isinstance(ex, Mapping):
        to, mode = ex.get("to"), ex.get("mode")
        return (
            to if isinstance(to, str) else None,
            mode if isinstance(mode, str) else None,
            ex.get("condition"),
        )
    return (
        getattr(ex, "to", None) if isinstance(getattr(ex, "to", None), str) else None,
        getattr(ex, "mode", None) if isinstance(getattr(ex, "mode", None), str) else None,
        getattr(ex, "condition", None),
    )


def _exit_lore(ex: object) -> Optional[str]:
    """单条通道 → lore（细化_2a1a §2.6 通道介绍文本；无 → None）。"""
    if isinstance(ex, Mapping):
        l = ex.get("lore")
        return l if isinstance(l, str) else None
    l = getattr(ex, "lore", None)
    return l if isinstance(l, str) else None


def _map_index(maps: object) -> Dict[str, object]:
    """maps 列表 → {id: 条目}（跳过无 id / 非对象条目；供 can_move/path_exists 查图）。"""
    idx: Dict[str, object] = {}
    if not isinstance(maps, list):
        return idx
    for entry in maps:
        mid = _entry_id(entry)
        if mid is not None:
            idx[mid] = entry
    return idx


def _hidden_satisfied(condition: object, ctx: Mapping[str, object]) -> bool:
    """隐藏通道条件求值（2a1b R7 / R8：条件引擎表达式满足才可走）。

    工程补白：求值器 = ctx["conditions"]（callable(cond)->bool）由调用方注入；
    未注入 / 非 callable / 求值抛异常 → 一律视为不满足（双层拒绝）。
    """
    evaluator = ctx.get("conditions")
    if not callable(evaluator):
        return False
    if condition is None:
        return False
    try:
        return bool(evaluator(condition))
    except Exception:
        return False


def _target_name(maps_idx: Mapping[str, object], to: Optional[str]) -> Optional[str]:
    """目标图 id → maps.name（供 /进入 提示；未知 → None）。"""
    if to is None:
        return None
    entry = maps_idx.get(to)
    if entry is None:
        return None
    name = getattr(entry, "name", None) if not isinstance(entry, Mapping) else entry.get("name")
    return name if isinstance(name, str) else None


# =====================================================================================
# M02 双向通道判定 + M03 单向拦截（契约 §2.4 can_move）
# =====================================================================================
def can_move(map_id: str, direction: str, ctx: Mapping[str, object]) -> MoveResult:
    """判定玩家于 map_id 走 direction 方向是否可通行（纯函数，无副作用）。

    契约 §2.4 语义：
      - 双向通道（R3）：直接可走 → ok=True，返回目标图 id / mode / to_name / lore；
      - 单向通道（R4）：前向（源端→目标端）可走；反方向（目标端无回本图的边）→
        ok=False，blocked_reason="此路不通"；
      - 隐藏通道（R6/R7）：condition 满足 → ok=True（hidden_ok=True）；不满足 →
        ok=False，blocked_reason="此处无通道"；
      - 方向缺失（R2 未配置方向=死路）→ ok=False，blocked_reason="此路不通"。

    ctx 契约：{maps: 地图列表, conditions?: callable(cond)->bool}；
    隐藏条件求值由调用方注入，未注入 = 不满足（工程补白 3）。
    """
    maps = ctx.get("maps")
    idx = _map_index(maps)
    entry = idx.get(map_id)
    if entry is None:
        # 未知地图 / maps 未注入：防御性拦截（不冒充可走）
        return _blocked(None, None, BLOCKED_NO_PASSAGE)

    ex = _entry_exits(entry).get(direction)
    if ex is None:
        # 方向缺失（死路，R2）或单向门目标端反方向（目标图无回本图边，R4）——同为"此路不通"
        return _blocked(None, None, BLOCKED_NO_PASSAGE)

    to, mode, condition = _exit_fields(ex)
    lore = _exit_lore(ex)
    to_name = _target_name(idx, to)

    if mode == "bidirectional":
        # R3：双向直接可走
        return {
            "ok": True,
            "to": to,
            "to_name": to_name,
            "mode": "bidirectional",
            "hidden_ok": False,
            "blocked_reason": None,
            "lore": lore,
        }

    if mode == "one_way":
        # R4：前向通行（玩家位于源端）——允许；反方向在本函数表现为方向缺失/无回边（上方拦截）
        return {
            "ok": True,
            "to": to,
            "to_name": to_name,
            "mode": "one_way",
            "hidden_ok": False,
            "blocked_reason": None,
            "lore": lore,
        }

    if mode == "hidden":
        # R6/R7：条件打开，满足才显示+可走
        ok = _hidden_satisfied(condition, ctx)
        return {
            "ok": ok,
            "to": to,
            "to_name": to_name,
            "mode": "hidden",
            "hidden_ok": ok,
            "blocked_reason": None if ok else BLOCKED_NO_CHANNEL,
            "lore": lore,
        }

    # mode 缺失/非法（数据错误，validate_maps R-1 已红拦）：防御性拦截
    return _blocked(to, mode, BLOCKED_NO_PASSAGE)


def _blocked(
    to: Optional[str],
    mode: Optional[str],
    reason: str,
) -> MoveResult:
    """构造拦截结果（ok=False）：dead-end / 单向反方向 / 目标悬空 / 非法 mode 共用。"""
    return {
        "ok": False,
        "to": to,
        "to_name": None,
        "mode": mode,
        "hidden_ok": False,
        "blocked_reason": reason,
        "lore": None,
    }


# =====================================================================================
# M02 双向一致性黄提示（契约 §2.2 ④ / §2.4 bidirectional_consistent）
# =====================================================================================
def bidirectional_consistent(maps: object) -> List[Warning]:
    """扫描「声明为 bidirectional 的边」对侧：B→A 缺失或非双向 → 黄提示（允许刻意不对称）。

    契约 §2.2 ④ / 2a1b §1.4 ④：A→B 双向而 B→A 单向/缺失 → 黄提示"双向不对称"。
    与 validate_maps._check_bidirectional_symmetry（Y-8）同口径；纯函数，无副作用。
    目标悬空（to 不在 maps，validate_maps R-4 已红拦）跳过，避免重复噪音。

    返回 list[Warning]（工程补白 1：dict 字段集）：
      {rule, map_id, direction, to, back_missing, back_direction?, back_mode?}
    """
    idx = _map_index(maps)
    warnings: List[Warning] = []

    for node_id, entry in idx.items():
        for direction, ex in _entry_exits(entry).items():
            if direction not in EXIT_DIRECTIONS:
                continue
            to, mode, _cond = _exit_fields(ex)
            if mode != "bidirectional" or to is None or to == node_id:
                continue
            if to not in idx:
                continue  # 目标悬空：validate_maps R-4 已红拦，此处跳过
            back_dir, back_mode = _find_back_edge(idx[to], node_id)
            if back_dir is None:
                warnings.append({
                    "rule": RULE_BIDIRECTIONAL_ASYMMETRY,
                    "map_id": node_id,
                    "direction": direction,
                    "to": to,
                    "back_missing": True,
                })
            elif back_mode != "bidirectional":
                warnings.append({
                    "rule": RULE_BIDIRECTIONAL_ASYMMETRY,
                    "map_id": node_id,
                    "direction": direction,
                    "to": to,
                    "back_missing": False,
                    "back_direction": back_dir,
                    "back_mode": back_mode,
                })
            # back_mode == "bidirectional"：对称，无提示
    return warnings


def _find_back_edge(entry: object, from_id: str) -> Tuple[Optional[str], Optional[str]]:
    """在目标图 entry 中找指向 from_id 的回边 → (direction, mode)；无 → (None, None)。"""
    for d2, e2 in _entry_exits(entry).items():
        to2, mode2, _c = _exit_fields(e2)
        if to2 == from_id:
            return d2, mode2
    return None, None


# =====================================================================================
# M04 捷径/追击路径计算（契约 §2.4 path_exists）
# =====================================================================================
def path_exists(
    from_id: str,
    to_id: str,
    maps: object,
    ctx: Mapping[str, object],
) -> bool:
    """BFS 寻路：from_id 能否沿通道到达 to_id（捷径=单向门回环场景可达）。

    依据：2a1b R5（捷径 = 单向边 + 绕回边组合实现，绕路连通）、R10（地图熟悉度 =
    追击资源，熟悉直追 / 不熟绕路）、契约 §2.4（捷径/追击路径计算）。

    - 双向/单向边按声明方向可通行；隐藏边仅当条件满足（ctx.conditions 注入）可通行，
      未注入 = 不满足（工程补白 3）。
    - 单向门回环（A→B 单向 + B→C→A 绕回）：B→A 可达（经 C 绕回）→ 返回 True。
    - from_id == to_id → True（已在原地）；任一未知 id / 不在 maps → False。
    - 与 can_move 共用同一通行判定（经 can_move 展开邻接），保证两函数口径一致。
    """
    idx = _map_index(maps)
    if from_id not in idx or to_id not in idx:
        return False
    if from_id == to_id:
        return True

    visited: set = {from_id}
    queue: deque = deque([from_id])
    while queue:
        cur = queue.popleft()
        for direction, ex in _entry_exits(idx[cur]).items():
            res = can_move(cur, direction, ctx)
            if not res["ok"]:
                continue
            nxt = res["to"]
            if nxt is None or nxt not in idx:
                continue
            if nxt == to_id:
                return True
            if nxt not in visited:
                visited.add(nxt)
                queue.append(nxt)
    return False
