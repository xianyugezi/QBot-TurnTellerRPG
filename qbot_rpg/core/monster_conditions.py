"""怪物条件行动引擎（M2 怪物体系 · B2 路：15 类触发完整评估器）。

依据：细化_1f_怪物AI状态机.md（② L3 条件行动——15 类触发匹配、priority 降序同级随机、
once/max_triggers/trigger_cooldown 过滤；① 1.2 决策管线总图 L3 行；⑤ 5.2 chain C 模型）
+ docs/m2_shared_contract.md 第一节（special_actions 条目结构 / trigger 15 类枚举 /
旧别名归一 / timing）+ 第五节（evaluate_conditions 返回约定）+ 第八节铁律。
印记扩展（enemy_mark/player_mark）2026-09-02 框架级新增：读 battle 印记，schema 见
_eval_enemy_mark / _eval_player_mark docstring；校验侧见 content/validator.py A06a。

纯规则引擎，零 NoneBot import（铁律 2）。本模块不产出概率数值；after_action 的
chance(0-100) 在内部折算小数与 rng 比较（铁律 5 口径）。随机一律走注入 rng（铁律 6，
可复现）；需随机决策（after_action chance roll / 同级随机排序）而未注入 rng → 抛 ValueError。

产出形态（供 MonsterAI._l3_conditions 消费，contract §五 evaluate_conditions 返回约定）：
  匹配条目列表 = special_actions[] 原始条目（含 action/priority/chain_ref/post_state 等），
  按 priority 降序、同级随机排列；队首 = 本次应执行条目。消费方取 matches[0] 产出，
  chain_ref 交给 MonsterAI._produce 入队（本模块不执行入队）。

工程收敛（设计文档未显式定义处，显式标注供审查）：
  1. 记账口径「匹配即触发」：commit=True（默认）时对**队首**条目记账（once 标记 /
     max_triggers 计数 / trigger_cooldown 登记）并应用 post_state（触发后进入状态）。
     once 条目只触发一次（TC-05「once=true 仅触发一次」口径）；多条目同时匹配时仅队首
     记账——低优 once 条目被 L3 短路丢弃不记账，后续回合仍可触发（语义=每条目仅触发一次）。
  2. 记账键：special_action.id；无 id → "{action}|{type}|{value}" 组合键（A04 id 选填）。
  3. ai_state 扩展键（14 键快照之外，跨模块契约 additive，battle 快照整体透传）：
       trigger_used_once: list   # once 已触发条目键
       trigger_counts:    dict   # {key: 已触发次数}
       trigger_cooldowns: dict   # contract 既有键 {special_action_id: 剩余回合}
       post_state:        dict   # 最近生效 {state, turns, until}（过期由 C1 回合边界处理，
                                 #   本模块只登记生效不管理过期）
  4. timing 口径：first_turn → 仅 turn<=1 匹配；current_turn/next_turn → 不设门
     （执行时机由 C1/battle 侧决定，本模块不调度——A08 timing 语义）。
  5. after_action 参数完整性：缺 action 或 chance → 不匹配返回空（对齐 A2 R11 硬拦口径）。
  6. 旧别名归一：broken/revive/enter_phase → pv_broken/get_up/battle_start（contract §一；
     1e A06 其余旧名 phase_below/cooldown_ready/turn_elapsed/chain_complete/tag_trigger/
     delayed 无 canonical 映射 → 运行时永不匹配，由校验器黄提示迁移）。
"""

from typing import Any, Callable, Dict, List, Mapping, Optional, TypeVar, Union

__all__ = [
    "TRIGGER_TYPES",
    "OLD_TRIGGER_ALIASES",
    "normalize_trigger_type",
    "register_condition",
    "evaluate_conditions_all",
]

_F = TypeVar("_F", bound=Callable[[Mapping, Mapping, Any], bool])

