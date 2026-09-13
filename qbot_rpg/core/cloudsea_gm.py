# -*- coding: utf-8 -*-
"""九期237（G6 存档与 GM）：cloudsea_state v2 迁移面＋GM 十指令 spec＋三级溯源诊断包。

三件（任务书「cloudsea_state 列 v1→v2 迁移＋GM 十指令扩展＋三级溯源诊断包」）：
1. **cloudsea_state v2**：storage/migrations.py `DB_SCHEMA_VERSION=2`＋
   `migrate_v1_to_v2`（players 补 cloudsea_state 列，MIG-1 缺补默认）——本模块
   提供 ``CLOUDSEA_STATE_VERSION = 2`` 常量与列缺省文档。
2. **GM 十指令扩展**：``CLOUDSEA_GM_COMMANDS`` 十条运维 spec（前缀沿用 GM
   体系；spec 只声明名/参数/权限/描述/处理键，指令实现由宿主按 spec 路由）。
3. **三级溯源诊断包**：``diagnostic_pack(level, ...)``——L1 概览统计／
   L2 玩家明细／L3 原始快照，纯函数装配，IO 由调用方注入。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

__all__ = [
    "CLOUDSEA_STATE_VERSION",
    "CLOUDSEA_GM_COMMANDS",
    "diagnostic_pack",
]

#: cloudsea_state 列结构版本（v2＝内容包状态独立列引入）
CLOUDSEA_STATE_VERSION = 2

#: GM 十指令（运维面 spec；执行器路由由装配层接线，本表为权威清单）
CLOUDSEA_GM_COMMANDS: Dict[str, Dict[str, str]] = {
    "cs查状态": {"args": "<玩家>", "perm": "gm", "desc": "查玩家云海状态总览（等级/潮位/熟练度/活动计数）"},
    "cs补发": {"args": "<玩家> <物品> <数量>", "perm": "gm", "desc": "补发道具/材料（出入库登记）"},
    "cs清冷却": {"args": "<玩家>", "perm": "gm", "desc": "清空玩家制造/招式冷却"},
    "cs跳日": {"args": "[N]", "perm": "gm", "desc": "游戏日推进 N 天（缺省 1，沿 215H 合成时钟）"},
    "cs重置活动": {"args": "<活动ID>", "perm": "gm", "desc": "重置指定赛季轮替活动计数"},
    "cs发符文": {"args": "<玩家> <符文> [档]", "perm": "gm", "desc": "发放指定符文（活化态缺省 Lv1）"},
    "cs看池": {"args": "[域]", "perm": "gm", "desc": "查典录域收集进度（缺省全域概览）"},
    "cs诊断": {"args": "<玩家> [级别]", "perm": "gm", "desc": "三级溯源诊断包（1 概览/2 明细/3 原始）"},
    "cs回档检查": {"args": "[玩家]", "perm": "gm", "desc": "存档一致性体检（破坏绑定/轴值/池余量）"},
    "cs重载内容": {"args": "", "perm": "gm", "desc": "内容包热重载（沿 GM 重载同权）"},
}


def diagnostic_pack(
    level: int,
    *,
    overview: Optional[Mapping[str, Any]] = None,
    player_detail: Optional[Mapping[str, Any]] = None,
    raw: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """三级溯源诊断包（纯函数装配：数据由调用方注入，本函数只裁剪分级）。

    - level 1：概览统计（overview 段）；
    - level 2：概览＋玩家明细（player_detail 段）；
    - level 3：全量（raw 原始快照段——溯源终态）。
    越级参数忽略、缺段以 null 占位，保证三级形态稳定可diff。
    """
    level = max(1, min(3, int(level)))
    pack: Dict[str, Any] = {"level": level, "overview": overview}
    if level >= 2:
        pack["player_detail"] = player_detail
    if level >= 3:
        pack["raw"] = raw
    return pack
