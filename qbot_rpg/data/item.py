"""物品实例领域类型 ItemInstance。

依据：细化_3a_架构分层契约 §3.2（ItemInstance 字段要点：item_id+name 冗余、
quality 四档、bound、count、装备槽位/词条 stats_bonus、冷却计时）；
细化_4a_存储层契约 §1.2（inventory JSON：{item_id, name, count, stack_max,
bound, quality, traits...}，ID+名称冗余 SCHEMA-5）；细化_4b_物品与背包契约
（物品实例语义：绑定不可赠送/掉落、品质、词条、冷却）。

frozen=True：实例一经构造不可变，防战斗/结算中被误改（细化_3a §3.2，U3）。

批40 · H4（实例唯一键）：`uid` = 落档实例身份，解「同 item_id 多件随机词条实例
跨存档/重登后聚合错实例」（打造系统_C E1/Q1；equipment.py:43-46 登记的未解项）。
生成口径见 `new_item_uid()`（唯一事实来源，勿在别处另生成）。
"""

import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from qbot_rpg.data.types import ItemID

__all__ = ["ItemInstance", "new_item_uid"]


def new_item_uid() -> str:
    """新物品实例唯一键（uid）生成器——**全仓唯一生成口径**。

    入参：无。出参：32 位小写十六进制字符串。
    核心逻辑：`uuid.uuid4().hex`——沿用仓库既有 id 生成风格
    （`commands/gm_commands.py`、`content/audit_store.py`、`core/battle.py`
    快照 id 同为 uuid4().hex）；不引入新依赖（uuid 为标准库）。
    唯一性：uuid4 随机 122 bit 空间，单玩家/全局碰撞概率可忽略；**新增实例一律
    经本函数取键**（`ItemInstance.__post_init__` 在 uid 为空时自动调用），不得在
    调用点各自拼字符串。旧档补发走存档迁移（storage/migrations，幂等）。
    """
    return uuid.uuid4().hex


@dataclass(frozen=True)
class ItemInstance:
    """玩家持有的物品实例（运行时实例，非内容包配置 ItemDef）。

    item_id+name 冗余存储（SCHEMA-5 / MIG-3：引用按 ID 存储、显示按名字，
    换包后旧条目仍可按旧名显示）。

    uid（批40 · H4）：实例落档唯一键。装备槽/交易/使用/掉落等「哪一件」的精确
    引用以 uid 为准（EquipmentSlot.uid 回指本字段）。`compare=False`——保持既有
    `==` 的结构等价语义（同 item_id/品质/词条等），实例同一性判定走显式 uid 比较，
    避免旧调用点/旧测试的相等性语义突变。旧档无 uid → 空串（读取兜底按 item_id，
    迁移步补发后转精确）。
    """

    item_id: ItemID
    name: str                                  # 冗余名称（MIG-3）
    count: int                                 # 堆叠数量
    quality: str                               # 品质（四档枚举，细化_3a §3.2）
    bound: bool                                # 绑定物品不可赠送/掉落
    stack_max: int = 99                        # 堆叠上限（4a §1.2 inventory 行格式字段；默认值对齐 4b ITM-07 items.json 定义级默认 99）
    slot: Optional[str] = None                 # 装备槽位（可装备时）
    stats_bonus: Dict[str, float] = field(default_factory=dict)  # 装备词条/虚拟属性键（细化_3b §4.1 ele_atk_*）
    traits: Tuple[str, ...] = ()               # 特性（tuple 保证冻结语义）
    cooldown_until: Optional[str] = None       # 冷却计时（ISO-8601 UTC）
    enhance_level: int = 0                     # 强化等级 +N（M12.5 强化接线：装备实例级
                                               # 持久化；穿装同步 EquipmentSlot.slot_level）
    uid: str = field(default="", compare=False)  # 实例落档唯一键（批40 · H4；见类 docstring）
    # ---- 批42 · C：打造产物的相性 / 套装词条 / 装备被动（打造时求值、冻进实例；原案
    # §3/§4/§8/§11）。全部 default 空 → 既有实例/非打造物品零影响（对拍）。----
    # 相性结算值 `{相性id: 数值}`（主/副相性从中判定；打造时写入，供后续强化/附魔复用）。
    affinities: Dict[str, float] = field(default_factory=dict)
    # 套装词条（固定 1 + 随机 0~2；同名词条件数用于套装激活，原案 §4）。
    set_affixes: Tuple[str, ...] = ()
    # 装备被动（模板固定 + 相性变更后的最终 id；原案 §11）。
    passives: Tuple[str, ...] = ()
    # ---- 批43：强化上限键与特殊词条载荷（原案 §7；H3 上限按品质等级取）----
    # 品质等级（1~10；打造产物写入；旧档/普通物品 0 = 走旧档品质桥接读上限）。
    quality_level: int = 0
    # 强化特殊词条键序列（每满 `special_affix_span` 级一条；键 ∈ data/gear_stats.py
    # 唯一源，数值已并入 stats_bonus；冷却缩减等占位键只登记不接引擎）。
    enhance_affixes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """uid 缺省自动补发（frozen=True → object.__setattr__）。

        口径：显式传入（旧档读取/迁移/等价重建）→ 原样保留；空串 → `new_item_uid()`。
        这保证「新库直接具备」（任何新建实例天然带 uid），旧档则经迁移步补发。
        """
        if not self.uid:
            object.__setattr__(self, "uid", new_item_uid())