# 触发类型权威枚举（contract §一 / 细化_1e A06 S3，权威=怪物行动AI定稿 §二）
# 15 类 = 定稿 13 类 + 印记扩展 2 类（enemy_mark/player_mark，2026-09-02 框架级新增：
#   纯配置读 battle 内印记（含玩家施加的敌侧印记），支撑内容包"部位技无破坏印记才可用"
#   "困斗满才宣泄"等状态响应；schema 见 monster_conditions docstring 附录 B）
TRIGGER_TYPES: tuple = (
    "hp_below", "pv_broken", "get_up", "battle_start", "after_action",
    "player_status", "player_hp_below", "turn_count", "phase_changed",
    "zone_changed", "ally_dead", "combo_broken", "script",
    "enemy_mark", "player_mark",
)

# 旧别名归一（contract §一「旧别名接受（兼容）」；canonical = 权威枚举名，1e A06 S4）
OLD_TRIGGER_ALIASES: Dict[str, str] = {
    "broken": "pv_broken",      # 防护崩溃后 → pv_broken（1e A06 ②）
    "revive": "get_up",         # 起身后 → get_up（1e A06 ③）
    "enter_phase": "battle_start",  # 进入战斗时 → battle_start（1e A06 ④）
}

# 自定义条件扩展注册表：register_condition(type, fn) 登记（x_ 前缀内置类型 + 任意自定义名）
_CUSTOM_HANDLERS: Dict[str, Callable[[Mapping, Mapping, Any], bool]] = {}


def normalize_trigger_type(t: str) -> str:
    """触发类型归一：旧别名 → canonical；x_ 前缀/未知名原样返回（注册表兜底）。"""
    if not isinstance(t, str):
        return ""
    return OLD_TRIGGER_ALIASES.get(t, t)


def register_condition(
    trigger_type: str,
    fn: Optional[_F] = None,
) -> Union[_F, Callable[[_F], _F]]:
    """注册自定义条件求值器（扩展口）。fn(trigger, battle_state, rng) -> bool。

    两种调用形态：
      register_condition("x_custom", my_fn)          # 直接注册
      @register_condition("x_custom")                # 装饰器
      def my_fn(trig, bstate, rng): ...

    可注册：x_ 前缀扩展类型、script 类型覆盖、或任意新触发名（未知名经本表兜底）。
    注册的 handler 优先于内建（同型覆盖）。
    """
    def _reg(f: _F) -> _F:
        _CUSTOM_HANDLERS[trigger_type] = f
        return f

    if fn is None:
        return _reg
    return _reg(fn)


# ================================================================ 主入口

def evaluate_conditions_all(
    special_actions: List[Mapping[str, Any]],
    battle_state: Mapping[str, Any],
    rng: Any = None,
    commit: bool = True,
) -> List[Mapping[str, Any]]:
    """L3 条件行动完整评估（15 类触发 + 过滤 + 排序）。返回匹配条目列表（队首=应执行条目）。

    参数：
      special_actions: enemies.json special_actions[]（contract §一条目结构）
      battle_state: 战斗快照（须含 ai_state 键；enemy/turn/players/allies/last_action/
                    downed/battle_start/zone_changed/combo_broken/script_flags 按类型读取）
      rng: 注入随机源（random.Random 或带 random() 的对象，铁律 6）；after_action 匹配
           需 roll 或同级随机排序时必传，缺失 → ValueError
      commit: True=对队首记账（once/max_triggers/trigger_cooldown）+ 应用 post_state；
              False=纯匹配（不记账，查询用）

    返回：匹配条目列表（原始 special_action 条目，含 action/priority/chain_ref/post_state），
    按 priority 降序、同级随机；无匹配返回 []（=L3 无产出，落 L4）。
    """
    ai = _ensure_ai_state(battle_state)
    turn = int(battle_state.get("turn", 0))

    matched: List[Mapping[str, Any]] = []
    for sa in special_actions:
        if not isinstance(sa, Mapping):
            continue
        trig = sa.get("trigger")
        if not isinstance(trig, Mapping) or not trig.get("type"):
            continue
        ttype = normalize_trigger_type(str(trig["type"]))
        if not ttype:
            continue
        key = _entry_key(sa, ttype)
        # 过滤：once / max_triggers / trigger_cooldown（1f ②L3 / 核心规则5）
        if _filtered(ai, sa, key):
            continue
        # timing：first_turn → 仅第一回合（A08；current/next_turn 不设门）
        if trig.get("timing") == "first_turn" and turn > 1:
            continue
        # 条件求值（内建 15 类 + 注册表扩展；未注册未知类型 → False）
        if not _match(ttype, trig, battle_state, ai, rng):
            continue
        matched.append(dict(sa))  # 浅拷贝，防消费方误改 enemy_def 原条目

    if not matched:
        return []

    # priority 降序、同级随机（核心规则5；稳定排序保同级乱序）
    _shuffle(matched, _resolve_rng(rng))
    matched.sort(key=lambda e: -float(e.get("priority", 0) or 0))

    if commit:
        head = matched[0]
        _mark_triggered(ai, head, _entry_key(head, normalize_trigger_type(
            (head.get("trigger") or {}).get("type") or "")), battle_state)
        _apply_post_state(ai, head, battle_state)
    return matched


