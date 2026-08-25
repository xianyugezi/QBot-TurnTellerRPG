"""怪物意图预告生成器（M2 怪物体系 · B3 路：意图预告 build_intent + 中断恢复播报）。

依据：细化_1f_怪物AI状态机.md（③ 意图预告：3.1 intent 运行时结构 / 3.2 预告分级
L1-L3 / 3.3 其他预告类型：蓄力进度/状态切换播报/连锁预演/中断恢复播报）+
docs/m2_shared_contract.md 第五节（AI 引擎接口：intent_for 返回 {level, category,
action_id, name_revealed, chain_preview, progress}；ai_state 快照含 charge 键；
intent.category 三值裁决 1f ③3.1 P2-7）+ 第八节铁律。

纯函数无 IO（铁律 2：零 NoneBot import；平台无关）。本模块**不持有状态**：
build_intent 是纯函数——输入 action_id/action_def/ai_state/codex_state，输出意图
预告 dict，不写 ai_state（蓄力进度取自入参 ai_state.charge，不递增）。

工程收敛（设计文档未显式定义处，显式标注供审查）：
  1. level 语义 = 本条预告覆盖的最高分级：L1 类别（charge/gather/stance）→ 1；
     图鉴解锁显示招名 → 2；图鉴解锁显示连锁预演 → 3（3.2 分级表逐级叠加）。
  2. reveal_condition 缺省 = 解锁（只有显式声明揭示条件的行动才被图鉴门禁）——
     与「普通招名人人可见、特技需图鉴」的小白优先直觉一致【细化】。
  3. reveal_condition 形态接口：支持 str 比较式（"codex>=3"/"lore:2"）、str 直接键
     （codex_state 内真值键，如 "tail_sweep"）、list（全满足=AND）、dict 表达式
     {type, key, value}（codex_gte/lore_gte/revealed/all）——解锁阈值计算留接口，
     主 agent 可在此函数外按真实图鉴数据源接入。
  4. intent.category 映射裁决（1f ③3.1 P2-7）：charge_*/蓄力类 → charge；
     防御/架势类 → stance；蓄积能量/积蓄类 → gather；其余无 L1 预告 category=None
     （或经 action_def.preview 显式声明 category）。**不得**用 action.json 的
     intent 字段（伤害/防御/蓄力…四值）直填 category。
  5. 蓄力进度 "1/2" 格式（3.3 / §五 消息模板）：优先取 ai_state.charge（同 action_id
     时的 shown/total），否则按 action_def.charge_turns 给起手 1/N。
  6. chain_preview = action_def.preview_chain 的 action id 列表（3.1 形态）；未解锁
     → []（3.2 L3「图鉴解锁后显示」，TC-11）。
"""

from __future__ import annotations

import re
from typing import Any, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "build_intent",
    "reveal_satisfied",
    "resume_broadcast",
    "chain_preview_text",
]

# ---------------------------------------------------------------- 意图类别常量（1f ③3.1）
CATEGORY_CHARGE = "charge"    # 蓄力
CATEGORY_GATHER = "gather"    # 积蓄能量
CATEGORY_STANCE = "stance"    # 攻击架势

# action.json intent 字段（值域 伤害/防御/蓄力/治疗/控制/buff/debuff/印记/功能，
# contract §四）→ intent.category 映射（1f ③3.1 P2-7 裁决）【细化】
_CHARGE_INTENT_HINTS = ("蓄力", "charge")
_STANCE_INTENT_HINTS = ("防御", "架势", "defense", "stance", "guard")
_GATHER_INTENT_HINTS = ("积蓄", "蓄能", "gather", "charge_up", "蓄力预备")


# ================================================================ 公开接口


