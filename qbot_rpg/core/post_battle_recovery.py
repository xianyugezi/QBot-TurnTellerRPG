"""批37 · X12 战后恢复引擎（`post_battle_recovery`）——纯函数 + ctx 落点。

依据：
  - 【框架】L294「### 3.13 等级上限与战后恢复（v2.6）」；
  - 【框架】L298 `- 【战后恢复（默认关闭）】：胜利后回复 HP/MP 比例 + 安全区回复`；
  - 【框架】L299 `  · 默认关闭（花钱治疗本身是资源循环的一部分）`；
  - 【框架】L300 `  · 用户可开启：战后治疗比例 / 安全区停留回复`；
  - 3h §4.2 `post_battle_recovery` 段 schema（`enabled` / `heal_ratio` / `safe_zone_heal`）；
  - 3h §L232 消费落点 = 1g 战斗结算链（胜利方结算后按比例回复）。

口径（定稿 → 实现）：
  · **触发**：仅 `win`（胜利后），由接线层判定；本引擎不做胜负判定（纯函数只算）。
  · **对象**：HP 与 MP 都回复（定稿 L298「HP/MP」）。
  · **量**：比例（非固定值）——`heal = int(max × ratio)`，加到当前值后**封顶 max**，
    且**只增不减**（升级回满后当前值可能大于旧快照 max，此时保持不变）。
  · **默认关**：`enabled` 非 `true` → 零操作（缺省内容包行为与现状逐字段一致）。
  · **数值大小**：定稿未给；`heal_ratio=0.2 / safe_zone_heal=0.1` 沿用 3h §4.2，
    其合法性无定稿依据 → `docs/战后恢复_实现口径.md` §四 D1 待用户裁决。

复用（不新开）：只写 `ctx["player"]`（与 `_sync_battle_vitals` 同落点，存档链路不变）；
不触碰战斗引擎快照 → 战斗内数值零影响；提示文案走模板表（本模块不内嵌文案）。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；零 IO；防御降级不抛异常。
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any, Mapping, MutableMapping, Optional, Tuple

__all__ = [
    "DEFAULT_HEAL_RATIO",
    "DEFAULT_SAFE_ZONE_HEAL",
    "SECTION_KEY",
    "RecoveryConfig",
    "compute_recovery",
    "parse_config",
    "recover_after_battle",
]

# settings 段键（3h §4.2）
SECTION_KEY: str = "post_battle_recovery"

# 缺省比例（3h §4.2；**无定稿依据**——定稿只写「比例」不给数值，见实现口径 §四 D1）
DEFAULT_HEAL_RATIO: float = 0.2
DEFAULT_SAFE_ZONE_HEAL: float = 0.1


@dataclasses.dataclass(frozen=True)
class RecoveryConfig:
    """战后恢复段归一结果（纯数据；缺省 = 关闭）。"""

    enabled: bool = False
    heal_ratio: float = DEFAULT_HEAL_RATIO
    safe_zone_heal: float = DEFAULT_SAFE_ZONE_HEAL


def _ratio(raw: Any, default: float) -> float:
    """比例归一：数值且在 [0,1] → 原值；非法/越界 → clamp 到 [0,1]（防御降级）。"""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return float(default)
    val = float(raw)
    if math.isnan(val) or math.isinf(val):
        return float(default)
    return max(0.0, min(1.0, val))


def parse_config(settings: Any) -> RecoveryConfig:
    """settings（Mapping）→ RecoveryConfig。

    段缺失 / 非对象 / `enabled` 非 True → 关闭（定稿 L299「默认关闭」）。
    `heal_ratio` 缺省取 3h §4.2 的 0.2（见模块头 D1）；`safe_zone_heal` 缺省 0.1。
    """
    if not isinstance(settings, Mapping):
        return RecoveryConfig()
    section = settings.get(SECTION_KEY)
    if not isinstance(section, Mapping):
        return RecoveryConfig()
    enabled = section.get("enabled") is True
    return RecoveryConfig(
        enabled=enabled,
        heal_ratio=_ratio(section.get("heal_ratio"), DEFAULT_HEAL_RATIO),
        safe_zone_heal=_ratio(section.get("safe_zone_heal"), DEFAULT_SAFE_ZONE_HEAL),
    )


def compute_recovery(cur: Any, max_value: Any, ratio: Any) -> Tuple[int, int]:
    """单轴恢复：返回 `(new_value, healed)`。

    `heal = int(max_value × ratio)`；`new = max(cur, min(max_value, cur + heal))`。
    - 满值 / ratio ≤ 0 / max ≤ 0 / 非数值 → `(cur, 0)`（零操作，不报错）；
    - 只增不减：`cur > max_value` 时 `healed = 0`（升级回满后旧快照 max 偏小的防御）。
    """
    try:
        cur_i = int(cur)
    except (TypeError, ValueError):
        cur_i = 0
    try:
        max_i = int(max_value)
    except (TypeError, ValueError):
        return cur_i, 0
    if max_i <= 0 or isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
        return cur_i, 0
    if math.isnan(float(ratio)) or math.isinf(float(ratio)) or float(ratio) <= 0:
        return cur_i, 0
    heal = int(max_i * float(ratio))
    if heal <= 0:
        return cur_i, 0
    target = min(max_i, cur_i + heal)
    new_val = max(cur_i, target)   # 只增不减
    return new_val, new_val - cur_i


def _axis_of(player: Any, key: str) -> int:
    """读当前 HP/MP：Mapping（dict 形态）→ 取键；对象（Player）→ 取属性；缺省 0。"""
    if isinstance(player, Mapping):
        try:
            return int(player.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0
    try:
        return int(getattr(player, key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _write_player(ctx: Any, player: Any, hp: int, mp: int) -> None:
    """HP/MP 写回（与 `_sync_battle_vitals` 同落点）。

    Player（frozen dataclass）→ `dataclasses.replace` 重建写回 `ctx["player"]`；
    dict 形态 → 就地改写；ctx 可写时同步镜像 `ctx["hp"]/ctx["mp"]`。
    """
    cur_ctx = ctx if isinstance(ctx, MutableMapping) else None
    try:
        from qbot_rpg.data import Player  # noqa: PLC0415 - 与 _sync_battle_vitals 同口径

        if isinstance(player, Player):
            rebuilt = dataclasses.replace(player, hp=hp, mp=mp)
            if cur_ctx is not None:
                cur_ctx["player"] = rebuilt
                cur_ctx["hp"] = hp
                cur_ctx["mp"] = mp
            return
    except Exception:  # noqa: BLE001 - Player 形态探测失败 → 回落 dict 分支
        pass
    if isinstance(player, MutableMapping):
        player["hp"] = hp
        player["mp"] = mp
    if cur_ctx is not None:
        cur_ctx["hp"] = hp
        cur_ctx["mp"] = mp


def recover_after_battle(ctx: Any, snapshot: Any, settings: Any) -> Optional[dict]:
    """战斗结束时应用战后恢复（**只在 ctx 玩家档上生效**，不动引擎快照）。

    调用时机：接线层在 `win` 结算之后、结束消息发送之前。
    返回 `None` = 未开启 / 无可恢复（无变化）；否则返回恢复明细：
      `{hp_before, hp, hp_max, hp_healed, mp_before, mp, mp_max, mp_healed}`。
    """
    cfg = parse_config(settings)
    if not cfg.enabled:
        return None
    player = ctx.get("player") if isinstance(ctx, Mapping) else None
    if player is None:
        return None
    sp = snapshot.get("player") if isinstance(snapshot, Mapping) else None
    if not isinstance(sp, Mapping):
        return None

    def _maxi(key: str) -> int:
        try:
            return int(sp.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    max_hp = _maxi("max_hp")
    max_mp = _maxi("max_mp")
    cur_hp = _axis_of(player, "hp")
    cur_mp = _axis_of(player, "mp")
    new_hp, hp_healed = compute_recovery(cur_hp, max_hp, cfg.heal_ratio)
    new_mp, mp_healed = compute_recovery(cur_mp, max_mp, cfg.heal_ratio)
    if hp_healed <= 0 and mp_healed <= 0:
        return None   # 满血/满蓝 / ratio=0 → 无变化，不写回、不出提示行
    _write_player(ctx, player, new_hp, new_mp)
    return {
        "hp_before": cur_hp, "hp": new_hp, "hp_max": max_hp, "hp_healed": hp_healed,
        "mp_before": cur_mp, "mp": new_mp, "mp_max": max_mp, "mp_healed": mp_healed,
    }
