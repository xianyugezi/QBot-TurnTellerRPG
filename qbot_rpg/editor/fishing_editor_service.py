"""M10 钓鱼·批7·路7A：编辑器服务层预留（T19 服务端函数，纯函数层零 UI）。

文件名：qbot_rpg/editor/fishing_editor_service.py
创建时间：2026-09-01
作者：Hermes 子agent-7A（M10 钓鱼实现组批7·路7A：编辑器服务层预留）

功能描述：
  - fish_card_schema() -> dict：settings.fishing 九键字段定义（键名/类型/默认值/
    说明），供 M12 编辑器钓鱼卡片表单渲染。字段定义对齐
    core/fishing_settings.FISHING_SETTINGS_FIELD_DEFS（批0 已落盘，本函数
    只做薄封装导出编辑器可渲染形态，零重写）。
  - fish_csv_export(species) -> str / fish_csv_import(text, strict=False)
    -> list[dict]：编辑器鱼种 CSV 导入导出入口，直接复用 core/fishing_csv.py
    的 fishing_to_csv/csv_to_fishing（同款 13 列双向），薄委托零重写。
  - fish_csv_validate(rows) -> dict：逐行校验（id 唯一/必填字段/数值区间/枚举/
    引用存在性），对齐校验器 V1/V3/V5/V6 口径（不重复实现校验器，只做
    编辑器友好的 {ok, errors, warnings} 聚合）。
  - crown_preview(pct_size, pct_weight, thresholds=None) -> dict：冠级阈值
    滑条预览——调 core/fishing_crown.crown_of 返回档位（编辑器拖动百分位
    实时看档位），默认阈值 5/85/95。
  - simulate_catches(species, n, thresholds=None, seed=42) -> dict：图鉴模拟
    ——用 gen_size_weight + crown_of 模拟 n 次捕捞，输出冠级分布与总览；
    种子化（seed 缺省 42）确定性；与运行分布同参数一致（T19 验收标准）。

依据：
  - docs/规划/规划_路2c1_钓鱼.md T19（L164-170：编辑器零代码配置——钓鱼卡片/
    鱼种 CSV/冠级预览/图鉴模拟）
  - docs/m10_batch_plan.md 批7·路7A（编辑器服务层预留，UI 归 M12）
  - docs/m10_启动包.md §五 批7（L92-93：本里程碑只做服务层）
  - 定稿 §五（L101-106：鱼种池 CSV 列 / 冠级阈值滑条 / 图鉴模拟）+
    §七 登记要求·编辑器（L124）
  - docs/细化/细化_2c1a_鱼种数据与冠级.md §一 1.4（CSV 13 列固定序）/
    §二 2.2（六档概率）/ §七（编辑器登记：CSV 列 + 冠级阈值滑条 +
    大小重量预览走 §2.2 判定）
  - docs/m10_shared_contract.md §二（Fish 行 F-01~F-14）/ §三（校验器
    V1-V6 口径）/ §五 铁律
模式参考：
  - qbot_rpg/core/fishing_settings.py（FISHING_SETTINGS_FIELD_DEFS 批0 形态）
  - qbot_rpg/core/fishing_csv.py（13 列双向，批0）
  - qbot_rpg/core/fishing_crown.py（crown_of/gen_size_weight，批3）
  - qbot_rpg/content/fishing_models.py（校验器 V1-V6 口径，批0）

【工程补白】（契约/定稿未显式定义处的实现口径，显式标注供审查，标 E-x）：
  E-1  本文件是纯函数服务层：零 NoneBot import、零 IO、零定时器/零睡眠调用、
       零随机（全部随机源注入或种子化）。CSV 文本仅作为 str 出入参，不做
       文件读写（M12 UI 层负责文件/上传装配）。
  E-2  fish_card_schema 的字段说明文案取自定稿 §三 各键语义（批0
       FISHING_SETTINGS_FIELD_DEFS 无中文说明，本层补「说明」键供表单提示）；
       类型/默认值/枚举逐键对齐批0 定义，零重写。
  E-3  fish_csv_validate 只做编辑器导入前的轻量预检：id 唯一 / 必填字段 /
       size/weight 区间（V1 口径）/ rarity/seasons/periods 枚举（V6 口径）/
       spots 非空（V6 口径）/ hours 格式（V6 口径）/ preferred_bait 引用
       settings.fishing.bait_ids（V3 口径，bait_ids 缺省时跳过不误报）。
       不做完整包级校验（V2/V4/W1 属 settings/king 域，M12 导入保存时由
       内容包校验器全量拦截）；「不重复实现校验器」——本函数只做编辑器
       友好的逐行聚合，规则口径与 fishing_models.validate_fishing 一致。
  E-4  simulate_catches 输出除分布外含期望理论值（theoretical，按细化 2c1a
       §2.2 均匀分布六档概率公式），供 M12 图鉴模拟对比；样本 n=0 时分布
       全零、期望为空。
  E-5  crown_preview 的 thresholds 入参透传 crown_of（显式 dict / None /
       ctx 三态），档位输出含中文标签（CROWN_LABELS）供滑条 UI 直接展示。

铁律：零 NoneBot import；纯函数确定性零 IO 零定时器/零睡眠（docstring 不含
      计时器函数字面量，M43 探针）；零 emoji；确定性种子化（无裸 random）。
"""

