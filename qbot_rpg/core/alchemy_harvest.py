"""第 2 层种植收获引擎（M8 批10·路10A · qbot_rpg/core/alchemy_harvest.py）——HarvestEngine。

文件名：qbot_rpg/core/alchemy_harvest.py
创建时间：2026-08-29
作者：Hermes 子agent-10A（并发同仓：仅新建本文件 + tests/unit/test_alchemy_harvest.py；
      兄弟路 10B 在写 core/alchemy_helper.py（代工引擎），本文件零 import 之，只读勿探查）

功能描述：HarvestEngine 承载第 2 层【种植/温室】（GU-60/61 + F-21）的全部业务逻辑——种植
  （/种植 <种子>：职业 ≥ 正式 → 种子存在且带 seed 标记 → 空闲地块 → 消耗 1 颗种子入地块
  {seed, planted_at, harvest_at}）/ 定时收获（/收获：收全部成熟地块 → 收获品质 ≥ 种子品质、
  种子继承特性 → 地块清空）/ 温室（大师解锁：复制一种素材 耗宝石/金币 → 素材入包 滚雪球）/
  地块存档（player.farm_plots dict 查看）。纯函数零 IO 零 NoneBot；返回 dict 结果、
  拒绝场景 {ok: False, reason, message} 不抛异常。

依据：
  - docs/m8_contract_指令契约.md §20（/种植 /收获：GU-60/61、F-21、M-21、数据落点）：
    GU-60 炼金职业 ≥ 正式 → GU-61 种子存在且带 seed 标记；空闲地块存在。
    F-21：种→等（定时收获默认 4 小时可配）→ /收获：收获品质 ≥ 种子品质、种子继承特性 →
    温室（大师解锁）：可复制一种素材（耗宝石/金币）→ 种子可群内交易分享 → 地块存档
    （种子+种植时间+收获时间）。M-21：种植「已种植〈种子〉，4 小时后可收获」；收获
    「收获〈材料〉×N（品质 精良·继承特性：…）」——按 M5 裁决（用户拍板「不用 emoji」，
    docs/m5_shared_contract.md §4.1 / 全局图标登记表）装饰性 emoji 一律降级纯文本。
  - /root/docs_archive/RPG框架项目/炼金系统设计定稿.md（下称【炼金】）：L381 items.json
    seed(可种植标记)；L392 种植表 = items.json seed 标记 + 收获表（种子→产出+继承特性）；
    L402 种植地块存档（种子+种植时间+收获时间）；L442-448 种植/温室（定时收获默认 4 小时
    可配 / 种子继承特性 / 收获品质 ≥ 种子品质 / 温室大师解锁复制一种素材 滚雪球 耗宝石/金币 /
    种子可群内交易分享）。
  - /root/docs_archive/RPG框架项目/职业熟练度与生活系统设计定稿.md（下称【熟练度】）：L56-58
    （特性继承项 正式 1/精通 2/专家 3、种植正式解锁）；L92-96（种植/温室）；L155（地块存档）。
  - docs/细化/细化_2c5c_种植品评代工.md 一（FARM-01~10）：FARM-01 消耗 1 颗种子道具占 1 地块 /
    FARM-02 harvest_sec 默认 14400 秒（4 小时）可配、按种植时配置结算 / FARM-03 种子继承特性
    按职业继承项（正式 1/精通 2/专家 3）超出丢弃并提示 / FARM-04 收获品质 ≥ 种子品质 /
    FARM-05 farming.seeds[] 收获表（seed_item/quality_floor/traits/output/harvest_sec）/
    FARM-07 温室大师解锁 / FARM-08 温室复制耗宝石+金币（默认 10/1000）滚雪球 / FARM-10 地块存档。
  - docs/细化/细化_2c4e_品质与特性.md：INH-14（正式 1 项 → 精通 2 项 → 专家 3 项，见习无
    继承位）；STO-06 品质文字档（品质 精良）。
  - 已落地：qbot_rpg/core/quality.py QualitySystem（品质四档判定/档位中文名）、
    qbot_rpg/core/alchemy_core.py（ALCHEMY_JOB_ID / DEFAULT_TIER_NAMES）、content/test_demo
    settings.json alchemy 段（quality_tiers / currencies 含 gem 键空间）。
  - 模式参考 qbot_rpg/core/synthesis.py（构造器注入 + 快照-回滚原子性 + ctx hook）/
    qbot_rpg/core/gem_wallet.py（settings.alchemy 配置单源 / 档位表中文档名键）。

【工程补白 · 显式标注】（定稿/细化未显式定义处，全部按本清单落地；不得新增定稿外机制行为）：
  H-1  种子标记形态（定稿 L381「seed(可种植标记)」+ L392「seed 标记 + 收获表」）：
       items.json 条目 `seed` 字段两形态——① `seed: true` 简单形态：可种植标记，收获产出 =
       种子自身 id，品质/特性 = 种子自身 quality/traits 字段（缺省 0/[]）；② `seed:
       {output, quality_floor, traits, harvest_sec, count}` 收获表形态（L392 种子→产出+继承
       特性）：output 收获素材 id（缺省种子自身 id）、quality_floor 品质下限（缺省种子自身
       quality → 0）、traits 继承特性集（缺省种子自身 traits → []）、harvest_sec 单种子时长
       覆盖（缺省全局，FARM-02 逐种子覆盖）、count 单地块产出量（缺省 1）。
  H-2  种子品质继承口径（FARM-04/TC-16「收获品质 ≥ 种子品质」）：引擎取收获品质 = 种子品质
       下限（H-1 quality_floor 解析值，满足「≥」取等号）；品质形态支持 int 品质分 / 四档键
       common..legendary / 缺省 0（普通档）。「上限受品质上限约束（SP 解锁品质上限+10）」为
       兄弟细化 2c5a 消费点，本引擎不实现，由装配层叠加。
  H-3  特性继承项口径（FARM-03/INH-14）：settings.alchemy.farming.trait_inherit（中文档名键
       {正式:1, 精通:2, 专家:3} 可配，对齐 decompose_rate 形态）；档位超专家 → 取专家值 3；
       见习 → 0；继承条数 = min(cap, 种子特性数)，超出部分丢弃并提示（FARM-03）。SP「特性位
       +1」扩展为兄弟细化消费点，本引擎不实现。
  H-4  地块存档落点（任务指示 player.farm_plots dict + 定稿 L402）：player["farm_plots"] 为
       dict {地块序号(int 1 起): {seed, planted_at, harvest_at}}（对齐任务指示取 dict 形态；
       细化_2c5c FARM-10 名 farming_plots[] 列表形态留待后续批次迁移，本批按任务落地）；
       plots_max 默认 3（FARM-01/细化 FARM-05 补白 3）可配 settings.alchemy.farming.plots_max。
  H-5  温室配置键（任务指示「温室费率配置键」按最小必要推导）：
       settings.alchemy.farming.greenhouse = {unlock_tier: "大师", copy_cost: {gem: 10,
       gold: 1000}}（FARM-07/08；unlock_tier 中文档名 → 档位索引，缺省大师=4；copy_cost 宝石
       +金币双付，缺省 10/1000）。口径冲突注记：m8_contract_战斗资源 SINK-07 言「耗宝石 或
       耗金币（二选一，不可双付——ARB-00 分账）」，与细化_2c5c FARM-08「宝石×N + 金币×M」冲突；
       本批按任务权威依据（细化 2c4e 同体系 FARM-08 双付）落地，copy_cost 置 0 即等效单付，
       SINK-07 分账由装配层按需仲裁。温室方法按任务签名提供单次复制能力
       （greenhouse(player, ctx, seed_id)），FARM-08「复制位随收获联动」编排由批10-2 指令壳
       结合本方法组合实现。
  H-6  消耗种子道具（FARM-01）：/种植 消耗背包 1 颗种子道具（ctx remove_item）；GU-61「种子
       存在」口径 = 注册表存在 + seed 标记 → 再校验持有 ≥ 1 → 原子扣减（缺持有 → 拒绝提示）。
  H-7  收获入包（FARM-06/F-21）：收获产物经 ctx add_item(output, count, bound=False) 入包
       （普通素材可交易，对齐 synthesis 标准版 bound=False 补白；副本滚雪球可再投）。
       产物实例的品质/特性落款（STO-02 堆叠键）为装配层/后续批次责任，引擎结果 dict 携带
       quality/traits 数据供落款。
  H-8  /收获 与 /种植 同享 GU-60（契约 §20 前置守卫覆盖整节）；/收获 无参收全部成熟地块
       （F-21），成熟判定 now >= harvest_at；重载按 harvest_at 重算不重置（FARM-10）；收获超时
       未取无惩罚、地块保持可收（FARM-10 裁定：只建议不限制）。
  H-9  消息模板 M5 纯文本：M-21 模板的 🌱/🌾 装饰性 emoji 按 M5 裁决（用户拍板「不用 emoji」）
       降级纯文本，引擎消息零 emoji（含拒绝场景，区别于既有引擎的 ❌ 前缀——本引擎全纯文本）。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；工程补白显式标注；不新增定稿外机制行为。
"""
from __future__ import annotations

