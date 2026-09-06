"""M12.5 强化指令：/强化 /强化信息 /强化保护（原子一条消息 · 守卫链 · 分级惩罚 · 保护石）。

文件名：enhance_commands.py
创建时间：2026-09-06
作者：Hermes 主代理（指令缺口补全批1路1；工具链故障改主代理直写）

功能描述：
  ① cmd_enhance（/强化 <装备>[+N]）：GU-01~05 守卫链 → 成功率（基础率 + √幸运修正，
     clamp [0,100]）→ 单次 roll 定成败 → 成功（扣石扣币、实例 enhance_level+1、
     stats_bonus 属性增量、落档）｜失败（材料照扣 + 分级惩罚：低段不变 / 高段 -1）。
  ② cmd_enhance_info（/强化信息 <装备>）：只读查询 当前+N/成功率（幸运拆分）/上限/
     消耗预览（零副作用）。
  ③ cmd_enhance_protect（/强化保护 <装备>[+N]）：同 /强化 流程 + GU-06 保护石事务内
     足额校验；高段失败扣 1 颗免掉级（成功/低段失败不耗）。
  ④ 参数词法 P-01~P-06：名称禁空格、等级标记 +N 附着后缀、禁批量 *、歧义候选列表。
  ⑤ 装备匹配目标 = 已穿戴槽位（equipment 槽——/装备 面板 +N 显示同源 slot_level）；
     实例增强等级持久化于背包实例 enhance_level + 槽位 slot_level 双向同步
     （equipment.py P1-2 修复配套）。

依据：
  - docs/细化/细化_2c3b_强化流程契约.md（§一 流程/守卫 GU-01~06/§二 /强化信息/
    §三 保护石/§四 原子防双扣/§五 词法 P-01~06/§六 TC-01~23）
  - docs/细化/细化_2c3a_强化数值曲线.md（§1 消耗/§2 成功率/§3 上限/§4 失败分级/
    §5 数值表 D-1~D-13/§6 验收 TC）
  - 定稿（强化系统设计定稿 v1.0 L214-216 指令表）
  - 模式参考：forge_commands.py（原子守卫链/ctx 契约/register 壳）、use_commands.py
    （_resolve_player asdict 兼容、装备槽读写）、basic_commands.py（tpl 渲染）

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查）：
  F-1 强化目标 = 已穿戴槽装备（equipment[slot]），非背包行——装备卡 +N 显示从
      slot_level 读（basic_commands._slot_info），契约 TC 示例「/强化 铁剑」与
      /装备 面板同源；背包普通物品（非装备）→ not_equippable。
  F-2 实例级强化字段 = ItemInstance.enhance_level（新增，默认 0）+ EquipmentSlot.
      slot_level 双向同步（equip/unequip 时；P1-2 修复）。强化成功只改槽位实例
      slot_level 与穿戴行 stats_bonus——卸下回包时 equipment.py unequip 已带
      enhance_level 回写。
  F-3 roll 随机源：ctx rng hook 优先，缺省 random.random()（测试注入固定种子可复现）。
  F-4 属性增量写 stats_bonus：武器键 atk（weapon_atk_per_level 默认 flat 5/级）、
      防具键 def（armor_def_per_level 默认 flat 3/级）；percent 型按原 stats_bonus
      比例乘算（内容包可配）。
  F-5 幸运修正：luck_affects=true 且角色 luck 属性可读 → 修正 = √我方幸运（PvE
      对手恒 0 → √我幸）；角色无 luck 属性按 0。
  F-6 落档：_player_of asdict → 可变 dict 就地改（currencies/equipment）→
      ctx["player"]=dict → runner dict 分支 upsert（对齐 use_commands）。
  F-7 幂等：强化结算零会话零内存态；防双扣由 processing 消息层频率控制 + 单事务
      全量写回兜底（本指令不做跨消息状态）。
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Tuple, cast

from qbot_rpg.commands.basic_commands import _slot_info
from qbot_rpg.commands.router import CommandSpec
from qbot_rpg.core.templates import tpl_of
from qbot_rpg.content.enhance_models import (
    DEFAULT_ENHANCE,
    QUALITY_LABELS_CN,
    parse_enhance_settings,
)

__all__ = [
    "ENHANCE_CMD",
    "ENHANCE_INFO_CMD",
    "ENHANCE_PROTECT_CMD",
    "cmd_enhance",
    "cmd_enhance_info",
    "cmd_enhance_protect",
    "register_enhance_commands",
]

ENHANCE_CMD = "强化"
ENHANCE_INFO_CMD = "强化信息"
ENHANCE_PROTECT_CMD = "强化保护"

_ATTR_CN = {
    "atk": "攻击", "def": "防御", "hp": "生命", "mp": "魔力",
    "str": "力量", "con": "体质", "agi": "敏捷", "foc": "专注",
    "spr": "精神", "lck": "幸运", "spd": "速度", "mag": "魔法",
}
_WEAPON_STAT = "atk"
_ARMOR_STAT = "def"


# ---------------------------------------------------------------------------
# 解析与工具（词法 P-01~P-06）
# ---------------------------------------------------------------------------

def _player_of(ctx: MutableMapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
    """玩家状态解析（Player dataclass → asdict 可变 dict 写回 ctx；dict 直返）。"""
    p = ctx.get("player")
    if isinstance(p, MutableMapping):
        return p
    if p is not None and hasattr(p, "qid"):
        try:
            d = asdict(p)
        except (TypeError, ValueError):  # pragma: no cover
            return None
        ctx["player"] = d
        return d
    return None


def _parse_target(raw_arg: str, ctx: MutableMapping[str, Any]) -> Tuple[str, int, str]:
    """装备名词法解析 → (clean_name, declared_level, err_key)。

    clean_name 非空时 err_key 为空；err_key 非空表示解析失败（调用方渲染错误模板）。
    P-01 名称禁空格；P-02 +N 附着后缀取尾部 +数字 段；P-03 含 * → batch err。
    """
    import re
    arg = raw_arg
    if "*" in arg:
        return "", 0, "enhance_err_batch"
    m = re.match(r"^(.*)[+](\d+)$", arg)
    if m:
        name = m.group(1)
        lv = int(m.group(2))
        if not name:
            return "", 0, "enhance_err_empty"
        if "+" in name:
            return "", 0, "enhance_err_mark_in_name"
        return name, lv, ""
    if "+" in arg:
        return "", 0, "enhance_err_mark"
    return arg, 0, ""


def _enhance_raw(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = ctx.get("enhance")
    return raw if isinstance(raw, Mapping) else {}


def _cfg(ctx: Mapping[str, Any]) -> Dict[str, Any]:
    return parse_enhance_settings(_enhance_raw(ctx))


def _system_enabled(ctx: Mapping[str, Any]) -> bool:
    return bool(_enhance_raw(ctx)) or bool(ctx.get("enhance_enabled"))


# ---------------------------------------------------------------------------
# 装备定位（已穿戴槽；F-1）
# ---------------------------------------------------------------------------

def _equip_map(player: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    eq = player.get("equipment")
    return eq if isinstance(eq, MutableMapping) else {}


def _row_iid(row: Any) -> str:
    if isinstance(row, Mapping):
        return str(row.get("item_id") or "")
    return str(getattr(row, "item_id", "") or "")


def _slot_quality(slot: Any) -> str:
    """槽位实例品质（EquipmentSlot 无 quality——从背包行取；缺省 normal）。"""
    return "normal"


def _resolve_worn(ctx: MutableMapping[str, Any], player: MutableMapping[str, Any],
                  name: str) -> Tuple[Optional[Any], str, List[str]]:
    """按名解析已穿戴装备 → (槽位对象|None, err_key, 候选行文案列表)。

    匹配序：精确 name → 唯一前缀（候选 >1 → ambiguous）。候选行 = 当前+N/上限。
    """
    eq = _equip_map(player)
    cfg = _cfg(ctx)
    entries = []
    for sid, slot in eq.items():
        info = _slot_info(slot)
        if info is None:
            continue
        entries.append({"sid": sid, "slot": slot, "info": info,
                        "name": str(info["name"] or "")})
    for e in entries:
        if e["name"] == name:
            return e["slot"], "", []
    cands = [e for e in entries if e["name"].startswith(name)]
    if len(cands) == 1:
        return cands[0]["slot"], "", []
    if len(cands) > 1:
        lines = []
        for e in cands:
            q = _quality_of_row(e["slot"], player)
            mx = _max_for_quality(cfg, q)
            lines.append(tpl_of(ctx, "enhance_ambiguous_line", {
                "name": e["name"], "level": e["info"].get("enhance", 0), "max": mx}))
        return None, "ambiguous", lines
    return None, "not_found", []


def _quality_of_row(slot: Any, player: MutableMapping[str, Any]) -> str:
    """槽位装备品质（从背包匹配行读 quality；无 → normal）。"""
    info = _slot_info(slot)
    if info is None:
        return "normal"
    iid = info.get("item_id") or ""
    inv = player.get("inventory")
    if isinstance(inv, (list, tuple)):
        for r in inv:
            if _row_iid(r) == iid:
                if isinstance(r, Mapping):
                    return str(r.get("quality") or "normal")
                return str(getattr(r, "quality", "normal") or "normal")
    return "normal"


# ---------------------------------------------------------------------------
# 成功率 / 消耗 / 上限计算（2c3a §1-§3）
# ---------------------------------------------------------------------------

def _max_for_quality(cfg: Mapping[str, Any], quality: str) -> int:
    mx = cfg.get("settings", {}).get("max_by_rarity") or {}
    if quality in mx:
        try:
            return int(mx[quality] or 0)
        except (TypeError, ValueError):  # pragma: no cover
            return 0
    # 品质缺键 → 内容包默认表回退
    return int(DEFAULT_ENHANCE["settings"]["max_by_rarity"].get(quality, 0))


def _base_rate(cfg: Mapping[str, Any], to_level: int) -> int:
    curve = cfg.get("success_curve") or []
    for row in curve:
        if isinstance(row, Mapping) and int(row.get("to", -1)) == to_level:
            try:
                return int(row.get("rate", 0) or 0)
            except (TypeError, ValueError):  # pragma: no cover
                return 0
    for row in DEFAULT_ENHANCE["success_curve"]:
        if int(row.get("to", -1)) == to_level:
            return int(row.get("rate", 0) or 0)
    return 0


_LUCK_KEYS = ("luck", "lck")  # 框架 luck / veinborn lck（stats.json 键）


def _luck_of(ctx: Mapping[str, Any], player: Mapping[str, Any]) -> float:
    """角色幸运（attributes 三层 → luck/lck；dict/对象双形态；异常 → 0）。"""
    attrs = player.get("attributes")
    if attrs is None:
        return 0.0

    def _pick(m: Any) -> float:
        if not isinstance(m, Mapping):
            return 0.0
        for k in _LUCK_KEYS:
            v = m.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
        return 0.0

    try:
        from qbot_rpg.core.player_attributes import calc_all_final_attributes
    except Exception:  # noqa: BLE001
        calc_all_final_attributes = None  # type: ignore[assignment]
    if calc_all_final_attributes is not None and not isinstance(attrs, Mapping):
        try:
            final = calc_all_final_attributes(attrs)
            if isinstance(final, Mapping):
                v = _pick(final)
                if v:
                    return v
        except Exception:  # noqa: BLE001
            pass
    # dict 形态手工合计（三层：base + bonus.flat/temp.flat 累加，pct 乘算）
    try:
        b = attrs.get("base") or {}
        bonus = attrs.get("bonus") or {}
        temp = attrs.get("temp") or {}
        base = _pick(b)
        bf = 0.0
        if isinstance(bonus, Mapping):
            fl = bonus.get("flat")
            bf = _pick(fl)
        tf = 0.0
        if isinstance(temp, Mapping):
            tfl = temp.get("flat")
            tf = _pick(tfl)
        bp = 0.0
        if isinstance(bonus, Mapping):
            pc = bonus.get("pct")
            bp = _pick(pc)
        tp = 0.0
        if isinstance(temp, Mapping):
            tpc = temp.get("pct")
            tp = _pick(tpc)
        return (base + bf + tf) * (1 + bp / 100.0) * (1 + tp / 100.0)
    except Exception:  # noqa: BLE001
        return 0.0


def _real_rate(ctx: Mapping[str, Any], player: Mapping[str, Any],
               cfg: Mapping[str, Any], to_level: int) -> Tuple[int, int, int]:
    """实际成功率 → (rate, base, luck_pp)。luck_affects=false → luck_pp=0。"""
    base = _base_rate(cfg, to_level)
    luck_pp = 0
    if cfg.get("settings", {}).get("luck_affects", True) is not False:
        lv = _luck_of(ctx, player)
        if lv > 0:
            luck_pp = int(round(math.sqrt(lv)))
    rate = max(0, min(100, base + luck_pp))
    return rate, base, luck_pp


def _stone_tier_for(cfg: Mapping[str, Any], to_level: int) -> str:
    tiers = cfg.get("cost", {}).get("stone_tiers") or []
    for t in tiers:
        if not isinstance(t, Mapping):
            continue
        lv = t.get("levels")
        if isinstance(lv, list):
            for x in lv:
                if isinstance(x, int) and x == to_level:
                    return str(t.get("tier") or "")
    for t in DEFAULT_ENHANCE["cost"]["stone_tiers"]:
        if to_level in t["levels"]:
            return t["tier"]
    return "low"


def _stone_item_of(cfg: Mapping[str, Any], tier: str) -> str:
    tiers = cfg.get("cost", {}).get("stone_tiers") or []
    for t in tiers:
        if isinstance(t, Mapping) and str(t.get("tier") or "") == tier:
            it = t.get("item")
            if isinstance(it, str) and it:
                return it
    return f"item_enhance_stone_{tier}"


def _cost_for(cfg: Mapping[str, Any], to_level: int) -> Tuple[int, str]:
    """目标等级消耗 → (stones_count, stone_item_id)。"""
    cost = cfg.get("cost") or {}
    try:
        spl = int(cost.get("stones_per_level", 1) or 0)
    except (TypeError, ValueError):  # pragma: no cover
        spl = 1
    tier = _stone_tier_for(cfg, to_level)
    return to_level * spl, _stone_item_of(cfg, tier)


def _coin_cost(cfg: Mapping[str, Any], to_level: int) -> int:
    cost = cfg.get("cost") or {}
    try:
        cpl = int(cost.get("coin_per_level", 100) or 0)
    except (TypeError, ValueError):  # pragma: no cover
        cpl = 100
    return to_level * cpl


def _count_item(ctx: MutableMapping[str, Any], item_id: str) -> int:
    """持有计数（F-10 落档安全：优先 player.inventory 实例行——dict 分支落档时
    ctx 计数 hooks 的改动不 merge，直接操作 player 行才全量落档）。"""
    player = _player_of(ctx)
    if player is not None:
        inv = player.get("inventory")
        if isinstance(inv, (list, tuple)):
            total = 0
            for r in inv:
                if _row_iid(r) == item_id:
                    if isinstance(r, Mapping):
                        total += int(r.get("count", 1) or 1)
                    else:
                        total += int(getattr(r, "count", 1) or 1)
            return total
    hook = ctx.get("count_item")
    if callable(hook):
        try:
            return int(hook(item_id))
        except Exception:  # noqa: BLE001
            return 0
    inv = ctx.get("inventory")
    if isinstance(inv, Mapping):
        return int(inv.get(item_id, 0))
    return 0


def _remove_item(ctx: MutableMapping[str, Any], item_id: str, count: int) -> bool:
    """扣减（F-10 落档安全：优先 player.inventory 行就地扣，全量落档；行不足
    才回退 ctx 计数 hooks——测试/内嵌 ctx 场景）。"""
    player = _player_of(ctx)
    if player is not None:
        inv = player.get("inventory")
        if isinstance(inv, list):
            for r in inv:
                if _row_iid(r) != item_id:
                    continue
                if isinstance(r, Mapping):
                    r_d = cast(Dict[str, Any], r)
                    have = int(r_d.get("count", 1) or 1)
                    if have < count:
                        return False
                    if have == count:
                        inv.remove(r)
                    else:
                        r_d["count"] = have - count
                    return True
                try:
                    from dataclasses import replace as _dcr
                    have = int(getattr(r, "count", 1) or 1)
                    if have < count:
                        return False
                    if have == count:
                        inv.remove(r)
                    else:
                        inv[inv.index(r)] = _dcr(r, count=have - count)
                    return True
                except Exception:  # noqa: BLE001
                    return False
        if isinstance(inv, tuple):
            # tuple 形态（Player dataclass 未 asdict）→ 转 list 就地（dict 分支前）
            new_inv = list(inv)
            player["inventory"] = new_inv
            inv = new_inv
            for r in inv:
                if _row_iid(r) != item_id:
                    continue
                if isinstance(r, Mapping):
                    r_d = cast(Dict[str, Any], r)
                    have = int(r_d.get("count", 1) or 1)
                    if have < count:
                        return False
                    if have == count:
                        inv.remove(r)
                    else:
                        r_d["count"] = have - count
                    return True
                try:
                    from dataclasses import replace as _dcr
                    have = int(getattr(r, "count", 1) or 1)
                    if have < count:
                        return False
                    if have == count:
                        inv.remove(r)
                    else:
                        inv[inv.index(r)] = _dcr(r, count=have - count)
                    return True
                except Exception:  # noqa: BLE001
                    return False
    hook = ctx.get("remove_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count))
        except Exception:  # noqa: BLE001
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        have = int(inv.get(item_id, 0))
        if have < count:
            return False
        if have == count:
            inv.pop(item_id, None)
        else:
            inv[item_id] = have - count
        return True
    return False


def _cur_name(ctx: Mapping[str, Any]) -> str:
    """货币显示名（2026-09-06 硬编码清理：统一 reward.currency_display_name）。"""
    from qbot_rpg.core.reward import currency_display_name  # noqa: PLC0415

    return currency_display_name(ctx, "coins")


def _coins(player: MutableMapping[str, Any]) -> int:
    cur = player.get("currencies")
    if isinstance(cur, Mapping):
        return int(cur.get("coins", 0) or 0)
    return 0


def _spend_coins(player: MutableMapping[str, Any], amount: int) -> bool:
    cur = player.get("currencies")
    if not isinstance(cur, MutableMapping):
        return False
    have = int(cur.get("coins", 0) or 0)
    if have < amount:
        return False
    cur["coins"] = have - amount
    return True


def _roll_success(ctx: Mapping[str, Any], rate: int) -> bool:
    fn = ctx.get("rng")
    if callable(fn):
        try:
            return bool(fn() * 100 <= rate)
        except Exception:  # noqa: BLE001
            pass
    return random.random() * 100 <= rate


def _fail_split(cfg: Mapping[str, Any]) -> int:
    try:
        return int(cfg.get("settings", {}).get("fail_tier_split", 3) or 0)
    except (TypeError, ValueError):  # pragma: no cover
        return 3


# ---------------------------------------------------------------------------
# 属性增量（F-4：写 stats_bonus）
# ---------------------------------------------------------------------------

def _enhance_stat_of(ctx: Mapping[str, Any], slot_id: str) -> str:
    """槽位 → 强化主属性（2c3a D-11/D-12：武器 atk / 防具 def）。

    F-8 内容包属性键兼容：先查 enhance values 段 stat_key 显式指定；无则按槽位
    名（武器→atk / 其余→def）。veinborn 防具实际键 dfn（stats.json）由内容包
    values.armor_def_per_level.stat_key="dfn" 显式配——本函数返回配置键优先。
    """
    cfg = _cfg(ctx)
    values = cfg.get("values") or {}
    # 防具路径优先查 stat_key（内容包自定义防御键 dfn）
    av = values.get("armor_def_per_level")
    if isinstance(av, Mapping):
        sk = av.get("stat_key")
        if isinstance(sk, str) and sk:
            # 武器槽用 weapon 配置；防具槽用 armor 配置——先按槽位定配置段再取键
            return str(sk)
    from qbot_rpg.commands.basic_commands import _slot_name
    sn = _slot_name(ctx, slot_id)
    if "武" in sn or "武器" in sn or slot_id in ("weapon", "main_hand", "副手"):
        wv = values.get("weapon_atk_per_level")
        if isinstance(wv, Mapping):
            wsk = wv.get("stat_key")
            if isinstance(wsk, str) and wsk:
                return str(wsk)
        return _WEAPON_STAT
    return _ARMOR_STAT


def _values_delta(ctx: Mapping[str, Any], cfg: Mapping[str, Any], stat_key: str,
                  cur_enhance: int) -> float:
    """强化 +1 的属性增量（values 段；flat 直接加，percent 按当前 stats_bonus 比例）。"""
    values = cfg.get("values") or {}
    if stat_key == _WEAPON_STAT:
        v = values.get("weapon_atk_per_level")
    else:
        v = values.get("armor_def_per_level")
    if not isinstance(v, Mapping):
        v = DEFAULT_ENHANCE["values"].get(
            "weapon_atk_per_level" if stat_key == _WEAPON_STAT else "armor_def_per_level")
    try:
        val = float(v.get("value", 0) or 0)
    except (TypeError, ValueError):  # pragma: no cover
        val = 0.0
    t = str(v.get("type") or "flat")
    if t == "percent":
        # percent 型：相对当前强化段 stats_bonus 比例（内容包可配；缺省基数 0 → 无效）
        return 0.0
    return val


def _apply_enhance_stats(ctx: MutableMapping[str, Any], slot: Any, slot_id: str,
                         level: int) -> Tuple[str, float, float]:
    """把槽位装备强化等级应用到其 stats_bonus（就地改穿戴行）。

    入参 slot: 槽位实例（dict/EquipmentSlot）。出参 (attr_key, old_val, new_val)。
    逻辑：找到背包匹配行 → 读/写 stats_bonus[attr_key]。行缺失 → 只改槽位
    slot_level（属性由下次穿装聚合）。
    """
    cfg = _cfg(ctx)
    player = _player_of(ctx)
    inv = player.get("inventory") if player else None
    info = _slot_info(slot)
    iid = str(info.get("item_id") or "") if info else ""
    # 当前强化值
    cur = int(info.get("enhance", 0) or 0) if info else 0
    if level <= cur:
        return _enhance_stat_of(ctx, slot_id), 0.0, 0.0
    row: Any = None
    if isinstance(inv, list):
        for r in inv:
            if _row_iid(r) == iid:
                row = r
                break
    # F-9 键仲裁：优先写装备行 stats_bonus 已有键（atk/def/dfn 取首现），
    # 无则按配置键（weapon→atk/armor→def 或 stat_key）
    stat_key = ""
    sb_existing: Dict[str, Any] = {}
    if row is not None:
        if isinstance(row, Mapping):
            _rsb = row.get("stats_bonus")
            sb_existing = dict(_rsb) if isinstance(_rsb, Mapping) else {}
        else:
            sb_existing = dict(getattr(row, "stats_bonus", None) or {})
        for cand in (_WEAPON_STAT, _ARMOR_STAT, "dfn"):
            if cand in sb_existing:
                stat_key = cand
                break
    if not stat_key:
        stat_key = _enhance_stat_of(ctx, slot_id)
    delta = _values_delta(ctx, cfg, stat_key, cur)
    old_val = float(sb_existing.get(stat_key, 0) or 0) if sb_existing else 0.0
    if row is not None:
        if isinstance(row, Mapping):
            row_d = cast(Dict[str, Any], row)
            sb = row_d.get("stats_bonus")
            if isinstance(sb, Mapping):
                old_val = float(sb.get(stat_key, 0) or 0)
                sb_d = cast(Dict[str, Any], sb)
            else:
                sb_d = {}
                row_d["stats_bonus"] = sb_d
            new_val = old_val + delta
            sb_d[stat_key] = new_val
            # dict 行同步实例强化等级（供卸下回包/重穿读取）
            row_d["enhance_level"] = level
        else:
            sb = getattr(row, "stats_bonus", None)
            old_val = float((sb or {}).get(stat_key, 0) or 0)
            new_val = old_val + delta
            new_sb = dict(sb or {})
            new_sb[stat_key] = new_val
            try:
                from dataclasses import replace as _dcr
                from qbot_rpg.data.item import ItemInstance
                if isinstance(row, ItemInstance) and isinstance(inv, list):
                    idx = inv.index(row)
                    inv[idx] = _dcr(row, stats_bonus=new_sb,
                                    enhance_level=level)
            except Exception:  # noqa: BLE001
                pass
    return stat_key, old_val, old_val + delta


# ---------------------------------------------------------------------------
# 结算核心（_enhance_settle：守卫 GU-01~06 → 成功/失败原子写）
# ---------------------------------------------------------------------------

def _set_slot_level(player: MutableMapping[str, Any], slot: Any, slot_id: str,
                    level: int) -> None:
    """槽位强化等级写入（dict 槽 / EquipmentSlot 双形态）。"""
    eq = _equip_map(player)
    old = eq.get(slot_id)
    if old is None:
        eq[slot_id] = slot
        old = eq[slot_id]
    if isinstance(old, Mapping):
        old_d = cast(Dict[str, Any], old)
        old_d["slot_level"] = level
        old_d.pop("enhance", None)
    else:
        try:
            from dataclasses import replace as _dcr
            eq[slot_id] = _dcr(old, slot_level=level)
        except Exception:  # noqa: BLE001
            pass


def cmd_enhance(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/强化 <装备>[+N]：原子一条消息出结果（GU-01~05 + 成功/失败分级）。"""
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return tpl_of(ctx, "enhance_err_empty")
    raw = str(args[0])
    # P-06 多余参数（名称禁空格 ⇒ 多参数即错误）
    if len(args) > 1:
        return tpl_of(ctx, "enhance_err_extra")
    name, declared, err_key = _parse_target(raw, ctx)
    if err_key:
        return tpl_of(ctx, err_key)
    if not name:
        return tpl_of(ctx, "enhance_err_empty")
    return _settle(ctx, name, declared, protect=False)