from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from qbot_rpg.core.fishing_crown import (
    CROWN_LABELS,
    DEFAULT_CROWN_THRESHOLDS,
    crown_of,
    gen_size_weight,
)
from qbot_rpg.core.fishing_csv import csv_to_fishing, fishing_to_csv
from qbot_rpg.core.fishing_settings import (
    DEFAULT_FISHING_SETTINGS,
    FISHING_SETTINGS_FIELD_DEFS,
    FISHING_SETTINGS_KEYS,
    MODE_VALUES,
)

# =====================================================================================
# 常量：编辑器服务层专用（契约 §二 / 细化 2c1a §1.1 F-01~F-14 + §2.2 六档概率）
# =====================================================================================

# 鱼种 CSV 列序（对齐 core/fishing_csv.CSV_COLUMNS，批0 契约 §二 13 列固定序）
SPECIES_CSV_COLUMNS: tuple = (
    "id",
    "name",
    "rarity",
    "size_min",
    "size_max",
    "weight_min",
    "weight_max",
    "seasons",
    "periods",
    "hours",
    "spots",
    "preferred_bait",
    "codex_text",
)

# 鱼种必填字段（细化 2c1a §1.1：F-01/F-02/F-03/F-04~F-07/F-11 必填）
_REQUIRED_SPECIES_FIELDS: tuple = ("id", "name", "rarity")

# 稀有度/季节/时段枚举（对齐 fishing_models V6 口径）
_RARITY_ENUM: tuple = ("normal", "rare", "gold")
_SEASON_ENUM: tuple = ("spring", "summer", "autumn", "winter")
_PERIOD_ENUM: tuple = ("dawn", "noon", "dusk", "night", "midnight")

# 数值区间字段（V1 口径：size_min<=size_max、weight_min<=weight_max）
_NUMERIC_RANGE_PAIRS: tuple = (("size_min", "size_max"), ("weight_min", "weight_max"))

# 图鉴模拟默认种子（T19 验收标准：与运行分布同参数一致；确定性种子化）
DEFAULT_SIM_SEED: int = 42

# 六档理论概率（细化 2c1a §2.2 默认阈值均匀分布；simulate_catches 期望对比）
_THEORETICAL_PROBS: Dict[str, float] = {
    "reverse": 0.0025,     # 0.05^2（逆金冠）
    "big_gold": 0.0025,    # 0.05^2（大金冠）
    "gold": 0.095,         # 1 - 0.95^2 - 0.00025（金冠）
    "big_silver": 0.01,    # 0.10^2（大银冠）
    "silver": 0.17,        # 2 * 0.10 * 0.85（银冠）
    "normal": 0.72,        # 其余（普通）
}