import copy
from typing import Any, List, Mapping, MutableMapping, Optional, Tuple

from qbot_rpg.core.quality import QualitySystem

__all__ = [
    "ALCHEMY_JOB_ID",
    "DEFAULT_TIER_NAMES",
    "DEFAULT_HARVEST_SEC",
    "DEFAULT_PLOTS_MAX",
    "DEFAULT_TRAIT_INHERIT",
    "DEFAULT_GREENHOUSE_UNLOCK_TIER",
    "DEFAULT_GREENHOUSE_COPY_COST",
    "FORMAL_TIER_INDEX",
    "MASTER_TIER_INDEX",
    "HarvestEngine",
]

# ---------------------------------------------------------------------------
# 常量（对齐 alchemy_core / 细化_2c5c FARM / 熟练度 L56-58）
# ---------------------------------------------------------------------------
# 炼金职业 ID（proficiency.json id / jobs.json；对齐 alchemy_core.ALCHEMY_JOB_ID）
ALCHEMY_JOB_ID: str = "alchemy"

# 7 级称号默认名（对齐 alchemy_core.DEFAULT_TIER_NAMES / proficiency.json tier_names）
DEFAULT_TIER_NAMES: Tuple[str, ...] = ("见习", "正式", "精通", "专家", "大师", "宗师", "王")

# 档位索引锚点（tier_index 0 起：见习0/正式1/精通2/专家3/大师4/宗师5/王6）
FORMAL_TIER_INDEX: int = 1   # 正式：种植解锁（熟练度 L56 / GU-60）
MASTER_TIER_INDEX: int = 4   # 大师：温室解锁（熟练度 L60 / FARM-07 / GU 温室）

# 定时收获时长默认 14400 秒（4 小时，FARM-02 / 定稿 L442，可配）
DEFAULT_HARVEST_SEC: int = 14400

# 地块数上限默认 3（FARM-01 / 细化 FARM-05 补白 3，可配）
DEFAULT_PLOTS_MAX: int = 3

# 特性继承项默认（FARM-03 / INH-14：正式 1 / 精通 2 / 专家 3，可配；见习 0，超专家取专家值 3）
DEFAULT_TRAIT_INHERIT: Mapping[str, int] = {"正式": 1, "精通": 2, "专家": 3}

