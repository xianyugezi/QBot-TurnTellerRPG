"""宝石货币引擎（M8 批6·路6B · qbot_rpg/core/gem_wallet.py）——GemWallet。

文件：qbot_rpg/core/gem_wallet.py
创建：2026-08-29
作者：Hermes 子agent-6B（并发同仓：仅新建本文件 + tests/unit/test_gem_wallet.py；兄弟路 6A 改
  qbot_rpg/commands/alchemy_commands.py /分解 指令壳，本文件只读勿探查、勿改任何 shared 文件）
功能：宝石货币纯引擎——/分解 计算（标准版拒绝 / 材料×回收率向下取整 / 宝石平铺基础值拍板① /
  两段式消息数据）+ decompose_rate 回收率随档位 + gem_base_value 平铺基础值 + grant_gem 统一
  入账 + is_decomposable 可分解判定。纯函数零 IO 零 NoneBot；构造器注入 settings + QualitySystem
  兜底缺省（对齐 core/synthesis.py / core/quality.py 构造注入模式）。

依据：
  - docs/m8_batch_plan.md §批6 路6B（宝石货币：wallet.gem（currencies dict 加 gem 键）、统一
    reward 入账（分解/挑战奖励/loot.json gem 列/品评会冠军）、/分解（仅炼金/深度产出可分解、
    标准版默认不可分解、材料×回收率向下取整、宝石平铺基础值拍板①、两段式消息）、分解公式可配置）
  - docs/m8_contract_战斗资源.md 一（GEM-01~16）：GEM-02 统一入账（gem 标量键走 reward）；
    GEM-03 键空间硬前置（gem 须登记 settings.currencies，否则 skip unknown_currency）；
    GEM-06/15 分解宝石=平铺基础值 普通1/精良3/史诗8/传说20 不乘回收率（拍板①）+ 两段式消息；
    GEM-13/14 四轴防套利（分解仅限炼金/深度产出、标准版默认不可分解、回收减半为内容包可配备选）；
    GEM-15 回收率档位 正式0.4/精通0.45/专家0.5/大师0.55/宗师0.6/王0.65（可配）。
  - docs/m8_contract_数据与校验.md §五 L205（decompose_rate 6 档、见习无分解）/ L208
    （gem.分解 平铺基础值 + 产出公式可配 gem.decompose_formula "flat"|"rate"，拍板①）
  - docs/细化/细化_2c4b_宝石货币经济.md DEC-01~06（对象限制/材料返还逐 id 向下取整/宝石平铺/
    两段式/原子幂等/降级返还不吞料）+ 验收 TC-19~22、TC-01
  - docs/细化/细化_2c4c_珠与合成指令.md DEC-01~05（标准版不可分解默认实现最严、回收减半内容包
    可配；低阶宝石门控为细化工程补白，本引擎不实现——见工程补白 GW-11）
  - 模式参考 qbot_rpg/core/reward.py（ctx currencies 就地累加/货币键空间校验）、core/synthesis.py
    （构造器注入 settings 单源）、core/quality.py（QualitySystem 档位判定，构造器注入兜底）
  - 已落地数据 content/test_demo/settings.json alchemy 段（decompose_rate 中文档名键 /
    gem.分解 / currencies 含 gem 登记）、items.json（炼金成品带 quality+traits，标准版无）

【工程补白 · 显式标注】（定稿/细化未给口径处，按最小必要推导，不得新增定稿外机制行为）：
  GW-1  标准版判定口径：is_decomposable = item_def 为 Mapping 且带品质章（quality 非空）且带
        非标准版标记（traits/awaken/evolution/core 任一非空）→ 可分解；缺任一 → 标准版不可分解
        （LAY-04a 标准版=品质固定+无特性；2c4c DEC-02「标准版不可分解」默认实现取最严口径）。
  GW-2  批量材料返还口径：逐材料 id 对整批向下取整 floor(mat_count × n × rate)（2c4b DEC-02
        逐 id 分别取整、不足 1 归 0；n=1 与单件口径一致）；返还 0 的材料 id 不进结果列表。
  GW-3  品质章解析：item_def["quality"] 支持 档位键字符串 / 品质分 int
        （QualitySystem.score_to_tier）/ {tier|key, score} 映射；无法解析 → 档位 None（宝石 0
        防御，见 GW-4）。
  GW-4  未知档位宝石防御：可分解物品品质章无法解析为四档 → gem=0（不凭空发宝石，message 标注
        quality_unknown 供指令壳提示）。
  GW-5  档位映射缺省：job_tier_index 0~6 ↔ 见习/正式/精通/专家/大师/宗师/王（对齐 proficiency.py
        _DEFAULT_TIER_NAMES）；回收率表 = settings.alchemy.decompose_rate（中文档名键，表自正式
        起）；见习恒 0.0（无分解，2c4c DEC-01）；配置缺档回落默认 0.4/0.45/0.5/0.55/0.6/0.65。
  GW-6  分解门槛归指令壳：大师解锁分解回炉/正式低阶分解 是 /分解 指令壳（批6A）前置门槛，本引擎
        只按 job_tier_index 算回收率/宝石，不做档位闸（纯计算；档位闸属指令层）。
  GW-7  宝石入账键空间：grant_gem 对齐 reward._grant_scalar（GEM-03 硬前置）——gem 未登记
        settings.currencies → {ok:False, reason:'unknown_currency'}（缺省键空间 coins/diamond，
        gem 不在内）；配置来源 = 构造器注入 settings 单源（对齐 synthesis.py 工程补白 1）。
  GW-8  标准版回收减半可配键：settings.alchemy.standard_decompose_half（bool 默认 False）——
        内容包置 True → 标准版可分解：材料×rate/2 向下取整、宝石恒 0（标准版无品质章，2c4c
        DEC-04「回收减半」）；键名为最小必要推导（定稿未给键名）。缺省 False=默认最严「标准版
        不可分解」（2c4c DEC-02）。
  GW-9  产出公式可配（拍板①）：settings.alchemy.gem.decompose_formula ∈ {"flat","rate"}，默认
        "flat"（平铺基础值×count）；"rate" = ⌊基础值×回收率⌋×count（数据与校验 L208 键名）。
        非法值回落 flat。
  GW-10 分解材料表来源：item_def["decompose"]["materials"]（item 分解表，列表或 {id:count} 映射
        形态）优先；缺省回退 ctx["recipe"] 注册表（dict 或 list）查 output.item/id==item_id 的
        配方 materials；都缺 → 无材料返还（宝石仍按品质章发，GEM-15 平铺不依赖材料表）。
  GW-11 低阶宝石门控不实现：2c4c DEC-04「正式-精通宝石产出关闭/减半为内容包可配门控」为细化工程
        补白、非契约要求，本引擎按 GEM-15 平铺恒发（含正式档）；门控由内容包/指令壳按需叠加。
  GW-12 decompose 为纯计算：不删物品/不入包/不入账（DEC-04 原子落账归指令壳快照-回滚）；指令壳
        流程 = resolve item → decompose 计算 → 原子扣物品+返材料 → grant_gem → 渲染两段式消息。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；工程补白显式标注；不新增定稿外机制行为。
"""

