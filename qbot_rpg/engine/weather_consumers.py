"""天气消费方联动纯模块 —— M3 批次2·路H（M39 天气消费方联动）。

依据：细化_2a4b_天气引擎.md（§4 权重修正：4.3 采集 weather_mods R25 / 4.4 战斗
      combat.weather_mult R26 / §5 [天气:X]）
      + 细化_2a1d_地图字段扩展.md（§一 gather_points weather_mods 字段 GP-08~GP-11 /
        §三 lore.condition LC-01~LC-04）
      + m3_shared_contract §6.1（核心规则：消费方联动）/ §八 铁律（8 每功能可追溯）。

本文件 = M39 消费方联动装配的纯函数集：
  apply_weather_mods(base_rate, rarity, weather_mods, current_weather) -> (rate, rarity)
      采集点天气修正：rate_mult 乘出率（0=不出）+ rarity_shift 平移档位（clamp 4 档）
  combat_weather_mult(combat_cfg, current_weather) -> float
      战斗天气倍率：默认关 → 1.0；开启取 mults[天气]（缺省 1.0）；不改伤害公式本体
  lore_visible(lore_condition, current_weather, ctx) -> bool
      图鉴 lore/codex condition 按当前图天气判定（缺省显示 True）

【工程补白】（定稿/契约未显式定义处，显式标注供审查）：
  1. weather_mods 归一：2a1d GP-08 配置形态为列表 [{weather, rate_mult, rarity_shift}]；
     本函数按签名接受「归一 dict」{天气: {"rate_mult":…, "rarity_shift":…}}，同时兼容
     列表形态（收口可不做转换直接传配置原文）。归一规则：rate_mult 缺省 1、
     rarity_shift 缺省 0、0 = 该天气不出（返回 rate 0）。
  2. 稀有度档位 clamp 4 档：normal / rare / gold / awakened（✨觉醒）——2a1d GP-11
     定稿写「普通/稀有/金色/✨觉醒」中文，未拍死第四档机器键，本模块取 "awakened"
     为补白落值（如需改用包内既有键由收口对齐 items 侧材料稀有度体系）。未知 base
     rarity（不在档位表）→ 原值返回（fail-safe 不平移不报错）。
  3. combat.weather_mult 配置形态（2a4b §4.4）：{enabled: bool, mults: {天气: 倍率}}；
     默认关（enabled 缺省 false，契约 §6.1 R26「默认关，respect 战斗数值层」）。
     本函数只返回倍率供战斗侧每回合开始相乘，不触碰 formula 伤害公式本体
     （2a4b R26 L230）。mults 值非正数（0/负）视为坏配置 → 1.0（fail-safe）。
  4. lore_visible：lore_condition 为 None/空 = 缺省显示 True（LC-01 原语义不变）；
     非空单原语 dict 或多条件 list（LC-C AND）逐项经 eval_condition 判定；求值失败
     默认不满足（LC-D，不崩不报错）。ctx 优先取上下文天气源（worldtime+map_id /
     weather_now 直接值）；current_weather 参数在 ctx 无天气源时兜底注入（工程补白：
     图鉴渲染侧已取当前图天气时可直接传参）。
  5. 公式接线：weather_mods 应用 / combat 倍率相乘 / lore 显示判定的**实际接线**由
     收口在采集结算、战斗每回合开始、图鉴详情渲染点接入本模块函数——本路仅提供
     纯函数装配，零新增机制（契约 §八 铁律 7 消费方零新增机制）。

铁律：零 NoneBot import（契约 §八 4）；纯函数无 IO（同刻同参必同值）。
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple, Union

from qbot_rpg.engine.weather_conditions import eval_condition

__all__ = [
    "RARITY_TIERS",
    "apply_weather_mods",
    "combat_weather_mult",
    "lore_visible",
]

# 稀有度档位（2a1d GP-11：普通/稀有/金色/✨觉醒 clamp 4 档；"awakened" 为工程补白机器键）
RARITY_TIERS: tuple = ("normal", "rare", "gold", "awakened")


# -------------------------------------------------------------------------------------
# 采集点天气修正（2a4b R25 / 2a1d GP-08~GP-11）
# -------------------------------------------------------------------------------------
def _entry(cfg: Mapping[str, Any]) -> dict:
    """weather_mods 单条目 → 归一 {rate_mult: float, rarity_shift: int}（缺省 1/0）。"""
    rm = cfg.get("rate_mult", 1)
    rs = cfg.get("rarity_shift", 0)
    try:
        rate_mult = float(rm)
    except (TypeError, ValueError):
        rate_mult = 1.0
    try:
        rarity_shift = int(rs)
    except (TypeError, ValueError):
        rarity_shift = 0
    return {"rate_mult": rate_mult, "rarity_shift": rarity_shift}


def _normalize_weather_mods(weather_mods: object) -> dict:
    """weather_mods 归一 → {天气: {"rate_mult", "rarity_shift"}}。

    兼容 dict 形态 {天气: {...}} 与列表形态（2a1d GP-08 [{weather, rate_mult,
    rarity_shift}]）；空/None/坏条目 → 空 dict（不联动）。
    """
    out: dict = {}
    if isinstance(weather_mods, Mapping):
        for key, val in weather_mods.items():
            if isinstance(key, str) and isinstance(val, Mapping):
                out[key] = _entry(val)
    elif isinstance(weather_mods, (list, tuple)):
        for it in weather_mods:
            if not isinstance(it, Mapping):
                continue
            key = it.get("weather")
            if isinstance(key, str) and key:
                out[key] = _entry(it)
    return out


def apply_weather_mods(
    base_rate: float,
    rarity: str,
    weather_mods: object,
    current_weather: object,
) -> Tuple[float, str]:
    """采集点天气修正（2a4b R25）：返回 (rate, rarity)。

    - weather_mods[当前天气] 命中：rate = base_rate × rate_mult（rate_mult 0 = 该天气
      不出，返回 rate 0）；rarity 按 rarity_shift 平移档位并 clamp 4 档
      （normal/rare/gold/awakened）。
    - 当前天气无配置 / weather_mods 空 / current_weather 缺省：返回 (base_rate, rarity)
      原值（2a1d GP-08 不联动，向后兼容）。
    - 未知 base rarity（不在档位表）→ rarity 原值返回（fail-safe 不平移不报错）。
    """
    rate = float(base_rate)
    rarity_out = rarity
    if not isinstance(current_weather, str) or not current_weather:
        return rate, rarity_out
    entry = _normalize_weather_mods(weather_mods).get(current_weather)
    if entry is None:
        return rate, rarity_out
    rate = rate * entry["rate_mult"]
    shift = entry["rarity_shift"]
    if shift != 0:
        rarity_out = _shift_rarity(rarity, shift)
    return rate, rarity_out


def _shift_rarity(rarity: str, shift: int) -> str:
    """稀有度档位平移 + clamp 4 档；未知档位 → 原值返回（fail-safe）。"""
    try:
        idx = RARITY_TIERS.index(rarity)
    except ValueError:
        return rarity
    idx = max(0, min(len(RARITY_TIERS) - 1, idx + int(shift)))
    return RARITY_TIERS[idx]


# -------------------------------------------------------------------------------------
# 战斗天气倍率（2a4b R26：默认关；不改 formula 本体）
# -------------------------------------------------------------------------------------
def combat_weather_mult(combat_cfg: object, current_weather: object) -> float:
    """战斗天气倍率（2a4b R26）：默认关 → 1.0；开启取 mults[天气]（缺省 1.0）。

    combat_cfg: combat 段 dict，形态 {weather_mult: {enabled: bool, mults: {天气: 倍率}}}
                （2a4b §4.4）；None/空/缺 weather_mult / enabled 非 true → 1.0（默认关）。
    current_weather: 当前图当前天气键（IF04）；缺省/非字符串 → 1.0。
    返回 float 倍率；本函数不改伤害公式，供战斗侧每回合开始读取天气后相乘
    （2a4b L228-230）。mults 值非正数（0/负）或非数值 → 1.0（fail-safe 坏配置）。
    """
    if not isinstance(combat_cfg, Mapping):
        return 1.0
    wm = combat_cfg.get("weather_mult")
    if not isinstance(wm, Mapping):
        return 1.0
    enabled = wm.get("enabled", False)
    if not isinstance(enabled, bool) or not enabled:
        return 1.0
    if not isinstance(current_weather, str) or not current_weather:
        return 1.0
    mults = wm.get("mults")
    if not isinstance(mults, Mapping):
        return 1.0
    v = mults.get(current_weather, 1.0)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 1.0
    if f <= 0:
        return 1.0  # 倍率须为正数；0/负 = 坏配置 → fail-safe 1.0
    return f


# -------------------------------------------------------------------------------------
# 图鉴 lore/codex 显示判定（2a1d §三 LC-01~LC-04 / 2a4b §5 [天气:X]）
# -------------------------------------------------------------------------------------
def lore_visible(
    lore_condition: object,
    current_weather: object,
    ctx: Optional[Mapping[str, Any]],
) -> bool:
    """图鉴 lore/codex 条目显示判定：缺省（无 condition）→ True。

    lore_condition: 单原语 dict {var,op,param} 或列表（多条件 AND，2a1d LC-C）或
                    None/空（LC-01 原语义不变，缺省显示 True）。
    current_weather: 当前图天气键（字符串；ctx 未显式提供天气时注入求值上下文）。
    ctx: 求值上下文（weather_conditions.eval_condition；可为 None）。
         天气源优先级：ctx["weather_now"] 显式键 > current_weather 参数（调用方已取好的
         当前图天气）> ctx worldtime+map_id 兜底。
    返回：无 condition → True；求值全部满足 → True；任一不满足 / 求值失败 / 坏配置
          → False（LC-D fail-safe，不崩不报错）。
    """
    if not lore_condition:
        return True
    ev_ctx: dict = dict(ctx) if isinstance(ctx, Mapping) else {}
    if isinstance(current_weather, str) and current_weather and "weather_now" not in ev_ctx:
        ev_ctx["weather_now"] = current_weather  # 兜底注入（ctx 显式天气源优先）
    if isinstance(lore_condition, Mapping):
        return bool(eval_condition(lore_condition, ev_ctx))
    if isinstance(lore_condition, (list, tuple)):
        if not lore_condition:
            return True
        for c in lore_condition:
            if not isinstance(c, Mapping) or not eval_condition(c, ev_ctx):
                return False
        return True
    return False  # 非 dict/列表形态 = 坏配置 → 不显示（LC-D）