# ================================================================ 内建条件求值

def _match(ttype: str, trig: Mapping[str, Any], bs: Mapping[str, Any],
           ai: Mapping[str, Any], rng: Any) -> bool:
    """条件求值分发：注册表 handler 优先 → 内建 → 未注册未知类型 False。"""
    handler = _CUSTOM_HANDLERS.get(ttype)
    if handler is not None:
        return bool(handler(trig, bs, rng))
    fn = _BUILTIN_HANDLERS.get(ttype)
    if fn is None:
        return False
    return bool(fn(trig, bs, ai, rng))


def _eval_hp_below(trig, bs, ai, rng) -> bool:
    """hp_below：敌方 HP 百分比严格小于 value（百分比阈值；B1 内建口径 hp_ratio < value）。
    对齐 monster_ai._hp_ratio：enemy.hp / enemy.max_hp * 100 < value。"""
    enemy = bs.get("enemy") or {}
    hp = float(enemy.get("hp", 0))
    mhp = float(enemy.get("max_hp", 0))
    if mhp <= 0:
        return False
    return hp / mhp * 100.0 < float(trig.get("value", 0))


def _eval_pv_broken(trig, bs, ai, rng) -> bool:
    """pv_broken：防护崩溃（enemy.pv <= 0；B1 内建口径 float(pv,1)<=0）。"""
    enemy = bs.get("enemy") or {}
    return float(enemy.get("pv", 1)) <= 0


def _eval_get_up(trig, bs, ai, rng) -> bool:
    """get_up：起身后触发（TC-05：downed → 起身 → 下一回合套间评估 get_up 条件行动）。
    匹配窗口：battle_state["downed"]=True 或 ai_state.exec_state == "downed"
    （C1 侧在起身动画后、L3 评估前保留标记一回合）。"""
    if bs.get("downed"):
        return True
    return (ai.get("exec_state") or "") == "downed"


def _eval_battle_start(trig, bs, ai, rng) -> bool:
    """battle_start：进入战斗时（开场技：第一回合、换区后第一回合，1e A06 ④）。
    匹配：battle_state["battle_start"]=True（含换区重触发）或 turn<=1。"""
    if bs.get("battle_start"):
        return True
    return int(bs.get("turn", 0)) <= 1


def _eval_after_action(trig, bs, ai, rng) -> bool:
    """after_action：特定行动后（固定连招锚点，A09）。必带 action+chance(0-100)；
    缺任一 → 不匹配（A2 R11 硬拦口径）。匹配 battle_state["last_action"] == trigger.action
    后再 roll：rng*100 < chance 才入列（chance roll 消耗注入 rng，可复现）。"""
    target = trig.get("action")
    chance = trig.get("chance")
    if not target or chance is None:
        return False
    if bs.get("last_action") != target:
        return False
    chance = float(chance)
    if chance <= 0:
        return False
    r = float(_resolve_rng(rng).random())
    return r * 100.0 < chance


