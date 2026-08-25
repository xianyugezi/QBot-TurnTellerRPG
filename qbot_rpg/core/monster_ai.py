"""怪物 AI 决策引擎（M2 怪物体系 · B1 路：决策管线核心 + 两级状态机 + 随机行动池）。

依据：细化_1f_怪物AI状态机.md（① 两级状态机+执行态迁移表+1.2 决策管线总图+1.3 关键场景语义；
② L0-L7 套间评估口径表；④ 行动表解析 4.1 字段语义+4.2 归一化规则）+ docs/m2_shared_contract.md
第五节（AI 引擎接口契约：MonsterAI 签名、ai_state 快照 14 键、L0-L7 决策管线、优先级总则）+
第八节铁律。行动执行侧复用玩家伤害通道（contract §六：T24 同构双库语义）。

纯规则引擎，零 NoneBot import（细化_3a R1 / 铁律 2）。
无状态设计（铁律契约）：运行时**不持有状态**——ai_state 以 battle 快照为权威，
本引擎只读写 `battle_state["ai_state"]`（传入 dict 原地更新，决策后经返回 action_dict
的 `ai_state` 键回灌快照，contract §六「决策后回灌快照（吸收返回）」）。
随机一律走注入 rng（random.Random 或带 random()/choice() 的对象，铁律 6，可复现）；
概率输出一律小数 fraction（铁律 5）。

本路范围（B1）+ 已接线（B2/B3 委托，2026-08-26 主 agent 收口）：两级状态机（行为态
normal/enraged/dying+配置自定义 / 执行态 idle/in_chain/charging/downed）、L0 套内门（链推进/蓄力结算）、
L1 状态机切换（transitions 条件求值 / enter_action 入强制队列 / weight_mod 权重修正）、L2 强制队列、
L3 条件行动（委托 monster_conditions 13 类触发）、L4 连锁队列（委托 monster_chains chain C 模型）、
L5 状态专属行动（exclusive_actions 白名单）、L6 随机行动表（probability 入池 /
P=(w×c×s)/Σ 归一化 / hungry 保底先查 / cooldown 过滤）、L7 兜底普攻、冷却/饥饿登记与
回合 tick（tick 由 battle 回合收尾单点调用）、intent 意图预告（委托 monster_intent）、
phases 阶段表写端（委托 monster_phases，套间更新 ai_state.phase 驱动 phase_changed 联动）。

工程收敛（设计文档未显式定义处，显式标注供审查）：
  1. 条件表达式形态：与条件行动同构的 trigger dict `{type, value?, ...}`（1f ①「与条件行动
     同一套表达式体系」）；本路内建最小求值集 hp_below/pv_broken/turn_count/phase_changed，
     其余类型经 register_condition_handler 注册表扩展（B2 填充 13 类全量）。
  2. weight_mod 键 = 行动 tags（1f ④ 4.2 示例：attack×1.5 / defense×0.5 按 tag 归属，
     tag 归属为示例假设【细化】）；s_a = Σ 乘积 weight_mod[tag]（无匹配 tag → 1.0）。
  3. hungry 保底口径：hungry=N 表示「连续 N 回合未选中即强制」，取「第 N 回合强制选」读法
     （TC-15）——本轮若 count+1 ≥ N 则强制，强制轮计入 N；count 只在随机池实际运行的回合
     对池内未选行动 +1（L0-L5 短路回合不计）。
  4. 冷却递减是回合边界事件，decide() 不递减（避免与 battle 回合收尾 tick 双重递减）；
     C1 在回合收尾调用 tick(ai_state) 统一递减 action/trigger/chain 三类冷却。
  5. 蓄力模型：选中蓄力行动 → 起手回合播报 1/N（占行动槽）→ 之后每回合 L0 结算播报
     k/N（k=2..N）→ shown≥total 的下一个 L0 回合释放行动本体。charge 快照键
     {action_id, total, shown, remaining_turns, armor}（remaining_turns 对齐 contract §五）。
  6. 链入队（chain_queue）由 L0 推进；触发行动=链首节点（TC-16 火球→尾扫：火球由触发者
     本次执行，尾扫入队待 L0）。roll_chain 由 B2 填充，False=断链+冷却（本路 stub 恒 False）。
"""

from typing import Any, Callable, Dict, List, Mapping, Optional

# 委托模块（B2/B3 路，主 agent 收口接线 2026-08-26）：
# L3 条件行动 13 类触发 / L4 chain C 连招链 / intent 意图预告
from qbot_rpg.core.monster_conditions import evaluate_conditions_all
from qbot_rpg.core.monster_chains import evaluate_chain, enqueue_chain
from qbot_rpg.core.monster_intent import build_intent

__all__ = [
    "MonsterAI",
    "NORMAL", "ENRAGED", "DYING",
    "IDLE", "IN_CHAIN", "CHARGING", "DOWNED",
]

# ---------------------------------------------------------------- 状态枚举（contract §五）