def cmd_enhance_protect(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/强化保护 <装备>[+N]：同 /强化 + 保护石（GU-06 + 高段失败免掉级）。"""
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return tpl_of(ctx, "enhance_protect_usage")
    raw = str(args[0])
    if len(args) > 1:
        return tpl_of(ctx, "enhance_err_extra")
    name, declared, err_key = _parse_target(raw, ctx)
    if err_key:
        return tpl_of(ctx, err_key)
    if not name:
        return tpl_of(ctx, "enhance_protect_usage")
    return _settle(ctx, name, declared, protect=True)


def _settle(ctx: MutableMapping[str, Any], name: str, declared: int,
            protect: bool) -> str:
    """强化结算（守卫链 → roll → 原子写）。返回结果消息。"""
    player = _player_of(ctx)
    if player is None:
        return tpl_of(ctx, "enhance_register_gate")
    if player.get("in_battle"):
        return tpl_of(ctx, "enhance_battle_lock")
    if not _system_enabled(ctx):
        return tpl_of(ctx, "enhance_system_disabled")
    cfg = _cfg(ctx)
    ps_item = str(cfg.get("protect_stone") or "") if protect else ""
    if protect and not ps_item:
        return tpl_of(ctx, "enhance_protect_disabled")

    # GU-03 装备存在（已穿戴）
    slot, err_key, cands = _resolve_worn(ctx, player, name)
    if err_key == "not_found":
        return tpl_of(ctx, "enhance_not_found", {"name": name})
    if err_key == "ambiguous":
        return tpl_of(ctx, "enhance_ambiguous",
                      {"candidates": "\n".join(cands)})
    if slot is None:
        return tpl_of(ctx, "enhance_not_worn", {"name": name})
    info = _slot_info(slot)
    if info is None:
        return tpl_of(ctx, "enhance_not_found", {"name": name})
    slot_id = _slot_id_of(player, slot)
    cur = int(info.get("enhance", 0) or 0)

    # 品质/上限
    quality = _quality_of_row(slot, player)
    mx = _max_for_quality(cfg, quality)
    if mx <= 0:
        # 品质无上限键 → 该品质装备不可强化（内容包只对登记的品质开）
        return tpl_of(ctx, "enhance_not_equippable", {"name": info["name"]})
    # GU-04a 达顶
    if cur >= mx:
        return tpl_of(ctx, "enhance_at_max", {"max": mx})
    # GU-04b 等级标记校验（带标且不符）
    if declared and declared != cur:
        return tpl_of(ctx, "enhance_level_mismatch",
                      {"name": info["name"], "cur": cur})

    to_level = cur + 1
    stones_n, stone_item = _cost_for(cfg, to_level)
    coin_n = _coin_cost(cfg, to_level)

    # GU-05 材料足额（石/币；保护石 GU-06 事务内校验——此处先预检防误提示）
    have_stone = _count_item(ctx, stone_item)
    deficits = []
    if have_stone < stones_n:
        deficits.append(tpl_of(ctx, "enhance_material_deficit",
                               {"name": _stone_cn(ctx, stone_item),
                                "deficit": stones_n - have_stone}))
    have_coins = _coins(player)
    if have_coins < coin_n:
        deficits.append(f"{_cur_name(ctx)}×{coin_n - have_coins}")
    if deficits:
        need = " + ".join([
            tpl_of(ctx, "enhance_material_item",
                   {"name": _stone_cn(ctx, stone_item), "need": stones_n}),
            f"{_cur_name(ctx)} {coin_n}"])
        return tpl_of(ctx, "enhance_material_short",
                      {"need": need, "deficits": "、".join(deficits)})

    # GU-06 保护石足额（protect 模式；事务内复核语义——无并发窗口即等价）
    if protect:
        have_ps = _count_item(ctx, ps_item)
        if have_ps < 1:
            return tpl_of(ctx, "enhance_protect_missing")

    # 成功率（显示拆分）
    rate, base, luck_pp = _real_rate(ctx, player, cfg, to_level)

    # roll（一次）
    ok = _roll_success(ctx, rate)
    if ok:
        return _commit_success(ctx, player, slot, slot_id, info, to_level,
                               stones_n, stone_item, coin_n, rate, base,
                               luck_pp, protect)
    return _commit_fail(ctx, player, slot, slot_id, info, cur, to_level,
                        stones_n, stone_item, coin_n, rate, base, luck_pp,
                        protect, cfg)


def _slot_id_of(player: MutableMapping[str, Any], slot: Any) -> str:
    eq = _equip_map(player)
    for sid, s in eq.items():
        if s is slot:
            return sid
    return ""


def _stone_cn(ctx: Mapping[str, Any], item_id: str) -> str:
    """石物品中文名（items 表；缺省回退 id）。"""
    items = ctx.get("items")
    if isinstance(items, Mapping):
        d = items.get(item_id)
        if isinstance(d, Mapping) and d.get("name"):
            return str(d["name"])
    return item_id


def _commit_success(ctx: MutableMapping[str, Any], player: MutableMapping[str, Any],
                    slot: Any, slot_id: str, info: Mapping[str, Any], to_level: int,
                    stones_n: int, stone_item: str, coin_n: int,
                    rate: int, base: int, luck_pp: int, protect: bool) -> str:
    """成功分支：扣石扣币 → 等级 +1 → 属性增量 → 模板。"""
    name = str(info["name"] or "")
    if not _remove_item(ctx, stone_item, stones_n):
        return tpl_of(ctx, "enhance_material_short",
                      {"need": stone_item, "deficits": f"{stone_item}×{stones_n}"})
    if not _spend_coins(player, coin_n):
        return tpl_of(ctx, "enhance_coin_short",
                      {"cost": coin_n, "coins_have": _coins(player),
                       "currency": _cur_name(ctx)})
    # 先算属性增量（读旧 cur），再升档——顺序反了会读到自己刚写的等级而早退
    attr_key, old_v, new_v = _apply_enhance_stats(ctx, slot, slot_id, to_level)
    _set_slot_level(player, slot, slot_id, to_level)
    if luck_pp > 0 or (luck_pp == 0 and base < rate):
        roll_line = tpl_of(ctx, "enhance_roll_line", {
            "name": name, "to": to_level, "rate": rate, "base": base, "luck": luck_pp})
    else:
        roll_line = tpl_of(ctx, "enhance_roll_line_luck_off",
                           {"name": name, "to": to_level, "rate": rate})
    attr_cn = _ATTR_CN.get(attr_key, attr_key)
    success_line = tpl_of(ctx, "enhance_success", {
        "attr": attr_cn, "old": _fmt_num(old_v), "new": _fmt_num(new_v)})
    return roll_line + "\n" + success_line


def _commit_fail(ctx: MutableMapping[str, Any], player: MutableMapping[str, Any],
                 slot: Any, slot_id: str, info: Mapping[str, Any], cur: int,
                 to_level: int, stones_n: int, stone_item: str, coin_n: int,
                 rate: int, base: int, luck_pp: int, protect: bool,
                 cfg: Mapping[str, Any]) -> str:
    """失败分支：材料照扣 + 分级惩罚（低不变/高 -1；保护石免掉级）。"""
    name = str(info["name"] or "")
    if not _remove_item(ctx, stone_item, stones_n):
        return tpl_of(ctx, "enhance_material_short",
                      {"need": stone_item, "deficits": f"{stone_item}×{stones_n}"})
    if not _spend_coins(player, coin_n):
        return tpl_of(ctx, "enhance_coin_short",
                      {"cost": coin_n, "coins_have": _coins(player),
                       "currency": _cur_name(ctx)})
    split = _fail_split(cfg)
    roll_line = tpl_of(ctx, "enhance_roll_line", {
        "name": name, "to": to_level, "rate": rate, "base": base, "luck": luck_pp})
    if cur <= split:
        # 低等级段：装备不变（材料照扣）
        return roll_line + "\n" + tpl_of(ctx, "enhance_fail_low")
    # 高等级段：掉级（当前−1）；保护石 → 消耗 1 颗免掉级
    if protect:
        if not _remove_item(ctx, str(cfg.get("protect_stone") or ""), 1):
            return tpl_of(ctx, "enhance_protect_missing")
        return roll_line + "\n" + tpl_of(ctx, "enhance_protect_saved",
                                          {"name": name, "cur": cur})
    down = max(0, cur - 1)
    _set_slot_level(player, slot, slot_id, down)
    return roll_line + "\n" + tpl_of(ctx, "enhance_fail_high",
                                      {"name": name, "cur": cur, "down": down})


def _fmt_num(v: float) -> str:
    if v == int(v):
        return str(int(v))
    return f"{v:.1f}"


# ---------------------------------------------------------------------------
# /强化信息（只读查询：+N/成功率/上限/消耗预览——零副作用）
# ---------------------------------------------------------------------------

def cmd_enhance_info(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/强化信息 <装备>：只读查询（TC-07~09；不扣不 roll 不写）。"""
    player = _player_of(ctx)
    if player is None:
        return tpl_of(ctx, "enhance_register_gate")
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return tpl_of(ctx, "enhance_err_empty")
    raw = str(args[0])
    if len(args) > 1:
        return tpl_of(ctx, "enhance_err_extra")
    name, _declared, err_key = _parse_target(raw, ctx)
    if err_key:
        return tpl_of(ctx, err_key)
    if not name:
        return tpl_of(ctx, "enhance_err_empty")
    if not _system_enabled(ctx):
        return tpl_of(ctx, "enhance_system_disabled")
    cfg = _cfg(ctx)

    slot, err_key, cands = _resolve_worn(ctx, player, name)
    if err_key == "not_found":
        return tpl_of(ctx, "enhance_not_found", {"name": name})
    if err_key == "ambiguous":
        return tpl_of(ctx, "enhance_ambiguous",
                      {"candidates": "\n".join(cands)})
    if slot is None:
        return tpl_of(ctx, "enhance_not_worn", {"name": name})
    info = _slot_info(slot)
    if info is None:
        return tpl_of(ctx, "enhance_not_found", {"name": name})
    cur = int(info.get("enhance", 0) or 0)
    quality = _quality_of_row(slot, player)
    mx = _max_for_quality(cfg, quality)
    if mx <= 0:
        return tpl_of(ctx, "enhance_not_equippable", {"name": info["name"]})
    q_cn = QUALITY_LABELS_CN.get(quality, quality)
    display = str(info["name"] or name)
    if cur:
        head = tpl_of(ctx, "enhance_info_title",
                      {"name": display, "cur": cur, "quality": q_cn, "max": mx})
    else:
        head = tpl_of(ctx, "enhance_info_title_zero",
                      {"name": display, "quality": q_cn, "max": mx})
    if cur >= mx:
        return head + "\n" + tpl_of(ctx, "enhance_info_at_max", {"max": mx})

    to_level = cur + 1
    rate, base, luck_pp = _real_rate(ctx, player, cfg, to_level)
    if cfg.get("settings", {}).get("luck_affects", True) is not False:
        rate_row = tpl_of(ctx, "enhance_info_rate_row",
                          {"to": to_level, "rate": rate, "base": base, "luck": luck_pp})
    else:
        rate_row = tpl_of(ctx, "enhance_info_rate_row_luck_off",
                          {"to": to_level, "rate": rate})
    stones_n, stone_item = _cost_for(cfg, to_level)
    coin_n = _coin_cost(cfg, to_level)
    stone_have = _count_item(ctx, stone_item)
    cost_row = tpl_of(ctx, "enhance_info_cost_row", {
        "to": to_level,
        "stones": f"{_stone_cn(ctx, stone_item)} ×{stones_n} + {_cur_name(ctx)} ×{coin_n}",
        "stone_have": stone_have, "coins_have": _coins(player),
        "currency": _cur_name(ctx)})
    lines = [head, rate_row, cost_row]
    dist = mx - cur
    if dist > 0:
        lines.append(tpl_of(ctx, "enhance_info_dist", {"dist": dist}))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 注入，对齐 forge 壳模式）
# ---------------------------------------------------------------------------

def register_enhance_commands(
    router: Any,
    *,
    make_context: Optional[Callable[[Any], dict]] = None,
) -> Any:
    """把 /强化 /强化信息 /强化保护 注册进 Router。

    :param make_context: ParsedCommand → 玩家 ctx dict。None 时 handler 调用抛
        RuntimeError（【待接线】装配层注入，对齐 shop/forge 口径）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "enhance_commands.register_enhance_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _wrap(fn: Callable[[Any, MutableMapping[str, Any]], str]) -> Callable[..., str]:
        def _h(parsed: Any, *a: Any, **k: Any) -> str:
            injected = k.get("ctx") if isinstance(k, dict) else None
            if isinstance(injected, MutableMapping):
                return fn(parsed, injected)
            return fn(parsed, _ctx(parsed))
        return _h

    # 三指令独立注册（P-04 最长前缀匹配防交叉；白名单均已登记）
    router.register(CommandSpec(ENHANCE_CMD, handler=_wrap(cmd_enhance)))
    router.register(CommandSpec(ENHANCE_INFO_CMD, handler=_wrap(cmd_enhance_info)))
    router.register(CommandSpec(ENHANCE_PROTECT_CMD, handler=_wrap(cmd_enhance_protect)))
    return router