# =====================================================================================
# 钓鱼卡片字段 schema（T19 · 编辑器表单渲染；薄封装批0 FISHING_SETTINGS_FIELD_DEFS）
# =====================================================================================
def fish_card_schema() -> Dict[str, Dict[str, object]]:
    """settings.fishing 九键字段定义（编辑器钓鱼卡片表单渲染数据源）。

    入参：无。
    出参：dict，键序照 FISHING_SETTINGS_KEYS（9 键）：
      {
        "mode": {"type": "enum", "default": "full", "enum": ("full","simple","off"),
                 "desc": "三态模式开关（full 完整 / simple 直接出鱼 / off 关闭）"},
        "bait_ids": {"type": "list", "default": [...], "element": "str",
                     "desc": "5 档饵 id 引用炼金 recipe"},
        ...
      }
    字段定义对齐批0 core/fishing_settings.FISHING_SETTINGS_FIELD_DEFS（键名/
    类型/默认值零重写）；「说明」文案按定稿 §三 各键语义补全（【工程补白 E-2】），
    枚举值（mode）对齐 MODE_VALUES。
    核心逻辑（纯函数确定性）：
      - 逐键读 FISHING_SETTINGS_FIELD_DEFS：FieldMeta.type → 表单控件类型；
        FieldMeta.default 缺省 None 时回落 DEFAULT_FISHING_SETTINGS 同键默认。
      - mode 键补 enum=("full","simple","off") 供下拉渲染；bait_ids 补
        element="str" 供列表编辑器。
      - 嵌套对象键（bait_bonus/rod_full_bonus/crown_thresholds/wait_sec/
        energy/king_event）补 children 键名列表（表单分组提示）。
    确定性：同环境恒同输出（无 IO 无随机）。
    """
    out: Dict[str, Dict[str, object]] = {}
    for key in FISHING_SETTINGS_KEYS:
        meta = FISHING_SETTINGS_FIELD_DEFS[key]
        default = meta.default
        if default is None:
            default = DEFAULT_FISHING_SETTINGS.get(key)
        entry: Dict[str, object] = {
            "type": meta.type,
            "default": default,
            "desc": _FIELD_DESC.get(key, ""),
        }
        if key == "mode":
            entry["enum"] = MODE_VALUES
        if meta.type == "list" and meta.element is not None:
            entry["element"] = meta.element.type
        if meta.type == "obj":
            entry["children"] = _OBJ_CHILDREN.get(key, ())
        out[key] = entry
    return out


# 九键说明文案（定稿 §三 L72-82 逐键语义；供编辑器表单提示，E-2）
_FIELD_DESC: Dict[str, str] = {
    "mode": "三态模式开关（full 完整流程 / simple 直接出鱼 / off 关闭）",
    "bait_ids": "5 档饵 id 引用炼金 recipe（对口饵加成见 bait_bonus）",
    "bait_bonus": "对口饵稀有/金加成百分数（rare/gold，0=无加成）",
    "rod_full_bonus": "满力收杆 roll 加成百分数（rare/gold，0=无加成）",
    "crown_thresholds": "冠级阈值（reverse/silver/gold，0<r<s<g<100）",
    "wait_sec": "等待区间秒（min/max，0=即收）",
    "daily_limit": "每日钓鱼次数上限",
    "energy": "能量条开关（enabled 布尔）",
    "king_event": "鱼王事件（enabled/window_daily/chance）",
}

# 嵌套对象键的子键名（表单分组提示；对齐 DEFAULT_FISHING_SETTINGS 各对象键）
_OBJ_CHILDREN: Dict[str, tuple] = {
    "bait_bonus": ("rare", "gold"),
    "rod_full_bonus": ("rare", "gold"),
    "crown_thresholds": ("reverse", "silver", "gold"),
    "wait_sec": ("min", "max"),
    "energy": ("enabled",),
    "king_event": ("enabled", "window_daily", "chance"),
}


# =====================================================================================
# 鱼种 CSV 导入导出（T19 · 复用批0 core/fishing_csv 13 列双向，薄委托零重写）
# =====================================================================================
def fish_csv_export(species: Sequence[Mapping[str, object]]) -> str:
    """鱼种池 → 13 列 CSV 文本（编辑器「导出 CSV」入口）。

    入参：species —— 鱼种 dict 列表（每项含 13 列键；额外键如 king 不导出，
      对齐批0 13 列固定契约）。
    出参：CSV 文本（utf-8，含表头行；行间 \\n 分隔）。
    核心逻辑：直接委托 core/fishing_csv.fishing_to_csv（同一函数，编辑器与
      运行层共用同款 13 列双向——T19「鱼种池 CSV 编辑（T02 列）」）。
    确定性：同输入恒同文本（无随机无 IO，E-1）。
    """
    return fishing_to_csv(species)


