"""M10 批2·路2C：钓鱼收杆稀有度 roll 概率纯函数（qbot_rpg/core/fishing_roll.py）。

文件名：qbot_rpg/core/fishing_roll.py
创建时间：2026-08-31
作者：Hermes 子agent-2C（M10 钓鱼实现组批2·路2C：/鱼讯 + /收杆 三选一 + roll 概率）

功能描述（T09 / 细化_2c1b §四 4.2 锚点）：
  - roll_rarity(choice, cfg, ctx, rng) -> str：满力/自动 的稀有度 roll，返回
    "normal"/"rare"/"gold" 三档之一（种子 42/2026 可复现，N=100000 分布收敛 ±0.5pp）。
      AUTO           自动收杆（无加成）           权重 70/25/5（基础锚点，定稿 L94）
      FULL·对口饵    满力 + 对口饵（满配）        权重 54/37/9（满配锚点，定稿 L94）
      FULL·无对口饵  满力，无对口饵               权重 60/31/9*（*实现层插值默认，
                                                  位于 settings.fishing.pull_odds 可配键）
  - 权重构成（契约 §四 4.2）：满配权重 = 基础(70/25/5) + 对口饵加成 bait_bonus
    （rare+8/gold+2，定稿 L16）+ 满力收杆加成 rod_full_bonus（rare+4/gold+2，定稿 L76）
    百分数加到基础权重再归一（normal 吸收余量，恒 100）。
  - pull_odds_of(cfg) -> dict：读 settings.fishing.pull_odds 可配键，缺省
    {normal:60, rare:31, gold:9}（FULL 无对口饵插值默认，非定稿值，细化 L159）。
  - has_matching_bait(ctx) -> bool：对口饵判定——本局目标鱼种（fish_state.
    target_species_id）preferred_bait 含玩家持有饵（inventory/count_item hook）。
  - 确定性铁律：rng 必须注入（ctx["rng"] 或参数 rng，种子 42/2026），禁裸 random；
    本模块纯函数零 IO 零定时器/零睡眠。

依据：细化_2c1b §四（4.1 三选一 / 4.2 roll 概率锚点）+ 定稿 §1 M5/§四（L94 概率锚点、
      L16 对口饵加成、L76 满力加成）+ docs/m10_接口摸底.md §九（种子 42/2026 可复现、
      确定性 rng 注入）+ docs/m10_shared_contract.md §一（bait_bonus/rod_full_bonus 默认值）
模式参考：
  - qbot_rpg/core/monster_ai.py _weighted_pick（rng.random()*total 权重归一选一，L484-502）
  - qbot_rpg/core/fishing_bait.py（is_preferred_bait/bait_bonus_of，对口饵语义同源）
  - qbot_rpg/core/fishing_settings.py（fishing_cfg 三态容错 + 默认值兜底）

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查）：
  R-1  pull_odds 键落点：细化 L159「位于 pull_odds 可配置键」未给完整路径——本路取
       settings.fishing.pull_odds（settings 全量 dict 的 fishing 段下，与 bait_bonus/
       rod_full_bonus 同级），缺省 {normal:60, rare:31, gold:9}。fishing_cfg 归一仅
       覆盖 9 个契约键，pull_odds 不在其列——本模块自行从原始段读取并容错（对齐
       fishing_cfg 三态入参 + 逐键类型容错口径）。
  R-2  满配权重归一：契约「百分数加到基础权重再归一」——rare = 25 + bait.rare +
       rod.rare，gold = 5 + bait.gold + rod.gold，normal = 100 - rare - gold 吸收
       余量（恒 100，与 54/37/9 锚点自洽）；负余量 → normal=0 截断（防御，理论不可达）。
  R-3  对口饵判定（本路在指令壳装配前提供引擎层判定）：目标鱼种来自 fish_state.
       target_species_id（批1 B-2 落档）；持有判定走 ctx["count_item"] hook 优先、
       ctx["inventory"] 计数映射兜底（对齐 fishing_bait._count_item 口径）；目标鱼种
       缺失/无 preferred_bait → 视为无对口饵（吃不到 bait_bonus，FULL 回落 pull_odds）。
  R-4  choice 语义：仅 "full" 走满配/插值档；"auto" 及未知（引擎层已拦非法 choice，
       本路防御回落）→ 基础 70/25/5（auto 无任何加成，细化 4.1 自动=基础概率）。

铁律：零 NoneBot import；纯函数确定性（零 IO、零定时器/零睡眠、rng 注入禁裸 random）；
      文件头/文档零 emoji；docstring 勿写字面定时器调用字样（M43 探针，用零定时器/
      零睡眠）；不修改 core/fishing.py / core/fishing_cast.py / commands/fishing_commands.py
      （兄弟路独占）；不 git commit。
"""

