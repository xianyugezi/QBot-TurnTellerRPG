"""品质系统引擎（M8 批1·路1B）——品质四档判定/系数/成品聚合/批量平均品质/上限叠加/未达标降级。

文件：qbot_rpg/core/quality.py
创建：2026-08-29
作者：Hermes 子agent-1B
功能：M8 炼金品质系统（QLT-01~13）纯函数引擎——品质四档唯一注册表（common/uncommon/rare/
      legendary ↔ 普通/精良/史诗/传说，拍板②）、品质分 0-100 区间落档（QLT-02/03）、档位系数
      （QLT-04）、成品品质分=投料材料品质分均值四舍五入（QLT-06 工程补白）、批量平均品质
      （QLT-07）、品质上限三处叠加（QLT-08）、未达标降级最低普通封底不吞材料（QLT-10）、
      档位序号换算。供批6A /确认 品质结算与批7B 珠档位消费点复用。

依据：
  - docs/细化/细化_2c4e_品质与特性.md 一（QLT-01~13）/ 五（TC-01~TC-11）
  - docs/m8_contract_核心机制.md §四（品质系统 QLT-01~13 全文）
  - docs/m8_contract_数据与校验.md §五（quality_tiers/quality_coef 键集 common/uncommon/
    rare/legendary，拍板②）
  - 批0 落地数据 content/test_demo/settings.json alchemy 段（quality_tiers {common:[0,39],
    uncommon:[40,59], rare:[60,79], legendary:[80,100]}、quality_coef {common:0.8,
    uncommon:1.0, rare:1.2, legendary:1.5}）——引擎构造兼容此形态（[lo,hi] 列表或 {min,max} 对象）
  - 模式参考 qbot_rpg/core/levelup.py LevelUpEngine（构造器配置注入 + 缺省默认值兜底；
    纯函数零 IO 零 NoneBot）

【工程补白 · 显式标注】（定稿未给口径处，本引擎最小必要推导，不得新增定稿外机制行为）：
  Q-1  成品品质分聚合公式（QLT-06）：定稿未给聚合公式，取最小必要推导——全部投料材料品质分
       均值，四舍五入取整（round-half-up，非 Python 默认 round 银行家舍入）；空列表防御返回 0。
  Q-2  品质上限叠加（QLT-08）：hard_max = 无加成时的基准可达上限（配方原上限，默认 100）；
       extra_cap = 三处加成合计（SP 品质上限+10×N + 核心镶嵌+X + 挑战+10），只放宽可达上限；
       可达上限 = min(hard_max + extra_cap, 100)（QLT-08：品质分仍 ≤100）；返回
       min(score, 可达上限)。默认配置（hard_max=100）下加成被 100 封顶吞掉（忠实「只放宽
       可达上限、品质分 ≤100」）；配方原上限 <100 时 extra_cap 真实放宽可达上限。
  Q-3  未达标降级分数口径（QLT-10）：降档后分数 = 原品质分裁剪到降档后档位区间 [lo, hi]
       （不增分、落档稳定：score_to_tier(降后分数) == 降后档位）；最低档封底不再降。
  Q-4  score_to_tier 越域防御：品质分裁剪到配置覆盖域 [min_lo, max_hi] 内落档（默认
       [0,100]，QLT-02 品质分 0-100 计算口径）。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；不抛异常（配置缺省兜底、方法防御降级）；
      档位键集只允许 common/uncommon/rare/legendary（拍板②），不另设档位（QLT-01）。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, cast

__all__ = [
    "ABSOLUTE_QUALITY_MAX",
    "DEFAULT_QUALITY_COEF",
    "DEFAULT_QUALITY_TIERS",
    "DEFAULT_TIER_LABELS",
    "QUALITY_KEYS",
    "QUALITY_KEYS_CN",
    "QualitySystem",
]

# 品质四档唯一注册表默认模板（拍板② 键集 + 数值：定稿 L411 / 细化 QLT-02/03 / 批0 settings）
DEFAULT_QUALITY_TIERS: Dict[str, Tuple[int, int]] = {
    "common": (0, 39),
    "uncommon": (40, 59),
    "rare": (60, 79),
    "legendary": (80, 100),
}

# 档位系数默认模板（定稿 L412 / 细化 QLT-04，数值不变）
DEFAULT_QUALITY_COEF: Dict[str, float] = {
    "common": 0.8,
    "uncommon": 1.0,
    "rare": 1.2,
    "legendary": 1.5,
}

# 档位中文名（拍板② 键集 ↔ 中文：普通/精良/史诗/传说；对齐 field_meta.QUALITY_KEYS_CN）
DEFAULT_TIER_LABELS: Dict[str, str] = {
    "common": "普通",
    "uncommon": "精良",
    "rare": "史诗",
    "legendary": "传说",
}

# 品质档键集（拍板②；与 content/field_meta.QUALITY_KEYS 同源，引擎本地持有保持零依赖）
QUALITY_KEYS: Tuple[str, ...] = ("common", "uncommon", "rare", "legendary")
QUALITY_KEYS_CN: Tuple[str, ...] = ("普通", "精良", "史诗", "传说")

# 品质分绝对上限（QLT-08：品质分仍 ≤100；0-100 为品质分计算口径）
ABSOLUTE_QUALITY_MAX: int = 100


class QualitySystem:
    """品质系统引擎（细化_2c4e 一：QLT-01~13）。

    构造器配置注入（quality_tiers/quality_coef/tier_labels）+ 缺省默认值兜底；
    纯函数，零 IO 零 NoneBot，不抛异常。档位判定/系数/聚合/上限/降级全部由本引擎提供，
    供批6A 品质结算与批7B 珠档位消费点复用。
    """

    def __init__(
        self,
        quality_tiers: Optional[Mapping[str, object]] = None,
        quality_coef: Optional[Mapping[str, object]] = None,
        tier_labels: Optional[Mapping[str, str]] = None,
    ) -> None:
        """构造品质引擎（配置注入 + 缺省默认值兜底，QLT-02/04）。

        - quality_tiers：档位注册表 {档位: [lo, hi]}（兼容 {min, max} 对象，批0 settings
          形态【工程补白 P-1】）；None/空 → 默认四档 {common:[0,39]..legendary:[80,100]}。
        - quality_coef：档位系数 {档位: 数值}；None/空 → 默认 {0.8,1.0,1.2,1.5}。
        - tier_labels：档位中文名（默认 普通/精良/史诗/传说）；缺标签的档位回落键名自身。
        """
        raw_tiers = dict(quality_tiers) if quality_tiers else {}
        raw_coef = dict(quality_coef) if quality_coef else {}
        raw_labels = dict(tier_labels) if tier_labels else {}

        if not raw_tiers:
            raw_tiers = dict(DEFAULT_QUALITY_TIERS)
        if not raw_coef:
            raw_coef = dict(DEFAULT_QUALITY_COEF)
        if not raw_labels:
            raw_labels = dict(DEFAULT_TIER_LABELS)

        # 归一区间：值形态 [lo,hi] 列表/元组 或 {min,max} 对象（工程补白 P-1 兼容）
        self._tiers: Dict[str, Tuple[int, int]] = {}
        for key, val in raw_tiers.items():
            parsed = self._parse_range(val)
            if parsed is not None:
                self._tiers[str(key)] = parsed
        if not self._tiers:
            # 全部区间非法/缺失 → 兜底默认四档（缺省默认值兜底铁律）
            self._tiers = dict(DEFAULT_QUALITY_TIERS)

        # 档位序号序：按区间 lo 升序（QLT-03 单调覆盖 0-100 不重叠）
        self._order: List[str] = sorted(self._tiers, key=lambda k: self._tiers[k][0])
        self._domain_lo: int = min(lo for lo, _ in self._tiers.values())
        self._domain_hi: int = max(hi for _, hi in self._tiers.values())

        self._coef: Dict[str, float] = {}
        for k, v in raw_coef.items():
            try:
                self._coef[str(k)] = float(cast(Any, v))
            except (TypeError, ValueError):
                continue  # 非法系数值跳过（缺省兜底：coef_for 回落中性 1.0）
        self._labels: Dict[str, str] = {str(k): str(v) for k, v in raw_labels.items()}

    @staticmethod
    def _parse_range(value: object) -> Optional[Tuple[int, int]]:
        """区间值归一 → (lo, hi)；非法 → None。

        【工程补白 P-1】值形态 [lo, hi] 两元素 int 列表/元组，或 {min, max} 对象
        （对齐 alchemy_settings._parse_range，批0 settings 兼容）。
        """
        if isinstance(value, (list, tuple)) and len(value) == 2:
            lo, hi = value[0], value[1]
            if (
                isinstance(lo, int)
                and not isinstance(lo, bool)
                and isinstance(hi, int)
                and not isinstance(hi, bool)
                and lo <= hi
            ):
                return (lo, hi)
            return None
        if isinstance(value, Mapping):
            lo, hi = value.get("min"), value.get("max")
            if (
                isinstance(lo, int)
                and not isinstance(lo, bool)
                and isinstance(hi, int)
                and not isinstance(hi, bool)
                and lo <= hi
            ):
                return (lo, hi)
        return None

    # ------------------------------------------------------------------
    # 档位判定（QLT-02/03/01）
    # ------------------------------------------------------------------
    def score_to_tier(self, score: int) -> str:
        """品质分 → 档位键（QLT-02/03）。

        入参：score 品质分（0-100 整数口径，四舍五入取整后落档）。
        出参：档位键 common/uncommon/rare/legendary。
        核心：score ∈ [lo, hi] → 档位；边界 39→common、40→uncommon、59→uncommon、
              60→rare、79→rare、80→legendary、100→legendary。
        【工程补白 Q-4】越域防御：score 裁剪到配置覆盖域 [domain_lo, domain_hi] 内落档。
        """
        score = int(score)
        if score < self._domain_lo:
            score = self._domain_lo
        elif score > self._domain_hi:
            score = self._domain_hi
        for key in self._order:
            lo, hi = self._tiers[key]
            if lo <= score <= hi:
                return key
        # 理论不可达：配置非单调覆盖时兜底返回覆盖域内最高区间档（防御，QLT-03 校验器只提示）
        return self._order[-1]

    def tier_label(self, tier: str) -> str:
        """档位键 → 中文档名（拍板② 键集 ↔ 中文：普通/精良/史诗/传说）。

        缺标签的档位（3/5/7 可配档位数场景）回落键名自身，不抛异常。
        """
        return self._labels.get(str(tier), str(tier))

    def tier_index(self, tier: str) -> int:
        """档位序号（0 起，按区间 lo 升序，QLT-03）。

        供降级换算（QLT-10）；未知档位 → 0（普通封底，防御）。
        """
        try:
            return self._order.index(str(tier))
        except ValueError:
            return 0

    def index_to_tier(self, index: int) -> str:
        """档位序号 → 档位键；越界裁剪到 [0, len-1]（防负档，QLT-10 绝不成负档）。"""
        try:
            i = int(index)
        except (TypeError, ValueError):
            i = 0
        if i < 0:
            i = 0
        if i >= len(self._order):
            i = len(self._order) - 1
        return self._order[i]

    # ------------------------------------------------------------------
    # 档位系数（QLT-04）
    # ------------------------------------------------------------------
    def coef_for(self, tier: str) -> float:
        """档位系数（QLT-04：common 0.8/uncommon 1.0/rare 1.2/legendary 1.5）。

        未知档位 → 1.0（中性系数，防御——只放大数值不改效果结构）。
        """
        return float(self._coef.get(str(tier), 1.0))

    def effect_value(self, base: float, tier: str) -> float:
        """成品效果数值 = 基准效果 × 档位系数（QLT-04）。

        只放大数值不改效果结构；返回 float（是否取整由调用方/展示层决定，批6A 结算侧）。
        """
        return float(base) * self.coef_for(tier)

    # ------------------------------------------------------------------
    # 成品品质分聚合（QLT-06/07）
    # ------------------------------------------------------------------
    def aggregate_quality(self, material_scores: Sequence[int]) -> int:
        """成品品质分 = 全部投料材料品质分均值（四舍五入取整）（QLT-06 工程补白 Q-1）。

        入参：material_scores 各投料材料品质分列表（Sequence[int]）。
        出参：聚合品质分 int（0-100 口径）。
        核心：四舍五入 = round-half-up（int(math.floor(mean + 0.5))，非 Python 默认 round
              银行家舍入）；空列表防御返回 0（QLT-06 基础调合 100% 成功，空投料按 0 分兜底）。
        """
        n = len(material_scores)
        if n == 0:
            return 0
        total = 0.0
        for s in material_scores:
            total += float(s)
        return int(math.floor(total / n + 0.5))

    def batch_tier(self, material_scores: Sequence[int]) -> str:
        """批量调合档位 = 平均品质档（QLT-07，QLT-06 均值口径）。

        引擎只算档位；批量「丢特性」（QLT-07 批量是保底通道）由会话层处理——本引擎零特性接触。
        """
        return self.score_to_tier(self.aggregate_quality(material_scores))

    # ------------------------------------------------------------------
    # 品质上限叠加（QLT-08）
    # ------------------------------------------------------------------
    def cap_quality(self, score: int, *, extra_cap: int = 0, hard_max: int = 100) -> int:
        """品质上限三处叠加（QLT-08，工程补白 Q-2）。

        入参：
          - score：聚合后的品质分（均值/加成道具增量已施加后）。
          - extra_cap：三处加成合计（SP 品质上限+10×N + 核心镶嵌+X + 挑战+10），只放宽
            可达上限；由调用方把 SP quality_cap_10 计数等折算后传入（批6A / 批8A）。
          - hard_max：无加成时的基准可达上限（配方原上限），默认 100。
        出参：裁剪后的品质分 int。
        核心：可达上限 = min(hard_max + extra_cap, 100)（QLT-08：品质分仍 ≤100）；
              返回 min(score, 可达上限)。默认配置（hard_max=100）下加成被 100 封顶吞掉
              （忠实「只放宽可达上限、品质分 ≤100」）；配方原上限 <100 时 extra_cap 真实放宽。
        """
        try:
            s = int(score)
        except (TypeError, ValueError):
            s = 0
        try:
            extra = int(extra_cap)
        except (TypeError, ValueError):
            extra = 0
        try:
            hmax = int(hard_max)
        except (TypeError, ValueError):
            hmax = ABSOLUTE_QUALITY_MAX
        if s < 0:
            s = 0
        if extra < 0:
            extra = 0
        reachable = min(hmax + extra, ABSOLUTE_QUALITY_MAX)
        if s > reachable:
            return reachable
        return s

    # ------------------------------------------------------------------
    # 未达标降级（QLT-10）
    # ------------------------------------------------------------------
    def degrade_quality(self, score: int, levels: int) -> Tuple[str, int]:
        """未达标降级（QLT-10，工程补白 Q-3）。

        入参：
          - score：当前品质分。
          - levels：未达标差档数（≥1 生效；≤0 → 不降级原样返回）。
        出参：(降档后档位, 降档后品质分)。
        核心：差 levels 档降 levels 档；最低档（common）封底不再降——绝不成负档、不吞材料
              （QLT-10：任何未达标不失败、不吞材料，降级出货）。
        分数口径【工程补白 Q-3】：降档后分数 = 原品质分裁剪到降档后档位区间 [lo, hi]
              （不增分、落档稳定：score_to_tier(降后分数) == 降后档位）。
        封底识别：返回档位 == 最低档键（默认 common）即已到下限。
        """
        try:
            s = int(score)
        except (TypeError, ValueError):
            s = 0
        try:
            lv = int(levels)
        except (TypeError, ValueError):
            lv = 0
        cur = self.score_to_tier(s)
        if lv <= 0:
            return (cur, s)
        new_index = max(0, self.tier_index(cur) - lv)
        new_tier = self.index_to_tier(new_index)
        lo, hi = self._tiers[new_tier]
        clamped = s
        if clamped < lo:
            clamped = lo
        elif clamped > hi:
            clamped = hi
        return (new_tier, clamped)

    # ------------------------------------------------------------------
    # 只读快照（供展示 / 批7B 珠档位消费点 / 批8A 珠升阶下一步）
    # ------------------------------------------------------------------
    @property
    def tiers(self) -> Dict[str, Tuple[int, int]]:
        """档位区间只读快照 {档位: (lo, hi)}（QLT-02 配置视图）。"""
        return dict(self._tiers)

    @property
    def tier_order(self) -> List[str]:
        """档位序号序（lo 升序）只读快照（QLT-03）。"""
        return list(self._order)

    @property
    def tier_count(self) -> int:
        """档位数（默认 4；3/5/7 可配、0=不限制走兜底，QLT-05）。"""
        return len(self._order)
