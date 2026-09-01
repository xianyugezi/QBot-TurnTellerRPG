"""玩家领域类型 PlayerAttributes / EquipmentSlot / Player。

依据：细化_3a_架构分层契约 §3.2（Player 字段要点：qid=QQ 号全局、name、job_id、
level/exp、currencies、属性三层、背包 ItemInstance[]、achievement/title 等）；
细化_3b_玩家属性三层 §4.4 运行时三子层键空间（base / bonus{flat,pct} /
temp{pct,flat} / cond —— 与属性计算管线一一对应）；细化_4a_存储层契约 §1.2
（players 表字段级 schema 唯一数据源）。

frozen=True：玩家快照不可变（U3）；变更经 storage save_player 单事务 upsert
（4a RW-3 / TX-1）。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.types import ItemID, PlayerQID

__all__ = ["PlayerAttributes", "EquipmentSlot", "Player"]


@dataclass(frozen=True)
class PlayerAttributes:
    """玩家属性三层结构（细化_3b §4.4 运行时三子层键空间）。

    - base:  ① 白值层（{} attr_id → float）—— 永久，落玩家存档
    - bonus: ② 加成层，子键固定为 'flat'/'pct' 两组
    - temp:  ③ 临时层，子键固定为 'pct'/'flat'（战斗 buff，结尾清楚）
    - cond:  条件加成产出（flat，终值桶，防无限叠乘）
    管线：白值+bonus.flat→基础合计 ×(1+bonus.pct)→加成后属性 ×(1+temp.pct)
    +temp.flat+cond→最终属性（细化_3b §2.1）。
    """

    base: Dict[str, float] = field(default_factory=dict)
    bonus: Dict[str, Dict[str, float]] = field(default_factory=lambda: {"flat": {}, "pct": {}})
    temp: Dict[str, Dict[str, float]] = field(default_factory=lambda: {"pct": {}, "flat": {}})
    cond: Dict[str, float] = field(default_factory=dict)

    def flat_bonus(self) -> Dict[str, float]:
        """加成层数值（flat）便捷访问。"""
        return self.bonus.get("flat", {})

    def pct_bonus(self) -> Dict[str, float]:
        """加成层百分比（pct）便捷访问。"""
        return self.bonus.get("pct", {})

    def temp_pct(self) -> Dict[str, float]:
        """临时层百分比（战斗 buff）便捷访问。"""
        return self.temp.get("pct", {})

    def temp_flat(self) -> Dict[str, float]:
        """临时层固定值便捷访问（ADR-01 扩展）。"""
        return self.temp.get("flat", {})


@dataclass(frozen=True)
class EquipmentSlot:
    """装备槽实例（装备实例持久化，槽位 → 槽对象）。

    依据：细化_4a 存储层契约 §1.2 equipment（{item_id, name, slot_level,
    locked(强化锁定概率), gems...}）；slot_level = 强化等级；locked = 强化锁定
    概率随装备实例持久化（随存档，不另存）。
    """

    item_id: ItemID
    name: str                                 # 冗余名称（MIG-3）
    slot_level: int = 0                       # 强化等级
    locked: bool = False                      # 强化锁定概率持久化
    gems: Tuple[str, ...] = ()                # 镶嵌宝石 ID（tuple 冻结语义）


@dataclass(frozen=True)
class Player:
    """玩家主档（运行实例；持久化到 players 宽表 §1.2）。

    qid = 玩家数据 key = QQ 号（全局，跨群/私聊同一角色）——群号仅记录
    在 last_seen_group，绝不是存档键（4a SCHEMA-3 / 3a D-06）。
    """

    qid: PlayerQID
    name: str                                 # 角色名（≤20 字，过滤控制字符）
    job_id: str = "novice"                    # 职业 ID
    level: int = 1
    exp: int = 0
    hp: int = 1
    mp: int = 1
    currencies: Dict[str, int] = field(default_factory=dict)          # 货币 ID → 数量
    inventory: Tuple[ItemInstance, ...] = ()                          # 背包实例数组
    equipment: Dict[str, EquipmentSlot] = field(default_factory=dict) # 槽位 → 槽实例
    attributes: PlayerAttributes = field(default_factory=PlayerAttributes)
    # M11 批1 路1A（G12）：achievement_state 迁移为持久化段形态——旧版为已达成
    # ID 元组（Tuple[str,...]）；成就引擎读写 {unlocked, repeat_count} 两子段。
    # 存档登记先例：字段登记由框架 3.7 持久化语义总表承载（4c §4.1），本 dataclass
    # 字段保留（旧档兼容读取/迁移），运行期成就状态经 context.py _ps_init 挂回
    # persistent_state["achievement_state"]（ctx["achievement_state"] 键，写入即落档）。
    achievement_state: Any = field(default_factory=dict)              # {unlocked:{ID:ISO}, repeat_count:{ID:N}}
    title_state: Dict[str, str] = field(default_factory=dict)         # 当前佩戴称号
    persistent_state: Dict[str, object] = field(default_factory=dict) # 非会话持久（checkin/shop/resource/time/dummy_log）
    longline_counters: Dict[str, int] = field(default_factory=dict)   # 长线计数（只增不减）
    reputation_state: Dict[str, int] = field(default_factory=dict)    # 声望等级+值（按板独立）
    codex_state: Dict[str, object] = field(default_factory=dict)      # 图鉴解锁+完成度
    content_pack_id: str = ""
    content_pack_version: str = ""
    schema_version: int = 4                                           # 内容包 schema_version（当前 5，默认 4 兼容）
    last_seen_group: Optional[str] = None                             # 群号仅作来源记录，非存档键
    created_at: str = ""                                              # ISO-8601 UTC
    last_active_at: str = ""                                          # ISO-8601 UTC（30 天回收判据）