# 温室解锁档默认（FARM-07：大师解锁，可配）
DEFAULT_GREENHOUSE_UNLOCK_TIER: str = "大师"
# 温室复制消耗默认（FARM-08：宝石 10 + 金币 1000，可配；置 0 即等效单付，见工程补白 H-5）
DEFAULT_GREENHOUSE_COPY_COST: Mapping[str, int] = {"gem": 10, "gold": 1000}

# 快照-回滚覆盖的可变子结构（对齐 synthesis 原子防双扣口径）
_SNAP_CTX_KEYS: Tuple[str, ...] = ("currencies", "inventory")
_SNAP_PLAYER_KEYS: Tuple[str, ...] = ("farm_plots",)

# 品质四档键（对齐 QualitySystem.QUALITY_KEYS，H-2 解析种子品质字符串用）
_QUALITY_KEYS: Tuple[str, ...] = ("common", "uncommon", "rare", "legendary")


# ---------------------------------------------------------------------------
# 基础工具（纯函数，镜像 synthesis.py / gem_wallet.py 同款实现）
# ---------------------------------------------------------------------------
def _as_int(value: object) -> Optional[int]:
    """int 归一（bool 除外）；非 int/bool/可转数字串 → None（对齐 synthesis._as_int）。"""
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


def _clamp_int(value: int, lo: int, hi: int) -> int:
    """int 钳制到 [lo, hi]。"""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _item_name(item_id: str, ctx: Mapping[str, Any]) -> str:
    """物品 id → 显示名（ctx[\"items\"] 注册表或 resolve_item 解析器；缺省回退原 id）。"""
    if not isinstance(item_id, str):
        return str(item_id)
    items = ctx.get("items")
    if isinstance(items, Mapping):
        hit = items.get(item_id)
        if isinstance(hit, Mapping):
            name = hit.get("name")
            if isinstance(name, str) and name:
                return name
    resolver = ctx.get("resolve_item")
    if callable(resolver):
        try:
            hit = resolver(item_id)
        except Exception:
            hit = None
        if isinstance(hit, Mapping):
            name = hit.get("name")
            if isinstance(name, str) and name:
                return name
    return item_id


def _trait_name(trait_id: str, ctx: Mapping[str, Any]) -> str:
    """特性 id → 显示名（ctx[\"traits\"] 注册表或 resolve_trait 解析器；缺省回退原 id）。"""
    if not isinstance(trait_id, str):
        return str(trait_id)
    traits = ctx.get("traits")
    if isinstance(traits, Mapping):
        hit = traits.get(trait_id)
        if isinstance(hit, Mapping):
            name = hit.get("name")
            if isinstance(name, str) and name:
                return name
    resolver = ctx.get("resolve_trait")
    if callable(resolver):
        try:
            hit = resolver(trait_id)
        except Exception:
            hit = None
        if isinstance(hit, Mapping):
            name = hit.get("name")
            if isinstance(name, str) and name:
                return name
    return trait_id