def _eval_player_status(trig, bs, ai, rng) -> bool:
    """player_status：玩家持有指定状态/效果（value=效果 id）。任一玩家命中即成立。
    读取 battle_state["players"]（list）：statuses 列表 id 或 effects 列表 {id,...}。"""
    want = trig.get("value")
    if not want:
        return False
    for p in bs.get("players") or []:
        if not isinstance(p, Mapping):
            continue
        st = p.get("statuses") or []
        if isinstance(st, str):
            st = [st]
        if want in st:
            return True
        for e in p.get("effects") or []:
            if isinstance(e, Mapping) and e.get("id") == want:
                return True
            if e == want:
                return True
    return False


def _mark_count_on(bs: Mapping[str, Any], side: str, mark: Any) -> int:
    """读 battle_state.marks_state[side] 中指定印记（mark_id 或冗余 name）的层数。
    缺段/缺实例 → 0（防御性，对齐 MarksManager.count_by_name 口径；battle 五块快照
    marks_state 为 {player: [实例], enemy: [实例]}，实例含 mark_id/name/count）。"""
    if not mark:
        return 0
    ms = bs.get("marks_state")
    if not isinstance(ms, Mapping):
        return 0
    insts = ms.get(side)
    if not isinstance(insts, list):
        return 0
    want = str(mark)
    for inst in insts:
        if not isinstance(inst, Mapping):
            continue
        if inst.get("mark_id") == want or inst.get("name") == want:
            return max(0, int(inst.get("count", 0) or 0))
    return 0


def _eval_enemy_mark(trig, bs, ai, rng) -> bool:
    """enemy_mark：敌方身上印记（含玩家施加的敌侧印记）条件触发。

    trigger schema（纯配置，值全部来自配置，零硬编码）：
      {"type":"enemy_mark","mark":"<mark_id|name>"}            存在（层数≥1）
      {"type":"enemy_mark","mark":"<id>","absent":true}        不存在（层数==0）
      {"type":"enemy_mark","mark":"<id>","min":6}              层数≥6
      {"type":"enemy_mark","mark":"<id>","max":2}              层数≤2
      {"type":"enemy_mark","mark":"<id>","min":2,"max":4}      区间 [2,4]
    语义：absent=true 优先（返回层数==0）；否则 min/max 夹取（缺省不限）。
    读取 marks_state["enemy"]（对齐 MarksManager.count_by_name：mark_id 或冗余 name
    均可匹配，同 (side,mark) 单实例聚合）。缺 marks_state 段 → 层数 0 → absent 成立/
    存在不成立（安全失败，对齐既有 handler 防御口径）。
    """
    return _match_mark_trigger(trig, bs, "enemy")


def _eval_player_mark(trig, bs, ai, rng) -> bool:
    """player_mark：玩家身上印记条件触发（schema 同 enemy_mark，side=player）。
    读取 marks_state["player"]；支持任一玩家实例命中（marks_state.player 已聚合为
    单实例列表，直接按 mark 匹配层数即可）。"""
    return _match_mark_trigger(trig, bs, "player")


def _match_mark_trigger(trig: Mapping[str, Any], bs: Mapping[str, Any],
                        side: str) -> bool:
    """印记触发统一求值（enemy_mark/player_mark 共用）：
      absent=true   → 要求层数==0
      否则（存在判定）→ min/max 夹取；min/max 均缺省 → 层数≥1（存在）
    mark 缺失/非字符串 → False（防御性；校验器侧红拦 R-5，引擎侧安全失败）。"""
    mark = trig.get("mark")
    if not isinstance(mark, str) or not mark:
        return False
    count = _mark_count_on(bs, side, mark)
    if trig.get("absent"):
        return count == 0
    lo = trig.get("min")
    hi = trig.get("max")
    if lo is None and hi is None:
        return count >= 1
    if lo is not None and count < int(lo):
        return False
    if hi is not None and count > int(hi):
        return False
    return True


def _eval_player_hp_below(trig, bs, ai, rng) -> bool:
    """player_hp_below：任一玩家 HP 百分比严格小于 value（与 hp_below 同口径，作用于玩家）。
    无玩家 → False。"""
    val = float(trig.get("value", 0))
    ratios = []
    for p in bs.get("players") or []:
        if not isinstance(p, Mapping):
            continue
        hp = float(p.get("hp", 0))
        mhp = float(p.get("max_hp", 0))
        if mhp > 0:
            ratios.append(hp / mhp * 100.0)
    if not ratios:
        return False
    return min(ratios) < val


