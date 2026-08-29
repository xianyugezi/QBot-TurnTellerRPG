"""调合会话核心引擎（M8 批4A·路1）——链式投料会话快照/连锁段数/属性刻度/特性候选池/PP 预算/
触媒/全物入料/确认复核/面板悬念分级。

文件名：qbot_rpg/core/alchemy_core.py
创建时间：2026-08-29
作者：Hermes 子agent-4A-1（并发同仓：仅新建本文件 + tests/unit/test_alchemy_core.py；
      兄弟路 2 在写 core/energy_bar.py 等（能量条/配平/批量引擎），本文件零 import 之，只读勿探查）

功能描述：AlchemyCore —— 调合会话核心引擎（纯逻辑零 IO 零 NoneBot）。承载「链式投料」会话内
  全部核心计算：会话快照（§7.1 形态：配方ID/材料链/连锁/特性候选池/触媒/PP/步骤/version）、
  投料计算（连锁段数 FEED-06 / 属性刻度 FEED-07 / 特性候选池 FEED-08·INH-01~04 / 全物入料
  FEED-09）、PP 预算（TSC-14）、触媒（CAT-02/03/05）、确认全量复核（FEED-10）、面板渲染数据
  （FEED-07/STO-08/QLT-13 悬念分级）。供批4B 指令壳（/炼金 开会话面板 /投料 /确认）与批6A
  结算消费。

依据：
  - docs/细化/细化_2c4f_投料触媒与能量条.md：FEED-01~10（槽位上限 FEED-04/材料持有 FEED-05/
    连锁段数 FEED-06/属性刻度 FEED-07/特性候选 FEED-08/全物入料 FEED-09/确认全量复核 FEED-10）、
    CAT-01~06（触媒：改变材料属性判定 CAT-02/注册制 CAT-03/type=触媒 CAT-05）、TC-01~20。
  - docs/m8_contract_核心机制.md：§五（TSC：PP 预算 pp_cost/pp_refresh 会话重置、超特性第 4 位、
    source 分类 INH-04）、§六（FEED 全文）、§七（快照形态 STO-03：配方ID+材料链+连锁+特性+
    触媒+PP+步骤+version）、§四（QLT-11~13 属性刻度×品质/悬念分级）。
  - docs/m8_contract_数据与校验.md：§一（recipe.json：slots/element_req{元素:[{阈值,效果}]}/
    traits_inherit/catalyst[]/pp_budget）、§二（traits.json：rarity/source/name）、§四（items.json：
    elements/traits/quality/awaken/type=触媒）、§五（settings alchemy：chain_map/pp_cost/
    pp_refresh）。
  - 已落地：qbot_rpg/core/proficiency.py（ProficiencyEngine tier 判定，投料全物入料需专家=档位
    索引 3）、qbot_rpg/core/quality.py（QualitySystem 品质）、qbot_rpg/core/alchemy_session.py
    （状态机）、content/test_demo/ 的 recipe.json/traits.json/items.json/settings.json。
  - 模式参考：core/reward.py + shop.py（ctx hook：ctx["items"]/["traits"]/["recipe"] 注册表、
    ctx["count_item"](id)->int）、core/quality.py（构造注入+缺省兜底）、core/levelup.py
    （纯函数引擎）。

【工程补白 · 显式标注】（定稿/细化未给口径处，本引擎最小必要推导，不得新增定稿外机制行为）：
  A-1  连锁段数边界（FEED-06）：段数 = 相邻同属性对数（连续 n 个 = n-1 段）；材料 count 展开为
       n 个链位（火晶石*2 即 2 个链位，TC-06「入链」）；首尾同属性照计（相邻即计，不排除首尾）。
       效果等级 = chain_map[段数]；段数超 chain_map 上限 → 钳制到最高配置等级；0 段/低于最小 →
       0（无效果等级）【最小必要推导：chain_map 可配 1:1…6:6，未定义超界行为】。
  A-2  材料「当前属性」判定（FEED-06 同属性判定口径）：items.json `elements` 的**主元素**（值最大
       者，平局按 8 元素注册表顺序 地水火风雷晶月无 取先）；无 elements 字段的材料属性 = None
       （无属性，不与任何元素成段）。
  A-3  触媒方向修饰（CAT-02/TC-16）：触媒物品的 `elements` 主元素即触媒方向；会话带触媒时材料
       「当前属性」= 触媒方向（连锁同属性判定与属性刻度累计均按新属性，L153）。触媒无 elements
       （如 test_demo 火之精华触媒）→ 不修饰方向（注册制仍通过 type 校验）。
  A-4  成品/装备判定（FEED-09 全物入料）：材料为「成品/装备」= items.json 该物品 `type` 非
       素材/触媒/种子 或带 `quality` 字段；type=material 视为原材料不触发全物入料折算。
  A-5  全物入料折算公式（FEED-09）：① 元素 = 成品/装备 items.json `elements` 原样累计（与普通
       材料同口径）；② 特性 = 成品携带 traits 按 source 分类入池（INH-04 成品 source 原样入池）；
       ③ 品质 = 成品 quality 参与成品品质均值（QLT-06，由批6A 结算消费）；④ 无 elements 字段的
       成品/装备 → 按品质档折算等值元素分（common=1/uncommon=2/rare=3/legendary=4）归入「无」
       (void) 元素桶【最小必要推导：定稿仅言「按 items 元素/特性/品质折算」未给公式】。
  A-6  投料槽位单位（FEED-04/TC-04）：slots 上限 = 材料单位总数（∑count，火晶石*2 占 2 槽），
       非条目数——对齐「连续 n 个同属性 = n-1 段」的单位口径与深度配方 6 槽示例（L235）。
  A-7  觉醒候选（FEED-08/INH-08）：✨素材（items.json awaken=true）投料 → 其携带特性入「觉醒
       候选池」（隐藏效果候选），不并入普通/超特性池【最小必要推导：定稿仅言「✨觉醒素材→隐藏
       效果候选」未给入池细则】。
  A-8  面板悬念分级（FEED-07/STO-08/QLT-13）：精通（index≥2）起显现刻度：未达标 → 引导语
       「火系还差一点，试试多投火系材料？」；大师（index≥4）起显示精确阈值「火 42/45」；
       精通前（index<2）刻度效果不显现（display=None）。刻度效果显现需 ≥ 精通（QLT-13）。

铁律：零 NoneBot import；纯函数（同刻同参必同值，ctx 只读不改写）；不抛异常（防御降级返回 dict）；
      每条规则注释标注出处（FEED/CAT/TSC/QLT 编号 + 定稿/细化行号）；不得新增定稿外机制行为。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "ALCHEMY_JOB_ID",
    "ELEMENTS",
    "ELEMENT_NAMES_CN",
    "ELEMENT_VOID",
    "DEFAULT_CHAIN_MAP",
    "DEFAULT_PP_COST",
    "DEFAULT_TIER_NAMES",
    "EXPERT_TIER_INDEX",
    "PROFICIENT_TIER_INDEX",
    "MASTER_TIER_INDEX",
    "STEP_FEED",
    "STEP_INHERIT",
    "STEP_CONFIRM",
    "SUSPENSE_HIDDEN",
    "SUSPENSE_GUIDE",
    "SUSPENSE_PRECISE",
    "AlchemyCore",
]

# ---------------------------------------------------------------------------
# 常量（8 元素注册表：定稿 L387「地水火风雷晶月无」，战斗弱点+炼金刻度+触媒方向共用；
# 键名对齐 items.json/element_req 数据（test_demo 用 earth/water/fire/void 等））
# ---------------------------------------------------------------------------
ALCHEMY_JOB_ID: str = "alchemy"  # 炼金职业 ID（proficiency.json id / jobs.json）

# 8 元素注册表顺序（定稿 L387；主元素平局仲裁顺序）
ELEMENTS: Tuple[str, ...] = (
    "earth", "water", "fire", "wind", "lightning", "crystal", "moon", "void"
)
# 元素中文名（面板/引导语展示）
ELEMENT_NAMES_CN: Mapping[str, str] = {
    "earth": "地",
    "water": "水",
    "fire": "火",
    "wind": "风",
    "lightning": "雷",
    "crystal": "晶",
    "moon": "月",
    "void": "无",
}
ELEMENT_VOID: str = "void"  # 「无」元素桶（全物入料折算兜底落点，A-5）

# chain_map 默认模板（FEED-06/L413：1 段=1 级…6 段=6 级，settings.alchemy.chain_map 可配）
DEFAULT_CHAIN_MAP: Dict[int, int] = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}
# PP 消耗默认模板（TSC-14/L414：normal=1/super=2，settings.alchemy.pp_cost 可配；rarity 是唯一依据）
DEFAULT_PP_COST: Dict[str, int] = {"normal": 1, "super": 2}
# 7 级称号默认名（JOB-01：见习→王；与 proficiency.json tier_names 对齐）
DEFAULT_TIER_NAMES: Tuple[str, ...] = ("见习", "正式", "精通", "专家", "大师", "宗师", "王")

# 档位索引锚点（tier_index 0 起：见习0/正式1/精通2/专家3/大师4/宗师5/王6）
EXPERT_TIER_INDEX: int = 3       # 专家：全物入料解锁（L218）+ 触媒解锁（CAT-01 R-07）
PROFICIENT_TIER_INDEX: int = 2   # 精通：属性刻度效果显现门槛（QLT-13）
MASTER_TIER_INDEX: int = 4       # 大师：精确阈值显示门槛（FEED-07 悬念分级）

# 会话步骤（§4.6 状态机步骤链：投料 → 继承 → 确认；引擎只存/回显，推进由壳层负责）
STEP_FEED: str = "feed"          # 投料中
STEP_INHERIT: str = "inherit"    # 继承中
STEP_CONFIRM: str = "confirm"    # 确认待

# 刻度悬念分级（FEED-07/STO-08/QLT-13，A-8）
SUSPENSE_HIDDEN: int = 0         # < 精通：刻度效果不显现
SUSPENSE_GUIDE: int = 1          # 精通/专家：第 2 层引导语
SUSPENSE_PRECISE: int = 2        # 大师+：精确阈值「火 42/45」

# 全物入料折算：无 elements 的成品/装备按品质档折算等值元素分（A-5 最小必要推导）
QUALITY_ELEMENT_FALLBACK: Dict[str, int] = {"common": 1, "uncommon": 2, "rare": 3, "legendary": 4}


def _clamp_int(value: Any, default: int = 0, *, lo: int = 0, hi: Optional[int] = None) -> int:
    """防御取整（bool 排除）；越界钳制。"""
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return default
    if value < lo:
        value = lo
    if hi is not None and value > hi:
        value = hi
    return value


class AlchemyCore:
    """调合会话核心引擎（FEED-01~10 / CAT-01~06 / TSC-11~14 / QLT-11~13 纯函数承载）。

    构造器配置注入（proficiency 引擎 + settings）+ 缺省默认值兜底（对齐 levelup.py / quality.py
    模式）。纯函数零 IO 零 NoneBot，不抛异常；ctx 只读（材料/特性/配方注册表 + count_item 计数），
    扣材料/能量等副作用由壳层在事务内执行。
    """

    def __init__(
        self,
        prof: Optional[Any] = None,
        settings: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """构造调合核心引擎（配置注入 + 缺省默认值兜底）。

        入参：
          - prof：ProficiencyEngine 实例（可选注入；用于 job_tier 称号名 → 档位索引归一，
            缺省按默认 7 级称号兜底）。
          - settings：settings dict（读 alchemy 段 chain_map/pp_cost/pp_refresh）；
            None/缺 alchemy 段 → 默认模板兜底（对齐 m8_contract §10.3 默认值速查）。
        """
        self._prof = prof
        self._settings: Mapping[str, Any] = settings if isinstance(settings, Mapping) else {}

    # ------------------------------------------------------------------
    # 配置读取（缺省默认值兜底）
    # ------------------------------------------------------------------
    def _alchemy_settings(self) -> Mapping[str, Any]:
        """settings.alchemy 段（缺省空 Mapping，调用方各自兜底）。"""
        alch = self._settings.get("alchemy")
        if isinstance(alch, Mapping):
            return alch
        return {}

    def _chain_map(self) -> Dict[int, int]:
        """段数→效果等级映射（FEED-06/L413，settings.alchemy.chain_map 可配；缺省 1:1…6:6）。"""
        raw = self._alchemy_settings().get("chain_map")
        out: Dict[int, int] = {}
        if isinstance(raw, Mapping):
            for k, v in raw.items():
                try:
                    kk, vv = int(k), int(v)
                except (TypeError, ValueError):
                    continue
                if kk >= 1:
                    out[kk] = vv
        if not out:
            out = dict(DEFAULT_CHAIN_MAP)
        return out

    def _pp_cost(self) -> Dict[str, int]:
        """特性继承 PP 消耗表（TSC-14/L414，settings.alchemy.pp_cost 可配；