# 行为态（ai.states 配置载体：normal/enraged/dying + 可配自定义，1f ①1.1）
NORMAL, ENRAGED, DYING = "normal", "enraged", "dying"
# 执行态（运行时快照 ai_state 承载，1f ①1.1：idle/in_chain/charging/downed）
IDLE, IN_CHAIN, CHARGING, DOWNED = "idle", "in_chain", "charging", "downed"

# 兜底普攻行动 ID 哨兵（L7，contract §五「L7 兜底普攻」）
_BASIC = "__basic__"


def _default_ai_state() -> Dict[str, Any]:
    """ai_state 快照默认形态（contract §五 14 键；每次新建防共享可变默认）。"""
    return {
        "state": NORMAL,            # 行为态
        "exec_state": IDLE,         # 执行态（idle/in_chain/charging/downed）
        "phase": 1,                 # phases 阶段（BOSS：1/2/3）
        "chain_pos": 0,             # 连招链位置
        "chain_queue": [],          # 在途链（action id 序列）
        "chain_id": None,           # 当前链 id
        "chain_cooldowns": {},      # 链冷却 {chain_id: 剩余回合}
        "charge": None,             # 蓄力 {action_id, total, shown, remaining_turns, armor}
        "trigger_cooldowns": {},    # 条件行动冷却 {special_action_id: 剩余}
        "action_cooldowns": {},     # 行动冷却 {action_id: 剩余}
        "hungry_count": {},         # 饥饿计数 {action_id: 连续未选回合}
        "intent": {},               # 意图预告（B3 填充）
        "forced_queue": [],         # 强制队列（开场技/脚本/enter_action）
        "boss_phase": 1,            # 兼容旧键（battle.py L487 已读此键；与 phase 同值冗余）
    }


