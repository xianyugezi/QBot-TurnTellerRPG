"""玩家级随机流状态持久化（批40 · H5）——沿用 `core/battle.py` 既有 `rng_state` 做法。

依据：`docs/深度打造_决策记录.md` §一 H5（"随机流沿用引擎既有做法：rng_state 持久化 +
逐指令推进，照 core/battle.py:5316,5409-5424 的既有实现"）；`打造系统_C` §二 Q6/R1
（E2：`random.Random(qid)` 每指令重建同 seed → 同玩家同指令走出同一条随机序列）。

本模块**只做同一机制的通用快照/恢复/落档函数**（不引入第二套随机内核、不改 battle）：
  · 快照 = `list(rng.getstate())` —— 与 battle `to_snapshot` 同形态（JSON 可序列化）；
  · 恢复 = 递归把 list 归一为 tuple 再 `setstate` —— 对齐 battle M12.5/veinborn
    「rng 死区修复」的 `_norm_rng_state`（JSON 往返后内层 tuple 变 list 会 TypeError）；
  · 落档位 = 玩家 `persistent_state[RNG_STATE_KEY]`（随档、包无关）；缺省 = 用注入的
    `rng_factory` 初种（测试注入确定性 RNG 的既有路径保持可用），存在则恢复推进。

铁律：零 NoneBot import；纯函数；只读写显式传入的 Mapping。
"""
from __future__ import annotations

import random
from typing import Any, List, Mapping, MutableMapping, Optional

__all__ = [
    "RNG_STATE_KEY",
    "snapshot_rng_state",
    "normalize_rng_state",
    "restore_rng_state",
    "player_rng",
    "persist_player_rng",
    "persist_player_rng_if_advanced",
]

# 玩家 persistent_state 内的随机流状态键（框架通用键，非内容包业务名）
RNG_STATE_KEY: str = "rng_state"


def snapshot_rng_state(rng: Any) -> Optional[List[Any]]:
    """RNG → JSON 可序列化快照 `list(getstate())`（异常 → None）。

    与 `core/battle.py::to_snapshot` 的 `snap["rng_state"] = list(self._rng.getstate())`
    同一形态（顶层 list；内层仍为 tuple，落 JSON 时变 list，恢复时归一）。
    """
    try:
        return list(rng.getstate())
    except Exception:  # noqa: BLE001 - 非 Random/异常 → 无状态（不阻断指令）
        return None


def normalize_rng_state(state: Any) -> Any:
    """递归把 list 归一为 tuple——`setstate` 契约要求 `(version, tuple[int,...], gauss)`。

    对齐 battle `from_snapshot` 内 `_norm_rng_state`（JSON 往返后内层 list 会 TypeError）。
    """
    if isinstance(state, list):
        return tuple(normalize_rng_state(x) for x in state)
    return state


def restore_rng_state(rng: random.Random, state: Any) -> bool:
    """把快照 state 恢复到 rng（成功 True；空/畸形 → False，调用方回落初种）。"""
    if not isinstance(state, (list, tuple)) or not state:
        return False
    try:
        rng.setstate(normalize_rng_state(state))
        return True
    except Exception:  # noqa: BLE001 - 畸形 state 回落（同 battle 口径）
        return False


def player_rng(ps: Any, fallback: random.Random) -> random.Random:
    """玩家存档态 → 可推进随机流：`ps[RNG_STATE_KEY]` 可恢复则续流，否则用 fallback。

    入参：ps = 玩家 persistent_state（Mapping 或 None）；fallback = 注入工厂初种的
    Random（`deps.rng_factory(qid)`）。出参：random.Random。
    **注入点兼容**：无落档状态（新档/未推进/测试注入）→ 原样返回 fallback（测试里
    `rng_factory` 返回的对象身份不变，既有断言不破）。
    """
    state = ps.get(RNG_STATE_KEY) if isinstance(ps, Mapping) else None
    if state:
        rng = random.Random()
        if restore_rng_state(rng, state):
            return rng
    return fallback


def persist_player_rng(ps: Any, rng: Any) -> bool:
    """把 rng 当前状态写回 `ps[RNG_STATE_KEY]`（就地；成功 True）。

    调用时机 = 每条指令落档前（runner `_plain_handler`）→ 「逐指令推进」：
    指令内消费 rng 后状态变化，写回玩家档；下条指令 make_context 恢复该状态续流。
    ps 不可写 / rng 非 Random → 返回 False（不做任何事，不阻断指令）。
    """
    if not isinstance(ps, MutableMapping) or not isinstance(rng, random.Random):
        return False
    snap = snapshot_rng_state(rng)
    if snap is None:
        return False
    ps[RNG_STATE_KEY] = snap
    return True


def persist_player_rng_if_advanced(
    ps: Any, rng: Any, initial: Any
) -> bool:
    """消费门控落档：仅当 rng 相对 `initial` 快照已推进时才写 `ps[RNG_STATE_KEY]`。

    `initial` = make_context 注入时（恢复或初种后）的 `snapshot_rng_state(rng)`。
    未消费 rng 的指令 → 不写（**不把 ~7KB 状态无谓写进每条指令的存档**，也不给
    从未用随机的玩家平白加字段）；已消费 → 写回推进后的状态。语义与
    「每次消费后推进」一致，且与 battle 快照口径不冲突（battle 只在战斗边界存）。
    返回是否实际写入。
    """
    snap = snapshot_rng_state(rng)
    if snap is None or snap == initial:
        return False
    if not isinstance(ps, MutableMapping):
        return False
    ps[RNG_STATE_KEY] = snap
    return True
