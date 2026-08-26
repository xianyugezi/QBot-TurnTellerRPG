"""NPC 发牌员核心（M4 批次2·路C2 · qbot_rpg/core/npc.py）——发牌员三策略 + 10 类动作 + 一次一物 + 条件统一。

依据：
  - m4_shared_contract.md §3.1（NPC/对话 B1-B6：dealer 牌池 rotate/random/condition 三策略 +
    不重复发已完成任务；一次一物信息类置灰"已听"落玩家存档；条件统一 {var,op,value,param}；
    会话路由/对话树归 core/dialog.py，本模块只管发牌与动作分发）
  - docs/细化/细化_2b1_NPC数据与发牌员.md（§二 发牌员机制：DR01-02 dealer 子结构 / P01-05 候选牌 /
    DS01-04 三策略+兼容映射 / SM01-07 抽牌状态机与去重；§三 10 类动作字段契约 AC01-10；
    §四 一次一物 O01-O08；2026-08-27 裁决④：保留细化版 rotate/random/condition，
    旧 first_match→condition、weighted→random 等权、random→random 兼容映射）
  - docs/审查参考/NPC系统设计定稿.md（§六 发牌员配置 L401-415 / 10 类动作 L126-137 /
    一次一物 L83-92 / 统一入账 L153 / 事件计数 L289 / 条件引擎 §四）
  - 2026-08-27 M4 设计审查裁决④（用户拍板：发牌员策略枚举保留细化版；定稿 first_match/weighted/random
    作兼容映射，保留兼容迁移提示）

【工程补白 · 显式标注】（契约/定稿未给字段名或落点，按"只建议不限制"取点定型，命名可改）：
  1) 条件求值统一走 qbot_rpg.engine.condition_engine.eval_condition（A2 唯一实现，m4 §1 A2）；
     core→engine 依赖由 G0 依赖矩阵允许（scripts/check_architecture.py ALLOWED_DEP["core"] += "engine"，
     契约 A2「任务/NPC/商店/签到全系统复用」的前提；本文件为 M4 首批消费方）。
  2) 玩家存档一次性节点 npc_delivered（O07）：ctx["npc_delivered"] = {npc_id: {交付键: 值}}；
     交付键 = "intel:<ref_id>" / "tutorial:<tutorial_id>" / "give_item:<指纹>" / "card:<牌id>"（P05）；
     值 = True（once/intel/tutorial/池牌）或日期键 "YYYY-MM-DD"（give_item repeat=daily 最后领取日）。
     落玩家存档（O03），不落会话快照；本模块只读写在 ctx，持久化由调用方完成。
  3) give_item repeat=daily 的"每日重置"复用 A3 dayroll 日界（today_of，统一配置键 refresh_time 默认 05:00），
     与 quest_daily/商店/签到同刻对齐（2b4 F-5）。
  4) quest 去重（SM06）读 ctx["quest_active"]/ctx["quest_completed"]（Mapping/set/list 均可）与
     ctx["quest_daily"]（扁平 {qid:...} 或嵌套 {日期: {qid:...}} 两形态兜底）；三表缺失 = 不去重（fail-safe）。
  5) rotate 轮转指针由调用方持有的可变 dict（rotate_state={"index": N}）持久化；本模块原地改写。
     回复 text[] 循环 mode="cycle" 复用同一 state（reply_index）。random 用 rng()/Random 实例注入。
  6) buff 增益落点：ctx["active_effects"]（dict {effect_id: {effect,turns,refreshed}}，同 buff 重触发仅刷新
     剩余回合，对齐 AC05 补白）；有 ctx["apply_effect"] 可调用 hook 时优先走 hook（对齐 A1 add_item 模式）。
  7) teleport 纯函数语义：扣费 + 改写 ctx["map_id"]=目标图；实际迁移（离图清当前商店/快照等世界侧副作用）
     由调用方（world 层）执行。
  8) repair 当前降级（S4 裁决/AC06/L139）：依赖装备耐久系统框架未实现 → 恒"不可用+友好提示"，配置不拦截。
  9) give_item once/daily 需 npc_id 才能记账；无 npc_id 时不记一次性（每次照发）——由调用方保证传入。
  10) 菜单「已听」置灰展示：调用方按 is_delivered(ctx, npc_id, "intel:<ref_id>") 逐条目判定（O01/O07）。

铁律：零 NoneBot import；纯函数（ctx dict 进出，就地改写可变子结构）；rng 注入确定性；
同刻同参必同值（不依赖全局状态）；工程补白显式标注。
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional

from qbot_rpg.core.dayroll import today_of
from qbot_rpg.core.reward import dispatch_reward
from qbot_rpg.engine.condition_engine import eval_condition

__all__ = [
    "STRATEGY_CONDITION",
    "STRATEGY_RANDOM",
    "STRATEGY_ROTATE",
    "STRATEGIES",
    "LEGACY_STRATEGY_MAP",
    "ACTIONS",
    "INFO_ACTIONS",
    "FUNCTIONAL_ACTIONS",
    "DEGRADED_ACTIONS",
    "normalize_strategy",
    "build_pool",
    "card_eligible",
    "available_quests",
    "draw_card",
    "resolve_heal",
    "dispatch_action",
    "deal",
    "mark_delivered",
    "is_delivered",
    "delivered_value",
]

# -------------------------------------------------------------------------------------
# 常量：三策略 + 10 类动作（裁决④ + 定稿 L126-137 / 细化 AC01-10）
# -------------------------------------------------------------------------------------
STRATEGY_CONDITION = "condition"
STRATEGY_RANDOM = "random"
STRATEGY_ROTATE = "rotate"
STRATEGIES: tuple = (STRATEGY_ROTATE, STRATEGY_RANDOM, STRATEGY_CONDITION)

# 旧定稿枚举 → 细化版（裁决④/DS04）：first_match→condition、weighted→random 等权、random→random
LEGACY_STRATEGY_MAP: dict = {
    "first_match": STRATEGY_CONDITION,
    "weighted": STRATEGY_RANDOM,
    "random": STRATEGY_RANDOM,
}

_MIGRATE_HINT = "新枚举 rotate/random/condition，建议迁移（旧值兼容解析）"

ACTIONS: tuple = (
    "quest", "shop", "heal", "give_item", "buff", "repair",
    "teleport", "intel", "tutorial", "reply",
)

# 信息类（一次一物：交付后置灰"已听"，O01/O05/L86-90）
INFO_ACTIONS: tuple = ("intel", "tutorial")
# 功能类（不置灰可重复使用，O05/L90）
FUNCTIONAL_ACTIONS: tuple = (
    "quest", "shop", "heal", "give_item", "buff", "teleport", "reply",
)
# 当前降级类（repair 依赖装备耐久系统，框架未实现 → 不可用+友好提示，S4/AC06）
DEGRADED_ACTIONS: tuple = ("repair",)


# -------------------------------------------------------------------------------------
# 结果构造（统一返回形态）
# -------------------------------------------------------------------------------------
def _res(action: str, ok: bool, kind: str = "functional", **kw: Any) -> dict:
    """动作结果：{ok, action, kind, reason?, message?, data?, granted?, skipped?, already?, delivered?}。

    kind ∈ "info"（一次一物信息类）/ "functional"（功能类）/ "degraded"（降级不可用）。
    already=True：重复命中（已听/已领/已教学）；delivered=True：本次为新交付（信息类/池牌 once）。
    """
    r: dict = {"ok": ok, "action": action, "kind": kind}
    for k in ("reason", "message", "data", "granted", "skipped", "already", "delivered"):
        v = kw.get(k)
        if v is not None:
            r[k] = v
    return r


# -------------------------------------------------------------------------------------
# 策略归一（裁决④/DS04）
# -------------------------------------------------------------------------------------
def normalize_strategy(strategy: object) -> dict:
    """策略名归一 → {"strategy", "legacy", "migrate_hint"}。

    - 细化版 rotate/random/condition 直接通过（legacy=False）；
    - 旧定稿枚举 first_match→condition、weighted→random 等权、random→random（legacy=True + 迁移提示）；
    - 缺省/未知 → condition（DR01 默认承接定稿 first_match 默认态）。纯函数不抛错。
    """
    if isinstance(strategy, str):
        s = strategy.strip().lower()
        if s in STRATEGIES:
            return {"strategy": s, "legacy": False, "migrate_hint": None}
        if s in LEGACY_STRATEGY_MAP:
            return {"strategy": LEGACY_STRATEGY_MAP[s], "legacy": True, "migrate_hint": _MIGRATE_HINT}
    return {"strategy": STRATEGY_CONDITION, "legacy": False, "migrate_hint": None}


# -------------------------------------------------------------------------------------
# 集合判定（对齐 condition_engine._exists：Mapping/set/frozenset/list/tuple）
# -------------------------------------------------------------------------------------
def _in_coll(ctx: Mapping[str, Any], key: str, qid: str) -> bool:
    coll = ctx.get(key)
    if coll is None:
        return False
    if isinstance(coll, Mapping):
        return qid in coll
    if isinstance(coll, (set, frozenset, list, tuple)):
        return qid in coll
    return False


def _in_quest_daily(ctx: Mapping[str, Any], qid: str) -> bool:
    """quest_daily 去重判定：扁平 {qid:...} 或嵌套 {日期: {qid:...}} 两形态兜底（工程补白④）。"""
    qd = ctx.get("quest_daily")
    if qd is None:
        return False
    if isinstance(qd, Mapping):
        if qid in qd:
            return True
        for v in qd.values():
            if isinstance(v, Mapping) and qid in v:
                return True
        return False
    if isinstance(qd, (set, frozenset, list, tuple)):
        return qid in qd
    return False


def available_quests(deliver: Mapping[str, Any], ctx: Mapping[str, Any]) -> list:
    """候选任务可用列表（SM06 去重 + 条件过滤，顺序即优先级）。

    规则：① quest_active（活跃）/ quest_daily（今日已发）/ quest_completed（已完成）三表命中 → 不重发；
          ② 候选条目自带 condition（AC01）不满足 → 剔除；③ 其余按候选数组顺序返回（首条即最高优先级）。
    """
    out: list = []
    quests = deliver.get("quests")
    if not isinstance(quests, (list, tuple)):
        return out
    for q in quests:
        if not isinstance(q, Mapping):
            continue
        qid = q.get("quest_id")
        if not isinstance(qid, str) or not qid:
            continue
        # 不重复发已完成/活跃任务（SM06 / AC01 / L414）：三表兜底
        if _in_coll(ctx, "quest_active", qid):
            continue
        if _in_quest_daily(ctx, qid):
            continue
        if _in_coll(ctx, "quest_completed", qid):
            continue
        cond = q.get("condition")
        if cond is not None and not eval_condition(cond, ctx):
            continue
        out.append(q)
    return out


# -------------------------------------------------------------------------------------
# 牌池构建（SM02）+ 单牌资格
# -------------------------------------------------------------------------------------
def _card_deliver(card: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    d = card.get("deliver")
    return d if isinstance(d, Mapping) else None


def card_eligible(card: Mapping[str, Any], ctx: Mapping[str, Any], npc_id: Optional[str] = None) -> bool:
    """单牌资格判定（SM02 过滤 + P05 once 出池 + SM06 quest 去重）。

    - 条件：牌无 condition = 恒真（P02 缺省）；有则 eval_condition 求值（A2 统一引擎）。
    - 牌级 once（P05）：已交付落 npc_delivered["card:<id>"] → 出池（落玩家存档）。
    - quest 卡：无可交付候选任务（活跃/今日已发/已完成/条件不满足）→ 不出（不重复发已完成任务）。
    """
    if not isinstance(card, Mapping):
        return False
    deliver = _card_deliver(card)
    if deliver is None:
        return False  # deliver 必填（P04）
    cond = card.get("condition")
    if cond is not None and not eval_condition(cond, ctx):
        return False
    if npc_id and card.get("once"):
        cid = card.get("id")
        if cid and is_delivered(ctx, npc_id, f"card:{cid}"):
            return False
    if deliver.get("action") == "quest" and not available_quests(deliver, ctx):
        return False
    return True


def build_pool(cards: object, ctx: Mapping[str, Any], npc_id: Optional[str] = None) -> list:
    """SM02 牌池构建：对 pool[] 逐牌过滤（条件 + once 出池 + quest 去重），保留原始顺序；空池=无牌。"""
    if not isinstance(cards, (list, tuple)):
        return []
    return [c for c in cards if card_eligible(c, ctx, npc_id=npc_id)]


# -------------------------------------------------------------------------------------
# 抽牌（SM03）：三策略
# -------------------------------------------------------------------------------------
def _weight_of(card: Mapping[str, Any]) -> float:
    """权重归一（P03）：缺省 1；weight=0=不入随机池；非法值（非数值/负数/bool）→ 默认 1（工程补白，只建议不限制）。"""
    w = card.get("weight", 1)
    if isinstance(w, bool):
        return 1
    if isinstance(w, (int, float)) and w >= 0:
        return float(w)
    return 1


def _rng_float(rng: object) -> float:
    """随机浮点 [0,1)：Random 实例 .random() / 普通 callable rng() / 缺省 → random 模块。"""
    if rng is None:
        import random

        return random.random()
    if hasattr(rng, "random"):
        return float(rng.random())  # type: ignore[union-attr]
    return float(rng())  # type: ignore[operator]  # 普通 callable


def _rng_int(rng: object, n: int) -> int:
    """随机整数 [0, n)：Random 实例 .randrange() 优先；普通 callable 退化为浮点取整；缺省 → random 模块。"""
    if n <= 0:
        return 0
    if rng is None:
        import random

        return random.randrange(n)
    if hasattr(rng, "randrange"):
        return int(rng.randrange(n))  # type: ignore[union-attr]
    return min(n - 1, int(_rng_float(rng) * n))


def _draw_condition(cards: list) -> dict:
    """condition（默认）：按候选池顺序取第一个（顺序即优先级，DS01/L404-405）。"""
    return cards[0]


def _draw_random(cards: list, rng: object) -> dict:
    """random：条件过滤后按 weight 归一化加权随机（DS02/L406-407）。

    全 weight=0 或等权 → 纯随机等概率；weight=0 的牌不入加权池（P03）。
    """
    weights = [_weight_of(c) for c in cards]
    total = sum(w for w in weights if w > 0)
    if total <= 0:
        return cards[_rng_int(rng, len(cards))]  # 全 0/非法 → 纯随机等概率
    r = _rng_float(rng) * total
    acc = 0.0
    for card, w in zip(cards, weights):
        if w > 0:
            acc += w
            if r < acc:
                return card
    return cards[-1]  # 浮点兜底（r == total 边界）


def _draw_rotate(cards: list, state: Optional[MutableMapping]) -> dict:
    """rotate：轮转指针环形推进（DS03 工程补白新增/L28）。

    抽过的牌本轮不重复：每抽一次计数 +1，读取位 = 计数 % len（环形取模）——连抽 len 张覆盖全部后回到首张。
    指针由调用方持有的 state={"index": N} 持久化（工程补白⑤；N=已抽次数，读取位恒在 [0,len)）；
    state 缺省 → 每次从 0 开始（无持久化）。
    """
    idx = int(state.get("index", 0)) if state is not None else 0
    card = cards[idx % len(cards)]
    if state is not None:
        state["index"] = idx + 1
    return card


def draw_card(cards: object, strategy: object, rng: object = None,
              state: Optional[MutableMapping] = None) -> Optional[dict]:
    """SM03 抽牌：按策略从（条件过滤后的）候选池选一；空池 → None（孤寂卡上游判定）。

    - condition：顺序首个满足条件的牌（顺序即优先级）
    - random：weight 归一化加权随机；全 0/等权 → 纯随机
    - rotate：轮转指针环形推进（state={"index": N} 持久化）
    strategy 先经 normalize_strategy 归一（旧枚举兼容，裁决④）。
    """
    if not isinstance(cards, (list, tuple)) or not cards:
        return None
    strat = normalize_strategy(strategy)["strategy"]
    if strat == STRATEGY_ROTATE:
        return _draw_rotate(list(cards), state)
    if strat == STRATEGY_RANDOM:
        return _draw_random(list(cards), rng)
    return _draw_condition(list(cards))


# -------------------------------------------------------------------------------------
# 一次一物存档（npc_delivered，O07 工程补白②）
# -------------------------------------------------------------------------------------
def mark_delivered(ctx: Mapping[str, Any], npc_id: str, key: str, value: object = True) -> bool:
    """落 npc_delivered 存档标记（落玩家存档不落会话快照，O03）。ctx 缺节点 → False（fail-safe 不崩）。"""
    if not isinstance(npc_id, str) or not npc_id or not isinstance(key, str) or not key:
        return False
    node = ctx.get("npc_delivered")
    if not isinstance(node, MutableMapping):
        return False
    sub = node.get(npc_id)
    if not isinstance(sub, MutableMapping):
        sub = {}
        node[npc_id] = sub
    sub[key] = value
    return True


def is_delivered(ctx: Mapping[str, Any], npc_id: str, key: str) -> bool:
    """是否已交付（信息类置灰"已听"判定 / 池牌 once 出池判定）。"""
    return delivered_value(ctx, npc_id, key) is not None


def delivered_value(ctx: Mapping[str, Any], npc_id: str, key: str) -> object:
    """已交付值：once/intel/tutorial/池牌 = True；give_item daily = 最后领取日期键；未交付 = None。"""
    node = ctx.get("npc_delivered")
    if not isinstance(node, Mapping):
        return None
    sub = node.get(npc_id)
    if not isinstance(sub, Mapping):
        return None
    return sub.get(key)


# -------------------------------------------------------------------------------------
# 日期键（give_item daily 重置复用 A3 日界，工程补白③）
# -------------------------------------------------------------------------------------
def _today_key(ctx: Mapping[str, Any]) -> str:
    t = ctx.get("today")
    if isinstance(t, str) and t:
        return t
    now = ctx.get("now")
    return today_of(None, now=now if isinstance(now, int) else None, cfg=ctx.get("settings"))["today"]


# -------------------------------------------------------------------------------------
# heal 恢复量解析（AC03：int 或 "N%" 百分比串=按上限）
# -------------------------------------------------------------------------------------
def _heal_amount(v: object, ctx: Mapping[str, Any], stat: str) -> int:
    if isinstance(v, str) and v.strip().endswith("%"):
        try:
            pct = float(v.strip()[:-1])
        except ValueError:
            return 0
        cap = ctx.get("max_" + stat)
        if not isinstance(cap, (int, float)) or isinstance(cap, bool):
            return 0
        return max(0, int(cap * pct / 100))
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
        return int(v)
    return 0


def resolve_heal(heal: object, ctx: Mapping[str, Any]) -> dict:
    """heal{hp,mp} → 恢复量 {hp: int, mp: int}（int 直量 / "N%" 按 max 上限；非法 → 0 不含该键）。"""
    out: dict = {}
    if not isinstance(heal, Mapping):
        return out
    for stat in ("hp", "mp"):
        amount = _heal_amount(heal.get(stat), ctx, stat)
        if amount > 0:
            out[stat] = amount
    return out


# -------------------------------------------------------------------------------------
# 动作专属键（once/daily 记账 / 置灰判定）
# -------------------------------------------------------------------------------------
def _items_fingerprint(entry: Mapping[str, Any]) -> str:
    """give_item 稳定指纹：显式 key/id 优先；否则 items[] 的 id 序列。"""
    for k in ("key", "id"):
        v = entry.get(k)
        if isinstance(v, str) and v:
            return v
    items = entry.get("items")
    if isinstance(items, (list, tuple)):
        ids = []
        for it in items:
            if isinstance(it, Mapping):
                rid = it.get("id") or it.get("item")
                ids.append(str(rid) if rid is not None else "?")
            else:
                ids.append(str(it))
        if ids:
            return ",".join(ids)
    return "?"


def _give_item_keys(entry: Mapping[str, Any]) -> list:
    return [f"give_item:{_items_fingerprint(entry)}"]


def _intel_keys(entry: Mapping[str, Any]) -> list:
    refs = entry.get("intel_refs")
    if not isinstance(refs, (list, tuple)):
        return []
    return [f"intel:{r.get('id') if isinstance(r, Mapping) else r}" for r in refs if r]


def _tutorial_keys(entry: Mapping[str, Any]) -> list:
    refs = entry.get("tutorials")
    if not isinstance(refs, (list, tuple)):
        return []
    return [f"tutorial:{r.get('id') if isinstance(r, Mapping) else r}" for r in refs if r]


# -------------------------------------------------------------------------------------
# 10 类动作分发（interactions[] 与 dealer.pool[].deliver 共用，S3 裁决）
# -------------------------------------------------------------------------------------
def _action_quest(entry: Mapping[str, Any], ctx: Mapping[str, Any], **kw: Any) -> dict:
    """AC01 quest：候选任务+条件；去重由 quest_active/quest_daily 三表兜底（SM06）；顺序即优先级。"""
    deliver = {"quests": entry.get("quests")}
    avail = available_quests(deliver, ctx)
    if not avail:
        return _res("quest", False, kind="functional", reason="no_available_quest",
                    message="暂时没有可接的任务")
    return _res("quest", True, kind="functional", reason=None,
                data={"quest_id": avail[0]["quest_id"], "quests": [q["quest_id"] for q in avail]},
                message="接取任务")


def _action_shop(entry: Mapping[str, Any], ctx: Mapping[str, Any], **kw: Any) -> dict:
    """AC02 shop：shop_refs[] 打开后 = 当前商店（地图级状态，L76-80 / 2.2）。"""
    refs = entry.get("shop_refs")
    if not isinstance(refs, (list, tuple)) or not refs:
        return _res("shop", False, reason="no_shop_ref", message="这家店没有货架")
    # 工程补白：多 shop_refs 取第一个为当前商店（2.2「记录当前商店 = 该 NPC 的 shop_refs」）
    if isinstance(ctx, MutableMapping):
        ctx["current_shop_ref"] = refs[0]
    return _res("shop", True, kind="functional", data={"shop_ref": refs[0], "shop_refs": list(refs)},
                message="打开商店")


def _action_heal(entry: Mapping[str, Any], ctx: Mapping[str, Any], **kw: Any) -> dict:
    """AC03 heal：cost{coins} 治疗费（免费=省略）+ heal{hp,mp}（int 或 "N%" 按上限）。"""
    cost = entry.get("cost") if isinstance(entry.get("cost"), Mapping) else {}
    coins_cost = cost.get("coins", 0)
    if not isinstance(coins_cost, int) or isinstance(coins_cost, bool) or coins_cost < 0:
        coins_cost = 0
    currencies = ctx.get("currencies")
    if not isinstance(currencies, MutableMapping):
        return _res("heal", False, reason="missing_bucket", message="无法结算治疗费")
    if coins_cost and currencies.get("coins", 0) < coins_cost:
        return _res("heal", False, reason="insufficient_funds", data={"needed": coins_cost,
                                                                      "have": currencies.get("coins", 0)},
                    message="金币不足，无法治疗")
    healed = resolve_heal(entry.get("heal"), ctx)
    if not healed:
        return _res("heal", False, reason="no_heal_amount", message="治疗配置为空")
    # 应用恢复（封顶 max_hp/max_mp，纯函数就地改写 ctx）
    for stat, amount in healed.items():
        cur = ctx.get(stat, 0)
        cap = ctx.get("max_" + stat)
        if isinstance(cap, (int, float)) and not isinstance(cap, bool):
            cur = min(int(cap), int(cur) + amount)
        else:
            cur = int(cur) + amount
        if isinstance(ctx, MutableMapping):
            ctx[stat] = cur
    if coins_cost:
        currencies["coins"] = currencies.get("coins", 0) - coins_cost
    return _res("heal", True, kind="functional", data={"cost": coins_cost, "heal": healed},
                message=f"治疗完成（恢复 {_fmt_heal(healed)}）")


def _fmt_heal(healed: Mapping[str, Any]) -> str:
    parts = [f"{k.upper()}+{v}" for k, v in healed.items()]
    return "/".join(parts) if parts else "0"


def _action_give_item(entry: Mapping[str, Any], ctx: Mapping[str, Any], **kw: Any) -> dict:
    """AC04 give_item：items[]{id,count} 经 reward 解析器统一入账（L153/A1）+ repeat∈{once,daily}。"""
    npc_id = kw.get("npc_id") or ctx.get("npc_id")
    items = entry.get("items")
    if not isinstance(items, (list, tuple)) or not items:
        return _res("give_item", False, reason="no_items", message="没有可领取的补给")
    repeat = entry.get("repeat", "once")
    if repeat not in ("once", "daily"):
        repeat = "once"
    keys = _give_item_keys(entry)
    if npc_id and keys:
        key = keys[0]
        if repeat == "daily":
            today = _today_key(ctx)
            last = delivered_value(ctx, npc_id, key)
            if last == today:
                return _res("give_item", False, kind="functional", reason="daily_claimed",
                            already=True, message="今天已经领过了，明天再来")
        elif is_delivered(ctx, npc_id, key):
            return _res("give_item", False, kind="functional", reason="once_claimed",
                        already=True, message="已经领取过了")
    # 统一入账：A1 dispatch_reward（逐条目失败黄字跳过，不中断整批）
    r = dispatch_reward(items, ctx)
    if not r.get("ok"):
        return _res("give_item", False, reason="reward_failed", data={"skipped": r.get("skipped", [])},
                    message="领取失败")
    if npc_id and keys:
        if repeat == "daily":
            mark_delivered(ctx, npc_id, keys[0], _today_key(ctx))
        else:
            mark_delivered(ctx, npc_id, keys[0])
    # granted/skipped 顶层透出（对齐 A1 dispatch_reward 返回形态 {ok, granted, skipped}）
    return _res("give_item", True, kind="functional",
                granted=r.get("granted", []), skipped=r.get("skipped", []),
                data={"granted": r.get("granted", []), "skipped": r.get("skipped", [])},
                message="领取补给")


def _action_buff(entry: Mapping[str, Any], ctx: Mapping[str, Any], **kw: Any) -> dict:
    """AC05 buff：effects[] 临时增益 + turns 持续回合（同 buff 重触发仅刷新回合，补白⑥）。"""
    effects = entry.get("effects")
    if not isinstance(effects, (list, tuple)) or not effects:
        return _res("buff", False, reason="no_effects", message="没有可施加的增益")
    turns = entry.get("turns")
    active = ctx.get("active_effects")
    if not isinstance(active, MutableMapping):
        return _res("buff", False, reason="no_effect_bucket", message="当前无法施加增益")
    granted: list = []
    skipped: list = []
    for eff in effects:
        if isinstance(eff, Mapping):
            eid = eff.get("id") or eff.get("effect")
            eturns = eff.get("turns", turns)
        else:
            eid, eturns = eff, turns
        if not isinstance(eid, str) or not eid:
            skipped.append({"effect": eff, "reason": "invalid_value"})
            continue
        t = eturns if (isinstance(eturns, int) and not isinstance(eturns, bool) and eturns >= 0) else None
        prev = active.get(eid)
        active[eid] = {"effect": eid, "turns": t, "refreshed": prev is not None}
        granted.append({"effect": eid, "turns": t, "refreshed": prev is not None})
    if not granted:
        return _res("buff", False, reason="buff_failed", data={"skipped": skipped}, message="增益无效")
    return _res("buff", True, kind="functional", data={"effects": granted, "skipped": skipped},
                message="获得临时增益")


def _action_repair(entry: Mapping[str, Any], ctx: Mapping[str, Any], **kw: Any) -> dict:
    """AC06 repair：依赖装备耐久系统（框架未实现）→ 当前降级不可用+友好提示（S4/L139/AC06）。"""
    return _res("repair", False, kind="degraded", reason="repair_unavailable",
                message="没有需要修理的装备")


def _action_teleport(entry: Mapping[str, Any], ctx: Mapping[str, Any], **kw: Any) -> dict:
    """AC07 teleport：map 传送目标 + cost 传送费（免费=省略）；纯函数扣费+改写 ctx["map_id"]（补白⑦）。"""
    target = entry.get("map")
    if not isinstance(target, str) or not target:
        return _res("teleport", False, reason="no_target", message="没有传送目的地")
    cost = entry.get("cost") if isinstance(entry.get("cost"), Mapping) else {}
    coins_cost = cost.get("coins", 0)
    if not isinstance(coins_cost, int) or isinstance(coins_cost, bool) or coins_cost < 0:
        coins_cost = 0
    currencies = ctx.get("currencies")
    if coins_cost:
        if not isinstance(currencies, MutableMapping):
            return _res("teleport", False, reason="missing_bucket", message="无法结算传送费")
        if currencies.get("coins", 0) < coins_cost:
            return _res("teleport", False, reason="insufficient_funds", data={"needed": coins_cost,
                                                                              "have": currencies.get("coins", 0)},
                        message="金币不足，无法传送")
        currencies["coins"] = currencies.get("coins", 0) - coins_cost
    if isinstance(ctx, MutableMapping):
        ctx["map_id"] = target
    return _res("teleport", True, kind="functional", data={"map": target, "cost": coins_cost},
                message=f"传送到 {target}")


def _action_intel(entry: Mapping[str, Any], ctx: Mapping[str, Any], **kw: Any) -> dict:
    """AC08 intel：intel_refs[] 图鉴情报；一次一物交付后置灰"已听"（O01-O02/L86-87）+ 写图鉴（L89/O04）。"""
    npc_id = kw.get("npc_id") or ctx.get("npc_id")
    keys = _intel_keys(entry)
    if not keys:
        return _res("intel", False, reason="no_intel_ref", message="没有可打听的情报")
    # 已交付标记逐 ref（O07）：已听 → 无新内容
    if npc_id:
        heard = [k for k in keys if is_delivered(ctx, npc_id, k)]
        if len(heard) == len(keys):
            return _res("intel", False, kind="info", reason="already_heard", already=True,
                        message="你已经听过了")
    # 交付：写图鉴（codex_state，复用既有图鉴解锁；O07/1e 口径）+ 标记已听
    unlocked: list = []
    for k, ref in zip(keys, entry.get("intel_refs") or []):
        cs = ctx.get("codex_state")
        if isinstance(cs, MutableMapping):
            rid = ref.get("id") if isinstance(ref, Mapping) else ref
            cs[rid] = True  # type: ignore[index]
        if npc_id:
            mark_delivered(ctx, npc_id, k)
        unlocked.append(k)
    return _res("intel", True, kind="info", data={"intel_refs": unlocked, "codex": list(unlocked)},
                delivered=True, message="情报已记入图鉴")


def _action_tutorial(entry: Mapping[str, Any], ctx: Mapping[str, Any], **kw: Any) -> dict:
    """AC09 tutorial：tutorials[] 教学（first_meet 仅首见触发）；首见即一次，可回看（L172/L347）。"""
    npc_id = kw.get("npc_id") or ctx.get("npc_id")
    keys = _tutorial_keys(entry)
    if not keys:
        return _res("tutorial", False, reason="no_tutorial", message="没有可教的课程")
    if npc_id and all(is_delivered(ctx, npc_id, k) for k in keys):
        return _res("tutorial", False, kind="info", reason="already_taught", already=True,
                    message="你已经学过了（可在教学回看复习）")
    if npc_id:
        for k in keys:
            mark_delivered(ctx, npc_id, k)
    return _res("tutorial", True, kind="info", data={"tutorials": [k for k in keys]},
                delivered=True, message="教学讲解")


def _action_reply(entry: Mapping[str, Any], ctx: Mapping[str, Any], **kw: Any) -> dict:
    """AC10 reply：text[] 聊天回复（随机/循环取一条，mode ∈ random|cycle 补白⑤；闲聊不触发一次一物）。"""
    texts = entry.get("text")
    if isinstance(texts, str):
        texts = [texts]
    if not isinstance(texts, (list, tuple)) or not texts:
        return _res("reply", False, reason="no_text", message="……")
    mode = entry.get("mode", "random")
    if mode == "cycle":
        state = kw.get("state")
        idx = int(state.get("reply_index", 0)) % len(texts) if state is not None else 0
        if state is not None:
            state["reply_index"] = idx + 1
        text = texts[idx]
    else:
        text = texts[_rng_int(kw.get("rng"), len(texts))]
    return _res("reply", True, kind="functional", data={"text": text}, message=str(text))


_HANDLERS: dict = {
    "quest": _action_quest,
    "shop": _action_shop,
    "heal": _action_heal,
    "give_item": _action_give_item,
    "buff": _action_buff,
    "repair": _action_repair,
    "teleport": _action_teleport,
    "intel": _action_intel,
    "tutorial": _action_tutorial,
    "reply": _action_reply,
}


def dispatch_action(entry: object, ctx: Mapping[str, Any], rng: object = None,
                    npc_id: Optional[str] = None, state: Optional[MutableMapping] = None) -> dict:
    """10 类动作统一分发（interactions[] 与 dealer.pool[].deliver 共用，S3 裁决）。

    entry: {action, condition?, …action 专属子字段}（AC01-AC10 统一条目）。
    公共 condition（AC 全列共用 / L175）：不满足 → 不执行（ok=False, reason=condition_not_met；
    显示/隐藏/置灰由调用方按作者配置呈现）。
    ctx: 结算上下文 dict（就地改写 currencies/hp/mp/map_id/current_shop_ref/active_effects/
         npc_delivered/codex_state 等）；rng 注入确定性；state 供 reply cycle 复用。
    """
    if not isinstance(entry, Mapping):
        return _res("invalid", False, reason="invalid_entry", message="动作配置非法")
    action = entry.get("action")
    if action not in ACTIONS:
        return _res("invalid", False, reason="unknown_action",
                    data={"action": action}, message=f"未知动作 {action!r}")
    cond = entry.get("condition")
    if cond is not None and not eval_condition(cond, ctx):
        return _res(action, False, reason="condition_not_met",
                    message="需要先满足条件")
    return _HANDLERS[action](entry, ctx, rng=rng, npc_id=npc_id, state=state)


# -------------------------------------------------------------------------------------
# 发牌员主入口（SM02-05：牌池构建 → 抽牌 → 交付 → 孤寂卡）
# -------------------------------------------------------------------------------------
def deal(npc_id: str, dealer: object, ctx: Mapping[str, Any], rng: object = None,
         rotate_state: Optional[MutableMapping] = None, greeting: object = None) -> dict:
    """发牌员抽牌状态机②-⑤（SM01 visible 判定由调用方负责：map 挂点内 + visible=true）。

    流程：牌池构建（条件过滤 + once 出池 + quest 去重）→ 按策略抽一张 → 交付（dispatch_action）
          → 无牌可抽 = 孤寂卡（普通问候 greeting 兜底，不交付任何内容，L412/L509）。

    返回（抽中）：
      {ok, action, kind, strategy, card, data/granted/skipped/...}（交付结果 + 命中牌信息）
    返回（孤寂卡）：
      {ok: True, strategy, card: None, lonely: True, reason: "empty_pool"|"no_cards",
       message: greeting 兜底}

    牌级 once（P05）：交付成功 → 落 npc_delivered["card:<id>"]（出池，全局去重语义仍生效）。
    """
    npc_id = npc_id or ctx.get("npc_id") or ""
    base = {"strategy": normalize_strategy(dealer.get("strategy") if isinstance(dealer, Mapping) else None)["strategy"]}
    if not isinstance(dealer, Mapping) or not isinstance(dealer.get("pool"), (list, tuple)):
        return {**base, "ok": True, "card": None, "lonely": True, "reason": "no_dealer_pool",
                "message": str(greeting) if greeting is not None else ""}
    cards = build_pool(dealer.get("pool"), ctx, npc_id=npc_id)
    if not cards:
        return {**base, "ok": True, "card": None, "lonely": True, "reason": "empty_pool",
                "message": str(greeting) if greeting is not None else ""}
    card = draw_card(cards, base["strategy"], rng=rng, state=rotate_state)
    if card is None:
        return {**base, "ok": True, "card": None, "lonely": True, "reason": "empty_pool",
                "message": str(greeting) if greeting is not None else ""}
    deliver = card.get("deliver") if isinstance(card, Mapping) else None
    res = dispatch_action(deliver, ctx, rng=rng, npc_id=npc_id, state=rotate_state)
    # 牌级 once（P05）：交付成功 → 落 npc_delivered（出池）；失败不记（下次仍可抽）
    if isinstance(card, Mapping) and card.get("once") and res.get("ok") and npc_id:
        cid = card.get("id")
        if cid:
            mark_delivered(ctx, npc_id, f"card:{cid}")
    res["card"] = card
    res["strategy"] = base["strategy"]
    return res