class MonsterAI:
    """怪物 AI 决策引擎（无状态，状态以 battle 快照 ai_state 为权威）。

    依据：m2_shared_contract §五 / 细化_1f ①②④。
    """

    def __init__(
        self,
        enemy_def: Mapping[str, Any],
        action_lib: Any,
        rng: Any,
    ) -> None:
        """enemy_def=enemies.json 条目 raw dict（八段 schema，contract §一）；
        action_lib=action 解析器（id→行动定义 dict；接受 callable 或 Mapping）；
        rng=确定性随机源（random.Random 实例或带 random()/choice() 的对象，铁律 6）。"""
        self._def = dict(enemy_def or {})
        self._action_lib = action_lib
        self._rng = rng

        # 行动表（enemies.json actions[]，6 字段 A01-A03 + A03b/c/d）
        self._actions: List[Dict[str, Any]] = list(self._def.get("actions") or [])
        # 特殊行动表（B2 路消费；本路仅解析保留）
        self._special_actions: List[Dict[str, Any]] = list(self._def.get("special_actions") or [])
        # 顶层连招表（chains 唯一载体，contract §一 / 1f ⑤5.1）
        self._chains: Dict[str, Any] = {
            c.get("id"): c for c in (self._def.get("chains") or []) if c.get("id")
        }
        # 兜底普攻（L7）：可经 basic_action 配置覆盖；缺省内置普攻
        self._basic_action: Optional[str] = self._def.get("basic_action")

        # ai 段（1f ①1.1 / T43）：states 行为态配置 + transitions 切换表
        ai_cfg = self._def.get("ai") or {}
        self._states_cfg: Dict[str, Any] = dict(ai_cfg.get("states") or {})
        self._transitions: List[Dict[str, Any]] = list(ai_cfg.get("transitions") or [])

        # 条件求值扩展注册表（B2 路注册 13 类全量 handler；注册优先于内建）
        self._condition_handlers: Dict[str, Callable[[Mapping, Mapping], bool]] = {}

    # ================================================================ 契约公开接口（§五）

    def decide(self, battle_state: dict) -> dict:
        """怪物行动阶段主入口：产出行动 action_dict（交给 battle._do_action/enemy_act 执行）。

        内部走：L0 套内门 → L1-L7 套间评估；同步更新 battle_state["ai_state"]（原地）。
        返回 action_dict 含 `ai_state` 键（决策后快照，供「吸收返回」回灌，contract §六）。

        action_dict 形态（C1 接线用）：
          {type: "skill"|"normal", skill_id, mult, kind, action_id, action, source,
           ai_state, [charging|progress|chain_id ...]}
        type=normal 的普攻与 battle.enemy_act 缺省 {"type":"normal","mult":1.0} 同构；
        type=skill 的 skill_id=action.json 行动 ID，由执行侧解析（T24 同构双库）。
        """
        ai = self._ensure_ai_state(battle_state)

        # ── L0 套内门（闸门最高，先于一切；TC-08/TC-18） ──
        if ai["chain_queue"] or ai["exec_state"] == CHARGING:
            return self._l0_inside(ai, battle_state)

        # downed 分支（1f ①1.2 总图）：起身演出占用行动槽 → 完成后进入套间评估
        if ai["exec_state"] == DOWNED:
            ai["exec_state"] = IDLE
            return self._emit("__get_up__", "downed", battle_state,
                              type="normal", kind="get_up", mult=1.0, action=None)

        # ── 套间评估 L1-L7（优先级总则：L2-L7 逐级短路；L1 例外——产出流入 L2 不停止） ──

        # M2 审查 P1-1：阶段写端（HP→phase 换算 + phase_changed 联动，TC-04 驱动口径）。
        # phases 配置时每套间更新 ai_state.phase/boss_phase，enter_action 入强制队列；
        # phase_changed 条件行动（L3）读 ai_state.phase（monster_ai._eval_condition）自然成立。
        phases_cfg = self._def.get("phases")
        if phases_cfg:
            try:
                from qbot_rpg.core.monster_phases import PhaseTable
                enemy = battle_state.get("enemy") or {}
                eh = float(enemy.get("hp", 0) or 0)
                em = float(enemy.get("max_hp", 0) or 0)
                trans = PhaseTable(phases_cfg).detect_transition(
                    eh, em, prev_phase=int(ai.get("phase") or 1))
                if trans.get("changed"):
                    ai["phase"] = int(trans.get("phase") or 1)
                    ai["boss_phase"] = ai["phase"]  # 兼容键（battle.py L487 读）
                    ea = trans.get("enter_action")
                    if ea:
                        ai["forced_queue"].append(ea)
            except Exception:  # phases 配置解析失败不阻断决策（工程兜底）
                pass

        # L1 状态机切换（套间先切；enter_action 入强制队列，weight_mod 生效）
        self.evaluate_transitions(battle_state)

        # L2 强制队列
        act = self._l2_forced(ai, battle_state)
        if act is not None:
            return act

        # L3 条件行动（B2 接口）
        act = self._l3_conditions(battle_state)
        if act is not None:
            return act

        # L4 连锁队列（B2 接口；本路在途链推进由 L0 承担）
        act = self._l4_chain(ai, battle_state)
        if act is not None:
            return act

        # L5 状态专属行动（exclusive_actions 白名单）
        act = self._l5_exclusive(ai, battle_state)
        if act is not None:
            return act

        # L6 随机行动表（probability=1 池 / P=(w×c×s)/Σ / hungry 先查 / cooldown 过滤）
        act = self._l6_random_pool(ai, battle_state)
        if act is not None:
            return act

        # L7 兜底普攻
        return self._l7_fallback(ai, battle_state)

    def evaluate_transitions(self, battle_state: dict) -> None:
        """L1 行为态切换（transitions 条件表达式求值，套间调用）。

        ai.transitions = [{from, to, condition}]，配置顺序短路（同 from 多条件先命中者胜）；
        命中 → 切行为态：enter_action 入 forced_queue（L2 消费）、weight_mod 生效（L5/L6 权重
        经 _state_mod 读取）、exclusive_actions 白名单生效（L5）。
        """
        ai = battle_state["ai_state"]
        current = ai.get("state") or NORMAL
        for trans in self._transitions:
            if trans.get("from") and trans["from"] != current:
                continue
            cond = trans.get("condition")
            if not isinstance(cond, dict):
                continue
            if self._eval_condition(cond, battle_state):
                new_state = trans.get("to")
                if new_state and new_state != current:
                    self._enter_state(ai, new_state)
                break

    def evaluate_conditions(self, battle_state: dict) -> list:
        """L3 条件行动匹配（13 类触发 + priority 降序同级随机；once/max_triggers/
        trigger_cooldown 过滤）。

        接线（B2）：委托 monster_conditions.evaluate_conditions_all 全量评估；
        返回按 priority 降序（同级随机已由 B2 用本引擎 rng 排序）的触发条目列表。
        """
        return evaluate_conditions_all(
            self._special_actions, battle_state, rng=self._rng, commit=True
        )

    def roll_chain(self, chain_id: str, battle_state: dict) -> bool:
        """chain C 模型：节点 chance roll（入队 true / 断链+冷却 false）。

        接线（B2）：委托 monster_chains.evaluate_chain 做链首节点 chance roll；
        True → 本引擎 _produce._enqueue_chain（触发行动=链首节点，余下入队待 L0）；
        False → _break_chain（断链 + chain_cooldowns 登记）。链不存在=False（悬空引用安全失败）。
        """
        chain_def = self._chains.get(chain_id)
        if not chain_def:
            return False
        ai = battle_state.get("ai_state") or {}
        # M2 审查 P1-2：冷却中同链重触发 → 不 roll 不落账（直接 False=断链，但 _break_chain
        # 的 max 保留确保不覆盖既有冷却）
        if int(ai.get("chain_cooldowns", {}).get(chain_id, 0)) > 0:
            return False
        return evaluate_chain(
            chain_id, chain_def, battle_state.get("ai_state") or {}, self._rng
        )

    def intent_for(self, action_id: str, battle_state: dict) -> dict:
        """意图预告（B3 接线）：{level, category, action_id, name_revealed,
        chain_preview, progress}。委托 monster_intent.build_intent；
        reveal_condition 未配=默认解锁显示；配了门禁按 codex_state 判定
        （缺 codex_state 时保守视作未解锁，L2/L3 显示？？？）。"""
        ai = battle_state.get("ai_state") or {}
        action_def = self._resolve_action(action_id)
        codex = battle_state.get("codex_state")
        return build_intent(action_id, action_def, ai, codex)

    # ================================================================ 扩展接口（B2/C1 接线）

    def register_condition_handler(
        self, trigger_type: str, fn: Callable[[Mapping, Mapping], bool]
    ) -> None:
        """注册条件求值 handler（B2 路填充 13 类触发；fn(cond, battle_state) -> bool）。
        注册 handler 优先于内建最小集。"""
        self._condition_handlers[trigger_type] = fn

    def tick(self, ai_state: Mapping[str, Any]) -> None:
        """回合收尾冷却递减（C1 在战斗回合收尾调用；工程收敛 4）。

        递减 action_cooldowns / trigger_cooldowns / chain_cooldowns 三表（≤0 移除）。
        decide() 不递减——冷却递减是回合边界事件，避免与 battle tick 双重递减。
        """
        for key in ("action_cooldowns", "trigger_cooldowns", "chain_cooldowns"):
            cd = ai_state.get(key)
            if not isinstance(cd, dict):
                continue
            for k in list(cd):
                cd[k] = int(cd[k]) - 1
                if cd[k] <= 0:
                    del cd[k]

    def pool_probabilities(self, battle_state: dict) -> Dict[str, float]:
        """L6 随机池归一化概率视图（纯计算，不消耗 rng；概率输出一律小数 fraction，铁律 5）。

        返回 {action_id: P(a)}，P(a)=(w_a×c_a×s_a)/Σᵢ(w_i×c_i×s_i)（1f ④4.2）；
        含 hungry/cooldown 过滤后的池成员；空池返回 {}。供测试/B2 复用。
        """
        ai = battle_state["ai_state"]
        pool = self._random_pool(ai, battle_state)
        if not pool:
            return {}
        weights = [self._weight_for(e, ai, battle_state) for e in pool]
        total = sum(weights)
        if total <= 0:
            return {e["action"]: 0.0 for e in pool}
        return {e["action"]: w / total for e, w in zip(pool, weights)}

    # ================================================================ L0-L7 实现

    def _l0_inside(self, ai: Dict[str, Any], battle_state: dict) -> dict:
        """L0 套内门：chain_queue 非空 → 链推进；charging → 蓄力结算。跳过 L1-L7（TC-08）。"""
        if ai["chain_queue"]:
            return self._advance_chain(ai, battle_state)
        if ai["exec_state"] == CHARGING:
            return self._settle_charge(ai, battle_state)
        # 理论不可达（decide 已判）→ 兜底普攻
        return self._l7_fallback(ai, battle_state)

    def _advance_chain(self, ai: Dict[str, Any], battle_state: dict) -> dict:
        """L0 链推进：队首行动确定性执行（套内不评估，中途不被条件打断，核心规则2）；
        队空=套结算完 → exec_state 回 idle（chain_id 清空；自然走完不设链冷却——
        冷却只在断链时登记，1f ⑤5.2）。"""
        q = ai["chain_queue"]
        if not q:
            ai["exec_state"] = IDLE
            return self._l7_fallback(ai, battle_state)
        action_id = q.pop(0)
        ai["chain_pos"] = int(ai.get("chain_pos", 0)) + 1
        result = self._execute_now(action_id, "L0_chain", battle_state)
        if not q:  # 套结算完
            ai["exec_state"] = IDLE
            ai["chain_id"] = None
            ai["chain_pos"] = 0  # M2 审查 P2-5：链自然走完 chain_pos 归零（防中断恢复读陈旧值）
        return result

    def _settle_charge(self, ai: Dict[str, Any], battle_state: dict) -> dict:
        """L0 蓄力结算：shown≥total → 释放行动本体；否则播报进度 k/N 继续蓄力（TC-18）。

        蓄力跨回合=同一套（核心规则1）：结算期间不评估条件/状态/权重。
        蓄力可被打断（armor=true 霸体免疫）——打断由执行侧/效果系统接线（1f ①1.1 核心规则7）。
        """
        ch = ai.get("charge") or {}
        aid = ch.get("action_id")
        total = max(1, int(ch.get("total", 1)))
        shown = int(ch.get("shown", 1))
        if shown >= total:
            ai["charge"] = None
            ai["intent"] = {}  # M2 审查 P2-5：释放后清蓄力 intent 残留（防渲染读陈旧值）
            return self._execute_now(aid, "L0_charge", battle_state)
        shown += 1
        ch["shown"] = shown
        ch["remaining_turns"] = total - shown + 1
        progress = f"{shown}/{total}"
        # M2 审查 P1-3：intent 统一走 build_intent（图鉴分级/连锁预演），叠蓄力进度
        base = self.intent_for(aid or "", battle_state)
        if not isinstance(base, dict):
            base = {}
        base.update({"category": "charge", "progress": progress, "level": max(int(base.get("level", 0) or 0), 1)})
        ai["intent"] = base
        return self._emit(aid, "L0_charge", battle_state,
                          type="skill", kind="charge", charging=True,
                          progress=progress)

    def _l2_forced(self, ai: Dict[str, Any], battle_state: dict) -> Optional[dict]:
        """L2 强制队列：队首行动执行；若引链则入 chain_queue（contract §五 L2 行）。"""
        if not ai["forced_queue"]:
            return None
        item = ai["forced_queue"].pop(0)
        if isinstance(item, dict):
            entry = {"chain_ref": item["chain_ref"]} if item.get("chain_ref") else {}
            return self._produce(item.get("action"), "L2", battle_state, entry=entry)
        return self._produce(item, "L2", battle_state)

    def _l3_conditions(self, battle_state: dict) -> Optional[dict]:
        """L3 条件行动（B2 填充）：匹配列表队首即产出；chain_ref 由 _produce 接线。"""
        matches = self.evaluate_conditions(battle_state)
        if not matches:
            return None
        first = matches[0]
        entry = {"chain_ref": first.get("chain_ref")} if first.get("chain_ref") else {}
        return self._produce(first.get("action"), "L3", battle_state, entry=entry)

    def _l4_chain(self, ai: Dict[str, Any], battle_state: dict) -> Optional[dict]:
        """L4 连锁队列（B2 填充）：在途链推进由 L0 承担；此处仅当强制/条件行动引链时
        经 roll_chain 入队（_produce 内接线）。本路恒无产出（B2 roll_chain 填充后生效）。"""
        return None

    def _l5_exclusive(self, ai: Dict[str, Any], battle_state: dict) -> Optional[dict]:
        """L5 状态专属行动：当前行为态 exclusive_actions 白名单内选行动（1f ②L5）。

        白名单行动=锚点（不要求 probability=1，状态机触发即出，TC-03 final_strike）；
        cooldown 过滤 → 白名单内加权归一化选一（无权重条目默认 1.0）；全冷却 → 无产出
        落 L6。"""
        state_cfg = self._states_cfg.get(ai.get("state") or NORMAL) or {}
        exclusive = state_cfg.get("exclusive_actions") or []
        if not exclusive:
            return None
        entries = [e for e in self._entries_from_ids(exclusive)
                   if int(ai["action_cooldowns"].get(e["action"], 0)) <= 0]
        if not entries:
            return None
        selected = self._weighted_pick(entries, ai, battle_state, zero_as_one=True)
        if selected is None:
            return None
        return self._produce(selected["action"], "L5", battle_state, entry=selected)

    def _l6_random_pool(self, ai: Dict[str, Any], battle_state: dict) -> Optional[dict]:
        """L6 随机行动表（1f ②L6 / ④4.2）：

        1. 池 = probability>0（0=锚点，其他正值等价 1）且不在冷却的行动；
        2. hungry 保底先查（抽取前，TC-15：count+1 ≥ N 强制选，配置序首个命中）；
        3. 加权归一化选一 P=(w×c×s)/Σ（rng 注入，可复现）；
        4. 选中 → 冷却登记 + 饥饿清零；池内未选 → 饥饿 +1。
        """
        pool = self._random_pool(ai, battle_state)
        if not pool:
            return None
        # hungry 保底先查（随机池抽取前，1f ④4.2-4）
        for e in pool:
            aid = e["action"]
            hungry = int(e.get("hungry") or 0)
            if hungry > 0 and int(ai["hungry_count"].get(aid, 0)) + 1 >= hungry:
                return self._consume_random(ai, pool, e, battle_state)
        selected = self._weighted_pick(pool, ai, battle_state)
        if selected is None:
            return None
        return self._consume_random(ai, pool, selected, battle_state)

    def _l7_fallback(self, ai: Dict[str, Any], battle_state: dict) -> dict:
        """L7 兜底普攻（1f ②L7 / TC-09）：L0-L6 均无产出 → 默认普攻
        （enemy_def.basic_action 可配；缺省与 battle.enemy_act 缺省 {"type":"normal"} 同构）。"""
        if self._basic_action:
            return self._execute_now(self._basic_action, "L7", battle_state)
        return self._emit(_BASIC, "L7", battle_state, type="normal", mult=1.0,
                          action=None)

    # ================================================================ 随机池/权重/选择

    def _random_pool(self, ai: Dict[str, Any], battle_state: dict) -> List[Dict[str, Any]]:
        """L6 池构造：probability>0（1 入池，其他正值等价 1，contract §一）且不在冷却。"""
        pool = []
        for e in self._actions:
            if float(e.get("probability", 0)) <= 0:
                continue  # 锚点（只被链/条件/状态机触发，核心规则4）
            aid = e.get("action")
            if int(ai["action_cooldowns"].get(aid, 0)) > 0:
                continue  # cooldown 过滤
            pool.append(e)
        return pool

    def _weight_for(self, entry: Mapping[str, Any], ai: Dict[str, Any],
                    battle_state: dict) -> float:
        """行动权重 w×c×s（1f ④4.2 概率公式分子）：

        w = weight 基准权重（缺省 1.0，权重档位建议见 1f ④4.2-7）；
        c = condition 条件修正（命中 → cond.mod，缺省 1.0；未命中 → 1.0）；
        s = 状态修正 weight_mod[tag] 乘积（无匹配 tag → 1.0）。"""
        w_raw = entry.get("weight")
        w = float(w_raw) if w_raw is not None else 1.0
        c = 1.0
        cond = entry.get("condition")
        if isinstance(cond, dict) and cond.get("type"):
            if self._eval_condition(cond, battle_state):
                c = float(cond.get("mod", 1.0))
        s = self._state_mod(self._resolve_action(entry.get("action")), ai)
        return max(0.0, w * c * s)

    def _state_mod(self, action_def: Optional[Mapping[str, Any]],
                   ai: Dict[str, Any]) -> float:
        """状态修正 s_a：当前行为态 weight_mod 按行动 tags 命中乘积（1f ①1.1 / ④4.2-3）。

        示例：enraged weight_mod {attack:1.5, defense:0.5} → 爪击(tag attack)×1.5、
        吼叫(tag defense)×0.5；无匹配 → 1.0（1f ④4.2 示例 63.2%/31.6%/5.3% 同口径）。"""
        wm = (self._states_cfg.get(ai.get("state") or NORMAL) or {}).get("weight_mod") or {}
        if not wm or not isinstance(action_def, Mapping):
            return 1.0
        tags = action_def.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        mod = 1.0
        for t in tags:
            if t in wm:
                mod *= float(wm[t])
        return mod

    def _weighted_pick(self, entries: List[Dict[str, Any]], ai: Dict[str, Any],
                       battle_state: dict, zero_as_one: bool = False) -> Optional[Dict[str, Any]]:
        """按 w×c×s 归一化权重选一（rng.random() 注入，可复现；全 0 权重 → None）。

        zero_as_one=True：weight≤0 的条目按 1.0 参与（L5 专属行动=锚点白名单，
        weight 无意义、无权重条目默认 1.0——1f ②L5 语义，修复全 0 权重落空）。"""
        weights = [self._weight_for(e, ai, battle_state) for e in entries]
        if zero_as_one:
            weights = [1.0 if w <= 0 else w for w in weights]
        total = sum(weights)
        if total <= 0:
            return None
        r = float(self._rng.random()) * total
        acc = 0.0
        for e, w in zip(entries, weights):
            acc += w
            if r <= acc:
                return e
        return entries[-1]

    def _consume_random(self, ai: Dict[str, Any], pool: List[Dict[str, Any]],
                        selected: Dict[str, Any], battle_state: dict) -> dict:
        """L6 选中后记账：选中者饥饿清零；池内未选者饥饿 +1；冷却登记；产出行动。"""
        for e in pool:
            aid = e["action"]
            if aid == selected["action"]:
                ai["hungry_count"][aid] = 0
            else:
                ai["hungry_count"][aid] = int(ai["hungry_count"].get(aid, 0)) + 1
        return self._produce(selected["action"], "L6", battle_state, entry=selected)

    # ================================================================ 行动产出/执行态

    def _produce(self, action_id: Optional[str], source: str,
                 battle_state: dict, entry: Optional[Mapping[str, Any]] = None) -> dict:
        """选中行动 → 执行态登记 + 记账 + action_dict 产出（L2/L3/L5/L6 共用）。

        蓄力起手：行动含 charge_* 字段 → 登记 charge + 执行态 CHARGING（播报 1/N）；
        链引用：roll_chain(B2) True → _enqueue_chain（触发行动=链首节点，余下 L0 推进），
        False → _break_chain（断链+链冷却）；其余 → 执行态 IN_CHAIN（单行动=长度 1 套）。"""
        ai = battle_state["ai_state"]
        action = self._resolve_action(action_id) or {}
        real_entry = self._entry_for(action_id)
        if entry:
            real_entry = {**real_entry, **entry}

        # 蓄力起手（charge_* 字段，contract §四 AI 字段）
        if self._is_charge_action(action):
            self._start_charge(ai, battle_state, action_id, action)
            self._apply_entry_meta(ai, real_entry, action_id)
            total = int((ai.get("charge") or {}).get("total", 1))
            return self._emit(action_id, source, battle_state, action=action,
                              type="skill", kind="charge", charging=True,
                              progress=f"1/{total}")

        # 链引用入队（contract §五 L2/L3 行；roll_chain 由 B2 填充）
        chain_ref = real_entry.get("chain_ref") or action.get("chain_ref")
        if chain_ref and chain_ref in self._chains:
            if self.roll_chain(chain_ref, battle_state):
                self._enqueue_chain(chain_ref, battle_state)
                if ai["chain_queue"]:  # 触发行动=链首节点，本次执行
                    ai["chain_queue"].pop(0)
                    if not ai["chain_queue"]:
                        ai["chain_id"] = None
            else:
                self._break_chain(ai, chain_ref)

        ai["exec_state"] = IN_CHAIN
        self._apply_entry_meta(ai, real_entry, action_id)
        return self._emit(action_id, source, battle_state, action=action)

    def _execute_now(self, action_id: Optional[str], source: str,
                     battle_state: dict) -> dict:
        """立即执行行动（L0 链推进/蓄力释放/L7 兜底）：不经蓄力起手/链入队，
        执行态 IN_CHAIN + 记账 + 产出。"""
        ai = battle_state["ai_state"]
        real_entry = self._entry_for(action_id)
        ai["exec_state"] = IN_CHAIN
        self._apply_entry_meta(ai, real_entry, action_id)
        return self._emit(action_id, source, battle_state,
                          action=self._resolve_action(action_id) or {})

    def _emit(self, action_id: Optional[str], source: str, battle_state: dict,
              **extra: Any) -> dict:
        """action_dict 产出（C1 接线形态，见 decide docstring）。"""
        ai = battle_state["ai_state"]
        action = extra.pop("action", None)
        if action is None and action_id:
            action = self._resolve_action(action_id) or {}
        result = {
            "type": "skill" if (action_id and action_id != _BASIC and action_id != "__get_up__") else "normal",
            # M2 审查 P2-4：__get_up__ 起身演出哨兵不进 skill_id（执行侧按 skill_id 解析未知行动）
            "skill_id": action_id if (action_id and action_id != _BASIC and action_id != "__get_up__") else None,
            "mult": float(action.get("power", 1.0)) if isinstance(action, Mapping) else 1.0,
            "kind": (action or {}).get("kind", "basic") if isinstance(action, Mapping) else "basic",
            "action_id": action_id,
            "action": action,
            "source": source,
            "ai_state": ai,  # 决策后 ai_state（回灌快照，contract §六「吸收返回」）
        }
        result.update(extra)
        return result

    def _apply_entry_meta(self, ai: Dict[str, Any], entry: Mapping[str, Any],
                          action_id: Optional[str]) -> None:
        """记账：行动冷却登记（>0 才写）+ 选中即饥饿清零（TC-15 口径）。"""
        if action_id:
            cd = int((entry or {}).get("cooldown") or 0)
            if cd > 0:
                ai["action_cooldowns"][action_id] = cd
            ai["hungry_count"][action_id] = 0

    def _start_charge(self, ai: Dict[str, Any], battle_state: dict, action_id: Optional[str],
                      action: Mapping[str, Any]) -> None:
        """蓄力起手：charge 快照 {action_id, total, shown=1, remaining_turns, armor}
        （contract §五 charge 键 {action_id, remaining_turns, armor} 的扩展形态，工程收敛 5）。

        M2 审查 P1-3：intent 统一走 build_intent（intent_for 委托）——含 reveal_condition
        的 L2 招名/L3 连锁预演（蓄力路径此前硬编码 name_revealed=False 绕过图鉴分级）。
        """
        turns = max(1, int(action.get("charge_turns") or 1))
        armor = bool(action.get("charge_armor") or action.get("armor") or False)
        ai["charge"] = {
            "action_id": action_id,
            "total": turns,
            "shown": 1,
            "remaining_turns": turns,
            "armor": armor,
        }
        ai["exec_state"] = CHARGING
        base = self.intent_for(action_id or "", battle_state)
        if not isinstance(base, dict):
            base = {}
        base.update({"category": "charge", "progress": f"1/{turns}", "level": max(int(base.get("level", 0) or 0), 1)})
        ai["intent"] = base

    def _enqueue_chain(self, chain_id: str, battle_state: dict) -> None:
        """连招链入队（B2 roll_chain True 后调用）：chain_queue = 链节点 action id 序列。

        M2 审查 P2-3：委托 monster_chains.enqueue_chain（唯一实现，消除双实现漂移）。
        """
        ai = battle_state["ai_state"]
        chain = self._chains.get(chain_id)
        if not chain:
            return
        enqueue_chain(chain_id, chain, ai)

    def _break_chain(self, ai: Dict[str, Any], chain_id: str) -> None:
        """断链+冷却（roll 失败，1f ⑤5.2-3）：在途链清空 + chain_cooldowns 登记。

        M2 审查 P1-2：冷却 max 保留（不覆盖既有冷却），冷却中重触发不会重置冷却
        ——否则条件持续成立时可每回合重置冷却锁死该链；断链冷却起算避免当回合
        被 tick 清零（登记 +1，次回合起算实际阻断）。
        """
        ai["chain_queue"] = []
        ai["chain_pos"] = 0
        ai["chain_id"] = None
        chain = self._chains.get(chain_id) or {}
        cd_val = max(1, int(chain.get("cooldown") or 1))
        ai["chain_cooldowns"][chain_id] = max(
            int(ai["chain_cooldowns"].get(chain_id, 0)), cd_val + 1
        )

    # ================================================================ 状态机/条件求值

    def _enter_state(self, ai: Dict[str, Any], new_state: str) -> None:
        """切行为态 + enter_action 入强制队列（TC-01：L1 产出流入 L2 不停止）。"""
        ai["state"] = new_state
        cfg = self._states_cfg.get(new_state) or {}
        enter_action = cfg.get("enter_action")
        if enter_action:
            aid = enter_action.get("action") if isinstance(enter_action, dict) else enter_action
            if aid:
                ai["forced_queue"].append(aid)

    def _eval_condition(self, cond: Mapping[str, Any], battle_state: dict) -> bool:
        """条件表达式求值（与条件行动同一套表达式体系，1f ①1.1）。

        内建最小集：hp_below（value=HP 百分比阈值，严格小于）/ pv_broken /
        turn_count（op 默认 >=）/ phase_changed（value=阶段号，phase>=value 即成立）。
        注册表 handler 优先；未注册未知类型 → False（B2 路 register_condition_handler
        填充 13 类全量）。"""
        if not isinstance(cond, Mapping):
            return False
        ctype = cond.get("type")
        handler = self._condition_handlers.get(ctype) if isinstance(ctype, str) else None
        if handler is not None:
            return bool(handler(cond, battle_state))
        if ctype == "hp_below":
            return self._hp_ratio(battle_state) < float(cond.get("value", 0))
        if ctype == "pv_broken":
            enemy = battle_state.get("enemy") or {}
            return float(enemy.get("pv", 1)) <= 0
        if ctype == "turn_count":
            op = cond.get("op", ">=")
            cur = int(battle_state.get("turn", 0))
            val = float(cond.get("value", 0))
            return {"<": cur < val, "<=": cur <= val,
                    ">": cur > val, ">=": cur >= val,
                    "==": cur == val}.get(op, False)
        if ctype == "phase_changed":
            val = cond.get("value")
            if val is None:
                return False
            ai = battle_state["ai_state"]
            return int(ai.get("phase", 1)) >= int(val)
        return False

    def _hp_ratio(self, battle_state: dict) -> float:
        """敌方 HP 百分比（0-100；hp_below 阈值口径，1f TC-01 49%<50 成立）。"""
        enemy = battle_state.get("enemy") or {}
        hp = float(enemy.get("hp", 0))
        mhp = float(enemy.get("max_hp", 0))
        if mhp <= 0:
            return 0.0
        return hp / mhp * 100.0

    # ================================================================ 配置解析辅助

    def _resolve_action(self, action_id: Optional[str]) -> Optional[Mapping[str, Any]]:
        """action_lib 解析：callable(id) 或 Mapping.get(id)；未注册返回 None。"""
        if not action_id:
            return None
        try:
            lib = self._action_lib
            if callable(lib):
                res = lib(action_id)  # type: ignore[operator]
            elif isinstance(lib, Mapping):
                res = lib.get(action_id)
            else:
                return None
        except Exception:
            return None
        return res if isinstance(res, Mapping) else None

    def _entry_for(self, action_id: Optional[str]) -> Dict[str, Any]:
        """行动表条目查找（按 action id；未登记返回空 dict）。"""
        for e in self._actions:
            if e.get("action") == action_id:
                return dict(e)
        return {}

    def _entries_from_ids(self, action_ids: List[str]) -> List[Dict[str, Any]]:
        """行动 id 列表 → 行动表条目列表（无表条目 → 缺省 {action} 权重 1.0）。"""
        out = []
        for aid in action_ids:
            e = self._entry_for(aid)
            out.append(e if e else {"action": aid})
        return out

    def _is_charge_action(self, action: Optional[Mapping[str, Any]]) -> bool:
        """蓄力行动判定：action.json 含 charge_turns 字段（charge_* 前缀，contract §四）。"""
        if not isinstance(action, Mapping):
            return False
        return action.get("charge_turns") is not None

    def _ensure_ai_state(self, battle_state: dict) -> Dict[str, Any]:
        """ai_state 快照就位：缺键补默认（14 键，contract §五）；phase/boss_phase 冗余同步
        （battle.py L487 读 boss_phase，contract §五注意行）。"""
        ai = battle_state.get("ai_state")
        if not isinstance(ai, dict):
            ai = {}
            battle_state["ai_state"] = ai
        for k, v in _default_ai_state().items():
            ai.setdefault(k, v)
        # phase 与 boss_phase 同值（冗余兼容；phase 权威，boss_phase 镜像）
        ai["boss_phase"] = int(ai.get("phase", ai.get("boss_phase", 1)))
        return ai