def _eval_turn_count(trig, bs, ai, rng) -> bool:
    """turn_count：回合数比较（op 默认 >=；B1 内建口径）。battle_state["turn"]。"""
    op = trig.get("op", ">=")
    cur = int(bs.get("turn", 0))
    val = float(trig.get("value", 0))
    return {"<": cur < val, "<=": cur <= val,
            ">": cur > val, ">=": cur >= val,
            "==": cur == val}.get(op, False)


def _eval_phase_changed(trig, bs, ai, rng) -> bool:
    """phase_changed：阶段进入判定（value=阶段号，phase>=value 即成立；B1 内建口径，
    保持一致性——名称含 changed，口径=当前 phase 已达到该阶段）。"""
    val = trig.get("value")
    if val is None:
        return False
    return int(ai.get("phase", 1)) >= int(val)


def _eval_zone_changed(trig, bs, ai, rng) -> bool:
    """zone_changed：换区（换区后第一回合触发 battle_start 联动由 C1 标记）。
    匹配：battle_state["zone_changed"]=True 或 (zone 与 prev_zone 均存在且不同)。"""
    if bs.get("zone_changed"):
        return True
    zone = bs.get("zone")
    prev = bs.get("prev_zone")
    return bool(zone) and bool(prev) and zone != prev


def _eval_ally_dead(trig, bs, ai, rng) -> bool:
    """ally_dead：友方（除自身外）阵亡。value=指定友方 id（选填）；缺省=任一友方阵亡。
    读取 battle_state["allies"]（list，条目 {id?, hp?, alive?, dead?}）；阵亡判定：
    hp<=0 或 alive=False 或 dead=True。"""
    want = trig.get("value")
    allies = bs.get("allies") or []
    if not allies:
        return False
    for a in allies:
        if not isinstance(a, Mapping):
            continue
        if want is not None and a.get("id") != want:
            continue
        if a.get("alive") is False or a.get("dead") is True:
            return True
        if float(a.get("hp", 1)) <= 0:
            return True
    return False


def _eval_combo_broken(trig, bs, ai, rng) -> bool:
    """combo_broken：本回合连招被打断（玩家 interrupt 命中 → 断链，contract §六接线；
    C1 在打断时置 battle_state["combo_broken"]=True）。"""
    return bool(bs.get("combo_broken"))


def _eval_script(trig, bs, ai, rng) -> bool:
    """script：脚本触发（value=脚本 key）。读取 battle_state["script_flags"][value] 为真。
    复杂脚本可经 register_condition("script", fn) 覆盖。"""
    key = trig.get("value")
    if not key:
        return False
    flags = bs.get("script_flags") or {}
    return bool(flags.get(key))


_BUILTIN_HANDLERS: Dict[str, Callable] = {
    "hp_below": _eval_hp_below,
    "pv_broken": _eval_pv_broken,
    "get_up": _eval_get_up,
    "battle_start": _eval_battle_start,
    "after_action": _eval_after_action,
    "player_status": _eval_player_status,
    "player_hp_below": _eval_player_hp_below,
    "turn_count": _eval_turn_count,
    "phase_changed": _eval_phase_changed,
    "zone_changed": _eval_zone_changed,
    "ally_dead": _eval_ally_dead,
    "combo_broken": _eval_combo_broken,
    "script": _eval_script,
    # 印记扩展 2 类（2026-09-02 框架级新增，schema 见上两函数 docstring）
    "enemy_mark": _eval_enemy_mark,
    "player_mark": _eval_player_mark,
}


# ================================================================ 过滤/记账/工具

def _filtered(ai: Mapping[str, Any], sa: Mapping[str, Any], key: str) -> bool:
    """触发过滤：once（已触发）/ max_triggers（达上限）/ trigger_cooldown（冷却中）。"""
    if sa.get("once"):
        used = ai.get("trigger_used_once") or []
        if key in used:
            return True
    mx = sa.get("max_triggers")
    if mx is not None and float(mx) > 0:
        cnt = int((ai.get("trigger_counts") or {}).get(key, 0))
        if cnt >= int(mx):
            return True
    cds = ai.get("trigger_cooldowns") or {}
    if int(cds.get(key, 0)) > 0:
        return True
    return False