def build_intent(
    action_id: Optional[str],
    action_def: Optional[Mapping[str, Any]],
    ai_state: Mapping[str, Any],
    codex_state: Optional[Mapping[str, Any]] = None,
) -> dict:
    """意图预告生成器（1f ③3.1 运行时结构 / contract §五 intent_for 返回值）。

    Args:
        action_id: 行动 ID（引用 action.json）。
        action_def: action.json 行动定义 raw dict（含 charge_*/preview/
            preview_chain/reveal_condition/armor/tags/intent 等 AI 字段，
            contract §四）。
        ai_state: 快照（contract §五）；蓄力进度读 ai_state.charge
            {action_id, total, shown, remaining_turns, armor}。
        codex_state: 图鉴解锁状态 dict（默认 {}；reveal_condition 求值数据源，
            解锁阈值计算留接口，见模块 docstring 工程收敛 3）。

    Returns:
        intent 运行时结构 dict：
            level          int    预告分级 1-3（工程收敛 1：最高覆盖分级）
            category       str|None  L1 类别 charge/gather/stance；无 L1 预告 → None
            action_id      str|None
            name_revealed  bool   L2 招名图鉴解锁（False → 渲染端显示？？？）
            chain_preview  list   L3 连锁预演 action id 列表（未解锁 → []）
            progress       str|None  蓄力进度 "1/2"（非蓄力 → None）
    """
    adef = dict(action_def or {})
    codex = codex_state or {}

    # ── L1 意图类别（永远公开；1f ③3.2 / P2-7 映射裁决） ──
    category = _resolve_category(adef)

    # ── 图鉴解锁（reveal_condition 控制 L2/L3，1f ③3.4） ──
    revealed = reveal_satisfied(adef.get("reveal_condition"), codex)

    # ── 蓄力进度（3.3 蓄力进度 / §五 消息模板 "1/2"） ──
    progress = _charge_progress(action_id, adef, ai_state)

    # ── L3 连锁预演（未解锁 → []，TC-11） ──
    chain_preview: List[str] = []
    if revealed:
        chain_preview = _normalize_preview_chain(adef.get("preview_chain"))

    # ── 分级（工程收敛 1：最高覆盖分级） ──
    if chain_preview:
        level = 3
    elif revealed:
        level = 2
    elif category is not None:
        level = 1
    else:
        level = 0  # 无任何可预告内容（调用方可不渲染）

    return {
        "level": level,
        "category": category,
        "action_id": action_id,
        "name_revealed": bool(revealed),
        "chain_preview": chain_preview,
        "progress": progress,
    }


def reveal_satisfied(
    reveal_condition: Any,
    codex_state: Optional[Mapping[str, Any]] = None,
) -> bool:
    """图鉴解锁判定（1f ③3.4：reveal_condition 控制 L2/L3 解锁）。

    形态（工程收敛 3，解锁阈值计算留接口）：
      - None/空 → True（无门禁默认解锁）
      - bool → 原值
      - list/tuple → 全满足 AND
      - dict {type, key, value}：
          codex_gte/lore_gte/unlock_gte  → codex[key] >= value
          revealed                       → key ∈ codex.revealed 或 codex[key] 真值
          all                            → conditions 全满足
      - str 比较式："codex>=3" / "lore:2" / "unlock == 5" → 数值比较
      - str 直接键：codex_state[key] 真值（如 codex_state["tail_sweep"] = True）
    """
    codex = codex_state or {}
    if reveal_condition is None or reveal_condition == "":
        return True
    if isinstance(reveal_condition, bool):
        return reveal_condition
    if isinstance(reveal_condition, (list, tuple, set)):
        return all(reveal_satisfied(x, codex) for x in reveal_condition)
    if isinstance(reveal_condition, Mapping):
        return _eval_reveal_mapping(dict(reveal_condition), codex)
    s = str(reveal_condition).strip()
    if not s:
        return True
    return _eval_reveal_str(s, codex)


def resume_broadcast(
    ai_state: Mapping[str, Any],
    action_lib: Optional[Any] = None,
    chain_ids: Optional[Sequence[str]] = None,
) -> str:
    """中断恢复播报（1f ③3.3 / TC-12）：「连招 火球→【尾扫】→吼叫（2/3 段）」。

    快照语义（M2 审查 P1-4 裁定）：ai_state.chain_queue 存**剩余段**（队首已被触发
    行动本次执行弹出，monster_ai._produce 弹队首），chain_pos=已执行段数——故
    完整链播报需调用方经 chain_ids 传入完整链定义来源（M6 恢复接线点）；
    chain_ids 缺省时按剩余段播报（调用方未补全的正确降级，不伪装完整链）。
    action_lib 可选：Mapping(id→{name}) 或 callable(id)→{name}；缺省回退显示
    原始 action id。

    Returns:
        "连招 火球→【尾扫】→吼叫（2/3 段）" 形态字符串；无在途链 → ""。
    """
    if chain_ids is None:
        queue = ai_state.get("chain_queue") or []
    else:
        queue = list(chain_ids)
    if not queue:
        return ""
    total = len(queue)
    raw_pos = int(ai_state.get("chain_pos", 1) or 1)
    pos = 1 if raw_pos < 1 else (total if raw_pos > total else raw_pos)

    names = [_resolve_name(aid, action_lib) for aid in queue]
    parts = [
        f"【{names[i]}】" if (i + 1) == pos else names[i]
        for i in range(total)
    ]
    return f"连招 {'→'.join(parts)}（{pos}/{total} 段）"


def chain_preview_text(
    chain_preview: Sequence[str],
    action_lib: Optional[Any] = None,
) -> str:
    """L3 连锁预演文案（1f ③3.3：「似乎要接【尾扫】」；多段 →「似乎要接【尾扫】→【吼叫】」）。

    chain_preview 为空 → ""。action_lib 缺省回退显示 action id。
    """
    if not chain_preview:
        return ""
    names = [_resolve_name(aid, action_lib) for aid in chain_preview]
    return "似乎要接" + "→".join(f"【{n}】" for n in names)


# ================================================================ L1 类别 / 蓄力进度 / 解锁实现