from __future__ import annotations

import math
from typing import Any, List, Mapping, MutableMapping, Optional, Tuple

from qbot_rpg.core.quality import QualitySystem

__all__ = [
    "DEFAULT_DECOMPOSE_RATES",
    "DEFAULT_GEM_FLAT_BASE",
    "DEFAULT_TIER_NAMES",
    "REASON_STANDARD_NOT_DECOMPOSABLE",
    "GemWallet",
]

# 标准版不可分解拒绝原因（LAY-05/2c4c DEC-02 / GEM-14，指令壳可复用）
REASON_STANDARD_NOT_DECOMPOSABLE: str = "standard_not_decomposable"

# 档位名（对齐 proficiency.py _DEFAULT_TIER_NAMES：index 0~6）
DEFAULT_TIER_NAMES: Tuple[str, ...] = ("见习", "正式", "精通", "专家", "大师", "宗师", "王")

# 回收率缺省表（表自正式起；见习无分解 → 恒 0.0，2c4c DEC-01/DEC-05 / 数据与校验 L205）
DEFAULT_DECOMPOSE_RATES: Mapping[str, float] = {
    "正式": 0.4, "精通": 0.45, "专家": 0.5, "大师": 0.55, "宗师": 0.6, "王": 0.65,
}

# 宝石平铺基础值缺省（拍板① / GEM-15 / 2c4c DEC-04：普通1/精良3/史诗8/传说20，键=品质档）
DEFAULT_GEM_FLAT_BASE: Mapping[str, int] = {
    "common": 1, "uncommon": 3, "rare": 8, "legendary": 20,
}

