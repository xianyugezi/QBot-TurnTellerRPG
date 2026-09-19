"""批46 · 符文地基（43-A）——符文基础刻度与纯解析（qbot_rpg/data/runes.py）。

定位：**data 层**——符文三阶刻度常量 + 与内容校验共用的**纯解析**（阶位/缺省孔位）。
放 data 层的原因（架构矩阵 `scripts/check_architecture.py:42`：`content → {data}`）：
`content/rune_models.validate_runes` 需要「阶枚举/阶位解析」做红拦，但 content **不得**
import core；故把这些口径常量与解析收敛到 data 层，`core/runes.py`（引擎）与
`content/rune_models.py`（校验）**同源引用**（不各写一套）。

依据：
  - `/root/deliverables/符文系统_实现口径.md` §二.1 形状草案 + 校验点 1/2；
  - `docs/深度打造_决策记录.md` H2（符文三阶 = **独立**刻度，禁与 quality 四档混）；
  - 原案 `打造系统_原案_20260919.md` §9（三阶 / 固定三孔）。

【工程补白】阶位只读 `tier` 字段；`quality` 一律忽略（H2 正交）。命名/落点可由用户覆盖。
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

__all__ = [
    "DEFAULT_EQUIP_TYPE_KEY",
    "DEFAULT_SOCKET_COUNT",
    "MAX_RUNE_TIER",
    "MIN_RUNE_TIER",
    "RUNES_STATE_KEY",
    "RUNE_TIERS",
    "RUNE_TYPE",
    "RUNE_UPGRADE_COUNT",
    "next_rune_tier",
    "rune_tier_of",
    "socket_count_of",
]

# 符文 items.type 值（口径 §二.5：对齐既有 items.type="装饰珠"，core/jewel.py:89）
RUNE_TYPE: str = "符文"

# 三阶刻度（原案 §9；独立于 quality 四档，H2）
MIN_RUNE_TIER: int = 1
MAX_RUNE_TIER: int = 3
RUNE_TIERS: Tuple[int, ...] = (MIN_RUNE_TIER, 2, MAX_RUNE_TIER)

# 3 合 1 输入个数（原案 §9「3 合一」；对齐 core/upgrade.py _exec_jewel count≥3）
RUNE_UPGRADE_COUNT: int = 3

# 镶嵌状态落档容器键（口径 §二.2b：persistent_state["rune_sockets"] = {uid: [rune_id|null,...]}）
RUNES_STATE_KEY: str = "rune_sockets"

# 缺省孔位数（口径 §二.2a；原案 §9「固定三个孔位」）
DEFAULT_SOCKET_COUNT: int = 3

# 差异表兜底键（口径 §二.1：by_equip_type 必须含 default）
DEFAULT_EQUIP_TYPE_KEY: str = "default"


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """Mapping 归一（其余 → 空 Mapping）。"""
    return value if isinstance(value, Mapping) else {}


def _to_int(value: Any) -> Optional[int]:
    """int 归一（bool 除外）；非 int/可转数字串 → None（对齐 jewel/upgrade 口径）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if float(value).is_integer() else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def rune_tier_of(rune_def: Any) -> Optional[int]:
    """符文阶位解析（`tier ∈ {1,2,3}` **独立刻度**；绝不读 `quality`）。

    入参：rune_def 符文定义（Mapping；Def 对象请先取 `.raw`）。
    出参：int 1/2/3；缺省/非法/越界 → None（校验层红拦；引擎侧防御降级）。
    """
    d = _as_mapping(rune_def)
    t = _to_int(d.get("tier"))
    if t is None or not (MIN_RUNE_TIER <= t <= MAX_RUNE_TIER):
        return None
    return t


def next_rune_tier(tier: Any) -> Optional[int]:
    """下一阶（3 合 1 的 +1 阶；满阶 → None = 无可再升/链终点）。"""
    t = _to_int(tier)
    if t is None or t < MIN_RUNE_TIER or t >= MAX_RUNE_TIER:
        return None
    return t + 1


def socket_count_of(rune_sockets_cfg: Any, default: int = DEFAULT_SOCKET_COUNT) -> int:
    """缺省孔位数解析（`settings.rune_sockets.default_count`，1..3 合法）。

    入参：rune_sockets_cfg = settings.rune_sockets 段（Mapping/缺省）；default 兜底值。
    出参：int 1..3（非法/越界 → default；default 自身也钳到 1..3 防御）。
    """
    fallback = _to_int(default)
    if fallback is None or not (1 <= fallback <= 3):
        fallback = DEFAULT_SOCKET_COUNT
    cfg = _as_mapping(rune_sockets_cfg)
    v = _to_int(cfg.get("default_count"))
    if v is None or not (1 <= v <= 3):
        return fallback
    return v