缺省 normal=1/super=2）。"""
        raw = self._alchemy_settings().get("pp_cost")
        out: Dict[str, int] = {}
        if isinstance(raw, Mapping):
            for k in ("normal", "super"):
                try:
                    out[k] = max(0, int(raw.get(k, DEFAULT_PP_COST[k])))
                except (TypeError, ValueError):
                    out[k] = DEFAULT_PP_COST[k]
        else:
            out = dict(DEFAULT_PP_COST)
        return out

    def _pp_refresh(self) -> str:
        """PP 重置时机（TSC-14/L415 pp_refresh="会话重置"：会话内累计、
        /确认 结算后随会话重置）。"""
        raw = self._alchemy_settings().get("pp_refresh")
        if isinstance(raw, str) and raw:
            return raw
        return "会话重置"

    def _tier_names(self) -> Tuple[str, ...]:
        """7 级称号名（用于 job_tier 称号名→索引归一；prof 注入则优先用其 tier_names）。"""
        prof = self._prof
        if prof is not None:
            try:
                job_entry = getattr(prof, "_entry", lambda _j: None)(ALCHEMY_JOB_ID)
                raw = job_entry.get("tier_names") if job_entry else None
                if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                    return tuple(str(x) for x in raw)
            except Exception:
                pass
        return DEFAULT_TIER_NAMES

    def _norm_tier_index(self, job_tier: Any) -> int:
        """job_tier 归一为档位索引 int（见习0/正式1/精通2/专家3/大师4/宗师5/王6）。

        int → 钳制 ≥0；str（称号名）→ 查 7 级表；None/其它 → 0（见习兜底）。
        """
        if isinstance(job_tier, bool):
            return 0
        if isinstance(job_tier, int):
            return max(0, job_tier)
        if isinstance(job_tier, str) and job_tier:
            names = self._tier_names()
            if job_tier in names:
                return names.index(job_tier)
            # 兼容英文 tier 名（专家=expert 等）
            alias: Dict[str, int] = {
                "apprentice": 0, "formal": 1, "proficient": 2, "expert": 3,
                "master": 4, "grandmaster": 5, "king": 6,
            }
            return alias.get(job_tier, 0)
        return 0

    # ------------------------------------------------------------------
    # ctx 注册表读取（items/traits/recipe：dict id→def，或 resolve_xxx 解析器，或 name 扫描）
    # ------------------------------------------------------------------
    @staticmethod
    def _find_def(
        key: Any, ctx: Mapping[str, Any], reg_key: str, resolve_key: str
    ) -> Optional[dict]:
        """注册表/解析器/名称扫描取 def（对齐 reward.py _item_exists 鸭子模式）。

        入参：key=id 或 name；ctx；reg_key=注册表键（"items"/"traits"/"recipe"）；
              resolve_key=解析器键（"resolve_item"/"resolve_trait"/"resolve_recipe"）。
        出参：def dict 或 None。查找顺序：①注册表直接键（id 优先）②解析器 ③注册表按 name 扫描。
        """
        if not isinstance(key, str) or not key:
            return None
        reg = ctx.get(reg_key)
        if isinstance(reg, Mapping) and key in reg:
            val = reg[key]
            return dict(val) if isinstance(val, Mapping) else None
        resolver = ctx.get(resolve_key)
        if callable(resolver):
            try:
                val = resolver(key)
                if isinstance(val, Mapping):
                    return dict(val)
            except Exception:
                return None
        if isinstance(reg, Mapping):
            for val in reg.values():
                if isinstance(val, Mapping) and val.get("name") == key:
                    return dict(val)
        return None

    def _find_item(self, key: Any, ctx: Mapping[str, Any]) -> Optional[dict]:
        """按 id 或 name 查 items.json def（ctx[\"items\"] 注册表 / ctx[\"resolve_item\"]）。"""
        return self._find_def(key, ctx, "items", "resolve_item")

    def _find_trait(self, key: Any, ctx: Mapping[str, Any]) -> Optional[dict]:
        """按 id 查 traits.json def（ctx[\"traits\"] 注册表 / ctx[\"resolve_trait\"]）。"""
        return self._find_def(key, ctx, "traits", "resolve_trait")

    def _find_recipe(self, key: Any, ctx: Mapping[str, Any]) -> Optional[dict]:
        """按 id 查 recipe.json def（ctx[\"recipe\"] 注册表 / ctx[\"resolve_recipe\"]）。"""
        return self._find_def(key, ctx, "recipe", "resolve_recipe")

    @staticmethod
    def _ctx_have(ctx: Mapping[str, Any], item_id: str) -> int:
        """背包持有数（ctx[\"count_item\"](id)->int 优先；ctx[\"inventory\"] dict 兜底）。"""
        count_item = ctx.get("count_item")
        if callable(count_item):
            try:
                return max(0, int(count_item(item_id)))
            except Exception:
                return 0
        inv = ctx.get("inventory")
        if isinstance(inv, Mapping):
            try:
                return max(0, int(inv.get(item_id, 0)))
            except (TypeError, ValueError):
                return 0
        return 0

    # ------------------------------------------------------------------
    # 材料「当前属性」判定（FEED-06/CAT-02，A-2/A-3）
    # ------------------------------------------------------------------
    @staticmethod
    def _main_element(elements: Mapping[str, Any]) -> Optional[str]:
        """材料主元素（A-2）：值最大者，平局按 8 元素注册表顺序取先；无/空 → None。"""
        if not isinstance(elements, Mapping):
            return None
        best: Optional[str] = None
        best_val: int = -1
        for elem in ELEMENTS:
            try:
                val = int(elements.get(elem, 0))
            except (TypeError, ValueError):
                val = 0
            if val > best_val:
                best_val = val
                best = elem
        return best

    @staticmethod
    def _catalyst_element(catalyst_def: Optional[Mapping[str, Any]]) -> Optional[str]:
        """触媒方向主元素（CAT-02/A-3）：触媒 items.json `elements` 主元素；
无/非 Mapping → None。"""
        if not isinstance(catalyst_def, Mapping):
            return None
        elements = catalyst_def.get("elements")
        if not isinstance(elements, Mapping):
            return None
        return AlchemyCore._main_element(elements)

    def _effective_element(
        self,
        record: Mapping[str, Any],
        catalyst_def: Optional[Mapping[str, Any]] = None,
    ) -> Optional[str]:
        """材料「当前属性」（FEED-06：同属性判定=材料当前属性，触媒改变后按新属性，L153）。

        有触媒方向 → 一律取触媒方向（A-3）；否则取材料主元素（A-2，可能 None=无属性）。
        """
        cat_elem = self._catalyst_element(catalyst_def)
        if cat_elem is not None:
            return cat_elem
        main = record.get("main_element")
        return main if isinstance(main, str) else None

    # ------------------------------------------------------------------
    # 材料记录解析（apply_feed 用：raw {item,count} 条目 → 解析记录，携带属性/特性/品质）
    # ------------------------------------------------------------------
    def _is_finished(self, item_def: Mapping[str, Any]) -> bool:
        """成品/装备判定（FEED-09/A-4）：type 非 素材/触媒/种子，或带 quality 字段。"""
        t = item_def.get("type")
        if t in ("material", "触媒", "种子"):
            return False
        if "quality" in item_def:
            return True
        return isinstance(t, str) and bool(t)

    def _resolve_material(self, entry: Any, ctx: Mapping[str, Any]) -> Optional[dict]:
        """解析单条投料条目 → 材料记录（TC-06：条目形态 {item, count}）。

        入参：entry={item|id, count}（count 缺省 1，int 非负）。
        出参：材料记录 dict 或 None（条目非法 / 物品不存在）。记录字段：
          {item, count, name, elements, main_element, traits, rarity, quality, awaken,
          is_finished}。
        """
        if not isinstance(entry, Mapping):
            return None
        item_id = entry.get("item") or entry.get("id")
        if not isinstance(item_id, str) or not item_id:
            return None
        idef = self._find_item(item_id, ctx)
        if idef is None:
            return None  # 材料不存在（FEED-05 前置：解析即校验存在）
        count_raw = entry.get("count", 1)
        if isinstance(count_raw, bool) or not isinstance(count_raw, int) or count_raw < 1:
            count = 1  # 数量非法 → 保守按 1（防御；批11 解析层已做数量铁律）
        else:
            count = count_raw
        elements = idef.get("elements")
        if not isinstance(elements, Mapping):
            elements = {}
        traits = idef.get("traits")
        if not isinstance(traits, (list, tuple)):
            traits = []
        return {
            "item": item_id,
            "count": count,
            "name": str(idef.get("name") or item_id),
            "elements": {str(k): int(v) for k, v in elements.items()
                         if not isinstance(v, bool) and isinstance(v, int)},
            "main_element": self._main_element(elements),
            "traits": [str(t) for t in traits],
            "rarity": idef.get("rarity"),
            "quality": idef.get("quality"),
            "awaken": bool(idef.get("awaken", False)),
            "is_finished": self._is_finished(idef),
        }

    def _snap_catalyst_def(self, snap: Mapping[str, Any], ctx: Mapping[str, Any]) -> Optional[dict]:
        """快照触媒 → 触媒 def（用于连锁/刻度重算的属性修饰，A-3）。

        快照 catalyst 存触媒名/ID（字符串）或已解析 def（Mapping）；字符串经 _find_item + type=触媒
        校验（非法/未注册 → None 不修饰）。
        """
        raw = snap.get("catalyst")
        if isinstance(raw, Mapping):
            return dict(raw) if raw.get("type") == "触媒" else None
        if isinstance(raw, str) and raw:
            idef = self._find_item(raw, ctx)
            if idef is not None and idef.get("type") == "触媒":
                return dict(idef)
        return None

    # ------------------------------------------------------------------
    # 会话快照（§7.1 快照形态：配方ID+材料链+连锁+特性+触媒+PP+步骤+version；STO-03）
    # ------------------------------------------------------------------
    def new_snapshot(
        self,
        recipe_def: Mapping[str, Any],
        *,
        catalyst: Optional[str] = None,
        job_tier: Any = None,
    ) -> dict:
        """新建调合会话快照（§7.1 行1 acquire 后由壳层持久化；STO-03 形态）。

        入参：
          - recipe_def：recipe.json 配方 def（含 id/slots/element_req/pp_budget/traits_inherit）。
          - catalyst：触媒名/ID（可选；壳层应先行 catalyst_resolve 校验，此处仅记录）。
          - job_tier：职业档位（int=索引 或 str=称号名；用于全物入料/刻度显现门槛，记录进快照）。
        出参：快照 dict——
          {recipe_id, materials:[], chain, element_scores, pool:{normal,gold,awaken}, catalyst,
           pp:{used,budget}, step, version:1, job_tier, job_tier_index}。
        """
        recipe_id = str(recipe_def.get("id") or "")
        chain = self.compute_chain([], None)
        return {
            "recipe_id": recipe_id,
            "materials": [],                                    # 材料链（解析记录列表）
            "chain": chain,  # 连锁（segments/pairs/effect_level）
            "element_scores": {},                               # 属性刻度（元素→累计值）
            "pool": {"normal": [], "gold": [], "awaken": []},   # 特性候选池
            "catalyst": catalyst,                               # 触媒名/ID（None=未指定）
            "pp": {"used": 0, "budget": self.pp_budget(recipe_def)},  # TSC-14 会话内累计
            "step": STEP_FEED,                                  # 步骤：投料 → 继承 → 确认
            "version": 1,                                       # §7.2 version 幂等（默认 1）
            "job_tier": job_tier,
            "job_tier_index": self._norm_tier_index(job_tier),
        }

    @staticmethod
    def snapshot_version(snap: Mapping[str, Any]) -> int:
        """读快照 version（§7.2 version 幂等锚点；None/非法 → 1）。"""
        if not isinstance(snap, Mapping):
            return 1
        v = snap.get("version")
        if isinstance(v, bool) or not isinstance(v, int):
            try:
                v = int(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return 1
        return max(1, int(v))

    # ------------------------------------------------------------------
    # 投料核心计算（纯函数：输入材料链+配方+触媒 → 输出状态，不 IO）
    # ------------------------------------------------------------------
    def _chain_positions(
        self,
        materials: Sequence[Mapping[str, Any]],
        catalyst_def: Optional[Mapping[str, Any]],
    ) -> List[Optional[str]]:
        """链位展开：每材料 count 展开为 n 个链位（A-1/TC-06），每位 = 材料「当前属性」。"""
        positions: List[Optional[str]] = []
        for rec in materials:
            elem = self._effective_element(rec, catalyst_def)
            n = max(1, int(rec.get("count", 1)))
            positions.extend([elem] * n)
        return positions

    def compute_chain(
        self,
        materials: Sequence[Mapping[str, Any]],
        catalyst: Optional[Mapping[str, Any]] = None,
    ) -> dict:
        """连锁段数计算（FEED-06/L153，TC-01/07/16）。

        入参：materials=材料链（解析记录列表）；catalyst=触媒 def（可选，方向修饰 A-3）。
        出参：{segments, pairs, effect_level, elements}——
          - segments = 相邻同属性对数（连续 n 个 = n-1 段，A-1；count 展开链位）；
          - pairs = 相邻同属性对数（= segments，FEED-06 同义）；
          - effect_level = chain_map[segments]（超界钳制 A-1；0 段 → 0）；
          - elements = 每个链位的「当前属性」（供面板/调试）。
        """
        positions = self._chain_positions(materials, catalyst)
        segments = 0
        for i in range(1, len(positions)):
            if positions[i] == positions[i - 1] and positions[i] is not None:
                segments += 1
        cmap = self._chain_map()
        if segments in cmap:
            effect_level = cmap[segments]
        elif cmap and segments > max(cmap):
            effect_level = cmap[max(cmap)]  # A-1 超界钳制到最高配置等级
        else:
            effect_level = 0  # A-1 0 段/低于最小 → 无效果等级
        return {
            "segments": segments,
            "pairs": segments,
            "effect_level": effect_level,
            "elements": positions,
        }

    def compute_element_scores(
        self,
        materials: Sequence[Mapping[str, Any]],
        ctx: Mapping[str, Any],
        catalyst: Optional[Mapping[str, Any]] = None,
    ) -> dict:
        """属性刻度累计（FEED-07/L152，TC-08/16）——累计材料「当前属性」对照 element_req 阈值。

        入参：materials=材料链（解析记录）；ctx（补查记录缺失字段兜底）；catalyst=触媒 def（可选）。
        出参：{元素: 累计值}，只留非零桶。
        核心逻辑：
          - 无触媒：材料 elements 全量累计（FEED-07）；
            无 elements 的成品/装备 → 按品质档折算等值元素分归「无」(void) 桶（A-5）；
          - 有触媒方向：材料「当前属性」= 触媒方向，其主元素值计入触媒元素桶（CAT-02/A-3）。
        """
        scores: Dict[str, int] = {}
        cat_elem = self._catalyst_element(catalyst)
        for rec in materials:
            elements = rec.get("elements")
            if not isinstance(elements, Mapping):
                elements = {}
            if cat_elem is not None:
                # 触媒方向修饰：材料当前属性=触媒方向，计入触媒元素桶（CAT-02/A-3）
                value = 0
                main = rec.get("main_element")
                if isinstance(main, str):
                    value = int(elements.get(main, 0))
                if value <= 0 and rec.get("is_finished"):
                    value = int(
                        QUALITY_ELEMENT_FALLBACK.get(str(rec.get("quality") or ""), 0)
                    )  # A-5
                scores[cat_elem] = scores.get(cat_elem, 0) + value
                continue
            for elem, value in elements.items():
                if isinstance(elem, str) and isinstance(value, int) and not isinstance(value, bool):
                    scores[elem] = scores.get(elem, 0) + value
            if not elements and rec.get("is_finished"):
                # A-5 全物入料折算兜底：无 elements 成品按品质档归「无」桶
                fallback = int(
                    QUALITY_ELEMENT_FALLBACK.get(str(rec.get("quality") or ""), 0)
                )
                if fallback > 0:
                    scores[ELEMENT_VOID] = scores.get(ELEMENT_VOID, 0) + fallback
        return {k: v for k, v in scores.items() if v}

    def check_element_req(
        self, recipe_def: Mapping[str, Any], element_scores: Mapping[str, Any]
    ) -> dict:
        """每元素达表/缺额（FEED-07/QLT-11，TC-08 刻度缺额输出）。

        入参：recipe_def（element_req={元素:[{阈值,效果}]}，多档阶梯）；element_scores 累计值。
        出参：{元素: {element, score, thresholds, met, met_effect, levels_missing, shortfall}}——
          - met=是否达最高可达档（任一阈值命中即有效果显现）；
          - levels_missing=未达标档数（总档 - 已达标档）；
          - shortfall=距下一未达标阈值的差值（全达标 → 0；供悬念分级/降级提示）。
        """
        req = recipe_def.get("element_req")
        if not isinstance(req, Mapping) or not req:
            return {}
        out: Dict[str, dict] = {}
        for elem, steps in req.items():
            if not isinstance(steps, (list, tuple)):
                continue
            norm: List[dict] = []
            for s in steps:
                if not isinstance(s, Mapping):
                    continue
                try:
                    th = int(s.get("threshold", -1))
                except (TypeError, ValueError):
                    continue
                if th >= 0:
                    norm.append({"threshold": th, "effect": s.get("effect")})
            norm.sort(key=lambda x: x["threshold"])  # 阶梯按阈值升序（多档判定）
            if not norm:
                continue
            score = 0
            raw = element_scores.get(elem, 0)
            if isinstance(raw, int) and not isinstance(raw, bool):
                score = raw
            met_count = sum(1 for s in norm if score >= s["threshold"])
            levels_missing = len(norm) - met_count
            if met_count > 0:
                top = norm[met_count - 1]
                met, met_effect, shortfall = True, top["effect"], 0
            else:
                met, met_effect = False, None
                shortfall = max(0, norm[0]["threshold"] - score)
            out[str(elem)] = {
                "element": str(elem),
                "score": score,
                "thresholds": norm,
                "met": met,
                "met_effect": met_effect,
                "levels_missing": levels_missing,
                "shortfall": shortfall,
            }
        return out

    def build_feature_pool(
        self,
        materials: Sequence[Mapping[str, Any]],
        ctx: Mapping[str, Any],
        *,
        job_tier_index: int,
    ) -> dict:
        """可继承特性候选池（FEED-08/INH-01~04，TSC-13，TC-01/09/超特性）。

        入参：materials=材料链（解析记录）；ctx（traits 注册表）；job_tier_index=职业档位索引。
        出参：{normal: [(trait_id, name, pp)], gold: [...], awaken: [...]}——
          - normal：source=素材/成品 的特性（普通池，INH-01/04；成品 source 专家级原样入池）；
          - gold：source=金色素材 的特性（超特性池，第 4 位独占候选，TSC-13）；
          - awaken：✨素材（awaken=true）携带特性（觉醒候选，INH-08/A-7）。
        同特性全局去重（每特性进首个命中池）；未知特性 ID 跳过（STO-05 引用失效兜底）。
        """
        tier = max(0, int(job_tier_index))
        normal: List[Tuple[str, str, int]] = []
        gold: List[Tuple[str, str, int]] = []
        awaken: List[Tuple[str, str, int]] = []
        seen: set = set()
        for rec in materials:
            awaken_mat = bool(rec.get("awaken"))
            traits = rec.get("traits")
            if not isinstance(traits, (list, tuple)):
                continue
            for tid in traits:
                tid = str(tid)
                if tid in seen:
                    continue
                tdef = self._find_trait(tid, ctx)
                if tdef is None:
                    continue  # STO-05 引用失效兜底：跳过不报错
                name = str(tdef.get("name") or tid)
                pp = self.pp_cost_of(tdef)
                # 全物入料未解锁（< 专家）时成品 source 特性不入池（INH-04/TC-09 防御；
                # apply_feed 已拦截非专家投成品，此处双保险）
                if rec.get("is_finished") and tier < EXPERT_TIER_INDEX:
                    continue
                source = tdef.get("source")
                if awaken_mat:
                    awaken.append((tid, name, pp))       # A-7 ✨素材 → 觉醒候选
                elif source == "金色素材":
                    gold.append((tid, name, pp))         # TSC-13 金色素材 → 超特性池
                else:
                    normal.append((tid, name, pp))       # INH-01/04 素材/成品 → 普通池
                seen.add(tid)
        return {"normal": normal, "gold": gold, "awaken": awaken}

    # ------------------------------------------------------------------
    # PP 预算（TSC-14/L414-415：pp_cost 会话内累计、pp_refresh=会话重置；超特性 PP2 第 4 位）
    # ------------------------------------------------------------------
    def pp_budget(self, recipe_def: Mapping[str, Any]) -> int:
        """配方卡 PP 预算（TSC-14：配方卡 PP 上限，例：火焰弹 5/5；recipe.pp_budget int ≥0）。"""
        return _clamp_int(recipe_def.get("pp_budget", 0), 0, lo=0)

    def pp_cost_of(self, trait_def: Mapping[str, Any]) -> int:
        """特性继承 PP 消耗（TSC-14：rarity 是唯一计价依据——super=pp_cost.super(2)、
其余 normal(1)）。"""
        cost = self._pp_cost()
        if trait_def.get("rarity") == "super":
            return max(0, int(cost.get("super", 2)))
        return max(0, int(cost.get("normal", 1)))

    def can_afford_pp(
        self, snap: Optional[Mapping[str, Any]], trait_def: Mapping[str, Any]
    ) -> bool:
        """会话内 PP 预算可支付（TSC-14/INH-09：pp_refresh=会话重置，used 会话内累计不跨会话）。

        入参：snap（快照含 pp{used,budget}）；trait_def。出参：bool。
        """
        if not isinstance(snap, Mapping):
            return False
        pp = snap.get("pp")
        if not isinstance(pp, Mapping):
            return False
        used = _clamp_int(pp.get("used", 0), 0)
        budget = _clamp_int(pp.get("budget", 0), 0)
        return used + self.pp_cost_of(trait_def) <= budget

    # ------------------------------------------------------------------
    # 投料应用（FEED-01~10 / CAT-02 / TC-01~09 / TC-15~20）
    # ------------------------------------------------------------------
    def apply_feed(
        self,
        snap: Optional[Mapping[str, Any]],
        materials: Sequence[Mapping[str, Any]],
        ctx: Mapping[str, Any],
        *,
        append: bool = False,
    ) -> dict:
        """追加/覆盖材料链（FEED-01~10，TC-01~09/15~20 引擎承载部分）。

        入参：
          - snap：会话快照（None → 拒绝，TC-03「无会话」由壳层判定，引擎侧防御降级）。
          - materials：投料条目列表 [{item, count}, ...]（TC-06 数量解析：count 缺省 1）。
          - ctx：注册表 + count_item；append=True=追加（TC-02 追加重算），False=覆盖链。
        出参：{ok, snap?, message, reason?, shortfall?, chain?, element_scores?, pool?,
          chain_bonus?}。
        核心校验链（FEED 顺序）：
          ① 无快照拒绝（TC-03 防御）；② 材料解析+存在校验（FEED-05 前置）；
          ③ 全物入料门槛（FEED-09/TC-09：专家=job_tier_index≥3 才可投成品/装备）；
          ④ 槽位上限（FEED-04/TC-04：∑count ≤ recipe.slots，A-6）；
          ⑤ 材料持有（FEED-05/TC-06：逐项 count_item，不足全拒+差异 shortfall）。
        通过后重算 chain/element_scores/pool（含触媒方向修饰 CAT-02），version 递增（§7.1 行4）。
        """
        if not isinstance(snap, Mapping):
            # TC-03：引擎不判会话状态（状态机批3 已落地），但无快照传入时防御拒绝
            return {
                "ok": False,
                "reason": "no_snapshot",
                "message": "当前没有调合会话，先 /炼金 <配方> 开始",
            }
        if not isinstance(materials, (list, tuple)):
            return {"ok": False, "reason": "invalid_materials", "message": "投料参数非法"}
        recipe = self._find_recipe(snap.get("recipe_id"), ctx)
        if recipe is None:
            return {"ok": False, "reason": "recipe_not_found", "message": "配方不存在"}

        # ① 材料解析 + 存在校验（FEED-05 前置 / REC-03 引用硬拦）
        records: List[dict] = []
        for entry in materials:
            rec = self._resolve_material(entry, ctx)
            if rec is None:
                raw_id = (
                    entry.get("item") or entry.get("id")
                    if isinstance(entry, Mapping) else None
                )
                return {
                    "ok": False,
                    "reason": "item_not_found",
                    "message": f"材料不存在：{raw_id}",
                    "shortfall": [{"item": raw_id, "count": 1, "have": 0}],
                }
            records.append(rec)

        # ② 全物入料门槛（FEED-09/TC-09：专家=档位索引 3，L218）
        tier = _clamp_int(snap.get("job_tier_index", 0), 0)
        finished = [r for r in records if r.get("is_finished")]
        if finished and tier < EXPERT_TIER_INDEX:
            return {
                "ok": False,
                "reason": "expert_required",
                "message": "全物入料需专家级",
                "items": [r["item"] for r in finished],
            }

        # ③ 槽位上限（FEED-04/TC-04：∑count ≤ recipe.slots；A-6 单位口径）
        base = list(snap.get("materials") or []) if append else []
        new_chain = list(base) + records
        slots = _clamp_int(recipe.get("slots", 4), 4, lo=2)
        units = sum(max(1, int(r.get("count", 1))) for r in new_chain)
        if units > slots:
            return {
                "ok": False,
                "reason": "slots_overflow",
                "message": "投料超槽位",
                "slots": slots,
                "units": units,
            }

        # ④ 材料持有（FEED-05/TC-06：逐项校验新增批次，不足全拒+差异；原子口径 L115）
        need: Dict[str, int] = {}
        for r in records:
            need[r["item"]] = need.get(r["item"], 0) + max(1, int(r.get("count", 1)))
        shortfall: List[dict] = []
        for item_id, cnt in need.items():
            have = self._ctx_have(ctx, item_id)
            if have < cnt:
                shortfall.append({"item": item_id, "count": cnt, "have": have})
        if shortfall:
            return {
                "ok": False,
                "reason": "materials_insufficient",
                "message": "材料不足",
                "shortfall": shortfall,
            }

        # ⑤ 重算（触媒方向修饰 CAT-02/A-3；FEED-06/07/08 复用）
        catalyst_def = self._snap_catalyst_def(snap, ctx)
        chain = self.compute_chain(new_chain, catalyst_def)
        element_scores = self.compute_element_scores(new_chain, ctx, catalyst_def)
        pool = self.build_feature_pool(new_chain, ctx, job_tier_index=tier)

        snap2 = dict(snap)
        snap2["materials"] = new_chain
        snap2["chain"] = chain
        snap2["element_scores"] = element_scores
        snap2["pool"] = pool
        snap2["step"] = STEP_FEED
        snap2["version"] = self.snapshot_version(snap) + 1  # §7.1 行4：状态更新 version 递增

        return {
            "ok": True,
            "snap": snap2,
            "message": "投料成功",
            "reason": None,
            "shortfall": [],
            "chain": chain,
            "element_scores": element_scores,
            "pool": pool,
            "chain_bonus": chain["segments"] >= 3,  # FEED-08 连锁 ≥3 段触发连锁奖励候选
        }

    # ------------------------------------------------------------------
    # 触媒（CAT-01~06 / TC-15~20）
    # ------------------------------------------------------------------
    def catalyst_resolve(self, catalyst_name: Optional[str], ctx: Mapping[str, Any]) -> dict:
        """触媒解析（CAT-03/05，TC-15/17/18/20 引擎承载部分）。

        入参：catalyst_name=触媒名/ID（None/空 → 无触媒）。
        出参：{ok, catalyst?, registered?, message?}——
          - 未指定 → {ok:True, catalyst:None, registered:False, message:""}；
          - 未注册（注册表查无）→ {ok:True, catalyst:None, registered:False,
            message:"触媒未注册，仅提示不阻断"}（CAT-03 注册制）；
          - 注册但 type≠触媒 → {ok:False, catalyst:None, registered:True, message:"触媒无效"}
            （CAT-05/L344 拒绝）；
          - 合法（type=触媒）→ {ok:True, catalyst:def, registered:True, message:""}
            （CAT-02 方向修饰由 compute_chain/scores 消费其 elements 主元素）。
        注：CAT-01 解锁等级（专家）由指令壳判定（任务书：等级不足由指令壳判——引擎管 type 校验）。
        """
        if not isinstance(catalyst_name, str) or not catalyst_name:
            return {"ok": True, "catalyst": None, "registered": False, "message": ""}
        idef = self._find_item(catalyst_name, ctx)
        if idef is None:
            # CAT-03 注册制：未注册 → 仅提示不阻断
            return {
                "ok": True,
                "catalyst": None,
                "registered": False,
                "message": f"触媒 {catalyst_name} 未注册，仅提示不阻断",
            }
        if idef.get("type") != "触媒":
            # CAT-05/L344：触媒必须是 items.json type=触媒；指定非触媒 → 「触媒无效」拒绝
            return {
                "ok": False,
                "catalyst": None,
                "registered": True,
                "message": f"触媒无效：{catalyst_name} 不是触媒",
            }
        return {"ok": True, "catalyst": dict(idef), "registered": True, "message": ""}

    # ------------------------------------------------------------------
    # 确认全量复核（FEED-10/L179 / CAT-04 / TC-20）
    # ------------------------------------------------------------------
    def verify_snapshot(self, ctx: Mapping[str, Any], snap: Optional[Mapping[str, Any]]) -> dict:
        """/确认 全量复核（FEED-10/L179，TC-20）——材料链+触媒仍在背包，不足拒绝+差异。

        入参：ctx（count_item）；snap（会话快照）。
        出参：{ok, shortfall?, message?}——材料逐项 count_item ≥ count；触媒（若指定）≥1；
          任一项不足 → {ok:False, shortfall:[{item,count,have}], message:"材料不足，无法确认"}。
        注：触媒纳入全量复核（CAT-04 与材料同事务扣减；catalyst_consume=false 只影响扣减不
          影响复核——指定了触媒则确认时须仍在背包，TC-20）。
        """
        if not isinstance(snap, Mapping):
            return {
                "ok": False,
                "reason": "no_snapshot",
                "shortfall": [],
                "message": "当前没有调合会话，先 /炼金 <配方> 开始",
            }
        shortfall: List[dict] = []
        for rec in snap.get("materials") or []:
            if not isinstance(rec, Mapping):
                continue
            item_id = rec.get("item")
            if not isinstance(item_id, str):
                continue
            cnt = max(1, int(rec.get("count", 1)))
            have = self._ctx_have(ctx, item_id)
            if have < cnt:
                shortfall.append({"item": item_id, "count": cnt, "have": have})
        catalyst = snap.get("catalyst")
        if isinstance(catalyst, Mapping):
            cat_id = catalyst.get("id") or catalyst.get("item")
        elif isinstance(catalyst, str):
            cat_id = catalyst
        else:
            cat_id = None
        if isinstance(cat_id, str) and cat_id:
            have = self._ctx_have(ctx, cat_id)
            if have < 1:
                shortfall.append({"item": cat_id, "count": 1, "have": have})
        if shortfall:
            return {
                "ok": False,
                "reason": "materials_insufficient",
                "shortfall": shortfall,
                "message": "材料不足，无法确认",
            }
        return {"ok": True, "shortfall": [], "message": ""}

    # ------------------------------------------------------------------
    # 面板渲染数据（FEED-07/STO-08/QLT-13 悬念分级，A-8）
    # ------------------------------------------------------------------
    def _scale_suspense_grade(self, job_tier_index: int) -> int:
        """刻度悬念分级（FEED-07/QLT-13/A-8）：<精通=0 隐藏 / 精通·专家=1 引导语 /
大师+=2 精确阈值。"""
        tier = max(0, int(job_tier_index))
        if tier >= MASTER_TIER_INDEX:
            return SUSPENSE_PRECISE
        if tier >= PROFICIENT_TIER_INDEX:
            return SUSPENSE_GUIDE
        return SUSPENSE_HIDDEN

    def _element_display(self, status: Mapping[str, Any], grade: int) -> Optional[str]:
        """单元素刻度展示文本（A-8：引导语 vs 精确阈值）。

        - grade 0（< 精通）：不显现 → None（QLT-13 精通前达标不显现）。
        - grade 1（精通/专家）：达标 → 「火系达标」；未达标 → 「火系还差一点，试试多投火系材料？」
        - grade 2（大师+）：达标 → 「火 45/45 达标」；未达标 → 「火 42/45」（score/下一未达阈值）。
        """
        elem = str(status.get("element", ""))
        cn = ELEMENT_NAMES_CN.get(elem, elem)
        score = _clamp_int(status.get("score", 0), 0)
        if grade == SUSPENSE_HIDDEN:
            return None
        if grade == SUSPENSE_GUIDE:
            if status.get("met"):
                return f"{cn}系达标"
            return f"{cn}系还差一点，试试多投{cn}系材料？"
        # SUSPENSE_PRECISE（大师+）
        if status.get("met"):
            met_count = len(status.get("thresholds", [])) - _clamp_int(
                status.get("levels_missing", 0), 0
            )
            top = status.get("thresholds", [])[max(0, met_count - 1)]
            th = _clamp_int(top.get("threshold", 0), 0)
            return f"{cn} {score}/{th} 达标"
        next_th = None
        for s in status.get("thresholds", []):
            if score < _clamp_int(s.get("threshold", 0), 0):
                next_th = _clamp_int(s.get("threshold", 0), 0)
                break
        if next_th is None and status.get("thresholds"):
            next_th = _clamp_int(status["thresholds"][0].get("threshold", 0), 0)
        return f"{cn} {score}/{next_th}" if next_th is not None else f"{cn} {score}"

    def assemble_panel(
        self,
        snap: Optional[Mapping[str, Any]],
        ctx: Mapping[str, Any],
        *,
        job_tier_index: int,
    ) -> dict:
        """面板渲染数据（FEED-07/STO-08/QLT-13，TC-01/08/15/16/20 面板承载）。

        入参：snap（会话快照）；ctx（recipe/items 注册表）；job_tier_index=职业档位索引。
        出参：dict 渲染数据（壳层负责消息模板拼装）——
          {recipe_id, recipe_name, materials, chain, element_scores, element_req_status,
           scale_suspense, pool, chain_bonus, pp, traits_inherit, catalyst, step, version,
           job_tier}。
        element_req_status 每元素含 {element, score, threshold 阶梯, met, met_effect,
          levels_missing, shortfall, display}（display 按悬念分级，A-8）。
        """
        if not isinstance(snap, Mapping):
            return {"ok": False, "reason": "no_snapshot", "message": "当前没有调合会话"}
        recipe = self._find_recipe(snap.get("recipe_id"), ctx)
        recipe_name = str(recipe.get("name") or snap.get("recipe_id") or "") if recipe else str(
            snap.get("recipe_id") or ""
        )
        grade = self._scale_suspense_grade(job_tier_index)
        element_scores = snap.get("element_scores") or {}
        if not isinstance(element_scores, Mapping):
            element_scores = {}
        req_status = self.check_element_req(recipe, element_scores) if recipe else {}
        for st in req_status.values():
            st["display"] = self._element_display(st, grade)

        chain = snap.get("chain") or {}
        materials_panel: List[dict] = []
        for rec in snap.get("materials") or []:
            if not isinstance(rec, Mapping):
                continue
            materials_panel.append({
                "item": rec.get("item"),
                "name": rec.get("name", rec.get("item")),
                "count": rec.get("count", 1),
                "element": rec.get("main_element"),
            })

        pp = snap.get("pp") or {}
        return {
            "ok": True,
            "recipe_id": snap.get("recipe_id"),
            "recipe_name": recipe_name,
            "materials": materials_panel,
            "chain": {
                "segments": chain.get("segments", 0),
                "pairs": chain.get("pairs", 0),
                "effect_level": chain.get("effect_level", 0),
            },
            "element_scores": dict(element_scores),
            "element_req_status": req_status,
            "scale_suspense": grade,
            "pool": {
                "normal": list(snap.get("pool", {}).get("normal", [])),
                "gold": list(snap.get("pool", {}).get("gold", [])),
                "awaken": list(snap.get("pool", {}).get("awaken", [])),
            },
            "chain_bonus": bool(chain.get("segments", 0) >= 3),  # FEED-08
            "pp": {
                "used": _clamp_int(pp.get("used", 0), 0),
                "budget": _clamp_int(pp.get("budget", 0), 0),
            },
            "traits_inherit": _clamp_int(recipe.get("traits_inherit", 1), 1, lo=1) if recipe else 1,
            "catalyst": snap.get("catalyst"),
            "step": snap.get("step", STEP_FEED),
            "version": self.snapshot_version(snap),
            "job_tier": snap.get("job_tier"),
        }