def _add_item(ctx: MutableMapping[str, Any], item_id: str, count: int, bound: bool) -> bool:
    """入包：优先 ctx[\"add_item\"] hook；回退 ctx[\"inventory\"] in-memory；均无 → False。"""
    hook = ctx.get("add_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count, bound))
        except Exception:
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        inv[item_id] = int(inv.get(item_id, 0)) + count
        return True
    return False


def _remove_item(ctx: MutableMapping[str, Any], item_id: str, count: int) -> bool:
    """扣减（不部分扣减）：优先 ctx[\"remove_item\"] hook；回退 ctx[\"inventory\"] in-memory。"""
    hook = ctx.get("remove_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count))
        except Exception:
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        cur = int(inv.get(item_id, 0))
        if cur < count:
            return False
        inv[item_id] = cur - count
        return True
    return False


def _count_item(ctx: Mapping[str, Any], item_id: str) -> int:
    """持有计数：优先 ctx[\"count_item\"] hook；回退 ctx[\"inventory\"] in-memory。"""
    hook = ctx.get("count_item")
    if callable(hook):
        try:
            return int(hook(item_id))
        except Exception:
            return 0
    inv = ctx.get("inventory")
    if isinstance(inv, Mapping):
        return int(inv.get(item_id, 0))
    return 0


def _snapshot(ctx: Mapping[str, Any], player: Mapping[str, Any]) -> dict:
    """快照（原子防双扣，对齐 synthesis._snapshot）。"""
    snap: dict = {"ctx": {}, "player": {}}
    for k in _SNAP_CTX_KEYS:
        snap["ctx"][k] = copy.deepcopy(ctx.get(k))
    for k in _SNAP_PLAYER_KEYS:
        snap["player"][k] = copy.deepcopy(player.get(k))
    return snap


def _restore(ctx: MutableMapping[str, Any], player: MutableMapping[str, Any], snap: dict) -> None:
    """回滚（对齐 synthesis._restore）。"""
    for k, v in snap["ctx"].items():
        if v is None:
            ctx.pop(k, None)
        else:
            ctx[k] = v
    for k, v in snap["player"].items():
        if v is None:
            player.pop(k, None)
        else:
            player[k] = v


class _Rollback(Exception):
    """结算阶段失败标记（进程内回滚触发，对齐 synthesis._Rollback）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# HarvestEngine
# ---------------------------------------------------------------------------
class HarvestEngine:
    """第 2 层种植收获引擎（GU-60/61 + F-21 + FARM-01~10）。

    操作对象为 player（farm_plots 地块存档 + 职业档位）+ ctx（物品/特性注册表 + 背包/货币 hook），
    就地改写；返回 dict 结果、拒绝场景 {ok: False, reason, message} 不抛异常；
    纯函数零 IO 零 NoneBot。构造器配置注入 settings（settings.alchemy.farming 段）+ QualitySystem
    兜底缺省（对齐 synthesis.py / gem_wallet.py 构造注入模式）。
    """

    def __init__(
        self,
        settings: Optional[Mapping[str, Any]] = None,
        quality: Optional[QualitySystem] = None,
    ) -> None:
        """构造种植收获引擎（构造器配置注入 + 缺省兜底，H-4/H-5）。

        入参：
          - settings：settings dict（alchemy.farming 段：harvest_sec/plots_max/trait_inherit/
            greenhouse 等）；None/非 Mapping → {} → 默认值兜底。
          - quality：QualitySystem（品质档位判定/中文档名）；None → 内部缺省构造（默认四档）。
        配置来源 = 构造器注入单源（对齐 synthesis.py 工程补白 1），不读 ctx["settings"]。
        """
        self._settings: Mapping[str, Any] = settings if isinstance(settings, Mapping) else {}
        if isinstance(quality, QualitySystem):
            self._quality: QualitySystem = quality
        else:
            self._quality = QualitySystem()

    # ------------------------------------------------------------------
    # 配置读取（构造器单源 + 缺省兜底）
    # ------------------------------------------------------------------
    def _farming_cfg(self) -> Mapping[str, Any]:
        """settings.alchemy.farming 段归一（缺省 {}，H-4/H-5 配置落点）。"""
        alchemy = self._settings.get("alchemy")
        if not isinstance(alchemy, Mapping):
            return {}
        farming = alchemy.get("farming")
        return farming if isinstance(farming, Mapping) else {}

    def _greenhouse_cfg(self) -> Mapping[str, Any]:
        """settings.alchemy.farming.greenhouse 段归一（缺省 {}，H-5）。"""
        gh = self._farming_cfg().get("greenhouse")
        return gh if isinstance(gh, Mapping) else {}

    def _farming_enabled(self) -> bool:
        """种植模块开关（FARM：四件套可独立开关；缺省开启，熟练度 L222/L235 精神）。"""
        return self._farming_cfg().get("enabled", True) is not False

    def _harvest_sec(self, seed_info: Optional[Mapping[str, Any]] = None) -> int:
        """定时收获时长（FARM-02/定稿 L442：默认 14400 秒 = 4 小时可配）。

        单种子 seed_info.harvest_sec 覆盖优先（FARM-02 逐种子覆盖，H-1）；否则全局
        settings.alchemy.farming.harvest_sec；非法/缺省 → DEFAULT_HARVEST_SEC。
        """
        if isinstance(seed_info, Mapping):
            per = _as_int(seed_info.get("harvest_sec"))
            if per is not None and per > 0:
                return per
        v = _as_int(self._farming_cfg().get("harvest_sec"))
        return v if v is not None and v > 0 else DEFAULT_HARVEST_SEC

    def _plots_max(self) -> int:
        """地块数上限（FARM-01/细化 FARM-05 补白 3：settings.alchemy.farming.plots_max 可配）。"""
        v = _as_int(self._farming_cfg().get("plots_max"))
        return v if v is not None and v > 0 else DEFAULT_PLOTS_MAX

    def _greenhouse_unlock_index(self) -> int:
        """温室解锁档索引（FARM-07：unlock_tier 中文档名 → 档位索引，缺省 大师=4，H-5）。"""
        raw = self._greenhouse_cfg().get("unlock_tier", DEFAULT_GREENHOUSE_UNLOCK_TIER)
        name = str(raw) if raw else DEFAULT_GREENHOUSE_UNLOCK_TIER
        try:
            return DEFAULT_TIER_NAMES.index(name)
        except ValueError:
            return MASTER_TIER_INDEX

    def _copy_cost(self) -> Tuple[int, int]:
        """温室复制消耗 (宝石, 金币额)（FARM-08：默认 10/1000 可配，H-5）。

        copy_cost 配置键：宝石 = `gem`；金币 = `coins` 优先、`gold` 兜底（细化_2c5c
        FARM-08 样例用 `gold`，系统货币键空间为 `coins`（settings.json currencies），
        两键兼容，落账一律走 `coins`）；缺字段按 0；非法 → 0；copy_cost 非 Mapping → 默认值。
        """
        cost = self._greenhouse_cfg().get("copy_cost")
        if not isinstance(cost, Mapping):
            cost = DEFAULT_GREENHOUSE_COPY_COST
        gem = _as_int(cost.get("gem"))
        coins_raw = cost.get("coins")
        if coins_raw is None:
            coins_raw = cost.get("gold")
        coins = _as_int(coins_raw)
        return (gem if gem is not None and gem >= 0 else 0,
                coins if coins is not None and coins >= 0 else 0)

    # ------------------------------------------------------------------
    # 职业档位 / 特性继承项（H-3；镜像 energy_bar._tier_index 启发式 E-6）
    # ------------------------------------------------------------------
    def _tier_index(self, player: Mapping[str, Any]) -> int:
        """职业档位索引提取启发式（0 起：见习0/正式1/精通2/专家3/大师4/宗师5/王6）。

        优先 player["tier_index"]（装配层预计算）→ proficiency 节点 level（ALCHEMY_JOB_ID
        指定或首个带 level 的条目）→ 0（防御兜底）；钳制到 [0, 6]。
        """
        top = len(DEFAULT_TIER_NAMES) - 1
        ti = player.get("tier_index")
        if isinstance(ti, int) and not isinstance(ti, bool):
            return _clamp_int(ti, 0, top)
        prof = player.get("proficiency")
        node: Any = None
        if isinstance(prof, Mapping):
            job = prof.get(ALCHEMY_JOB_ID)
            if isinstance(job, Mapping):
                node = job
            if node is None:
                for _k, v in prof.items():
                    if isinstance(v, Mapping) and isinstance(v.get("level"), int):
                        node = v
                        break
        if isinstance(node, Mapping):
            level = node.get("level")
            if isinstance(level, int) and not isinstance(level, bool):
                return _clamp_int(level, 0, top)
        return 0

    def _trait_cap(self, tier_index: int) -> int:
        """特性继承项（FARM-03/INH-14，H-3）：settings.alchemy.farming.trait_inherit
        {正式:1, 精通:2, 专家:3} 可配；见习 0；超专家取专家值 3。
        """
        cfg = self._farming_cfg().get("trait_inherit")
        if isinstance(cfg, Mapping):
            name = DEFAULT_TIER_NAMES[tier_index]
            v = _as_int(cfg.get(name))
            if v is not None and v >= 0:
                return v
        if tier_index <= 0:
            return 0
        if tier_index == 1:
            return DEFAULT_TRAIT_INHERIT.get("正式", 1)
        if tier_index == 2:
            return DEFAULT_TRAIT_INHERIT.get("精通", 2)
        return DEFAULT_TRAIT_INHERIT.get("专家", 3)

    # ------------------------------------------------------------------
    # 地块存档容器（H-4：player["farm_plots"] dict，定稿 L402）
    # ------------------------------------------------------------------
    @staticmethod
    def _plots_read(player: Mapping[str, Any]) -> Mapping[Any, Any]:
        """player.farm_plots 只读容器（H-4）；缺失 → 空 dict（不新建）。"""
        plots = player.get("farm_plots")
        return plots if isinstance(plots, Mapping) else {}

    @staticmethod
    def _plots_rw(player: MutableMapping[str, Any]) -> MutableMapping[Any, Any]:
        """player.farm_plots 读写容器（H-4）；缺失 → 新建并挂回 player。"""
        plots = player.get("farm_plots")
        if not isinstance(plots, MutableMapping):
            plots = {}
            player["farm_plots"] = plots
        return plots

    # ------------------------------------------------------------------
    # 种子解析（H-1：seed 标记两形态）
    # ------------------------------------------------------------------
    def _resolve_item(self, ctx: Mapping[str, Any], item_id: str) -> Optional[Mapping[str, Any]]:
        """物品解析：ctx[\"items\"] 注册表或 resolve_item 解析器；查无 → None。"""
        items = ctx.get("items")
        if isinstance(items, Mapping):
            hit = items.get(item_id)
            if isinstance(hit, Mapping):
                return hit
        resolver = ctx.get("resolve_item")
        if callable(resolver):
            try:
                hit = resolver(item_id)
            except Exception:
                hit = None
            if isinstance(hit, Mapping):
                return hit
        return None

    def _seed_info(self, ctx: Mapping[str, Any], seed_id: str) -> Optional[dict]:
        """种子解析 → 收获信息 dict（H-1 两形态归一）；无 seed 标记/查无 → None。

        出参：{seed_def, output, quality, traits, harvest_sec, count}
          - seed 标记 `true`（简单形态）：output=种子自身 id；quality/traits=种子自身字段。
          - seed 标记 Mapping（收获表形态 L392）：output/quality_floor/traits/harvest_sec/count
            字段覆盖，缺省回落种子自身字段 → 默认值。
        """
        seed_def = self._resolve_item(ctx, seed_id)
        if seed_def is None:
            return None
        mark = seed_def.get("seed")
        if mark is True:
            return {
                "seed_def": seed_def,
                "output": seed_id,
                "quality": seed_def.get("quality"),
                "traits": seed_def.get("traits"),
                "harvest_sec": None,
                "count": 1,
            }
        if isinstance(mark, Mapping):
            q = mark.get("quality_floor")
            if q is None:
                q = mark.get("quality")
            if q is None:
                q = seed_def.get("quality")
            t = mark.get("traits")
            if t is None:
                t = seed_def.get("traits")
            cnt = _as_int(mark.get("count"))
            return {
                "seed_def": seed_def,
                "output": mark.get("output", seed_id),
                "quality": q,
                "traits": t,
                "harvest_sec": mark.get("harvest_sec"),
                "count": cnt if cnt is not None and cnt > 0 else 1,
            }
        return None

    def _quality_floor(self, raw: Any) -> int:
        """种子品质 → 品质分下限（H-2）：int 品质分原样；四档键 → 档位区间 lo；缺省 0。"""
        if isinstance(raw, bool):
            return 0
        if isinstance(raw, int):
            if raw < 0:
                return 0
            return raw
        if isinstance(raw, str) and raw in _QUALITY_KEYS:
            tiers = self._quality.tiers
            bounds = tiers.get(raw)
            if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
                lo = bounds[0]
                if isinstance(lo, int):
                    return lo
            return 0
        return 0

    def _tier_for_floor(self, score: int) -> str:
        """品质分 → 档位键（QualitySystem.score_to_tier，H-2/STO-06）。"""
        return self._quality.score_to_tier(score)

    def _trait_ids(self, raw: Any) -> List[str]:
        """种子特性集归一 → 特性 id 列表（H-1；仅收 str 元素）。"""
        out: List[str] = []
        if not isinstance(raw, (list, tuple)):
            return out
        for t in raw:
            if isinstance(t, str) and t:
                out.append(t)
        return out

    # ------------------------------------------------------------------
    # /种植（GU-60/61 + F-21 + FARM-01/02，H-6）
    # ------------------------------------------------------------------
    def plant(
        self,
        player: MutableMapping[str, Any],
        ctx: MutableMapping[str, Any],
        seed_id: object,
        *,
        now: Any = None,
        plot_index: object = None,
    ) -> dict:
        """/种植 ⟨种子⟩（GU-60/61 + F-21 + FARM-01/02）。

        入参：
          - player：玩家状态 dict（farm_plots 地块存档 + proficiency/tier_index 档位，就地改写）。
          - ctx：上下文（items/traits 注册表 + count_item/remove_item/add_item hook 或
            inventory/currencies，就地改写）。
          - seed_id：种子名/种子 id（位置参数 1，P-21）。
          - now：注入当前时刻（秒；None=UTC 现刻，确定性可测）。
          - plot_index：指定地块序号（可选，1 起）；缺省取首个空闲地块。
        出参：
          - 成功 {ok, reason=None, seed_id, seed_name, plot_index, planted_at, harvest_at,
            harvest_sec, message}；message = 「已种植〈种子〉，N 小时后可收获」（M-21 纯文本）。
          - 拒绝 {ok:False, reason, message, ...}（mode_off / level_insufficient /
            seed_not_found / not_seed / seed_missing / no_free_plot / plot_occupied /
            plot_index_invalid / consume_failed）。
        核心：消耗 1 颗种子道具（FARM-01，H-6）→ 写入地块 {seed, planted_at=now,
              harvest_at=now+harvest_sec}（F-21 数据落点）→ 原子（快照-回滚防双扣）。
        """
        now_ts = int(now) if now is not None else _now_ts()
        # 模块开关 + GU-60 职业 ≥ 正式
        if not self._farming_enabled():
            return {"ok": False, "reason": "mode_off", "message": "种植系统未开启",
                    "seed_id": None, "seed_name": None}
        tier = self._tier_index(player)
        if tier < FORMAL_TIER_INDEX:
            return {"ok": False, "reason": "level_insufficient",
                    "message": "等级不足：炼金职业需达到 正式（种植解锁）",
                    "seed_id": seed_id, "seed_name": None}
        # GU-61a 种子存在且带 seed 标记（H-1）
        if not isinstance(seed_id, str) or not seed_id.strip():
            return {"ok": False, "reason": "seed_not_found", "message": "种子不存在",
                    "seed_id": None, "seed_name": None}
        sid = seed_id.strip()
        info = self._seed_info(ctx, sid)
        if info is None:
            return {"ok": False, "reason": "seed_not_found",
                    "message": "种子不存在：未找到带 seed 标记的物品",
                    "seed_id": sid, "seed_name": None}
        # 持有校验 + 消耗（FARM-01/H-6）
        if _count_item(ctx, sid) < 1:
            return {"ok": False, "reason": "seed_missing",
                    "message": f"背包中没有〈{_item_name(sid, ctx)}〉，无法种植",
                    "seed_id": sid, "seed_name": _item_name(sid, ctx)}
        # GU-61b 空闲地块（H-4）
        plots_max = self._plots_max()
        plots = self._plots_read(player)
        if plot_index is not None:
            pi = _as_int(plot_index)
            if pi is None or pi < 1 or pi > plots_max:
                return {"ok": False, "reason": "plot_index_invalid",
                        "message": f"地块序号非法：需在 1-{plots_max} 之间",
                        "seed_id": sid, "seed_name": _item_name(sid, ctx)}
            if str(pi) in plots or pi in plots:
                return {"ok": False, "reason": "plot_occupied",
                        "message": f"地块 {pi} 已被占用", "seed_id": sid,
                        "seed_name": _item_name(sid, ctx)}
        else:
            occupied = {int(k) for k in plots if isinstance(k, int)} | {
                int(k) for k in plots if isinstance(k, str) and k.isdigit()}
            pi = next((i for i in range(1, plots_max + 1) if i not in occupied), None)
            if pi is None:
                return {"ok": False, "reason": "no_free_plot",
                        "message": f"没有空闲地块（上限 {plots_max} 块，先收获腾地）",
                        "seed_id": sid, "seed_name": _item_name(sid, ctx)}
        # 定时收获时长（FARM-02：按种植时配置结算）
        harvest_sec = self._harvest_sec(info)
        # 原子结算：扣种子 + 写地块（快照-回滚防双扣）
        snap = _snapshot(ctx, player)
        try:
            if not _remove_item(ctx, sid, 1):
                raise _Rollback("remove_seed_failed")
            plots_w = self._plots_rw(player)
            plots_w[pi] = {
                "seed": sid,
                "planted_at": now_ts,
                "harvest_at": now_ts + harvest_sec,
            }
        except _Rollback as exc:
            _restore(ctx, player, snap)
            return {"ok": False, "reason": "consume_failed",
                    "message": f"种植失败：{exc.reason}", "seed_id": sid,
                    "seed_name": _item_name(sid, ctx)}
        hours, rem = divmod(harvest_sec, 3600)
        if rem == 0:
            when = f"{hours} 小时后可收获"
        else:
            when = f"{harvest_sec} 秒后可收获"
        return {
            "ok": True,
            "reason": None,
            "seed_id": sid,
            "seed_name": _item_name(sid, ctx),
            "plot_index": pi,
            "planted_at": now_ts,
            "harvest_at": now_ts + harvest_sec,
            "harvest_sec": harvest_sec,
            "message": f"已种植〈{_item_name(sid, ctx)}〉，{when}",
        }

    # ------------------------------------------------------------------
    # /收获（F-21：收全部成熟地块 + FARM-03/04 + H-2/H-3/H-7/H-8）
    # ------------------------------------------------------------------
    def harvest(
        self,
        player: MutableMapping[str, Any],
        ctx: MutableMapping[str, Any],
        *,
        now: Any = None,
    ) -> dict:
        """/收获（F-21 + FARM-03/04 + FARM-06/10）。

        入参：
          - player：玩家状态 dict（farm_plots + 档位，就地改写）。
          - ctx：上下文（注册表 + hook，就地改写）。
          - now：注入当前时刻（秒；None=UTC 现刻）。
        出参：
          - 成功 {ok, reason=None, harvested:[{plot_index, seed_id, output, output_name, count,
            quality_score, quality_tier, quality_label, traits(继承特性 id), trait_names,
            dropped(丢弃特性 id)}], message}；message = 「收获〈材料〉×N（品质 精良·继承特性：
            …）」多条折叠为一条（RATE-05）。
          - 拒绝 {ok:False, reason, message}（mode_off / level_insufficient / no_plots /
            no_mature）。
        核心：成熟判定 now >= harvest_at（H-8）→ 逐地块出产：收获品质 = 种子品质下限
              （FARM-04，H-2）、继承特性按职业继承项截断（FARM-03，H-3）→ 入包 → 地块清空。
        """
        now_ts = int(now) if now is not None else _now_ts()
        if not self._farming_enabled():
            return {"ok": False, "reason": "mode_off", "message": "种植系统未开启"}
        tier = self._tier_index(player)
        if tier < FORMAL_TIER_INDEX:
            return {"ok": False, "reason": "level_insufficient",
                    "message": "等级不足：炼金职业需达到 正式（收获解锁）"}
        plots = self._plots_read(player)
        if not plots:
            return {"ok": False, "reason": "no_plots", "message": "还没有种植任何作物"}
        cap = self._trait_cap(tier)
        harvested: List[dict] = []
        pending: List[Tuple[Any, Mapping[str, Any], dict]] = []  # (key, plot, seed_info)
        for key, plot in plots.items():
            if not isinstance(plot, Mapping):
                continue
            seed_id = plot.get("seed")
            harvest_at = _as_int(plot.get("harvest_at"))
            if harvest_at is None or now_ts < harvest_at:
                continue  # 未成熟（H-8：now >= harvest_at 才成熟）
            if not isinstance(seed_id, str) or not seed_id:
                continue
            info = self._seed_info(ctx, seed_id)
            if info is None:
                continue  # 种子配置缺失（热重载删配置降级：该地块跳过，STO-05 精神）
            pending.append((key, plot, info))
        if not pending:
            immature = sum(1 for p in plots.values() if isinstance(p, Mapping))
            return {"ok": False, "reason": "no_mature",
                    "message": f"作物还未成熟（{immature} 个地块未到收获时间，"
                               f"等 harvest_at 到点再来）"}
        # 原子结算：入包 + 清空地块（快照-回滚防双扣）
        snap = _snapshot(ctx, player)
        try:
            for key, plot, info in pending:
                output = info["output"]
                count = info["count"]
                seed_id = plot["seed"]
                if not _add_item(ctx, output, count, False):
                    raise _Rollback(f"add_item_failed:{output}")
                score = self._quality_floor(info["quality"])
                tier_key = self._tier_for_floor(score)
                traits = self._trait_ids(info["traits"])
                inherited = traits[:cap]
                dropped = traits[cap:]
                harvested.append({
                    "plot_index": self._plot_index_of(key),
                    "seed_id": seed_id,
                    "output": output,
                    "output_name": _item_name(output, ctx),
                    "count": count,
                    "quality_score": score,
                    "quality_tier": tier_key,
                    "quality_label": self._quality.tier_label(tier_key),
                    "traits": list(inherited),
                    "trait_names": [_trait_name(t, ctx) for t in inherited],
                    "dropped": list(dropped),
                    "dropped_names": [_trait_name(t, ctx) for t in dropped],
                })
            plots_w = self._plots_rw(player)
            for key, _plot, _info in pending:
                plots_w.pop(key, None)
        except _Rollback as exc:
            _restore(ctx, player, snap)
            return {"ok": False, "reason": "add_item_failed",
                    "message": f"收获失败：{exc.reason}"}
        return {
            "ok": True,
            "reason": None,
            "harvested": harvested,
            "message": self._harvest_message(harvested),
        }

    @staticmethod
    def _plot_index_of(key: Any) -> Any:
        """地块存档键 → 地块序号（int 优先，字符串数字键转 int）。"""
        if isinstance(key, str) and key.isdigit():
            return int(key)
        return key

    def _harvest_message(self, harvested: List[dict]) -> str:
        """收获消息折叠（RATE-05 单条）：「收获〈材料〉×N（品质 精良·继承特性：…）」。

        多条「；」分隔；无继承特性 → 省略「·继承特性」段；有丢弃 → 附「（超出继承上限丢弃：…）」。
        """
        parts: List[str] = []
        for h in harvested:
            name = h.get("output_name")
            count = h.get("count", 1)
            label = h.get("quality_label")
            seg = f"收获〈{name}〉×{count}（品质 {label}"
            traits = h.get("trait_names", [])
            if traits:
                seg += "·继承特性：" + "、".join(str(t) for t in traits)
            seg += "）"
            dropped = h.get("dropped_names", [])
            if dropped:
                seg += f"（超出继承上限丢弃：{'、'.join(str(t) for t in dropped)}）"
            parts.append(seg)
        return "；".join(parts)

    # ------------------------------------------------------------------
    # 温室（FARM-07/08：大师解锁 · 复制一种素材 耗宝石/金币 · H-5）
    # ------------------------------------------------------------------
    def greenhouse(
        self,
        player: MutableMapping[str, Any],
        ctx: MutableMapping[str, Any],
        seed_id: object,
        *,
        now: Any = None,
    ) -> dict:
        """温室复制（FARM-07/08：大师解锁 → 复制一种素材 耗宝石/金币 → 素材入包 滚雪球）。

        入参：
          - player：玩家状态 dict（档位，只读）。
          - ctx：上下文（注册表 + currencies/add_item hook，就地改写）。
          - seed_id：种子名/种子 id——温室复制该种子产出的素材（F-21「可复制一种素材」）。
          - now：注入当前时刻（秒；None=UTC 现刻，本方法仅透传确定语义）。
        出参：
          - 成功 {ok, reason=None, material_id, material_name, count, gem_cost, coins_cost,
            gem_balance, coins_balance, message}；message = 「温室复制〈素材〉×1（消耗 宝石 10
            + 金币 1000）」（ARB-00 分账：宝石账/金币账分列）。
          - 拒绝 {ok:False, reason, message}（mode_off / level_insufficient / seed_not_found /
            not_seed / currency_shortfall / add_item_failed）。
        核心：大师解锁（FARM-07）→ 解析种子产出素材 → 原子扣宝石+金币 → 素材入包（滚雪球）。
        """
        if not self._farming_enabled():
            return {"ok": False, "reason": "mode_off", "message": "种植系统未开启"}
        unlock = self._greenhouse_unlock_index()
        tier = self._tier_index(player)
        if tier < unlock:
            name = DEFAULT_TIER_NAMES[unlock]
            return {"ok": False, "reason": "level_insufficient",
                    "message": f"等级不足：温室需要 {name} 解锁（FARM-07）"}
        if not isinstance(seed_id, str) or not seed_id.strip():
            return {"ok": False, "reason": "seed_not_found", "message": "种子不存在",
                    "material_id": None, "material_name": None}
        sid = seed_id.strip()
        info = self._seed_info(ctx, sid)
        if info is None:
            return {"ok": False, "reason": "seed_not_found",
                    "message": "种子不存在：未找到带 seed 标记的物品",
                    "material_id": sid, "material_name": None}
        material_id = info["output"]
        material_name = _item_name(material_id, ctx)
        gem_cost, coins_cost = self._copy_cost()
        currencies = ctx.get("currencies")
        gem_have = int(currencies.get("gem", 0)) if isinstance(currencies, Mapping) else 0
        coins_have = int(currencies.get("coins", 0)) if isinstance(currencies, Mapping) else 0
        if gem_cost > 0 and gem_have < gem_cost:
            return {"ok": False, "reason": "currency_shortfall",
                    "message": f"温室复制需要 宝石 {gem_cost}，当前只有 {gem_have}",
                    "material_id": material_id, "material_name": material_name,
                    "gem_cost": gem_cost, "coins_cost": coins_cost}
        if coins_cost > 0 and coins_have < coins_cost:
            return {"ok": False, "reason": "currency_shortfall",
                    "message": f"温室复制需要 金币 {coins_cost}，当前只有 {coins_have}",
                    "material_id": material_id, "material_name": material_name,
                    "gem_cost": gem_cost, "coins_cost": coins_cost}
        # 原子结算：扣货币 + 素材入包（快照-回滚防双扣；ARB-00 分账，金币账走 coins 键）
        snap = _snapshot(ctx, player)
        try:
            if not isinstance(currencies, MutableMapping):
                raise _Rollback("no_currency_bucket")
            if gem_cost > 0:
                currencies["gem"] = gem_have - gem_cost
            if coins_cost > 0:
                currencies["coins"] = coins_have - coins_cost
            if not _add_item(ctx, material_id, 1, False):
                raise _Rollback(f"add_item_failed:{material_id}")
        except _Rollback as exc:
            _restore(ctx, player, snap)
            return {"ok": False, "reason": "add_item_failed",
                    "message": f"温室复制失败：{exc.reason}",
                    "material_id": material_id, "material_name": material_name}
        parts = []
        if gem_cost > 0:
            parts.append(f"宝石 {gem_cost}")
        if coins_cost > 0:
            parts.append(f"金币 {coins_cost}")
        cost_seg = " + ".join(parts) if parts else "无消耗"
        return {
            "ok": True,
            "reason": None,
            "material_id": material_id,
            "material_name": material_name,
            "count": 1,
            "gem_cost": gem_cost,
            "coins_cost": coins_cost,
            "gem_balance": gem_have - gem_cost,
            "coins_balance": coins_have - coins_cost,
            "message": f"温室复制〈{material_name}〉×1（消耗 {cost_seg}）",
        }

    # ------------------------------------------------------------------
    # 地块存档查看（H-4 / 定稿 L402 / TC-08）
    # ------------------------------------------------------------------
    def plots_of(self, player: Mapping[str, Any]) -> List[dict]:
        """地块存档查看（H-4：player.farm_plots dict → 列表）。

        出参：[{plot_index, seed_id, planted_at, harvest_at}, ...] 按地块序号升序；
        无地块 → []。种子显示名需 ctx（items 注册表），本方法签名无 ctx（任务规定
        plots_of(player)）故仅回填 seed_id，由装配层按需映射名称；成熟度需 now（未注入），
        由装配层按 harvest_at 计算（FARM-10 重算不重置）。
        """
        plots = self._plots_read(player)
        out: List[dict] = []
        for key, plot in plots.items():
            if not isinstance(plot, Mapping):
                continue
            seed_id = plot.get("seed")
            if not isinstance(seed_id, str):
                continue
            out.append({
                "plot_index": self._plot_index_of(key),
                "seed_id": seed_id,
                "planted_at": plot.get("planted_at"),
                "harvest_at": plot.get("harvest_at"),
            })
        out.sort(key=lambda e: str(e["plot_index"]))
        return out


def _now_ts() -> int:
    """秒级时间戳（缺省 = UTC 现刻，确定性可测由调用方注入 now）。"""
    import time
    return int(time.time())
