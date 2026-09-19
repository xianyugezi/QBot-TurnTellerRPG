"""M12.5 强化数据层：enhance.json 数据模型 + 专项校验器（2c3a §5/§7 轻量落地）。

文件名：enhance_models.py
创建时间：2026-09-06

功能描述：
  - enhance.json 顶层 obj（对齐 forge.json 形态：registry.modules_raw["enhance"]）。
    段：settings（max_by_quality_level/legacy_quality_level_by_rarity/
    special_affix_span/fail_tier_split/shatter_mode/luck_affects/level_gated）、
    cost（coin_per_level/stones_per_level/stone_tiers）、success_curve[]、
    values（weapon_atk_per_level/armor_def_per_level）、protect_stone。
  - validate_enhance(modules, report) 纯函数（(modules, report) 鸭子类型，
    对齐 alchemy_models.validate_recipes 口径）：
    V1 曲线单调不增（硬）；V2 曲线档位覆盖 1..MaxR（硬）；
    V4 石档位引用 items 存在性 + 覆盖连续（硬）；
    V7 上限表键品质等级（正整数；硬）+ 旧档桥接键品质枚举（硬）；V6 值/类型（硬）；
    V5 等级门槛开关一致性（硬）；V3 碎率超限软警告；结构异常（缺段/类型错）硬拦。
  - 缺失/未接线 enhance 模块 → 跳过（对齐既有校验器「默认放行」惯例）。

依据：
  - docs/深度打造_决策记录.md §一 **H3**（用品质等级 6 档上限 +3/+6/+9/+12/+15/+18
    **替换**既有 max_by_rarity 5/8/10/12；旧装备按桥接表读上限、既有 enhance_level 原样保留）
    + §二 N（数值一律包声明）。
  - 打造系统_原案_20260919.md §7（品质决定上限；每 4 级一个特殊词条；冷却缩减占位）。
  - docs/细化/细化_2c3a_强化数值曲线.md §5.1 字段表 / §5.2 校验器映射（V1~V7）。
  - docs/细化/细化_2c3b_强化流程契约.md（交互流程层，本模块只落数据/校验）。
  - 模式参考：qbot_rpg/content/forge_models.py（顶层 obj 模块形态）/
    qbot_rpg/content/alchemy_models.py（validate 鸭子类型）。

【工程补白】
  1. 品质等级枚举 1~10（H2）；上限表默认只声明 1~6 六档（原案 §7 六个上限值），
     超出已声明档位 → 引擎**顶档封顶**（validate 只校验表内值）。
  2. 默认配置（未配 enhance.json）→ 系统未启用（GU-01），不加载不报错。
  3. V2 档位覆盖目标 = 1..MaxR（MaxR = max(上限表值)，默认 18）。
  4. 内容包配置超上限档位（如 +19）→ V2 硬拦（曲线未覆盖）。
  5. 旧档桥接表 `legacy_quality_level_by_rarity`：旧品质枚举 → 品质等级，
     取「新档 ≥ 旧档上限」的最小档（normal5→2、fine8→3、epic10→4、legendary12→4），
     保证旧装备上限**只升不降**（详见批43 报告「旧档→新档映射」）。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Set

__all__ = [
    "QUALITY_KEYS",
    "DEFAULT_MAX_BY_QUALITY_LEVEL",
    "DEFAULT_LEGACY_QUALITY_LEVEL_BY_RARITY",
    "DEFAULT_SPECIAL_AFFIX_SPAN",
    "DEFAULT_FAIL_TIER_SPLIT",
    "DEFAULT_CURVE",
    "DEFAULT_STONE_TIERS",
    "DEFAULT_VALUES",
    "DEFAULT_ENHANCE",
    "parse_enhance_settings",
    "validate_enhance",
]

# 品质枚举四档（items.json 四档；旧档桥接键枚举锚点）
QUALITY_KEYS = ("normal", "fine", "epic", "legendary")
QUALITY_LABELS_CN = {
    "normal": "普通", "fine": "精良", "epic": "史诗", "legendary": "传说",
}

# 强化上限表（H3）：**品质等级 → 上限**（六档；原案 §7 +3/+6/+9/+12/+15/+18）。
# JSON 键为字符串数字（"1".."6"）；引擎经 enhance_affix.normalize_cap_table 归一为 int。
DEFAULT_MAX_BY_QUALITY_LEVEL = {1: 3, 2: 6, 3: 9, 4: 12, 5: 15, 6: 18}
# 旧档桥接（工程补白 5）：旧品质枚举 → 品质等级（取「新档 ≥ 旧档上限」的最小档）。
DEFAULT_LEGACY_QUALITY_LEVEL_BY_RARITY = {
    "normal": 2, "fine": 3, "epic": 4, "legendary": 4,
}
# 特殊词条跨度（原案 §7「每 4 级获得一个词条」；包可配，不写死）。
DEFAULT_SPECIAL_AFFIX_SPAN = 4
DEFAULT_FAIL_TIER_SPLIT = 3

# 默认成功率曲线（L80-81 + R-04 补 11/12；批43 延长 13~18 以覆盖新 18 档上限——
# 13~18 为原案/决策记录未给值的**待裁决**延续，保持单调不增：12/10/8/6/5/4）。
DEFAULT_CURVE = [
    {"to": 1, "rate": 90}, {"to": 2, "rate": 85}, {"to": 3, "rate": 80},
    {"to": 4, "rate": 70}, {"to": 5, "rate": 60}, {"to": 6, "rate": 50},
    {"to": 7, "rate": 40}, {"to": 8, "rate": 35}, {"to": 9, "rate": 30},
    {"to": 10, "rate": 25}, {"to": 11, "rate": 20}, {"to": 12, "rate": 15},
    {"to": 13, "rate": 12}, {"to": 14, "rate": 10}, {"to": 15, "rate": 8},
    {"to": 16, "rate": 6}, {"to": 17, "rate": 5}, {"to": 18, "rate": 4},
]

# 默认石档位（L178-182 + R-04 high 延至 12；批43 再延至 18 覆盖新上限）。
DEFAULT_STONE_TIERS = [
    {"tier": "low", "levels": [1, 2, 3]},
    {"tier": "mid", "levels": [4, 5, 6]},
    {"tier": "high", "levels": [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18]},
]

# 每级属性增量（2c3a §8 values；D-11 武器 flat5 / D-12 防具 flat3）
DEFAULT_VALUES = {
    "weapon_atk_per_level": {"type": "flat", "value": 5},
    "armor_def_per_level": {"type": "flat", "value": 3},
}

# 默认完整配置（内容包未配 enhance.json 时的兜底锚点；GU-01 判定「已启用」
# 以内容包是否提供 enhance 段为准，本默认仅供引擎读取缺省段）
DEFAULT_ENHANCE: Dict[str, Any] = {
    "settings": {
        "max_by_quality_level": dict(DEFAULT_MAX_BY_QUALITY_LEVEL),
        "legacy_quality_level_by_rarity": dict(DEFAULT_LEGACY_QUALITY_LEVEL_BY_RARITY),
        "special_affix_span": DEFAULT_SPECIAL_AFFIX_SPAN,
        "fail_tier_split": DEFAULT_FAIL_TIER_SPLIT,
        "shatter_mode": False,
        "shatter_chance": 0,
        "shatter_max": 5,
        "luck_affects": True,
        "level_gated": False,
    },
    "cost": {
        "coin_per_level": 100,
        "stones_per_level": 1,
        "stone_tiers": DEFAULT_STONE_TIERS,
    },
    "success_curve": DEFAULT_CURVE,
    "values": DEFAULT_VALUES,
    "protect_stone": "item_protect_stone",
}


def parse_enhance_settings(raw: Any) -> Dict[str, Any]:
    """enhance 模块 raw → 归一配置（缺省段深补，非法值回退默认）。

    入参 raw: registry.modules_raw["enhance"]（Mapping / None）。
    出参 dict：与 DEFAULT_ENHANCE 同构，逐段深合并（内容包段可部分覆盖）。
    纯函数（不改写 raw）。
    """
    base = DEFAULT_ENHANCE
    if not isinstance(raw, Mapping):
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    out: Dict[str, Any] = {}
    for sec in ("settings", "cost", "values"):
        b = base.get(sec)
        r = raw.get(sec)
        merged = dict(b) if isinstance(b, Mapping) else {}
        if isinstance(r, Mapping):
            for k, v in r.items():
                if isinstance(v, list):
                    merged[k] = list(v)
                elif isinstance(v, Mapping):
                    merged[k] = dict(v)
                else:
                    merged[k] = v
        out[sec] = merged
    curve = raw.get("success_curve")
    out["success_curve"] = (
        [dict(x) for x in curve] if isinstance(curve, list) else list(base["success_curve"])
    )
    ps = raw.get("protect_stone")
    out["protect_stone"] = str(ps) if isinstance(ps, str) and ps else base["protect_stone"]
    return out


# ---------------------------------------------------------------------------
# 模块 meta（field_meta 登记用；entry_type=object——enhance.json 顶层是 obj）
# ---------------------------------------------------------------------------

def enhance_module_meta() -> Any:
    """enhance 模块 ModuleMeta（entry_type=object——enhance.json 顶层是 obj）。

    M12.5 强化接线：对齐 forge_module_meta 形态。fields 宽松登记（顶层五段宽容器
    settings/cost/success_curve/values/protect_stone，中文段名 label），深结构
    校验由 validate_enhance 专项全权（V1~V7），泛型只做顶层形态（零新增红拦）。
    """
    from qbot_rpg.content.models import FieldMeta, ModuleMeta

    top_fields = {
        "settings": FieldMeta(type="obj", children={}, soft_label=True, label="设置"),
        "cost": FieldMeta(type="obj", children={}, soft_label=True, label="消耗"),
        "success_curve": FieldMeta(type="list", element=FieldMeta(type="obj", children={}),
                                   soft_label=True, label="成功率曲线"),
        "values": FieldMeta(type="obj", children={}, soft_label=True, label="属性增量"),
        "protect_stone": FieldMeta(type="str", label="保护石物品"),
    }
    return ModuleMeta(entry_type="object", fields=top_fields, kind="enhance")


# ---------------------------------------------------------------------------
# 校验器（validate_enhance(modules, report) 鸭子类型，对齐 forge/alchemy 口径）
# ---------------------------------------------------------------------------

def _emit(report: Any, method: str, *args: Any, **kwargs: Any) -> None:
    _MAP = {"error": "_err", "warning": "_warn", "note": "_note"}
    fn = getattr(report, method, None)
    if not callable(fn):
        fn = getattr(report, _MAP.get(method, "_" + method), None)
    if callable(fn):
        fn(*args, **kwargs)


def _err(report: Any, field: str, kind: str, **detail: Any) -> None:
    _emit(report, "error", "enhance", field, kind, **detail)


def _warn(report: Any, field: str, kind: str, **detail: Any) -> None:
    _emit(report, "warning", "enhance", field, kind, **detail)


def _item_id_set(modules: Mapping[str, Any]) -> Set[str]:
    items = modules.get("items")
    out: Set[str] = set()
    if isinstance(items, list):
        for e in items:
            if isinstance(e, Mapping):
                iid = e.get("id")
                if isinstance(iid, str) and iid:
                    out.add(iid)
    return out


def validate_enhance(modules: Mapping[str, Any], report: Any) -> None:
    """enhance 模块专项校验（2c3a §5.2 V1~V7 核心规则）。

    入参 modules/report 鸭子类型（同 validate_recipes）。出参 None。
    缺失/形态异常 → 跳过（未接线默认放行）。红拦 → 加载失败（系统未启用）。
    """
    raw = modules.get("enhance")
    if not isinstance(raw, Mapping):
        return
    cfg = parse_enhance_settings(raw)
    settings = cfg.get("settings") or {}
    cost = cfg.get("cost") or {}
    curve = cfg.get("success_curve") or []
    values = cfg.get("values") or {}

    # ---- 上限表（H3：品质等级 → 上限）+ 旧档桥接 ----
    max_by = settings.get("max_by_quality_level")
    if not isinstance(max_by, Mapping):
        _err(report, "enhance.settings.max_by_quality_level", "V7",
             msg="max_by_quality_level 需对象（品质等级 → 上限）")
        return
    # V7：键为品质等级（正整数）；允许子集（缺省由引擎回退默认）
    cap_by_level: Dict[int, int] = {}
    for k, v in max_by.items():
        try:
            ik = int(k)
        except (TypeError, ValueError):
            _err(report, "enhance.settings.max_by_quality_level", "V7",
                 key=k, msg="max_by_quality_level 键须为品质等级（正整数）")
            continue
        if ik <= 0:
            _err(report, "enhance.settings.max_by_quality_level", "V7",
                 key=k, msg="max_by_quality_level 键须为正整数")
            continue
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            _err(report, "enhance.settings.max_by_quality_level", "V6",
                 key=k, value=v, msg="max_by_quality_level 值须为非负整数")
            continue
        cap_by_level[ik] = v
    if not cap_by_level:
        _err(report, "enhance.settings.max_by_quality_level", "V6",
             msg="max_by_quality_level 须至少一个合法档位")
        return
    max_r = max(cap_by_level.values())
    if max_r > 20:
        _err(report, "enhance.settings.max_by_quality_level", "V6",
             value=max_r, msg="上限值范围 0-20")

    # 旧档桥接表：键须品质枚举 + 值为品质等级
    legacy = settings.get("legacy_quality_level_by_rarity")
    if legacy is not None:
        if not isinstance(legacy, Mapping):
            _err(report, "enhance.settings.legacy_quality_level_by_rarity", "V7",
                 msg="legacy_quality_level_by_rarity 需对象（旧品质枚举 → 品质等级）")
        else:
            for k, v in legacy.items():
                if k not in QUALITY_KEYS:
                    _err(report, "enhance.settings.legacy_quality_level_by_rarity", "V7",
                         key=k, msg=f"键须为品质枚举之一 {QUALITY_KEYS}")
                if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                    _err(report, "enhance.settings.legacy_quality_level_by_rarity", "V6",
                         key=k, value=v, msg="值须为非负整数（品质等级）")

    # 特殊词条跨度（原案 §7；包声明，非负整数；0 = 关闭词条）
    span = settings.get("special_affix_span")
    if span is not None and (isinstance(span, bool) or not isinstance(span, int) or span < 0):
        _err(report, "enhance.settings.special_affix_span", "V6",
             value=span, msg="special_affix_span 须为非负整数（0=关闭）")

    # V1/V2：曲线单调不增 + 覆盖 1..MaxR
    rates: Dict[int, int] = {}
    for i, row in enumerate(curve):
        if not isinstance(row, Mapping):
            _err(report, f"enhance.success_curve[{i}]", "V1", msg="曲线条目需对象")
            continue
        try:
            _to_v = row.get("to")
            _rate_v = row.get("rate")
            if _to_v is None or _rate_v is None:
                raise ValueError("missing")
            to = int(_to_v)
            rate = int(_rate_v)
        except (TypeError, ValueError):
            _err(report, f"enhance.success_curve[{i}]", "V1",
                 msg="曲线条目 to/rate 须为整数")
            continue
        if rate < 0 or rate > 100:
            _err(report, f"enhance.success_curve[{i}]", "V1",
                 rate=rate, msg="成功率须 0-100")
        if to in rates:
            _err(report, f"enhance.success_curve[{i}]", "V1",
                 to=to, msg="目标档位重复")
        rates[to] = rate
    prev_rate: Optional[int] = None
    prev_to: Optional[int] = None
    for to in sorted(rates):
        r = rates[to]
        if prev_rate is not None and r > prev_rate:
            _err(report, "enhance.success_curve", "V1",
                 to=to, rate=r, prev=prev_rate,
                 msg=f"成功率曲线须单调不增（+{to}={r}% 高于 +{prev_to}={prev_rate}%）")
        prev_rate, prev_to = r, to
    for need in range(1, max_r + 1):
        if need not in rates:
            _err(report, "enhance.success_curve", "V2",
                 missing=need, msg=f"曲线未覆盖档位 +{need}（需覆盖 1..+{max_r}）")

    # V4：石档位引用 items 存在性 + 覆盖连续
    tiers = cost.get("stone_tiers")
    if not isinstance(tiers, list):
        _err(report, "enhance.cost.stone_tiers", "V4", msg="stone_tiers 需数组")
    else:
        item_ids = _item_id_set(modules)
        covered: Set[int] = set()
        for i, t in enumerate(tiers):
            if not isinstance(t, Mapping):
                _err(report, f"enhance.cost.stone_tiers[{i}]", "V4", msg="档位条目需对象")
                continue
            item_id = str(t.get("item") or t.get("tier") or "")
            levels = t.get("levels")
            # 石 item 引用（2c3a 简版：条目含 item 字段则校验存在性）
            if item_id and item_id not in item_ids:
                _warn(report, f"enhance.cost.stone_tiers[{i}]", "V4",
                      item=item_id,
                      msg=f"强化石物品「{item_id}」不在 items.json（加载后黄提示）")
            if isinstance(levels, list):
                for lv in levels:
                    try:
                        covered.add(int(lv))
                    except (TypeError, ValueError):
                        continue
        for need in range(1, max_r + 1):
            if need not in covered:
                _err(report, "enhance.cost.stone_tiers", "V4",
                     missing=need, msg=f"石档位未覆盖强化目标 +{need}")

    # V3：碎率软警告
    if settings.get("shatter_mode"):
        chance = settings.get("shatter_chance", 0)
        smax = settings.get("shatter_max", 5)
        try:
            if int(chance or 0) > int(smax or 0):
                _warn(report, "enhance.settings.shatter_chance", "V3",
                      chance=chance, max=smax,
                      msg="碎率高挫败感强，确认？(超出建议上限)")
        except (TypeError, ValueError):
            _warn(report, "enhance.settings.shatter_chance", "V3", msg="碎率非整数，按 0 处理")

    # V5：等级门槛开关一致性（level_gated 键存在即 true 语义；2026-09-16 批28 D-6
    # 已删除空壳键 transfer_allowed——键在、校验在、core/ 无消费点，遵循奥卡姆直接删）
    for key in ("level_gated",):
        if key in settings and not isinstance(settings.get(key), bool):
            _err(report, f"enhance.settings.{key}", "V5", msg=f"{key} 须布尔")

    # V6：values 类型
    for vk in ("weapon_atk_per_level", "armor_def_per_level"):
        v = values.get(vk)
        if v is not None:
            if not isinstance(v, Mapping):
                _err(report, f"enhance.values.{vk}", "V6", msg="values 条目需对象")
                continue
            t = v.get("type")
            if t not in ("flat", "percent"):
                _err(report, f"enhance.values.{vk}", "V6", type=t,
                     msg="type 须 flat/percent")
            val = v.get("value")
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                _err(report, f"enhance.values.{vk}", "V6", msg="value 须数值")
