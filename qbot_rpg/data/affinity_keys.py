"""相性通用层键空间注册表（批38 · ④；data 层纯数据模块）。

唯一源：相性池类型 / 材料互动类型 / settings 段键 / 词条行 `requires_affinity` 读取口径——
`core/affinity.py`（计算/查询）与 `content/validator.py`（校验）共用本表，避免两处各写一套枚举
（G0 依赖矩阵 `content → data`、`core → data` 均允许；`content -/-> core`，故共用常量必须落
data 层，与 `data/gear_stats.py` 同先例）。

零 import、零 IO、零业务名（相性 id / 池 id / 词条键全部由内容包声明）。
"""
from __future__ import annotations

from typing import Any, Mapping, Tuple

__all__ = [
    "POOL_COMMON",
    "POOL_EXCLUSIVE",
    "POOL_LINKAGE",
    "POOL_KINDS",
    "REACTION_CONFLICT",
    "REACTION_AMPLIFY",
    "REACTION_REVERSE",
    "REACTION_KINDS",
    "AFFINITY_KEYS",
    "affinity_requires",
    "ENTRY_PAYLOAD_STAT",
    "ENTRY_PAYLOAD_SET_AFFIX",
    "ENTRY_PAYLOAD_EFFECT_REF",
    "ENTRY_PAYLOAD_ENHANCE_AFFIX",
    "ENTRY_PAYLOAD_KEYS",
]

# 池类型（内容包声明 kind；框架只认这三类结构语义）
POOL_COMMON = "common"
POOL_EXCLUSIVE = "exclusive"
POOL_LINKAGE = "linkage"
POOL_KINDS: Tuple[str, ...] = (POOL_COMMON, POOL_EXCLUSIVE, POOL_LINKAGE)

# 材料互动三类（原案 §12：互相减少 / 互相增加 / A→B 转换）
REACTION_CONFLICT = "conflict"
REACTION_AMPLIFY = "amplify"
REACTION_REVERSE = "reverse"
REACTION_KINDS: Tuple[str, ...] = (REACTION_CONFLICT, REACTION_AMPLIFY, REACTION_REVERSE)

# settings 顶层四段（唯一数据落点；引擎/校验/编辑器共用）
AFFINITY_KEYS: Tuple[str, ...] = (
    "affinities", "affinity_pools", "affinity_linkage", "affinity_reactions",
)

# 相性池词条行**载荷键**（框架 schema；内容包在 settings.affinity_pools[].entries[] 声明）。
# 唯一源落 data 层：`core/deep_craft.py`（批42 抽取引擎）与 `content/validator.py`
# （校验）均引用本表——content 层不得 import core，故共用常量必须落 data（同 gear_stats 先例）。
#   · stat          → 随机属性候选（键 = 属性键；数值取同行 `value`）
#   · set_affix     → 随机套装词条候选（值 = 套装词条 id）
#   · effect_ref    → 效果引用候选（占位/留待消费）
#   · enhance_affix → **批43 强化特殊词条候选**（值 = data/gear_stats.py 已登记词条键；
#                     数值取同行 `value`）——键空间唯一源仍是 gear_stats，不得在此新造键。
ENTRY_PAYLOAD_STAT: str = "stat"
ENTRY_PAYLOAD_SET_AFFIX: str = "set_affix"
ENTRY_PAYLOAD_EFFECT_REF: str = "effect_ref"
ENTRY_PAYLOAD_ENHANCE_AFFIX: str = "enhance_affix"
ENTRY_PAYLOAD_KEYS: Tuple[str, ...] = (
    ENTRY_PAYLOAD_STAT, ENTRY_PAYLOAD_SET_AFFIX,
    ENTRY_PAYLOAD_EFFECT_REF, ENTRY_PAYLOAD_ENHANCE_AFFIX,
)


def affinity_requires(entry: Any) -> Tuple[str, ...]:
    """词条行 `requires_affinity`（str 或 list）→ 相性 id 元组（缺省空 = 通用）。"""
    if not isinstance(entry, Mapping):
        return ()
    req = entry.get("requires_affinity")
    if isinstance(req, str):
        return (req,) if req else ()
    if isinstance(req, (list, tuple)):
        return tuple(str(x) for x in req if isinstance(x, str) and x)
    return ()