def _mark_triggered(ai: Dict[str, Any], sa: Mapping[str, Any], key: str,
                    bs: Mapping[str, Any]) -> None:
    """队首条目记账（commit=True）：once 标记 / max_triggers 计数 / trigger_cooldown 登记。
    冷却键用条目 key（与 _filtered 同键口径）。"""
    if sa.get("once"):
        ai.setdefault("trigger_used_once", [])
        if key not in ai["trigger_used_once"]:
            ai["trigger_used_once"].append(key)
    mx = sa.get("max_triggers")
    if mx is not None and float(mx) > 0:
        ai.setdefault("trigger_counts", {})
        ai["trigger_counts"][key] = int(ai["trigger_counts"].get(key, 0)) + 1
    cd = sa.get("trigger_cooldown")
    if cd is not None and int(cd) > 0:
        ai.setdefault("trigger_cooldowns", {})
        ai["trigger_cooldowns"][key] = int(cd)


def _apply_post_state(ai: Dict[str, Any], sa: Mapping[str, Any],
                      bs: Mapping[str, Any]) -> None:
    """post_state 生效：ai_state.state 切到 post_state.state；turns 记入扩展键 post_state
    {state, turns, until}（until = 当前回合 + turns，过期处理归 C1 回合边界）。"""
    ps = sa.get("post_state")
    if not isinstance(ps, Mapping) or not ps.get("state"):
        return
    state = str(ps["state"])
    turns = int(ps.get("turns") or 0)
    ai["state"] = state
    ai["post_state"] = {
        "state": state,
        "turns": turns,
        "until": int(bs.get("turn", 0)) + turns,
    }


def _entry_key(sa: Mapping[str, Any], ttype: str) -> str:
    """记账键：special_action.id（选填，A04）优先；无 id → "{action}|{type}|{value}"。"""
    sid = sa.get("id")
    if sid:
        return str(sid)
    trig = sa.get("trigger") or {}
    return "{}|{}|{}".format(sa.get("action"), ttype, trig.get("value"))


def _shuffle(items: List[Any], rng: Any) -> None:
    """Fisher-Yates（rng.random() 注入，兼容任意带 random() 的对象；铁律 6）。"""
    for i in range(len(items) - 1, 0, -1):
        j = int(rng.random() * (i + 1))
        items[i], items[j] = items[j], items[i]


def _resolve_rng(rng: Any) -> Any:
    """rng 就位：注入优先；None 时仅无随机决策路径可用（需 roll → 抛 ValueError，铁律 6
    禁止裸 random——不给隐式系统随机源）。"""
    if rng is not None:
        return rng
    raise ValueError(
        "monster_conditions: 需随机决策（after_action chance roll / 同级随机排序）但未注入 rng"
    )


def _ensure_ai_state(bs: Mapping[str, Any]) -> Dict[str, Any]:
    """ai_state 就位：缺键补默认（对齐 contract §五 14 键 + 本模块扩展键）；
    与 monster_ai._default_ai_state 同构，本模块独立内联避免跨模块耦合。"""
    ai = bs.get("ai_state")
    if not isinstance(ai, dict):
        ai = {}
        # 缺省不可原地回写（bs 可能为 Mapping 只读）→ 由调用方保证 bs 为 dict 且含 ai_state
        raise ValueError("battle_state['ai_state'] 缺失或非 dict（须由调用方/MonsterAI 先确保）")
    defaults = {
        "state": "normal", "exec_state": "idle", "phase": 1,
        "chain_pos": 0, "chain_queue": [], "chain_id": None,
        "chain_cooldowns": {}, "charge": None,
        "trigger_cooldowns": {}, "action_cooldowns": {},
        "hungry_count": {}, "intent": {}, "forced_queue": [], "boss_phase": 1,
    }
    for k, v in defaults.items():
        ai.setdefault(k, v)
    ai.setdefault("trigger_used_once", [])
    ai.setdefault("trigger_counts", {})
    return ai