from __future__ import annotations

import random
from typing import Any, Dict, Mapping, TypeGuard

from qbot_rpg.core.fishing_bait import is_preferred_bait
from qbot_rpg.core.fishing_settings import fishing_cfg

# =====================================================================================
# 常量：稀有度档位 + 概率锚点（细化_2c1b §4.2 表 + 定稿 L94/L16/L76）
# =====================================================================================

RARITIES: tuple = ("normal", "rare", "gold")

# AUTO 基础权重（定稿 L94 基础锚点 70/25/5，无任何加成）
AUTO_WEIGHTS: Dict[str, int] = {"normal": 70, "rare": 25, "gold": 5}

# FULL·无对口饵 插值默认（细化 L159：*实现层插值默认，位于 pull_odds 可配键，非定稿值）
DEFAULT_FULL_ODDS: Dict[str, int] = {"normal": 60, "rare": 31, "gold": 9}

# 缺省满力收杆加成（契约 §一 rod_full_bonus 默认值，百分数）
_DEFAULT_ROD_BONUS: Dict[str, int] = {"rare": 4, "gold": 2}


# =====================================================================================
# 工具：类型归一 + 配置读取（复用 fishing_cfg 三态容错 + 逐键类型兜底）
# =====================================================================================
def _is_nonneg_int(v: object) -> TypeGuard[int]:
    """非负 int 判定（排除 bool——bool 是 int 子类；TypeGuard 供 mypy 窄化）。"""
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _bonus_of(cfg: object, key: str, default: Dict[str, int]) -> Dict[str, int]:
    """读 settings.fishing.<key> 加成 dict（rare/gold 非负 int，缺省/非法 → default）。

    入参 cfg：settings 全量 / settings.fishing 段 / ctx（三态容错，fishing_cfg 口径）。
    出参：{rare: int, gold: int}。逐键类型容错——显式非负 int 覆盖，其余保留 default。
    """
    section = fishing_cfg(cfg)
    raw = section.get(key)
    out: Dict[str, int] = dict(default)
    if isinstance(raw, Mapping):
        for k in ("rare", "gold"):
            v = raw.get(k)
            if _is_nonneg_int(v):
                out[k] = v
    return out


def bait_bonus_of(cfg: object) -> Dict[str, int]:
    """对口饵加成（契约 §一 bait_bonus 默认 {rare:8, gold:2}；零加成可配 {0,0}）。"""
    return _bonus_of(cfg, "bait_bonus", {"rare": 8, "gold": 2})


def rod_full_bonus_of(cfg: object) -> Dict[str, int]:
    """满力收杆 roll 加成（契约 §一 rod_full_bonus 默认 {rare:4, gold:2}；0=无加成）。"""
    return _bonus_of(cfg, "rod_full_bonus", _DEFAULT_ROD_BONUS)