# 非标准版标记键（LAY-04a：特性/超特性/进化/核心类）
_ADVANCE_MARKER_KEYS: Tuple[str, ...] = ("traits", "awaken", "evolution", "core")

# 缺省货币键空间（对齐 reward.DEFAULT_CURRENCY_IDS；gem 不在此内 → GEM-03 硬前置）
_DEFAULT_CURRENCY_SPACE: Tuple[str, ...] = ("coins", "diamond")


class GemWallet:
    """宝石货币引擎（GEM-01~16 / 2c4b DEC-01~06 / 2c4c DEC-01~05）。

    构造器配置注入（settings）+ QualitySystem 兜底缺省；纯函数零 IO 零 NoneBot；拒绝场景
    {ok: False, reason, message} 不抛异常（对齐 core/synthesis.py / core/quality.py 铁律）。
    操作对象 ctx 为可变 dict；本引擎只读 ctx（decompose 纯计算）或就地改写 ctx["currencies"]
    （grant_gem 入账），存储与持久化由调用方完成。
    """

    def __init__(
        self,
        settings: Optional[Mapping[str, Any]] = None,
        quality: Optional[QualitySystem] = None,
    ) -> None:
        """构造宝石货币引擎（构造器配置注入 + 缺省兜底）。

        入参：
          - settings：settings dict（alchemy 段：decompose_rate/gem.分解/standard_decompose_half/
            currencies 键空间等）；None/非 Mapping → {} → 默认值兜底（GW-5/GW-7）。
          - quality：QualitySystem（档位判定/中文档名）；None → 内部缺省构造（默认四档）。
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
    def _alchemy_cfg(self) -> Mapping[str, Any]:
        """settings.alchemy 段归一（缺省 {}）。"""
        alchemy = self._settings.get("alchemy")
        return alchemy if isinstance(alchemy, Mapping) else {}

    def _gem_cfg(self) -> Mapping[str, Any]:
        """settings.alchemy.gem 段归一（缺省 {}）。"""
        gem = self._alchemy_cfg().get("gem")
        return gem if isinstance(gem, Mapping) else {}

    @staticmethod
    def _to_int(value: object) -> Optional[int]:
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

    def _normalize_tier_index(self, value: object) -> int:
        """档位序号归一：裁剪到 [0, 6]；非法/越界回落边界（GW-5）。"""
        v = self._to_int(value)
        if v is None:
            return 0
        if v < 0:
            return 0
        if v > 6:
            return 6
        return v

    # ------------------------------------------------------------------
    # 回收率 / 宝石基础值（GEM-15 / DEC-02 / 拍板①）
    # ------------------------------------------------------------------
    def decompose_rate(self, job_tier_index: int) -> float:
        """分解回收率（DEC-02/05：正式0.4/精通0.45/专家0.5/大师0.55/宗师0.6/王0.65，档位跳变）。

        入参：job_tier_index 职业档位序号（0~6 ↔ 见习/正式/精通/专家/大师/宗师/王，GW-5）。
        出参：回收率 float ∈ [0,1]。
        核心：settings.alchemy.decompose_rate（中文档名键，可配）命中取配置值并裁剪到 [0,1]；
              见习恒 0.0（无分解，2c4c DEC-01）；配置缺档回落默认表。
        """
        idx = self._normalize_tier_index(job_tier_index)
        if idx == 0:  # 见习无分解（GW-5）
            return 0.0
        name = DEFAULT_TIER_NAMES[idx]
        cfg = self._alchemy_cfg().get("decompose_rate")
        if isinstance(cfg, Mapping):
            raw = cfg.get(name)
            if raw is not None:
                try:
                    v = float(raw)
                except (TypeError, ValueError):
                    v = None
                if v is not None:
                    return max(0.0, min(1.0, v))
        return DEFAULT_DECOMPOSE_RATES.get(name, 0.0)

    def gem_base_value(self, quality_tier: str) -> int:
        """宝石平铺基础值（拍板① / GEM-15：普通1/精良3/史诗8/传说20，不乘回收率）。

        入参：quality_tier 品质档键（common/uncommon/rare/legendary）。
        出参：基础值 int；未知档位/非法值 → 0（防御）。
        核心：settings.alchemy["gem.分解"][tier] 可配；缺省 DEFAULT_GEM_FLAT_BASE。
        """
        if not isinstance(quality_tier, str) or not quality_tier:
            return 0
        cfg = self._gem_cfg().get("分解")
        table = cfg if isinstance(cfg, Mapping) else DEFAULT_GEM_FLAT_BASE
        raw = table.get(quality_tier)
        if raw is None:
            raw = DEFAULT_GEM_FLAT_BASE.get(quality_tier)
        v = self._to_int(raw)
        return v if v is not None and v > 0 else 0

    def _gem_formula(self) -> str:
        """产出公式（拍板① 可配）：settings.alchemy.gem.decompose_formula ∈ {"flat","rate"}。

        缺省 "flat"（平铺基础值×count）；"rate" = ⌊基础值×回收率⌋×count（GW-9）。
        """
        raw = self._gem_cfg().get("decompose_formula", "flat")
        return str(raw) if raw in ("flat", "rate") else "flat"

    def _gem_amount(self, base: int, rate: float, n: int) -> int:
        """宝石产出额（GW-9）：flat → base×n；rate → ⌊base×rate⌋×n。"""
        if base <= 0 or n <= 0:
            return 0
        if self._gem_formula() == "rate" and rate > 0:
            return int(math.floor(base * rate)) * n
        return base * n

    # ------------------------------------------------------------------
    # 可分解判定（标准版口径，GW-1）
    # ------------------------------------------------------------------
    @staticmethod
    def _has_quality_stamp(item_def: Mapping[str, Any]) -> bool:
        """带品质章：quality 字段非空（炼金/深度产出的品质定格标记；标准版无，LAY-04a）。"""
        q = item_def.get("quality")
        if q is None or q == "" or q == [] or q == {}:
            return False
        if isinstance(q, bool):
            return False
        return True

    @staticmethod
    def _has_advance_marker(item_def: Mapping[str, Any]) -> bool:
        """带非标准版标记：traits/awaken/evolution/core 任一非空（LAY-04a，GW-1）。"""
        for key in _ADVANCE_MARKER_KEYS:
            v = item_def.get(key)
            if isinstance(v, bool) and v:
                return True
            if isinstance(v, (list, tuple, dict, str)) and v:
                return True
        return False

    def is_decomposable(self, item_def: Any) -> bool:
        """可分解判定（GW-1 标准版口径）。

        入参：item_def 物品定义 dict（可含 quality/traits/awaken/evolution/core）。
        出参：bool——非标准版（带品质章 + 带非标准版标记的炼金/深度产出）→ True；
              标准版（无 quality 或无 traits/非炼金·深度产出）→ False。
        """
        if not isinstance(item_def, Mapping):
            return False
        return self._has_quality_stamp(item_def) and self._has_advance_marker(item_def)

    # ------------------------------------------------------------------
    # 分解材料表来源（GW-10）
    # ------------------------------------------------------------------
    def _material_table(self, ctx: Mapping[str, Any], item_def: Mapping[str, Any]) -> List[Any]:
        """分解材料表：item 分解表优先，回退配方 materials，都缺 → []（GW-10）。"""
        dec = item_def.get("decompose")
        if isinstance(dec, Mapping):
            mats = dec.get("materials")
            if isinstance(mats, list):
                return mats
            if isinstance(mats, Mapping):  # {id: count} 映射形态归一
                return [{"id": k, "count": v} for k, v in mats.items()]
        item_id = item_def.get("id")
        if isinstance(item_id, str) and item_id:
            recipes = ctx.get("recipe")
            candidates: List[Any] = []
            if isinstance(recipes, Mapping):
                candidates = list(recipes.values())
            elif isinstance(recipes, list):
                candidates = list(recipes)
            for r in candidates:
                if isinstance(r, Mapping) and self._recipe_outputs(r, item_id):
                    mats = r.get("materials")
                    if isinstance(mats, list):
                        return mats
        return []

    @staticmethod
    def _recipe_outputs(recipe: Mapping[str, Any], item_id: str) -> bool:
        """配方产出匹配：output.item 或 output.id == item_id。"""
        out = recipe.get("output")
        if isinstance(out, Mapping):
            oid = out.get("item")
            if oid is None:
                oid = out.get("id")
            if oid == item_id:
                return True
        return False

    def _recover_materials(
        self, ctx: Mapping[str, Any], item_def: Mapping[str, Any], n: int, rate: float,
    ) -> List[Tuple[str, str, int]]:
        """材料返还计算（DEC-02/GW-2）：逐材料 id floor(material_count × n × rate)。

        出参：[(item_id, 显示名, 返还数), ...]——返还 0 的材料 id 不进列表（不足 1 归 0）。
        """
        out: List[Tuple[str, str, int]] = []
        for m in self._material_table(ctx, item_def):
            mid = m.get("id") if isinstance(m, Mapping) else None
            mcount = self._to_int(m.get("count")) if isinstance(m, Mapping) else None
            if not isinstance(mid, str) or not mid or mcount is None or mcount < 0:
                continue
            total = int(math.floor(mcount * n * rate))
            if total <= 0:
                continue
            out.append((mid, self._item_name(mid, ctx), total))
        return out

    def _item_name(self, item_id: str, ctx: Mapping[str, Any]) -> str:
        """物品 id → 显示名（ctx["items"] 注册表或 resolve_item 解析器；缺省回退原 id）。"""
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

    # ------------------------------------------------------------------
    # 品质章解析（GW-3/GW-4）
    # ------------------------------------------------------------------
    def _resolve_tier(self, item_def: Mapping[str, Any]) -> Optional[str]:
        """品质章 → 档位键（GW-3）：字符串档位键 / int 品质分 / {tier|key, score} 映射。

        无法解析 → None（gem=0 防御，GW-4）。
        """
        q = item_def.get("quality")
        if isinstance(q, str) and q:
            return q if q in DEFAULT_GEM_FLAT_BASE else None
        if isinstance(q, bool):
            return None
        if isinstance(q, int):
            return self._quality.score_to_tier(q)
        if isinstance(q, Mapping):
            t = q.get("tier")
            if t is None:
                t = q.get("key")
            if isinstance(t, str) and t:
                return t if t in DEFAULT_GEM_FLAT_BASE else None
            s = self._to_int(q.get("score"))
            if s is not None:
                return self._quality.score_to_tier(s)
        return None

    # ------------------------------------------------------------------
    # 两段式结果组装（GEM-15 / DEC-03）
    # ------------------------------------------------------------------
    def _compose_result(
        self,
        ctx: Mapping[str, Any],
        item_def: Mapping[str, Any],
        n: int,
        rate: float,
        materials: List[Tuple[str, str, int]],
        gem: int,
        tier: Optional[str],
        *,
        standard_half: bool = False,
        quality_unknown: bool = False,
    ) -> dict:
        """两段式消息数据组装（对齐 L248 示例「火晶石×2 + 宝石×5」）。"""
        item_id = item_def.get("id")
        item_name = self._item_name(item_id, ctx) if isinstance(item_id, str) else "?"
        if materials:
            material_seg = " + ".join(f"{name}×{c}" for _i, name, c in materials)
        else:
            material_seg = "无材料返还"
        gem_seg = f"宝石×{gem}" if gem > 0 else "宝石×0"
        result = {
            "ok": True,
            "reason": None,
            "item_id": item_id,
            "item_name": item_name,
            "count": n,
            "quality_tier": tier,
            "quality_label": self._quality.tier_label(tier) if tier else None,
            "decompose_rate": rate,
            "materials": materials,
            "gem": gem,
            "material_seg": material_seg,
            "gem_seg": gem_seg,
            "message": f"分解返还：{material_seg}\n{gem_seg}",
        }
        if standard_half:
            result["standard_half"] = True
        if quality_unknown:
            result["quality_unknown"] = True
        return result

    # ------------------------------------------------------------------
    # 标准版回收减半 alternative（GW-8 / 2c4c DEC-04）
    # ------------------------------------------------------------------
    def _standard_decompose_half(self) -> bool:
        """settings.alchemy.standard_decompose_half（bool 默认 False，GW-8 最小必要推导键名）。"""
        return self._alchemy_cfg().get("standard_decompose_half") is True

    # ------------------------------------------------------------------
    # /分解 计算入口（GEM-06/15 + DEC-01~05；纯计算不落账，GW-12）
    # ------------------------------------------------------------------
    def decompose(
        self,
        ctx: Mapping[str, Any],
        item_def: Any,
        count: int = 1,
        *,
        job_tier_index: int,
    ) -> dict:
        """/分解 计算（DEC-01~05 / GEM-06/15；纯计算，不删物品/不入包/不入账，GW-12）。

        入参：
          - ctx：玩家表示（items 注册表 / recipe 注册表 / resolve_item，只读）。
          - item_def：待分解物品定义 dict（含 quality/traits/decompose 等）。
          - count：分解件数（非正整数归一为 1）。
          - job_tier_index：职业档位序号（0~6，取回收率档位，GW-5）。
        出参：
          - 标准版（LAY-05/2c4c DEC-02）→ {ok:False, reason:'standard_not_decomposable',
            message, item_id, item_name, count}（GW-8 回收减半 alternative 例外：ok:True）。
          - 可分解 → {ok:True, materials:[(id,name,count)], gem, message 两段式消息数据,
            quality_tier/quality_label, decompose_rate, material_seg, gem_seg, ...}。
        核心：材料返还 = 逐 id floor(材料×n×回收率)（DEC-02）；宝石 = 平铺基础值×n 不乘回收率
              （拍板①，GW-9 可配 rate 公式）；两段式消息 = 材料行 + 宝石行（GEM-15）。
        """
        n = self._to_int(count)
        if n is None or n < 1:
            n = 1
        idx = self._normalize_tier_index(job_tier_index)

        if not isinstance(item_def, Mapping):
            return {"ok": False, "reason": "invalid_item", "count": n,
                    "message": "❌ 物品数据无效，无法分解"}

        if not self.is_decomposable(item_def):
            # GW-8：内容包可配回收减半 alternative（默认 False 最严「标准版不可分解」）
            if self._standard_decompose_half():
                rate = self.decompose_rate(idx) / 2.0
                materials = self._recover_materials(ctx, item_def, n, rate)
                return self._compose_result(ctx, item_def, n, rate, materials, 0, None,
                                            standard_half=True)
            item_id = item_def.get("id")
            item_name = self._item_name(item_id, ctx) if isinstance(item_id, str) else "?"
            return {
                "ok": False,
                "reason": REASON_STANDARD_NOT_DECOMPOSABLE,
                "message": f"❌ {item_name} 为标准版，不可分解（仅炼金/深度炼金产出可分解）",
                "item_id": item_id,
                "item_name": item_name,
                "count": n,
            }

        rate = self.decompose_rate(idx)
        materials = self._recover_materials(ctx, item_def, n, rate)
        tier = self._resolve_tier(item_def)
        base = self.gem_base_value(tier) if tier else 0
        gem = self._gem_amount(base, rate, n)
        return self._compose_result(ctx, item_def, n, rate, materials, gem, tier,
                                    quality_unknown=(tier is None))

    # ------------------------------------------------------------------
    # 宝石统一入账（GEM-02/03，对齐 reward 入账管线）
    # ------------------------------------------------------------------
    def _currency_space(self) -> Tuple[str, ...]:
        """已配置货币键空间（settings.currencies[].id）；缺省 = coins/diamond（对齐 reward）。"""
        raw = self._settings.get("currencies")
        if isinstance(raw, list):
            ids: List[str] = []
            for e in raw:
                if not isinstance(e, Mapping):
                    continue
                eid = e.get("id")
                if isinstance(eid, str) and eid:
                    ids.append(eid)
            if ids:
                return tuple(ids)
        return _DEFAULT_CURRENCY_SPACE

    def grant_gem(self, ctx: MutableMapping[str, Any], amount: int) -> dict:
        """宝石入账（GEM-02/03：currencies["gem"] 累加，对齐 reward 入账管线）。

        入参：ctx 玩家表示（就地改写 ctx["currencies"]["gem"]）、amount 入账数额。
        出参：{ok, reason?, currency, amount, balance?, message}；失败 {ok:False, reason, message}。
        核心：非负整数校验 → 货币表存在校验 → 键空间硬前置（gem ∈ settings.currencies，
              GEM-03）→ currencies["gem"] += amount。失败不抛异常（skip 语义，GEM-03）。
        """
        amt = self._to_int(amount)
        if amt is None or amt < 0:
            return {"ok": False, "reason": "invalid_amount",
                    "message": f"❌ 宝石数额非法: {amount!r}"}
        if not isinstance(ctx, MutableMapping):
            return {"ok": False, "reason": "missing_bucket",
                    "message": "❌ 货币表缺失，无法入账"}
        if not isinstance(ctx.get("currencies"), MutableMapping):
            return {"ok": False, "reason": "missing_bucket",
                    "message": "❌ 货币表缺失，无法入账"}
        space = self._currency_space()
        if "gem" not in space:
            return {"ok": False, "reason": "unknown_currency",
                    "message": "❌ 宝石未登记在货币键空间（settings.currencies 需含 gem）",
                    "currency_space": list(space)}
        ctx["currencies"]["gem"] = int(ctx["currencies"].get("gem", 0)) + amt
        return {"ok": True, "reason": None, "currency": "gem", "amount": amt,
                "balance": int(ctx["currencies"]["gem"]), "message": f"宝石 +{amt}"}