def fish_csv_import(text: str, strict: bool = False) -> List[Dict[str, Any]]:
    """CSV 文本 → 鱼种 dict 列表（编辑器「导入 CSV」入口）。

    入参：
      text —— CSV 文本（表头行自动跳过；空行跳过）。
      strict —— True 时非法行抛 ValueError（暴露坏行）；False（默认）跳过
        非法行容错返回。
    出参：鱼种 dict 列表（每项含 13 列键；codex_text 解析回 dict/None；
      数组列解析回 list，空字符串 → []）。
    核心逻辑：直接委托 core/fishing_csv.csv_to_fishing（同一函数）。
    确定性：同输入恒同结果（无 IO 无随机，E-1）。
    """
    return csv_to_fishing(text, strict=strict)


# =====================================================================================
# 鱼种 CSV 逐行校验（T19 · 编辑器导入预检；对齐校验器 V1/V3/V5/V6 口径）
# =====================================================================================
def fish_csv_validate(
    rows: Sequence[Mapping[str, object]],
    bait_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """鱼种 CSV 导入行逐行校验（编辑器友好聚合，对齐校验器 V1/V3/V5/V6 口径）。

    入参：
      rows —— fish_csv_import 返回的鱼种 dict 列表（或同形态 Mapping 列表）。
      bait_ids —— settings.fishing.bait_ids（可选；None 时 preferred_bait 引用
        检查宽松跳过不误报，对齐 fishing_models _bait_ids 缺失跳过口径）。
    出参：{"ok": bool, "errors": [...], "warnings": [...]}：
      - errors：list[dict]，每项 {"row": 行号(1 起), "field": 字段路径,
        "rule": 规则码, "message": 人话描述}；非空 → ok=False。
      - warnings：list[dict]（同结构）；ok 不受 warnings 影响。
    规则（对齐 fishing_models.validate_fishing V1/V3/V5/V6 口径，E-3）：
      - V5 id 必填（fish_id_required）/ id 唯一（fish_id_duplicate）。
      - 必填字段 name/rarity 缺失（required_field_missing，F-02/F-03 必填）。
      - V1 区间 size_min<=size_max 且 weight_min<=weight_max（size_range_reversed/
        weight_range_reversed；非数字字段不判，交内容包校验器拦截）。
      - V6 rarity/seasons/periods 枚举合法（rarity_invalid/season_invalid/
        period_invalid）；hours 格式 HH:MM-HH:MM（hours_format）；spots 非空
        （spots_empty，F-11 必填且 ≥1）。
      - V3 preferred_bait 引用存在（bait_ref_missing；bait_ids 缺省跳过）。
    确定性：纯函数，同入参恒同结果。
    """
    errors: List[Dict[str, object]] = []
    warnings: List[Dict[str, object]] = []
    seen: Dict[str, int] = {}
    bait_set: Optional[set] = None
    if bait_ids is not None:
        bait_set = {b for b in bait_ids if isinstance(b, str) and b} or None

    for i, row in enumerate(rows):
        idx = i + 1  # 行号 1 起（表头已被 csv_to_fishing 跳过）
        if not isinstance(row, Mapping):
            errors.append(_err(idx, "", "row_not_object", "行数据非对象"))
            continue
        eid = row.get("id")
        if not isinstance(eid, str) or not eid:
            errors.append(_err(idx, "id", "fish_id_required", "id 必填（英文小写蛇形）"))
        elif eid in seen:
            errors.append(_err(
                idx, "id", "fish_id_duplicate",
                f"id 重复：{eid}（首个出现于第 {seen[eid]} 行）",
            ))
        else:
            seen[eid] = idx
        for f in ("name", "rarity"):
            v = row.get(f)
            if not isinstance(v, str) or not v:
                errors.append(_err(idx, f, "required_field_missing", f"{f} 必填"))
        # V1 区间（非数字不判——类型问题交内容包校验器）
        for lo_key, hi_key in _NUMERIC_RANGE_PAIRS:
            lo, hi = row.get(lo_key), row.get(hi_key)
            if isinstance(lo, (int, float)) and not isinstance(lo, bool) \
                    and isinstance(hi, (int, float)) and not isinstance(hi, bool):
                if lo > hi:
                    errors.append(_err(
                        idx, lo_key, "range_reversed",
                        f"{lo_key}({lo}) 大于 {hi_key}({hi})，须 {lo_key}<={hi_key}"))
        # V6 枚举
        _check_enum(idx, row, "rarity", _RARITY_ENUM, errors, "rarity_invalid")
        _check_enum_list(idx, row, "seasons", _SEASON_ENUM, errors, "season_invalid")
        _check_enum_list(idx, row, "periods", _PERIOD_ENUM, errors, "period_invalid")
        # V6 hours 格式（HH:MM-HH:MM，对齐 HOURS_RANGE_RE 口径；另查分钟 ≤59）
        hours = row.get("hours")
        if isinstance(hours, list):
            for hi, h in enumerate(hours):
                if not isinstance(h, str) or not _HOURS_RE.match(h) \
                        or not _minutes_valid(h):
                    errors.append(_err(idx, f"hours.{hi}", "hours_format",
                                       "小时区间格式须 HH:MM-HH:MM（分钟 00-59）"))
        else:
            errors.append(_err(idx, "hours", "hours_format",
                               "hours 须为字符串列表（如 [\"00:00-24:00\"]）"))
        # V6 spots 非空（F-11 必填且 ≥1）
        spots = row.get("spots")
        if not isinstance(spots, list) or not spots:
            errors.append(_err(idx, "spots", "spots_empty", "spots 必填且至少 1 个钓点"))
        # V3 preferred_bait 引用（bait_ids 缺省跳过）
        pb = row.get("preferred_bait")
        if isinstance(pb, list) and bait_set is not None:
            for bi, b in enumerate(pb):
                if not isinstance(b, str) or not b:
                    errors.append(_err(idx, f"preferred_bait.{bi}", "bait_not_str",
                                       "preferred_bait 元素须为字符串"))
                elif b not in bait_set:
                    errors.append(_err(idx, f"preferred_bait.{bi}", "bait_ref_missing",
                                       f"饵 {b} 不在 settings.fishing.bait_ids"))

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _err(idx: int, field: str, rule: str, message: str) -> Dict[str, object]:
    """校验错误条目构造（编辑器友好聚合形态）。"""
    return {"row": idx, "field": field, "rule": rule, "message": message}


def _check_enum(
    idx: int,
    row: Mapping[str, object],
    key: str,
    enum: tuple,
    errors: List[Dict[str, object]],
    rule: str,
) -> None:
    """单值枚举校验（V6 口径：值非 None 且不在枚举 → 错误）。"""
    v = row.get(key)
    if v is not None and v not in enum:
        errors.append(_err(idx, key, rule, f"{key} 非法值 {v!r}（合法：{list(enum)}）"))


def _check_enum_list(
    idx: int,
    row: Mapping[str, object],
    key: str,
    enum: tuple,
    errors: List[Dict[str, object]],
    rule: str,
) -> None:
    """数组枚举校验（V6 口径：元素不在枚举 → 错误）。"""
    vals = row.get(key)
    if isinstance(vals, list):
        for vi, v in enumerate(vals):
            if v not in enum:
                errors.append(_err(idx, f"{key}.{vi}", rule,
                                   f"{key} 非法值 {v!r}（合法：{list(enum)}）"))


# 小时区间格式（对齐 fishing_models.HOURS_RANGE_RE：宽松 1-2 位小时 + 2 位分钟）
_HOURS_RE = re.compile(r"^\d{1,2}:\d{2}-\d{1,2}:\d{2}$")


def _minutes_valid(hours_range: str) -> bool:
    """分钟合法性检查（编辑器预检增强：分钟须 00-59，小时 0-24 已由正则覆盖）。

    对齐 fishing_models.HOURS_RANGE_RE 结构（HH:MM-HH:MM）；fishing_models
    只查格式（宽松），本预检额外查分钟 ≤59 拦明显笔误（"25:99" 类），
    完整合法性仍由内容包校验器最终拦截。
    """
    for part in hours_range.split("-"):
        minute = part.split(":")[1]
        if not minute.isdigit() or int(minute) > 59:
            return False
    return True


# =====================================================================================
# 冠级阈值滑条预览（T19 · 拖动百分位实时看档位；走批3 crown_of 判定）
# =====================================================================================
def crown_preview(
    pct_size: object,
    pct_weight: object,
    thresholds: Optional[Dict[str, int]] = None,
) -> Dict[str, object]:
    """冠级阈值滑条预览：给定大小/重量百分位 → 六档判定结果。

    入参：
      pct_size   —— 大小百分位（0~100 开区间语义，理论 ∈[0,100)）。
      pct_weight —— 重量百分位。
      thresholds —— 阈值参数化（{reverse, silver, gold}；None → 默认 5/85/95，
        或 ctx 形态透传 crown_of 三态归一，【工程补白 E-5】）。
    出参：
      {
        "pct_size": float, "pct_weight": float,
        "crown": "reverse"/"big_gold"/"gold"/"big_silver"/"silver"/"normal",
        "label": "逆金冠"/"大金冠"/"金冠"/"大银冠"/"银冠"/"普通",
        "thresholds": {"reverse": r, "silver": s, "gold": g},
      }
    核心逻辑：直接调 core/fishing_crown.crown_of（批3 判定引擎，判定顺序
      写死、边界语义 <r / >=s / >=g 全复用）；中文标签取 CROWN_LABELS。
    确定性：纯函数零 IO 零随机，同入参恒同结果。
    """
    crown = crown_of(pct_size, pct_weight, thresholds)
    pct_s = float(pct_size) if isinstance(pct_size, (int, float)) \
        and not isinstance(pct_size, bool) else 0.0
    pct_w = float(pct_weight) if isinstance(pct_weight, (int, float)) \
        and not isinstance(pct_weight, bool) else 0.0
    return {
        "pct_size": pct_s,
        "pct_weight": pct_w,
        "crown": crown,
        "label": CROWN_LABELS.get(crown, crown),
        "thresholds": dict(DEFAULT_CROWN_THRESHOLDS),
    }


# =====================================================================================
# 图鉴模拟（T19 · 种子化 n 次捕捞冠级分布；与运行分布同参数一致）
# =====================================================================================
def simulate_catches(
    species: object,
    n: int,
    thresholds: Optional[Dict[str, int]] = None,
    seed: Optional[int] = DEFAULT_SIM_SEED,
) -> Dict[str, object]:
    """图鉴模拟：种子化模拟 n 次捕捞，输出冠级分布与总览。

    入参：
      species   —— 鱼种定义：FishDef（批0 访问器）或 Mapping（含 size_min/
                    size_max/weight_min/weight_max 四键），透传
                    core/fishing_crown.gen_size_weight 双形态容错。
      n         —— 模拟次数（非负 int；0 → 分布全零）。
      thresholds—— 冠级阈值（{reverse, silver, gold}；None → 默认 5/85/95，
                    或 ctx 形态透传 crown_of 三态归一）。
      seed      —— 随机种子（缺省 42，T19 确定性）；None 时不注入 rng
                    （不推荐，破坏确定性）。
    出参：
      {
        "n": n,
        "distribution": {"reverse": x, "big_gold": y, "gold": z,
                         "big_silver": w, "silver": v, "normal": u},
        "total": n,
        "theoretical": {"reverse": 0.0025, ..., "normal": 0.72},  # E-4
        "seed": seed,
      }
    核心逻辑（与运行分布同参数一致——T19 验收标准）：
      - 每次捕捞 = gen_size_weight(species, rng)（百分位均匀 + 线性插值）
        + crown_of(size_pct, weight_pct, thresholds)（六档判定）。
      - 与运行时出鱼结算（批3 gen_size_weight/crown_of）同一引擎同一参数，
        仅样本量 n 由编辑器指定。
      - 种子化：random.Random(seed) 注入，同 seed 同 species 同 n →
        恒同分布（确定性重放）。
    确定性：同入参恒同结果（种子化，无裸 random）。
    """
    count = n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else 0
    dist: Dict[str, int] = {key: 0 for key in _THEORETICAL_PROBS}
    if count > 0:
        rng: Any = random.Random(seed) if seed is not None else random
        for _ in range(count):
            gen = gen_size_weight(species, rng)
            crown = crown_of(gen["size_pct"], gen["weight_pct"], thresholds)
            dist[crown] = dist.get(crown, 0) + 1
    return {
        "n": count,
        "distribution": dist,
        "total": count,
        "theoretical": dict(_THEORETICAL_PROBS),
        "seed": seed,
    }


__all__ = [
    # 常量
    "SPECIES_CSV_COLUMNS",
    "DEFAULT_SIM_SEED",
    # 钓鱼卡片字段
    "fish_card_schema",
    # 鱼种 CSV 导入导出
    "fish_csv_export",
    "fish_csv_import",
    "fish_csv_validate",
    # 冠级阈值滑条预览
    "crown_preview",
    # 图鉴模拟
    "simulate_catches",
]