def pull_odds_of(cfg: object) -> Dict[str, int]:
    """FULL 无对口饵权重（细化 L159 pull_odds 可配键；缺省 60/31/9 插值默认）。

    读 settings.fishing.pull_odds（{normal/rare/gold: 非负 int}）；逐键容错——缺省键/
    非法类型保留默认；无此键/非 Mapping → 全默认。返回副本防污染常量。
    【修复 R-1b】pull_odds 不在 fishing_cfg 9 契约键内（fishing_cfg 归一会丢弃），
    本函数直接从原始段提取（与 fishing_cfg 三态入参同构，防可配键失效）。
    """
    out: Dict[str, int] = dict(DEFAULT_FULL_ODDS)
    raw = cfg
    # ctx 形态解包（同 fishing_cfg：含 settings 键 → 解包）
    if isinstance(raw, Mapping) and isinstance(raw.get("settings"), Mapping):
        raw = raw["settings"]
    if not isinstance(raw, Mapping):
        return out
    # ① 含 "fishing" 键 → settings 全量取段；段非对象 → 默认
    if "fishing" in raw:
        fishing = raw["fishing"]
        if not isinstance(fishing, Mapping):
            return out
        section: Mapping[str, object] = fishing
    else:
        # ② 无 "fishing" 键 → 视为 settings.fishing 段本身
        section = raw
    raw_odds = section.get("pull_odds")
    if isinstance(raw_odds, Mapping):
        for k in ("normal", "rare", "gold"):
            v = raw_odds.get(k)
            if _is_nonneg_int(v):
                out[k] = v
    return out


# =====================================================================================
# 权重计算（纯函数，确定性）
# =====================================================================================
def _full_weights(cfg: object, matching: bool) -> Dict[str, int]:
    """满力档权重：对口饵 → 满配（基础+双加成归一）；无对口饵 → pull_odds 插值默认。"""
    if not matching:
        return pull_odds_of(cfg)
    base = AUTO_WEIGHTS
    bait = bait_bonus_of(cfg)
    rod = rod_full_bonus_of(cfg)
    rare = base["rare"] + bait["rare"] + rod["rare"]
    gold = base["gold"] + bait["gold"] + rod["gold"]
    normal = max(0, 100 - rare - gold)  # normal 吸收余量恒 100（R-2）
    return {"normal": normal, "rare": rare, "gold": gold}


def roll_weights(choice: object, cfg: object, ctx: Mapping[str, Any]) -> Dict[str, int]:
    """按 choice 归一权重（AUTO 基础 / FULL 满配或插值）。纯函数零副作用。

    入参 choice："auto" → 基础 70/25/5；"full" → 对口饵判定后满配或 pull_odds；
    其余（防御）→ 基础（引擎层已拦非法 choice，R-4）。出参：{normal, rare, gold}。
    """
    if choice == "full":
        return _full_weights(cfg, has_matching_bait(ctx))
    return dict(AUTO_WEIGHTS)


# =====================================================================================
# 对口饵判定（引擎层，供 roll 权重与指令壳复用）
# =====================================================================================
def _held_count(ctx: Mapping[str, Any], item_id: str) -> int:
    """玩家持有计数：ctx["count_item"](id) hook 优先；ctx["inventory"] 计数映射兜底。"""
    hook = ctx.get("count_item")
    if callable(hook):
        try:
            return int(hook(item_id))
        except Exception:
            return 0
    inv = ctx.get("inventory")
    if isinstance(inv, Mapping):
        cur = inv.get(item_id, 0)
        return cur if isinstance(cur, int) and not isinstance(cur, bool) else 0
    return 0


def _target_species_of(ctx: Mapping[str, Any]) -> object:
    """本局目标鱼种（raw dict / FishDef）：fish_state.target_species_id → 池内查找。

    查找源：ctx["fish_table"]（Def→raw dict 映射，装配注入形态）→ ctx["fishing"]
    ["species"]（raw list）→ ctx["fish_table"] 缺省时构造器 species（经 ctx["species"]
    兼容）。目标 id 缺失/未找到 → None。
    """
    fs = ctx.get("fish_state")
    if not isinstance(fs, Mapping):
        return None
    target_id = fs.get("target_species_id")
    if not isinstance(target_id, str) or not target_id.strip():
        return None
    ft = ctx.get("fish_table")
    if isinstance(ft, Mapping):
        entry = ft.get(target_id)
        if entry is not None:
            return entry
    fishing = ctx.get("fishing")
    if isinstance(fishing, Mapping):
        species = fishing.get("species")
        if isinstance(species, list):
            for s in species:
                if isinstance(s, Mapping) and s.get("id") == target_id:
                    return s
    pool = ctx.get("species")
    if isinstance(pool, (list, tuple)):
        for s in pool:
            if isinstance(s, Mapping) and s.get("id") == target_id:
                return s
    return None


