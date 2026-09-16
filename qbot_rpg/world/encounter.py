"""主动遭遇结算（批24 E2：`encounter_chance` + `encounter_count_min/max`）。

依据：
  - CakeGame `Config_Map.md:68`「该怪组主动触发强制战斗的概率」/`:69`「触发后进攻数量随机区间」
  - 我们既有：`maps.monsters[]` 行已有 `count`（同场存量，`field_meta.py`）、`signal`、
    `hidden_boss`；`encounter_*` 语义是**主动遭遇**（进入/移动结算时按概率触发），
    与 `count`（同场存量口径）和 `enemies.actions[].probability`（战斗内行动概率）都不同。

职责（world 层纯函数，零 IO、零 NoneBot import）：
  - `roll_encounter(map_entry, rng=None)`：进入**目标地图**时按刷怪行 `encounter_chance`
    （百分数 0-100）逐行 Roll；命中 → 返回该行遭遇信号 {enemy, count, ...}，否则 None。
  - 参战数 = `encounter_count_min`..`encounter_count_max` 区间内随机（引擎既有 RNG 口径：
    `random.Random` 的 `randint`/`random`，与 core/battle_reward 一致）。

边界（本批拍板，写进报告）：
  - `chance=0` / 缺该字段 / 非法值 → 不主动触发（行为与现状逐字段一致）；
  - `min > max` 由校验器红拦（`map_models._check_spawn`）；
  - 未给区间 → 参战数回落该行 `count`（同场存量，缺省 1）；
  - 逐行短路：首行命中即返回（一张图一次进入至多一次主动遭遇）。

【工程补白】真实战斗接线：本模块只出「遭遇信号」，实际进入战斗由上层战斗管线消费
（对齐 core/battle_reward 与副本流程「只出结算信号」的既有分层）。
"""
from __future__ import annotations

import random
from typing import Any, Dict, Mapping, Optional, Sequence

__all__ = ["roll_encounter", "ENCOUNTER_CHANCE_KEY", "ENCOUNTER_MIN_KEY", "ENCOUNTER_MAX_KEY"]

ENCOUNTER_CHANCE_KEY = "encounter_chance"
ENCOUNTER_MIN_KEY = "encounter_count_min"
ENCOUNTER_MAX_KEY = "encounter_count_max"


def _monster_rows(map_entry: object) -> Sequence[Mapping[str, Any]]:
    """地图条目 → monsters 刷怪行（MapDef.spawn property 或原始 dict monsters 键）。"""
    if map_entry is None:
        return ()
    if isinstance(map_entry, Mapping):
        raw = map_entry.get("monsters")
        return tuple(r for r in raw if isinstance(r, Mapping)) if isinstance(raw, list) else ()
    try:
        rows = map_entry.spawn  # MapDef property（tuple of Mapping）
    except Exception:  # noqa: BLE001 - 形态探测失败 → 无行
        return ()
    return tuple(r for r in rows if isinstance(r, Mapping)) if rows else ()


def _as_int(value: object) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _count_range(row: Mapping[str, Any]) -> tuple:
    """参战数随机区间 (lo, hi)：min/max 缺省回退行 `count`（同场存量，缺省 1）。"""
    lo = _as_int(row.get(ENCOUNTER_MIN_KEY))
    hi = _as_int(row.get(ENCOUNTER_MAX_KEY))
    if lo is None and hi is None:
        base = _as_int(row.get("count"))
        base = base if base is not None and base >= 1 else 1
        return base, base
    if lo is None or lo < 1:
        lo = 1
    if hi is None or hi < 1:
        hi = lo
    if hi < lo:
        hi = lo
    return lo, hi


def roll_encounter(
    map_entry: object, rng: Optional[random.Random] = None
) -> Optional[Dict[str, Any]]:
    """目标地图主动遭遇 Roll（无命中 → None）。

    逐行扫描 `monsters[]`：`encounter_chance`（0-100 百分数）> 0 才参与；`rng.random()*100
    < chance` 命中 → 参战数在 `[min, max]`（缺省回退 `count`）内 `rng.randint`；首行命中即返回。
    无任何可触发行 → None（不消耗 rng）。
    """
    candidates = []
    for row in _monster_rows(map_entry):
        chance = row.get(ENCOUNTER_CHANCE_KEY)
        if not isinstance(chance, (int, float)) or isinstance(chance, bool):
            continue
        if chance <= 0:
            continue
        candidates.append((row, min(float(chance), 100.0)))
    if not candidates:
        return None
    if rng is None:
        rng = random.Random()
    for row, chance in candidates:
        if rng.random() * 100.0 < chance:
            lo, hi = _count_range(row)
            enemy = row.get("enemy")
            return {
                "enemy": enemy if isinstance(enemy, str) else None,
                "count": rng.randint(lo, hi),
                "chance": chance,
                "min": lo,
                "max": hi,
                "name": row.get("name") if isinstance(row.get("name"), str) else enemy,
            }
    return None