def _resolve_category(action_def: Mapping[str, Any]) -> Optional[str]:
    """intent.category 三值裁决（1f ③3.1 P2-7；工程收敛 4）。"""
    # 显式 preview.category 声明优先（1f ③3.1「或经 preview 字段显式声明」）
    preview = action_def.get("preview")
    if isinstance(preview, Mapping):
        declared = preview.get("category")
        if declared in (CATEGORY_CHARGE, CATEGORY_GATHER, CATEGORY_STANCE):
            return str(declared)

    # charge_* 前缀 / 蓄力类（contract §四 charge_* 蓄力字段）
    if any(k.startswith("charge_") for k in action_def.keys()):
        return CATEGORY_CHARGE

    intent = action_def.get("intent")
    if isinstance(intent, str):
        it = intent.strip().lower()
        if any(h in it for h in _CHARGE_INTENT_HINTS):
            return CATEGORY_CHARGE
        if any(h in it for h in _STANCE_INTENT_HINTS):
            return CATEGORY_STANCE
        if any(h in it for h in _GATHER_INTENT_HINTS):
            return CATEGORY_GATHER
    return None  # 其余行动无 L1 预告（category 缺省）


def _charge_progress(
    action_id: Optional[str],
    action_def: Mapping[str, Any],
    ai_state: Mapping[str, Any],
) -> Optional[str]:
    """蓄力进度 "k/N"（1f ③3.3 / §五 消息模板 1/2）。

    优先取 ai_state.charge（同 action_id 进行中的蓄力 shown/total）；否则按
    action_def.charge_turns 给起手 1/N。非蓄力 → None。
    """
    charge = ai_state.get("charge")
    if isinstance(charge, Mapping) and charge.get("action_id") == action_id:
        total = charge.get("total")
        shown = charge.get("shown")
        if total:
            try:
                return f"{int(shown or 1)}/{int(total)}"
            except (TypeError, ValueError):
                pass
    turns = action_def.get("charge_turns")
    if turns:
        try:
            return f"1/{int(turns)}"
        except (TypeError, ValueError):
            pass
    return None


def _normalize_preview_chain(preview_chain: Any) -> List[str]:
    """preview_chain → action id 列表（3.1 形态 ["tail_sweep"]）。"""
    if isinstance(preview_chain, str):
        return [preview_chain]
    if isinstance(preview_chain, Mapping):
        preview_chain = preview_chain.get("actions")
    if not isinstance(preview_chain, (list, tuple)):
        return []
    return [str(x) for x in preview_chain if str(x)]


def _eval_reveal_mapping(cond: Mapping[str, Any], codex: Mapping[str, Any]) -> bool:
    """dict 形态 reveal_condition 求值（接口；未知 type → False）。"""
    ctype = str(cond.get("type", "")).strip()
    key = cond.get("key")
    value = cond.get("value")
    if ctype in ("codex_gte", "lore_gte", "unlock_gte"):
        if not isinstance(key, str) or value is None:
            return False
        try:
            cur = int(codex.get(key, 0) or 0)
            return cur >= int(value)
        except (TypeError, ValueError):
            return False
    if ctype == "revealed":
        if isinstance(codex.get("revealed"), (list, tuple, set)):
            return key in codex["revealed"]
        return bool(codex.get(key))
    if ctype == "all":
        conditions = cond.get("conditions")
        if isinstance(conditions, (list, tuple)):
            return all(reveal_satisfied(c, codex) for c in conditions)
        return False
    return False


_REVEAL_CMP_RE = re.compile(
    r"^\s*(\w+)\s*(>=|<=|>|<|==|=|:)\s*(-?\d+)\s*$"
)


def _eval_reveal_str(s: str, codex: Mapping[str, Any]) -> bool:
    """str 形态 reveal_condition 求值：比较式或直接键。"""
    m = _REVEAL_CMP_RE.match(s)
    if m:
        key, op, val = m.group(1), m.group(2), m.group(3)
        try:
            cur = int(codex.get(key, 0) or 0)
            target = int(val)
        except (TypeError, ValueError):
            return False
        return {
            ">=": cur >= target,
            "<=": cur <= target,
            ">": cur > target,
            "<": cur < target,
            "==": cur == target,
            "=": cur == target,
            ":": cur >= target,  # "lore:2" 读作 lore 达到 2 级
        }.get(op, False)
    return bool(codex.get(s))


def _resolve_name(action_id: Any, action_lib: Optional[Any]) -> str:
    """action id → 显示名（action_lib Mapping/callable → def.name；缺省回退 id）。"""
    aid = str(action_id)
    try:
        if callable(action_lib):
            d = action_lib(aid)
        elif isinstance(action_lib, Mapping):
            d = action_lib.get(aid)
        else:
            d = None
    except Exception:
        d = None
    if isinstance(d, Mapping):
        name = d.get("name")
        if name:
            return str(name)
    return aid
