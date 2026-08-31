"""M10 批次0·路0A：settings.fishing 段读取容错归一（fishing_cfg）+ 默认值/键集/字段定义。

文件：qbot_rpg/core/fishing_settings.py
创建：2026-08-31
作者：Hermes 子agent-0A（M10 钓鱼数据层 路0A）
功能：settings.fishing 段读取归一（fishing_cfg，缺省合并默认值，纯函数确定性零 IO
      零定时器）+ 默认值常量 DEFAULT_FISHING_SETTINGS + 键集 FISHING_SETTINGS_KEYS
      + settings.fishing 段 FieldMeta（FISHING_SETTINGS_FIELD_DEFS，供主 agent 收口
      合并 SETTINGS_FIELDS["fishing"]，本路不写 field_meta.py）。

依据：细化_2c1a §1.0（F-12 preferred_bait 引用 bait_ids / §三 crown_thresholds）
      + 定稿 §三 配置结构（行 72-82：mode/bait_ids/bait_bonus/rod_full_bonus/
      crown_thresholds/wait_sec/daily_limit/energy/king_event 九键默认值）
      + docs/m10_shared_contract.md §一（settings.fishing 段字段表，默认值与定稿逐键
      一致）/ §四（路0A 文件清单与独占：settings.json）/ §五 铁律。
模式参考：
  - qbot_rpg/content/forge_settings.py（M9 路0B：read_forge_settings 段缺失默认兜底/
    逐键类型容错/FIELD_DEFS 供收口——本模块同一形态，差异：契约要求三态入参（全量
    dict / settings.fishing 段 / None），forge 只收 settings 全量）
  - qbot_rpg/content/field_meta.py forge_settings_meta()（L690：SETTINGS_FIELDS 登记
    形态 type=obj + children——本路只产出 FISHING_SETTINGS_FIELD_DEFS，不写 field_meta）

铁律：本文件零 NoneBot import、纯函数确定性、零 IO、零定时器/零睡眠调用、平台无关；
      mode 枚举硬错（V4）由校验器（路0C）拦，本路读段不拦非法值只做类型容错；
      未知键默认放行不破坏加载（对齐加载器 §2.3 兜底）。

【工程补白】清单（契约/定稿未显式定义处的实现口径，标 A-x）：
  A-1  fishing_cfg 三态判定：入参为 Mapping 且含 "fishing" 键 → 视为 settings 全量取段；
       入参为 Mapping 且含 "settings" 键（ctx 形态，settings 为 Mapping）→ 先解包再判；
       其余 Mapping → 视为 settings.fishing 段本身逐键读取（全量缺段时键不匹配 →
       全默认，语义等价）；None/非 Mapping → 全默认。对齐契约 §一「段缺失/空 → 默认值
       兜底不报错」+ 摸底 §八 ctx["fishing_cfg"] 注入形态。
  A-2  嵌套对象（bait_bonus/rod_full_bonus/crown_thresholds/wait_sec/energy/king_event）
       显式为 Mapping → 与默认合并（显式键类型合法则覆盖，缺省保留默认；非法类型回退
       默认）——对齐 forge decompose_rate 合并口径。
  A-3  bait_ids 显式为 list/tuple → 过滤 str 元素（宽松容错）；过滤后非空则生效，
       空/非 list → 默认 5 档。
  A-4  mode 仅非空 str 生效（枚举合法性不判，V4 归路0C 校验器）。
  A-5  daily_limit 仅非负 int 生效（排除 bool）。
"""

from __future__ import annotations

import copy
from typing import Dict, Mapping, Tuple, TypeGuard, cast

from qbot_rpg.content.models import FieldMeta

# =====================================================================================
# 常量：settings.fishing 段默认值（定稿 §三 行 72-82 九键 + 共享契约 §一 逐键一致）
# =====================================================================================

# 钓鱼模式三态枚举（full/simple/off，V4 校验器硬拦枚举；读段不拦）
MODE_VALUES: Tuple[str, ...] = ("full", "simple", "off")

# settings.fishing 段默认值（契约 §一 字段表 + 定稿 §三 行 72-82）
DEFAULT_FISHING_SETTINGS: Dict[str, object] = {
    "mode": "full",
    # 5 档饵引用炼金 recipe（定稿 L74）
    "bait_ids": ["饵_蚯蚓", "饵_面团", "饵_小鱼", "饵_黄金虫", "饵_龙涎"],
    # 对口饵加成（百分数，默认稀有+8%/金+2% 不变，0=无加成）| 定稿 L75
    "bait_bonus": {"rare": 8, "gold": 2},
    # 满力收杆 roll 加成（百分数可配，0=无加成）| 定稿 L76
    "rod_full_bonus": {"rare": 4, "gold": 2},
    # 冠级阈值（可配；V2 序校验 reverse < silver < gold 归路0C）| 定稿 L77
    "crown_thresholds": {"reverse": 5, "silver": 85, "gold": 95},
    # 等待区间秒（可配 0=即收）| 定稿 L78
    "wait_sec": {"min": 300, "max": 900},
    # 每日次数（quest_daily 懒计算）| 定稿 L79
    "daily_limit": 20,
    # 可选能量条（默认关）| 定稿 L80
    "energy": {"enabled": False},
    # 鱼王事件（30% 触发）| 定稿 L81
    "king_event": {"enabled": True, "window_daily": 2, "chance": 0.3},
}