def _preferred_bait_of(species: object) -> tuple:
    """目标鱼种 preferred_bait（tuple[str, ...]）；缺失/非 list → 空元组。"""
    if isinstance(species, Mapping):
        raw = species.get("preferred_bait")
        return tuple(x for x in raw if isinstance(x, str)) if isinstance(raw, (list, tuple)) else ()
    return tuple(getattr(species, "preferred_bait", ()) or ())


def has_matching_bait(ctx: Mapping[str, Any]) -> bool:
    """对口饵判定（R-3）：目标鱼种 preferred_bait 含玩家持有饵 → True。

    目标鱼种缺失 / 无 preferred_bait / 目标鱼种不在池 → False（吃不到 bait_bonus）。
    纯函数确定性：持有判定走 count_item hook / inventory 映射，零 IO。
    """
    species = _target_species_of(ctx)
    if species is None:
        return False
    preferred = _preferred_bait_of(species)
    if not preferred:
        return False
    return any(is_preferred_bait(species, bid) and _held_count(ctx, bid) > 0 for bid in preferred)


# =====================================================================================
# rng 解析 + 权重归一选一（确定性；禁裸 random）
# =====================================================================================
def _resolve_rng(rng: Any, ctx: Mapping[str, Any]) -> Any:
    """rng 注入单源：参数 rng 优先 → ctx["rng"] → 兜底 random 模块（测试一律注入）。

    对齐 fishing._resolve_rng / shop._rng 惯例；生产装配层注入 ctx["rng"]（种子化）。
    """
    if rng is not None:
        return rng
    r = ctx.get("rng")
    if r is not None:
        return r
    return random


def _weighted_pick(weights: Mapping[str, int], rng: Any) -> str:
    """按权重归一选一（monster_ai._weighted_pick 同构，L484-502）：rng.random()*total。

    返回 rarity 档；全 0 权重 / total<=0 → 保守回落 normal（防御不炸）。确定性由注入
    rng 保证（同 rng 同调用序同结果）。
    """
    total = sum(weights.values())
    if total <= 0:
        return "normal"
    r = float(rng.random()) * total
    acc = 0.0
    for k in RARITIES:
        acc += float(weights.get(k, 0))
        if r <= acc:
            return str(k)
    return "gold"


# =====================================================================================
# 对外主入口
# =====================================================================================
def roll_rarity(choice: object, cfg: object, ctx: Mapping[str, Any], rng: Any = None) -> str:
    """收杆稀有度 roll（T09 / 细化 §4.2）：满力/自动 → "normal"/"rare"/"gold"。

    入参：
      choice —— "full"（满力）/ "auto"（自动）；其余防御回落 auto（引擎层已拦非法）。
      cfg    —— settings 全量 / settings.fishing 段 / ctx（fishing_cfg 三态容错）。
      ctx    —— 含 fish_state（目标鱼种）/ fish_table 或 fishing（鱼种池）/
                inventory 或 count_item（持有判定）/ rng（确定性源）。
      rng    —— 注入 rng（Random 实例，种子 42/2026）；None → ctx["rng"] → random 兜底。
    出参：rarity 档位字符串（normal/rare/gold）。

    确定性：同 seed 同 cfg 同 ctx 同调用序 → 恒同结果（种子 42/2026 下 N=100000
    分布收敛 ±0.5pp，TC-15/16）。
    """
    weights = roll_weights(choice, cfg, ctx)
    return _weighted_pick(weights, _resolve_rng(rng, ctx))


__all__ = [
    # 常量
    "RARITIES",
    "AUTO_WEIGHTS",
    "DEFAULT_FULL_ODDS",
    # 配置读取
    "bait_bonus_of",
    "rod_full_bonus_of",
    "pull_odds_of",
    # 权重/判定/主入口
    "roll_weights",
    "has_matching_bait",
    "roll_rarity",
]
