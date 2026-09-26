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
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from qbot_rpg.data.types import ItemID

__all__ = ["ItemInstance", "new_item_uid", "item_instance_from_mapping"]


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
    # ---- 批57 · 装备淬炼 + 打造档案（原案 §5/§10；决策记录 §5 D12）----
    # 装备等级（打造时 = Σ(材料等级×占比)，由 deep_craft.plan_craft 的 `level` 写入；
    # 淬炼上限 `total_cap = 等级 × cap_per_level` 的唯一输入。旧档/非打造 0 = 无等级，
    # 缺省不可淬炼（`temper.default_level` 可配兜底））。
    required_level: int = 0
    # 淬炼分配（属性键 → 已投点数；**分账**于 `enhance_level`，是上限判定/分解返还/
    # 规划展示的唯一事实源）。数值增量经 `core/temper.materialize_temper` **物化进
    # `stats_bonus`** → 面板聚合/战斗桥/展示零改动。默认空 → 既有实例零影响（对拍）。
    temper_alloc: Dict[str, int] = field(default_factory=dict)
    # ---- 批61 · 口径 B 附加型：相性抽中的「追加效果/状态」引用（spec §4.4 B-2）----
    # 值 = 炼金结算时由相性池 `effect_ref` 载荷抽中的效果 id 序列；使用时由
    # `commands/use_commands._use_consumable` 分派（非战斗三类并入既有分支，其余落既有
    # `active_effects` 状态桶）。**默认空元组** → 既有实例/商店药剂/非炼金产物零影响（对拍）。
    effect_refs: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """uid 缺省自动补发（frozen=True → object.__setattr__）。

        口径：显式传入（旧档读取/迁移/等价重建）→ 原样保留；空串 → `new_item_uid()`。
        这保证「新库直接具备」（任何新建实例天然带 uid），旧档则经迁移步补发。
        """
        if not self.uid:
            object.__setattr__(self, "uid", new_item_uid())


def item_instance_from_mapping(raw: Mapping[str, Any]) -> ItemInstance:
    """dict 行 → `ItemInstance` 归一（写路径**公共归一函数**，唯一源）。

    依据：《手册·1》§3.1 构造点清单 + §3.4「收敛而非补齐」——`assembly/runner.py`
    的 `_ctx_inventory_to_player`（ctx `inventory_instances` 行）与
    `commands/basic_commands.py` 的 `/装备` dict 归一，原为两份**内联**构造，
    逐批补字段时只补一处即丢字段（批82 · Q4/N2/N3/N5：`effect_refs` / `stack_max`
    在两条链路静默丢失，回落默认值）。本函数把两条链路收敛为**同一处定义**，
    字段集与读档 codec `storage.repository._item_from_dict`（20/20）对齐，以后新增
    `ItemInstance` 字段只改这里 + 读 codec 两处。

    入参：`raw` —— 形如 `dataclasses.asdict(ItemInstance)` 的 dict 行（缺键容忍）。
    出参：`ItemInstance`。核心逻辑：逐字段读取，与既有内联归一**逐字段同口径**
    （缺省补默认、非法值过滤），并**保留全部 20 字段**——本次补回两条链路原丢的
    `stack_max` / `cooldown_until` / `effect_refs`。

    边界：`effect_refs` 只收非空 str（保序、**不去重**，与既有 runner 内联一致；
    读档 codec `_effect_refs_of` 另行去重，是读取侧口径，本函数不改动）。
    `stats_bonus` / `affinities` / `temper_alloc` 非 Mapping → 取默认空。
    """
    _sb = raw.get("stats_bonus")
    _aff = raw.get("affinities")
    _ta = raw.get("temper_alloc")
    return ItemInstance(
        item_id=str(raw.get("item_id") or ""),
        name=str(raw.get("name") or ""),
        count=int(raw.get("count", 1)),
        quality=str(raw.get("quality") or "normal"),
        bound=bool(raw.get("bound", False)),
        # N3：stack_max 原两条归一均漏 → 回落默认 99（`stack_max=1` 的实例变"可堆叠"）；
        # 按读档 codec 同口径补读（缺省 99）。
        stack_max=int(raw.get("stack_max", 99) or 99),
        slot=str(raw.get("slot")) if raw.get("slot") else None,
        stats_bonus=dict(_sb) if isinstance(_sb, Mapping) else {},
        traits=tuple(raw.get("traits") or ()),
        cooldown_until=raw.get("cooldown_until"),
        enhance_level=int(raw.get("enhance_level", 0) or 0),
        uid=str(raw.get("uid") or ""),
        affinities={str(k): float(v) for k, v in _aff.items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)}
        if isinstance(_aff, Mapping) else {},
        set_affixes=tuple(raw.get("set_affixes") or ()),
        passives=tuple(raw.get("passives") or ()),
        quality_level=int(raw.get("quality_level", 0) or 0),
        enhance_affixes=tuple(raw.get("enhance_affixes") or ()),
        required_level=int(raw.get("required_level", 0) or 0),
        temper_alloc={str(_k): int(_v) for _k, _v in (_ta or {}).items()
                      if isinstance(_v, int) and not isinstance(_v, bool) and _v > 0}
        if isinstance(_ta, Mapping) else {},
        # N2：effect_refs 原仅 runner 链路保留、`/装备` 链路漏（写回背包永久丢失）；
        # 本函数统一保留（只收非空 str，保序）。
        effect_refs=tuple(x for x in (raw.get("effect_refs") or ())
                          if isinstance(x, str) and x),
    )
