"""M12.5 强化数据层：enhance.json 数据模型 + 专项校验器（2c3a §5/§7 轻量落地）。

文件名：enhance_models.py
创建时间：2026-09-06

功能描述：
  - enhance.json 顶层 obj（对齐 forge.json 形态：registry.modules_raw["enhance"]）。
    段：settings（max_by_rarity/fail_tier_split/shatter_mode/luck_affects/
    transfer_allowed/level_gated）、cost（coin_per_level/stones_per_level/
    stone_tiers）、success_curve[]、values（weapon_atk_per_level/
    armor_def_per_level）、protect_stone。
  - validate_enhance(modules, report) 纯函数（(modules, report) 鸭子类型，
    对齐 alchemy_models.validate_recipes 口径）：
    V1 曲线单调不增（硬）；V2 曲线档位覆盖 1..MaxR（硬）；
    V4 石档位引用 items 存在性 + 覆盖连续（硬）；
    V7 max_by_rarity 键品质枚举（硬）；V5 转移/门槛开关一致性（硬）；
    V3 碎率超限软警告；结构异常（缺段/类型错）硬拦。
  - 缺失/未接线 enhance 模块 → 跳过（对齐既有校验器「默认放行」惯例）。

依据：
  - docs/细化/细化_2c3a_强化数值曲线.md §5.1 字段表（D-1~D-13）/ §5.2 校验器
    映射（V1~V7）/ §7 接缝审计（R-04：默认曲线补 +11/+12、high 档延至 12）。
  - docs/细化/细化_2c3b_强化流程契约.md（交互流程层，本模块只落数据/校验）。
  - 模式参考：qbot_rpg/content/forge_models.py（顶层 obj 模块形态）/
    qbot_rpg/content/alchemy_models.py（validate 鸭子类型）。

【工程补白】
  1. 品质枚举四档：normal/fine/epic/legendary（中文 普通/精良/史诗/传说）。
  2. 默认配置（未配 enhance.json）→ 系统未启用（GU-01），不加载不报错。
  3. V2 档位覆盖目标 = 1..MaxR（MaxR=max(max_by_rarity.values)，默认 12）。
  4. 内容包配置超上限档位（如 +13）→ V2 硬拦（曲线未覆盖）。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Set

__all__ = [
    "QUALITY_KEYS",
    "DEFAULT_MAX_BY_RARITY",
    "DEFAULT_FAIL_TIER_SPLIT",
    "DEFAULT_CURVE",
    "DEFAULT_STONE_TIERS",
    "DEFAULT_VALUES",
    "DEFAULT_ENHANCE",
    "parse_enhance_settings",
    "validate_enhance",
]

# 品质四档枚举（items.json 四档；V7 键枚举锚点）
QUALITY_KEYS = ("normal", "fine", "epic", "legendary")
QUALITY_LABELS_CN = {
    "normal": "普通", "fine": "精良", "epic": "史诗", "legendary": "传说",
}

# 定稿默认（2c3a §0/§5.1：上限 普通5 精良8 史诗10 传说12）
DEFAULT_MAX_BY_RARITY = {"normal": 5, "fine": 8, "epic": 10, "legendary": 12}
DEFAULT_FAIL_TIER_SPLIT = 3

# 默认成功率曲线（L80-81 + R-04 补 +11=20%/+12=15%）
DEFAULT_CURVE = [
    {"to": 1, "rate": 90}, {"to": 2, "rate": 85}, {"to": 3, "rate": 80},
    {"to": 4, "rate": 70}, {"to": 5, "rate": 60}, {"to": 6, "rate": 50},
    {"to": 7, "rate": 40}, {"to": 8, "rate": 35}, {"to": 9, "rate": 30},
    {"to": 10, "rate": 25}, {"to": 11, "rate": 20}, {"to": 12, "rate": 15},
]

# 默认石档位（L178-182 + R-04 high 延至 12）
DEFAULT_STONE_TIERS = [
    {"tier": "low", "levels": [1, 2, 3]},
    {"tier": "mid", "levels": [4, 5, 6]},
    {"tier": "high", "levels": [7, 8, 9, 10, 11, 12]},
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
        "max_by_rarity": dict(DEFAULT_MAX_BY_RARITY),
        "fail_tier_split": DEFAULT_FAIL_TIER_SPLIT,
        "shatter_mode": False,
        "shatter_chance": 0,
        "shatter_max": 5,
        "luck_affects": True,
        "transfer_allowed": False,
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

    max_by = settings.get("max_by_rarity")
    if not isinstance(max_by, Mapping):
        _err(report, "enhance.settings.max_by_rarity", "V7",
             msg="max_by_rarity 需对象（四档品质枚举 → 上限）")
        return
    # V7：键枚举（允许子集——内容包只配出现的品质；缺省由引擎回退默认）
    for k in max_by:
        if k not in QUALITY_KEYS:
            _err(report, "enhance.settings.max_by_rarity", "V7",
                 key=k, msg=f"max_by_rarity 键须为品质枚举之一 {QUALITY_KEYS}")
    # V6：值与类型
    try:
        max_r = max(int(v) for v in max_by.values())
    except (TypeError, ValueError):
        _err(report, "enhance.settings.max_by_rarity", "V6",
             msg="max_by_rarity 值须为非负整数")
        return
    if max_r < 0 or max_r > 20:
        _err(report, "enhance.settings.max_by_rarity", "V6",
             value=max_r, msg="上限值范围 0-20")

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

    # V5：转移/门槛开关一致性（transfer_allowed/level_gated 键存在即 true 语义）
    for key in ("transfer_allowed", "level_gated"):
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
