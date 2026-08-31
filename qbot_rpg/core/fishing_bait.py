"""M10 批1·路1A：鱼饵体系核心（bait_lookup / 对口饵判定 / 饵加成读取 / 无饵保底消耗）。

文件名：qbot_rpg/core/fishing_bait.py
创建时间：2026-08-31
作者：Hermes 子agent-1A（M10 钓鱼实现组批1·路1A：鱼饵体系；兄弟路1B 独占
      core/fishing.py 流程状态机，本文件零 import 之）

功能描述（T04 鱼饵体系）：
  - bait_ids_of(cfg) -> list：读 settings.fishing.bait_ids（缺省 5 档默认值兜底）。
  - is_bait(ctx, item_id) -> bool：item 是否在 bait_ids 档内（通用饵判定）。
  - is_preferred_bait(species, item_id) -> bool：对口饵判定（item ∈ species.preferred_bait）。
  - bait_bonus_of(cfg) -> {rare:int, gold:int}：读 settings.fishing.bait_bonus
    （缺省 {rare:8, gold:2}）。本路只做读取与判定，不做概率计算——对口饵加成作用于
    收杆 roll 概率由批2 路2C 消费（契约要点）。
  - bait_available(ctx, qid) -> bool：玩家是否持有任一档饵（背包计数 >0）。
  - consume_bait(ctx, qid) -> dict：扣 1 饵 → {ok, used, had_bait}；无饵保底不卡死
    （定稿 L16 铁律：可无饵抛竿仅不吃对口饵加成）——背包无任何 bait_ids 内条目 →
    had_bait=False 且不扣饵，仍 ok=True。

背包读取契约（M9 已注 _inventory_hooks）：
  - ctx["inventory"]：{item_id: count} 计数映射（兜底）。
  - ctx["count_item"](item_id) -> int：持有计数 hook（优先）。
  - ctx["remove_item"](item_id, count) -> bool：扣减 hook（优先）；返回 False = 扣减失败。

依据：细化_2c1a §1.2（F-12 preferred_bait 引用 bait_ids）/ §五（V3 双向引用）
      + 定稿 §1 M2（鱼饵 L16：无饵保底不卡死；L96：1 次=1 饵）
      + docs/m10_shared_contract.md §一（settings.fishing bait_ids/bait_bonus 默认值）
模式参考：
  - qbot_rpg/core/fishing_settings.py（fishing_cfg 三态容错 + DEFAULT_FISHING_SETTINGS）
  - qbot_rpg/core/quest.py _count_item/_remove_item（hook 优先 + inventory 兜底形态）

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查）：
  F-1  饵条目/配方素材与金币数值自拟合理值（items.json 5 档饵条目 type=consumable，
       recipe.json 5 条 rcp_bait_* 配方 kind=craft，materials 用既有 moon_grass/
       star_iron/ghost_moss/ore/ash_core/fire_dragon_scale，cost.coins 小额）——
       定稿只定饵档位/加成，未给配方投入明细，本路按对齐既有 recipe 形态补白。
  F-2  consume_bait 择饵序：按 settings.fishing.bait_ids 档序取玩家持有第一档扣 1
       （对齐兄弟路1B fishing.py _consume_bait 内置最小扣饵同序）。
  F-3  qid 参数：契约定 bait_available(ctx, qid)/consume_bait(ctx, qid) 带玩家标识；
       本路背包读取仍走 ctx（装配层 ctx 已是单玩家作用域），qid 仅作身份冗余参数
       （供批2 装配层若需按 qid 路由时复用，本路不依赖）。

铁律：零 NoneBot import；纯函数确定性（零 IO、零定时器/零睡眠、无随机）；不引入
      实时计时调用；不修改 core/fishing.py（兄弟路1B 独占）与 settings.json/
      loader/field_meta（批0 已收口）；不 git commit。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, cast

from qbot_rpg.core.fishing_settings import DEFAULT_FISHING_SETTINGS, fishing_cfg

# 缺省 5 档饵（定稿 L74 / 契约 §一 bait_ids 默认值）
_DEFAULT_BAIT_IDS: List[str] = [
    "饵_蚯蚓",
    "饵_面团",
    "饵_小鱼",
    "饵_黄金虫",
    "饵_龙涎",
]

# 缺省对口饵加成（定稿 L75 / 契约 §一 bait_bonus 默认值；百分数）
_DEFAULT_BAIT_BONUS: Dict[str, int] = {"rare": 8, "gold": 2}


# =====================================================================================
# 内部：配置读取（复用 fishing_cfg 三态容错 + 默认值兜底）
# =====================================================================================
def _cfg_fishing(cfg: object) -> Mapping[str, object]:
    """cfg 归一为 settings.fishing 段 dict（复用 fishing_cfg 三态容错）。"""
    out = fishing_cfg(cfg)
    return cast(Mapping[str, object], out)


# =====================================================================================
# 饵档位读取 / 判定
# =====================================================================================
def bait_ids_of(cfg: object) -> List[str]:
    """读 settings.fishing.bait_ids（缺省 5 档默认值兜底）。

    入参 cfg：settings 全量 / settings.fishing 段 / ctx（三态容错，fishing_cfg 口径）。
    出参：bait_ids 档序列表（str 元素；非 str 元素过滤；空/缺失 → 5 档默认）。
    """
    section = _cfg_fishing(cfg)
    raw = section.get("bait_ids")
    if isinstance(raw, list):
        cleaned = [x for x in raw if isinstance(x, str) and bool(x.strip())]
        if cleaned:
            return cleaned
    # 从 DEFAULT_FISHING_SETTINGS 取 5 档默认（防拷贝污染常量）
    default = DEFAULT_FISHING_SETTINGS.get("bait_ids")
    if isinstance(default, list):
        return [str(x) for x in default if isinstance(x, str)]
    return list(_DEFAULT_BAIT_IDS)


def is_bait(ctx: Mapping[str, Any], item_id: object) -> bool:
    """item 是否在 settings.fishing.bait_ids 档内（通用饵判定）。

    入参 ctx：含 fishing_cfg（或 settings.fishing）的上下文；item_id：物品 id。
    出参：bool。item_id 非 str / 空 → False（非饵）。
    """
    if not isinstance(item_id, str) or not item_id.strip():
        return False
    return item_id in bait_ids_of(ctx)


def is_preferred_bait(species: object, item_id: object) -> bool:
    """对口饵判定：item_id ∈ species.preferred_bait（细化 2c1a F-12）。

    入参 species：FishDef（有 .preferred_bait 访问器）或 raw dict（含 preferred_bait
    键，list[str]）；item_id：饵 id。出参：bool。
    species 缺失 preferred_bait / 非 str item → False。
    """
    if not isinstance(item_id, str) or not item_id.strip():
        return False
    preferred: object = None
    if isinstance(species, Mapping):
        preferred = species.get("preferred_bait")
    elif species is not None:
        preferred = getattr(species, "preferred_bait", None)
    if isinstance(preferred, (list, tuple)):
        return any(isinstance(x, str) and x == item_id for x in preferred)
    return False


def bait_bonus_of(cfg: object) -> Dict[str, int]:
    """读 settings.fishing.bait_bonus（缺省 {rare:8, gold:2}）。

    出参：{rare: int, gold: int}（非负整数；rare/gold 缺省或非法 → 默认值兜底）。
    本路只读取，不做概率计算（对口饵加成作用于收杆 roll 概率，批2 路2C 消费）。
    """
    section = _cfg_fishing(cfg)
    bonus = section.get("bait_bonus")
    out: Dict[str, int] = {}
    if isinstance(bonus, Mapping):
        for key in ("rare", "gold"):
            v = bonus.get(key)
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                out[key] = v
    if not out:
        return dict(_DEFAULT_BAIT_BONUS)
    return out


# =====================================================================================
# 背包读取（M9 _inventory_hooks 契约：hook 优先 + inventory 计数映射兜底）
# =====================================================================================
def _count_item(ctx: Mapping[str, Any], item_id: str) -> int:
    """持有计数：ctx["count_item"](id) hook 优先；ctx["inventory"] 计数映射兜底。"""
    hook = ctx.get("count_item")
    if callable(hook):
        try:
            return int(hook(item_id))
        except Exception:
            return 0
    inv = ctx.get("inventory")
    if isinstance(inv, Mapping):
        cur = inv.get(item_id, 0)
        if isinstance(cur, int) and not isinstance(cur, bool):
            return cur
        return 0
    return 0


def _remove_item(ctx: MutableMapping[str, Any], item_id: str, count: int) -> bool:
    """扣减：ctx["remove_item"](id, count) hook 优先；inventory 计数映射就地扣减兜底。"""
    hook = ctx.get("remove_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count))
        except Exception:
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        cur = inv.get(item_id, 0)
        if not (isinstance(cur, int) and not isinstance(cur, bool)) or cur < count:
            return False
        inv[item_id] = cur - count
        return True
    return False


# =====================================================================================
# 无饵保底：抛竿时饵池空仍可下钩，仅不吃对口饵加成（定稿 L16 铁律）
# =====================================================================================
def bait_available(ctx: Mapping[str, Any], qid: object) -> bool:
    """玩家是否持有任一档饵（背包计数 >0）。

    入参 ctx：背包上下文（inventory 计数映射 + count_item/remove_item hooks）；
    qid：玩家标识（本路仅身份冗余，装配层 ctx 已是单玩家作用域，【工程补白 F-3】）。
    出参：bool——任一 bait_ids 档内条目计数 >0 → True；全无 → False。
    """
    for bid in bait_ids_of(ctx):
        if _count_item(ctx, bid) > 0:
            return True
    return False


def consume_bait(ctx: MutableMapping[str, Any], qid: object) -> Dict[str, object]:
    """扣 1 饵（定稿 L96：1 次 = 1 饵）→ {ok, used, had_bait}。

    语义（无饵保底不卡死，定稿 L16 铁律）：
      - 背包持有任一 bait_ids 档内条目 → 按档序取持有第一档扣 1：
          {ok: True, used: <饵 id>, had_bait: True}
      - 背包无任何 bait_ids 档内条目 → 不扣饵，仍 ok：
          {ok: True, used: None, had_bait: False}
    出参：
      ok      —— 是否可下钩（无饵保底恒 True，不卡死）
      used    —— 实际消耗的饵 id；had_bait=False 时为 None
      had_bait—— 是否有饵（False = 不吃对口饵加成，仅无饵抛竿）
    """
    for bid in bait_ids_of(ctx):
        if _count_item(ctx, bid) > 0:
            if _remove_item(ctx, bid, 1):
                return {"ok": True, "used": bid, "had_bait": True}
            # 扣减 hook 失败（不足/异常）→ 视为该档无饵，继续尝试后续档
            continue
    return {"ok": True, "used": None, "had_bait": False}


__all__ = [
    "bait_ids_of",
    "is_bait",
    "is_preferred_bait",
    "bait_bonus_of",
    "bait_available",
    "consume_bait",
]