# settings.fishing 段可解析键（fishing_cfg 遍历顺序，照共享契约 §一 字段表 9 键）
FISHING_SETTINGS_KEYS: Tuple[str, ...] = (
    "mode",
    "bait_ids",
    "bait_bonus",
    "rod_full_bonus",
    "crown_thresholds",
    "wait_sec",
    "daily_limit",
    "energy",
    "king_event",
)

# =====================================================================================
# settings.fishing 段 FieldMeta（对齐 FORGE_SETTINGS_FIELD_DEFS 形态；供主 agent 收口
# SETTINGS_FIELDS["fishing"] = fishing_settings_meta()）
# =====================================================================================
FISHING_SETTINGS_FIELD_DEFS: Dict[str, FieldMeta] = {
    # mode 三态枚举（V4 硬拦；default=full，定稿 L73）——FIELD_DEFS 登记枚举供校验器
    # 红拦非法值（读段 fishing_cfg 不拦，归路0C 校验器）
    "mode": FieldMeta(type="enum", enum=MODE_VALUES, default="full"),
    # bait_ids 5 档饵 id 引用炼金 recipe（str 列表，定稿 L74）
    "bait_ids": FieldMeta(type="list", element=FieldMeta(type="str")),
    # bait_bonus 对口饵加成（百分数，rare/gold，定稿 L75）
    "bait_bonus": FieldMeta(type="obj"),
    # rod_full_bonus 满力收杆 roll 加成（百分数，rare/gold，定稿 L76）
    "rod_full_bonus": FieldMeta(type="obj"),
    # crown_thresholds 冠级阈值（reverse/silver/gold，定稿 L77）
    "crown_thresholds": FieldMeta(type="obj"),
    # wait_sec 等待区间（min/max 秒，0=即收，定稿 L78）
    "wait_sec": FieldMeta(type="obj"),
    # daily_limit 每日次数（int，定稿 L79）
    "daily_limit": FieldMeta(type="int"),
    # energy 能量条开关（obj，定稿 L80）
    "energy": FieldMeta(type="obj"),
    # king_event 鱼王事件（obj，enabled/window_daily/chance，定稿 L81）
    "king_event": FieldMeta(type="obj"),
}


def fishing_settings_meta() -> FieldMeta:
    """settings.fishing 段 FieldMeta（type=obj + 全字段 children；合并进 SETTINGS_FIELDS）。"""
    return FieldMeta(type="obj", children=FISHING_SETTINGS_FIELD_DEFS)


# =====================================================================================
# 工具：类型判定（排除 bool——bool 是 int 子类）
# =====================================================================================
def _is_int(v: object) -> TypeGuard[int]:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_nonneg_int(v: object) -> TypeGuard[int]:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _is_bool(v: object) -> TypeGuard[bool]:
    return isinstance(v, bool)


def _is_number(v: object) -> TypeGuard[float]:
    """数字判定（int/float，排除 bool）；chance 百分数/概率用。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _nonempty_str(v: object) -> TypeGuard[str]:
    return isinstance(v, str) and bool(v.strip())


def _merge_int_map(default: Mapping[str, object], explicit: object) -> Dict[str, object]:
    """嵌套 int 值对象合并（对齐 forge decompose_rate 合并口径）。

    显式 Mapping → 与默认合并：键类型合法（非负 int）则覆盖，缺省/非法类型保留默认。
    非 Mapping / None → 默认深拷贝。键序照默认。
    """
    out: Dict[str, object] = dict(default)
    if not isinstance(explicit, Mapping):
        return out
    for key, val in explicit.items():
        if isinstance(key, str) and _is_nonneg_int(val):
            out[key] = val
    return out


# =====================================================================================
# fishing_cfg：settings.fishing 段读取归一（缺省合并默认值，纯函数确定性）
# =====================================================================================
def fishing_cfg(ctx_or_settings: object) -> Dict[str, object]:
    """解析 settings.fishing 段，缺省合并默认值（契约 §一 字段表 + 定稿 §三 行 72-82）。

    入参（三态容错，【工程补白 A-1】）：
      ctx_or_settings ——
        ① settings 全量 dict（Mapping 且含 "fishing" 键）→ 取 data["fishing"] 段；
        ② settings.fishing 段本身（Mapping 无 "fishing" 键）→ 逐键读取；
        ③ ctx 形态（Mapping 且含 "settings" 键且其为 Mapping）→ 先解包 settings 再判；
        ④ None / 非 Mapping → 全默认值兜底（对齐契约 §一「段缺失/空 → 默认值兜底不报错」）。
    出参：
      合并后的 dict（键序照 FISHING_SETTINGS_KEYS 9 键）：mode / bait_ids / bait_bonus /
      rod_full_bonus / crown_thresholds / wait_sec / daily_limit / energy / king_event。
    核心逻辑（纯函数、确定性、无副作用）：
      - 段缺失/空/非对象 → DEFAULT_FISHING_SETTINGS 深拷贝全量返回（不报错）。
      - 段存在 → 逐键取值：显式键类型合法则覆盖默认；非法类型回退默认（运行期兜底
        不炸，越界/引用问题由校验器硬拦——对齐 battle_boundary from_settings 容错口径）。
      - mode：仅非空 str 生效；枚举合法性不判（V4 归路0C 校验器，【工程补白 A-4】）。
      - bait_ids：list/tuple → 过滤 str 元素，非空则生效（【工程补白 A-3】）。
      - 嵌套对象（bait_bonus/rod_full_bonus/crown_thresholds/wait_sec）：显式 Mapping
        → 与默认合并（非负 int 键覆盖，非法/缺省保留默认，【工程补白 A-2】）。
      - daily_limit：仅非负 int 生效（排除 bool，【工程补白 A-5】）。
      - energy：Mapping → {enabled: bool} 合并；非 bool 回退默认 false。
      - king_event：Mapping → enabled 仅 bool / window_daily 仅非负 int / chance 仅数字
        逐键合并；非法类型回退默认。
    """
    raw = ctx_or_settings
    # ③ ctx 形态解包（【工程补白 A-1】：make_context 传入 deps.settings 或 ctx 均可）
    if isinstance(raw, Mapping) and isinstance(raw.get("settings"), Mapping):
        raw = raw["settings"]

    out: Dict[str, object] = copy.deepcopy(DEFAULT_FISHING_SETTINGS)
    if not isinstance(raw, Mapping):
        return out  # ④ None/非 Mapping → 全默认值兜底

    # ① 含 "fishing" 键 → settings 全量取段；段非对象 → 全默认兜底
    if "fishing" in raw:
        fishing = raw["fishing"]
        if not isinstance(fishing, Mapping):
            return out  # 段存在但非对象 → 全默认（契约 §一 段缺失/空兜底口径）
        section: Mapping[str, object] = fishing
    else:
        # ② 无 "fishing" 键 → 视为 settings.fishing 段本身逐键读取
        #    （全量缺段时键不匹配 → 全默认，语义等价）
        section = raw

    # ---- mode：仅非空 str 生效；枚举合法性不判（V4 归路0C，【工程补白 A-4】）----
    m = section.get("mode")
    if _nonempty_str(m):
        out["mode"] = m

    # ---- bait_ids：list/tuple → 过滤 str 元素，非空则生效（【工程补白 A-3】）----
    bid = section.get("bait_ids")
    if isinstance(bid, (list, tuple)):
        cleaned = [x for x in bid if isinstance(x, str) and bool(x.strip())]
        if cleaned:
            out["bait_ids"] = cleaned

    # ---- 嵌套 int 值对象：bait_bonus / rod_full_bonus / crown_thresholds / wait_sec ----
    for key in ("bait_bonus", "rod_full_bonus", "crown_thresholds", "wait_sec"):
        default_map = cast(Mapping[str, object], out[key])
        out[key] = _merge_int_map(default_map, section.get(key))

    # ---- daily_limit：仅非负 int 生效（排除 bool，【工程补白 A-5】）----
    dl = section.get("daily_limit")
    if _is_nonneg_int(dl):
        out["daily_limit"] = dl

    # ---- energy：{enabled: bool} 合并（非 bool 回退默认 false）----
    en = section.get("energy")
    if isinstance(en, Mapping):
        if "enabled" in en and _is_bool(en["enabled"]):
            out["energy"] = {"enabled": en["enabled"]}

    # ---- king_event：enabled(bool)/window_daily(非负 int)/chance(数字) 逐键合并 ----
    ke = section.get("king_event")
    if isinstance(ke, Mapping):
        merged_ke: Dict[str, object] = dict(cast(Mapping[str, object], out["king_event"]))
        if "enabled" in ke and _is_bool(ke["enabled"]):
            merged_ke["enabled"] = ke["enabled"]
        if "window_daily" in ke and _is_nonneg_int(ke["window_daily"]):
            merged_ke["window_daily"] = ke["window_daily"]
        if "chance" in ke and _is_number(ke["chance"]):
            merged_ke["chance"] = ke["chance"]
        out["king_event"] = merged_ke

    return out


__all__ = [
    # 常量 / 默认值
    "MODE_VALUES",
    "DEFAULT_FISHING_SETTINGS",
    "FISHING_SETTINGS_KEYS",
    # 字段定义
    "FISHING_SETTINGS_FIELD_DEFS",
    "fishing_settings_meta",
    # 读段归一
    "fishing_cfg",
]
