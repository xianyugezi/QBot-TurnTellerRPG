"""连段引擎（M1-批3 · 1c1a 状态集 + 1c1b 迁移表 + 1c1c 到顶清零 + 1c2 配置/打断霸体）。

纯规则引擎，零 NoneBot import（细化_3a R1）。接口层 frozen dataclass；
内部处理 dict（快照形态遵循 JSON 序列化契约）。运行时**不持有状态**——
combo_state 始终以战斗快照为权威（同 effects.EffectRuntime 哲学），本引擎
只读写 `snap["combo_state"][side]`（侧内五字段）+ 读 `snap["turn"]` /
`snap[side]` / `snap["status_state"]`。

依据（全部引用细化节号，不编造行号）：
  - 细化_1c1a_连段状态集：6 态（idle/in_combo/derivable/deriving/
    at_max_reset/at_max_hold）§1.0-§1.7；combo_state 字段级 schema
    （chain_id/chain_name/count/hold/step_index 持久化五字段 §2.1；
    state/pending_derivations/max_combo/armor_active/last_clear_reason
    运行期/瞬态 §2.2；生命周期约束 §2.3）
  - 细化_1c1b_连段迁移表：主迁移 8 条（①普攻+1 ②连段技+1 ③段数达标→派生
    ④到顶→reset ⑤到顶→hold ⑥指令被拒 ⑦战斗结束清零 ⑧防御/道具不打断）
    + 辅助 A1-A5（打断/被控/逃跑/无标签自断/中断恢复）
  - 细化_1c1c_到顶与清零：reset/hold 语义与判定顺序（L158）、清零事件全集、
    不清零豁免清单、职业预置（剑士4/reset 刺客2/reset 法师5/hold 盾卫3/hold）
  - 细化_1c2_combo配置与打断霸体：链级/步节点/技能侧/条件对象字段级 schema；
    打断/霸体时序 §2.2（攻击窗口三条件）；防御续链 §2.3-§2.6
  - 细化_1c3_连段测试集：TC-01..52（9 类需求）——本模块承担全部核心判定，
    battle 层承担施放-结算接线。

【工程收敛】（设计文档未显式定义或存在歧义处，显式标注，供策划/审查对照）：
  1. combo_state 快照形态：本仓库 effects.interrupt L0（写入
     combo_state[target]["interrupted"]=True）与 battle._settle（combo_state={}）
     已确立「按战斗侧嵌套」惯例（combo_state={player:{...}, enemy:{...}}），
     本引擎沿用；侧内五字段与 1c1a §2.1 单侧示例完全一致。
  2. 派生触发语义（收敛 1c1a L92-94「玩家自选，不强制」与 TC-03「连斩→追斩·变
     替换式派生」）：玩家施放链内技能 skill_id 时——
       a) skill_id == 某步.to 且条件满足 → 派生施放（TC-04 可用分支）；
       b) skill_id == 某步.to 但条件不满足 → **降级**为源技能 step.from 结算，
          原因标注「需连段N」置灰（TC-04）；
       c) skill_id == 某步.from 且存在 mode=replace 且条件满足的步 → 本次施放
          自动替换为派生形态 step.to（TC-03，施放后形态还原、非终点）。
     「不强制派生」= 无满足条件时基技能原样结算；多派生同时满足（TC-06）全部
      入 pending_derivations，玩家按技能名自选其一（列表全部可用，互不互斥）。
  3. 派生计数（收敛 L73「派生 count 不变」与 L75「标签独立、缺省继承原技能」）：
     派生施放的段数变化按【步配置优先】：
       - step.consume > 0                    → count -= N（L74，hold 大招消耗出口）
       - step.tag 显式配置                   → 按该标签（combo +1 / preserve +0 /
                                               push +N，L75）
       - 两者皆缺省                          → 继承源技能 step.from 的 tag；源技能
                                               亦无 tag → +0 保留（L73 默认）
     循环互派生（TC-15）据此在步 tag=combo/源 tag=combo 下持续累计不归零。
  4. reset 归零时点（收敛 1c1c §1.1 回合粒度与 1c1b 主迁移④）：以「到顶后下一
     次连段技/普攻成功结算时先归零再 +delta」实现（可观察结果 = 0→1 重打，
     TC-TOP-01）；到顶当回合 eq=max 派生先判（TC-TOP-02 / TC-21，L158）在派生
     解析阶段先行处理，与归零解耦（先判 eq=max 再视无派生归零）。
  5. 指令被拒（MP/冷却/条件，⑥）：engine 层提供 should_reject/can_execute 完整
     判定（TC-30/32/49-52 + 派生原子拒绝）；battle 层 MP 扣费与「不耗回合」接线
     随 contract_deviations F-24 递延至 M5 技能库（本层保留 rejected 通道，
     战斗层可据 plan.rejected 短路）。
  6. hold「到顶普通技能不清零」仅豁免 hold 且 count==max（TC-TOP-05 特例，
     L157）；reset 到顶无豁免（普通技能仍自断，L53）——豁免是 hold 专属被动态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    # 状态枚举
    "COMBO_IDLE",
    "COMBO_IN_COMBO",
    "COMBO_DERIVABLE",
    "COMBO_DERIVING",
    "COMBO_AT_MAX_RESET",
    "COMBO_AT_MAX_HOLD",
    "COMBO_STATES",
    # 标签 / 到顶行为 / 派生模式
    "TAG_COMBO",
    "TAG_PRESERVE",
    "TAG_PUSH",
    "TAG_INTERRUPT",
    "TAG_ARMOR",
    "BEHAVIOR_RESET",
    "BEHAVIOR_HOLD",
    "MODE_REPLACE",
    "MODE_ENHANCE",
    "MODE_APPEND",
    "MODE_UNLOCK",
    # 数据结构
    "ComboState",
    "StepConfig",
    "ChainConfig",
    "ConditionCtx",
    "DerivationRef",
    "ComboActionResult",
    "InterruptResult",
    # 纯函数
    "empty_combo_state",
    "derive_state",
    "evaluate_condition",
    "default_resolver",
    "validate_chain",
    # 运行时
    "ComboEngine",
    # 配置
    "COMBO_DEFAULT_CONFIG",
]

# ---------------------------------------------------------------------------
# 状态枚举（细化_1c1a §1.0 六态）
# ---------------------------------------------------------------------------

COMBO_IDLE = "idle"                 # ① 空闲：无活跃连段链 count=0
COMBO_IN_COMBO = "in_combo"         # ② 连段中：1 <= count < max，条件全不满足
COMBO_DERIVABLE = "derivable"       # ③ 段数达标：>=1 条派生条件成立（不强制派生）
COMBO_DERIVING = "deriving"         # ④ 派生中：本回合正在执行派生形态
COMBO_AT_MAX_RESET = "at_max_reset"  # ⑤ 到顶-reset：count==max 且 behavior=reset
COMBO_AT_MAX_HOLD = "at_max_hold"   # ⑥ 到顶-hold：count==max 且 behavior=hold

COMBO_STATES: Tuple[str, ...] = (
    COMBO_IDLE,
    COMBO_IN_COMBO,
    COMBO_DERIVABLE,
    COMBO_DERIVING,
    COMBO_AT_MAX_RESET,
    COMBO_AT_MAX_HOLD,
)

# 技能连段标签（细化_1c2 §1.5 六值枚举）
TAG_COMBO = "combo"                 # 连段技：+1（P0）
TAG_PRESERVE = "combo_preserve"     # 保留连段：+0 不清零（P1 喘息技）
TAG_PUSH = "combo_push"             # 推进连段：+N 不清零（P1 喘息变体）
TAG_INTERRUPT = "interrupt"         # 打断技：对目标连段清零（P0）
TAG_ARMOR = "armor"                 # 霸体：使用期间免疫打断（P0，与 armor:true 等效标记）
TAG_NONE = ""                       # 无标签普通技能：归零（打断自己）

# 到顶行为（细化_1c1c §1.1/§1.2）
BEHAVIOR_RESET = "reset"            # 归零重打（节奏循环：剑士/刺客）
BEHAVIOR_HOLD = "hold"              # 保持最大（蓄力：法师/盾卫）

# 派生四模式（细化_1c2 §1.2 字段 12）
MODE_REPLACE = "replace"            # 替换：本次形态替换为 to 技能（TC-03 语义）
MODE_ENHANCE = "enhance"            # 强化：同形态、数值提升
MODE_APPEND = "append"              # 追加：基础 + 额外效果
MODE_UNLOCK = "unlock"              # 解锁：解锁额外效果/能力

# 引擎级默认配置
COMBO_DEFAULT_CONFIG: Dict[str, Any] = {
    # 跨战斗蓄力（1c1c TC-END-06 / 1c1b L213）：默认关，内容包可开
    "cross_battle_charge": False,
    # 霸体/攻打半点（1c2 §2.5）：armor 步骤无任何代价时校验器提示（提示不拒绝）
    "warn_armor_without_cost": True,
    # 大招溢出补偿（1c1c TC-END-07 / L238）：默认不启用
    "overflow_compensation": "off",   # off | exp_scale | next_start_plus1
    "overflow_exp_scale": 1.0,        # 溢出转经验系数（exp_scale 模式）
    "overflow_next_start_plus1": 1,   # 下场起始段数（next_start_plus1 模式）
    # MP 门槛（⑥ 指令被拒）：默认关（battle MP 体系随 F-24 递延 M5，engine 层可测）
    "enforce_mp": False,
}

# 快照中 combo_state 的侧内五字段（1c1a §2.1）
_PERSIST_KEYS: Tuple[str, ...] = (
    "chain_id", "chain_name", "count", "hold", "step_index",
)

_NUMERIC_KEYS: Tuple[str, ...] = ("count", "step_index")


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComboState:
    """连段状态（1c1a §2.1 持久化五字段；空闲默认 `empty_combo_state()`）。
    """

    chain_id: Optional[str] = None
    chain_name: Optional[str] = None
    count: int = 0
    hold: bool = False
    step_index: int = -1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "chain_name": self.chain_name,
            "count": int(self.count),
            "hold": bool(self.hold),
            "step_index": int(self.step_index),
        }

    @classmethod
    def from_dict(cls, d: Optional[Mapping[str, Any]]) -> "ComboState":
        if not isinstance(d, Mapping):
            return empty_combo_state()
        count = int(d.get("count", 0) or 0)
        # P1-1（dsh 批3）：`0 or -1` 致 step_index=0（合法：空闲=-1、其余≥0，1c1a §2.1）回读成 -1
        step_index = int(d.get("step_index", -1))
        return cls(
            chain_id=str(d["chain_id"]) if d.get("chain_id") else None,
            chain_name=str(d["chain_name"]) if d.get("chain_name") else None,
            count=max(0, count),
            hold=bool(d.get("hold", False)),
            step_index=step_index,
        )

    @property
    def active(self) -> bool:
        """链活跃 = 有链且 count > 0（1c2 §2.2 打断生效条件之一）。"""
        return bool(self.chain_id) and self.count > 0

    def __bool__(self) -> bool:  # 兼容旧代码 `if combo_state:` 判空
        return bool(self.chain_id) or self.count > 0


def empty_combo_state() -> ComboState:
    return ComboState()


# ---------------------------------------------------------------------------
# 链配置（1c2 §1.1/§1.2 schema）——运行期只读视图
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepConfig:
    """链步节点（1c2 §1.2 九字段）。condition 为原始 ConditionObject dict。"""

    index: int
    from_: str                       # 源技能 ID
    to: str                          # 目标派生技能 ID
    mode: str = MODE_REPLACE
    tag: Optional[str] = None        # None=缺省继承源技能标签
    condition: Mapping[str, Any] = field(default_factory=dict)  # 缺省=无条件恒可用
    priority: int = 0
    armor: bool = False              # 派生使用期间免疫打断
    consume: int = 0                 # 消耗连段数（大招）
    variant_override: Mapping[str, Any] = field(default_factory=dict)  # {dmg_mult?, cost?}

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any], index: int) -> "StepConfig":
        cond = raw.get("condition")
        vo = raw.get("variant_override")
        return cls(
            index=index,
            from_=str(raw.get("from", "")),
            to=str(raw.get("to", "")),
            mode=str(raw.get("mode") or MODE_REPLACE),
            tag=str(raw["tag"]) if raw.get("tag") else None,
            condition=dict(cond) if isinstance(cond, Mapping) else {},
            priority=int(raw.get("priority") or 0),
            armor=bool(raw.get("armor", False)),
            consume=max(0, int(raw.get("consume") or 0)),
            variant_override=dict(vo) if isinstance(vo, Mapping) else {},
        )


@dataclass(frozen=True)
class ChainConfig:
    """连段链配置（1c2 §1.1 六字段）。steps 按原始顺序保留 index。"""

    id: str
    name: str
    trigger_skill: str
    max_combo: int
    max_combo_behavior: str
    steps: Tuple[StepConfig, ...]

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> "ChainConfig":
        steps_raw = raw.get("steps")
        steps_lst: Sequence[Mapping[str, Any]] = (
            [s for s in steps_raw if isinstance(s, Mapping)]
            if isinstance(steps_raw, list)
            else []
        )
        steps = tuple(
            StepConfig.from_raw(s, i) for i, s in enumerate(steps_lst)
        )
        return cls(
            id=str(raw.get("id", "")),
            name=str(raw.get("name") or raw.get("id") or ""),
            trigger_skill=str(raw.get("trigger_skill") or ""),
            max_combo=max(1, int(raw.get("max_combo") or 1)),
            max_combo_behavior=str(raw.get("max_combo_behavior") or BEHAVIOR_RESET),
            steps=steps,
        )

    # ---- 查询 ----

    def step_from(self, skill_id: str) -> Tuple[StepConfig, ...]:
        return tuple(s for s in self.steps if s.from_ == skill_id)

    def step_to(self, skill_id: str) -> Tuple[StepConfig, ...]:
        return tuple(s for s in self.steps if s.to == skill_id)

    def involves(self, skill_id: str) -> bool:
        return any(s.from_ == skill_id or s.to == skill_id for s in self.steps)

    def at_max(self, state: ComboState) -> bool:
        return state.count >= self.max_combo

    @property
    def behavior(self) -> str:
        return self.max_combo_behavior


# ---------------------------------------------------------------------------
# 条件对象（1c2 §1.4 六字段）：count / target_hp_pct / self_status /
# target_status / round / and·or·not 复合
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConditionCtx:
    """条件求值上下文（来自战斗快照**声明时快照**，1c1a §1.3/L92 不重评）。

    statuses 为 {self: set[str], target: set[str]} 状态 ID 集合（求值失败默认
    「条件不满足」安全失败，L328-329）。
    """

    count: int = 0
    target_hp_pct: float = 100.0
    self_statuses: frozenset = frozenset()
    target_statuses: frozenset = frozenset()
    round_: int = 1


def _cond_bound(cond: Mapping[str, Any], key: str, value: float) -> bool:
    """`{key: {min?, max?, eq?}}` 边界求值（min/max 含边界，TC-11「≤ 含边界」）。"""
    if not isinstance(cond, Mapping):
        return False
    mn = cond.get("min")
    mx = cond.get("max")
    eq = cond.get("eq")
    ok = True
    if mn is not None:
        try:
            ok = ok and value >= float(mn)
        except (TypeError, ValueError):
            ok = False
    if mx is not None and ok:
        try:
            ok = ok and value <= float(mx)
        except (TypeError, ValueError):
            ok = False
    if eq is not None and ok:
        try:
            ok = ok and abs(float(value) - float(eq)) < 1e-9
        except (TypeError, ValueError):
            ok = False
    return ok


def _status_has(cond: Mapping[str, Any], ctx: ConditionCtx) -> bool:
    """self_status/target_status: {has: [status_id]} 子句（引用 statuses.json）。"""
    which = "self"
    for key in ("self_status", "target_status"):
        c = cond.get(key)
        if not isinstance(c, Mapping):
            continue
        if key == "target_status":
            which = "target"
        has = c.get("has")
        ids = (has,) if isinstance(has, str) else (list(has) if isinstance(has, list) else [])
        pool = ctx.target_statuses if which == "target" else ctx.self_statuses
        if not isinstance(pool, (set, frozenset, list, tuple)):
            return False
        if all(sid in pool for sid in ids if isinstance(sid, str)):
            return True
    return False


def _eval_marks_sub(
    sub: Any,
    which: str,
    marks_lookup: Optional[Callable[[str, str, Mapping[str, Any], Optional[str]], bool]],
    mkey: str,
) -> bool:
    """印记条件子句（细化_1d §3.1 C-1..C-5）→ 转接 marks_lookup（battle 注入的
    MarksManager.evaluate，唯一正确实现）。

    - C-1/C-2（self_marks/target_marks）：`{mark_id: {min|max}}` 任一满足（V-2 至少其一，
      1d L146-147）；退化 `{min|max}` → 总数
    - C-3 marks_total / C-4 marks_set(all) / C-5 marks_any(种类数)：rule 直传
    - 无 marks_lookup → False（安全失败，1c3 TC-13）
    """
    if marks_lookup is None:
        return False
    if not isinstance(sub, Mapping):
        return False
    if mkey in ("self_marks", "target_marks"):
        for mid, r in sub.items():
            if isinstance(mid, str) and isinstance(r, Mapping):
                if marks_lookup(mkey, which, r, mid):
                    return True  # 任一指定印记满足（V-2）
        # 退化：sub 直接是 {min|max}(:N)（无印记指定）→ 总数口径；否则指定印记均不满足 → False
        if "min" in sub or "max" in sub or "eq" in sub:
            return bool(marks_lookup(mkey, which, sub, None))
        return False
    return bool(marks_lookup(mkey, which, sub, None))


def evaluate_condition(
    cond: Optional[Mapping[str, Any]],
    ctx: ConditionCtx,
    marks_lookup: Optional[Callable[[str, str, Mapping[str, Any], Optional[str]], bool]] = None,
) -> bool:
    """ConditionObject 递归求值；求值失败/未知键默认「条件不满足」（安全失败）。

    支持：
      - {count: {eq|min|max}} 段数（TC-03/11/12）
      - {target_hp_pct: {min|max}} 目标血量百分比（TC-09-11，边界含）
      - {self_status: {has: [...]}} {target_status: {has:[...]}} 状态引用
      - {round: {eq|min|max}} 战斗第 N 回合，与段数独立（TC-14/L214）
      - {self_marks/target_marks/marks_total/marks_set/marks_any: ...} 印记条件
        （1d §3.1 C-1..C-5，需 marks_lookup 接线；无接线或求值失败 → 不满足）
      - 复合 {and: [...]}/{or: [...]}/{not: {...}} 任意拓扑（TC-09/L91）
    **未知键 → 条件不满足**（1c3 TC-13「未注册字段/求值异常 → 安全失败」；P0-1 修复：
    原实现静默忽略未知键恒 True，含印记条件的派生无条件触发——反安全）。
    未配置 condition（{}）+ 恒可用：返回 True（1c2 §1.2 字段 10「缺省=无条件」）。
    """
    c = cond if isinstance(cond, Mapping) else {}
    if not c:
        return True

    result = True

    def _slot_bound(sub: Any, value: float, default_key: str) -> bool:
        """条件槽求值：简写裸数字 → eq（如 {"count": 2}，1c1c TC-11 简写形态）；
        对象形态 {eq|min|max} → 按界求值。原实现 `"min" in sub` 对 int 简写 TypeError（P0 收口修复）。"""
        if isinstance(sub, Mapping):
            key = "eq" if "eq" in sub else ("min" if "min" in sub else
                                            ("max" if "max" in sub else default_key))
            return _cond_bound(sub, key, value)
        try:
            return _cond_bound({"eq": float(sub)}, "eq", value)
        except (TypeError, ValueError):
            return False  # 无法数值化 → 条件不满足（安全失败）

    # 单条件槽
    for key, spec in (
        ("count", (ctx.count, "eq")),
        ("target_hp_pct", (ctx.target_hp_pct, "min")),
        ("round", (ctx.round_, "eq")),
    ):
        if key in c and not _slot_bound(c[key], spec[0], spec[1]):
            result = False
    for skey in ("self_status", "target_status"):
        sc = c.get(skey)
        if isinstance(sc, Mapping) and "has" in sc:
            if not _status_has({skey: sc}, ctx):
                result = False

    # 复合操作符（任意拓扑）
    if "and" in c:
        subs = c["and"]
        subs = subs if isinstance(subs, list) else [subs]
        if not all(evaluate_condition(s, ctx, marks_lookup) for s in subs if isinstance(s, Mapping)):
            result = False
    if "or" in c:
        subs = c["or"]
        subs = subs if isinstance(subs, list) else [subs]
        if not any(evaluate_condition(s, ctx, marks_lookup) for s in subs if isinstance(s, Mapping)):
            result = False
    if "not" in c:
        if evaluate_condition(c["not"], ctx, marks_lookup):
            result = False

    # 印记条件（1d §3.1 C-1..C-5；marks_lookup 由 battle 接线，转 MarksManager.evaluate——
    # D1 定稿对照修复：原自建 _eval_marks 语法与 1d 规范不符（C-1 指定印记 min/max、
    # C-4 all 齐备、C-5 种类数），改全量转接 marks.py 唯一正确实现）
    for mkey, which in (("self_marks", "self"), ("target_marks", "target"),
                        ("marks_total", "self"), ("marks_set", "self"), ("marks_any", "self")):
        if mkey in c and not _eval_marks_sub(c[mkey], which, marks_lookup, mkey):
            result = False

    # 未知键 → 安全失败（1c3 TC-13；P0-1 修复：原静默忽略恒 True）
    _KNOWN = {"count", "target_hp_pct", "round", "self_status", "target_status",
              "and", "or", "not",
              "self_marks", "target_marks", "marks_total", "marks_set", "marks_any"}
    for k in c:
        if not isinstance(k, str) or k not in _KNOWN:
            result = False
    return result


# ---------------------------------------------------------------------------
# 派生引用 / 行动结果 / 打断结果
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DerivationRef:
    """pending_derivations 项（1c1a §2.2 字段 7：步骤引用，含求值结果）。"""

    step: StepConfig
    ok: bool = True
    reason: str = ""                 # 条件不满足时标注原因（"需连段2"，TC-04）

    @property
    def to_skill(self) -> str:
        return self.step.to


@dataclass(frozen=True)
class ComboActionResult:
    """单次连段性行动的结果（battle 层消费：形态替换/计数/反馈事件）。

    - ok: 行动是否被接受（命令被拒=false，不改连段不耗回合，⑥）
    - rejected: 是否被拒（MP/冷却/条件，⑥）——rejected 必与 ok=False 同现
    - count_before/count_after: 结算前后段数
    - chain_id/chain_name: 行动结算后活跃链（可为 None）
    - form_id: 实际结算的技能形态（派生→step.to，自动替换→to，否则原 skill_id）
    - derivation: 本次是否派生施放（路径 a/c）
    - step: 命中的步（派生/自动替换时）
    - consume: 本次消耗段数（派生 step.consume）
    - armor: 本次施放是否霸体（技能 armor 或派生 step.armor）
    - cleared_reason: 本次结算清除连段的原因（None=未清除）
    - state: 结算后状态机态（展示层；不落档，1c1a §2.2 字段 6）
    - messages: 反馈消息（"连段中断！…" / "🔥 完美连段！…"）
    """

    ok: bool = True
    rejected: bool = False
    reject_reason: str = ""
    count_before: int = 0
    count_after: int = 0
    chain_id: Optional[str] = None
    chain_name: Optional[str] = None
    form_id: Optional[str] = None
    derivation: bool = False
    step: Optional[StepConfig] = None
    consume: int = 0
    armor: bool = False
    cleared_reason: Optional[str] = None
    state: str = COMBO_IDLE
    messages: Tuple[str, ...] = ()
    max_combo: int = 0
    at_max: bool = False


@dataclass(frozen=True)
class InterruptResult:
    """打断技结算结果（1c2 §2.2 攻击窗口判定）。"""

    success: bool                    # 是否成功清零目标连段
    target: str
    reason: str                      # "no_active" / "armor" / "hold_immune" / "cleared"
    message: str
    target_count_before: int = 0
    target_count_after: int = 0


# ---------------------------------------------------------------------------
# 状态推导（1c1a §1.0 六态；state 为运行期推导态，不落档）
# ---------------------------------------------------------------------------


def derive_state(
    state: ComboState,
    chain: Optional[ChainConfig],
    pending: Sequence[DerivationRef] = (),
    deriving: bool = False,
) -> str:
    """由（state, 链配置, 待派生列表, 是否派生中）推导六态。

    - 无链或 count<=0    → idle（空闲）
    - count>=max         → at_max_hold / at_max_reset（按链 behavior）
    - 派生中             → deriving
    - 有待派生           → derivable（段数达标，不强制派生）
    - 其余               → in_combo
    """
    if deriving:
        return COMBO_DERIVING
    if not bool(state.chain_id) or state.count <= 0:
        return COMBO_IDLE
    if chain is not None and chain.at_max(state):
        return COMBO_AT_MAX_HOLD if chain.behavior == BEHAVIOR_HOLD else COMBO_AT_MAX_RESET
    if any(d.ok for d in pending):
        return COMBO_DERIVABLE
    return COMBO_IN_COMBO


# ---------------------------------------------------------------------------
# 配置解析器
# ---------------------------------------------------------------------------


def default_resolver(defs: Optional[Mapping[str, Any]] = None) -> Callable[[str, str], Any]:
    """扁平 defs 映射解析器（kind 无关，对齐 battle._make_battle_resolver）。"""
    if defs is None:
        return lambda _id_, _kind: None
    return lambda id_, _kind: defs.get(id_)


def validate_chain(raw: Mapping[str, Any], warnings: Optional[List[str]] = None) -> List[str]:
    """combo 专项轻量校验（1c1c §1.3 校验器要点 / 1c2 §1.4 校验器）。

    **提示不拒绝**：返回（或追加到 warnings）的均为提示性内容，加载方自行决策。
    - reset 模式 eq=max → 死配置提示（L357/TC-TOP-03），建议 hold 或 min-max；
    - count 条件 min/max 与 max_combo 矛盾（1c2 §1.4/L355-356）；
    - eq > max_combo → 死配置提示（L355-356）；
    - 环形链：**环=特性允许**（D11 拍板，用户 2026-08-19 / TC-16「环=特性」）——只查
      「从 trigger_skill 入口可达性」，不可达节点为死配置 → 提示（TC-17）；环本身不报错；
    - armor 步骤无任何代价配置 → 「霸体无代价」提示（1c2 §2.5/§10.5）。
    """
    out: List[str] = []
    if warnings is None:
        sink_holder: Optional[List[str]] = None
    else:
        sink_holder = warnings
        sink_holder.clear()

    def _emit(msg: str) -> None:
        out.append(msg)
        if sink_holder is not None:
            sink_holder.append(msg)

    chain = ChainConfig.from_raw(raw)
    # 环 + 可达性（从 trigger_skill 起沿 from→to 边 BFS；链环合法但必须可达）
    reachable: Dict[str, bool] = {chain.trigger_skill: True}
    queue = [chain.trigger_skill]
    visited: set = set()
    while queue:
        cur = queue.pop()
        if cur in visited:
            continue
        visited.add(cur)
        for s in chain.steps:
            if s.from_ == cur and s.to not in reachable:
                reachable[s.to] = True
                queue.append(s.to)
    for s in chain.steps:
        if s.from_ not in reachable:
            _emit(f"链 {chain.id}：从入口 {chain.trigger_skill!r} 不可达节点 {s.from_!r}（死配置，TC-17）")
        if s.to not in reachable:
            _emit(f"链 {chain.id}：从入口 {chain.trigger_skill!r} 不可达节点 {s.to!r}（死配置，TC-17）")

    if chain.behavior == BEHAVIOR_RESET:
        for s in chain.steps:
            c = s.condition
            cc = c.get("count") if isinstance(c, Mapping) else None
            if isinstance(cc, Mapping) and "eq" in cc:
                try:
                    if int(cc["eq"]) == chain.max_combo:
                        _emit(
                            f"链 {chain.id}：reset 模式步 #{s.index} eq={cc['eq']}==max_combo，"
                            f"到顶归零死配置（L357），建议 hold 或 min-max"
                        )
                except (TypeError, ValueError):
                    pass
                else:
                    try:
                        if int(cc["eq"]) > chain.max_combo:
                            _emit(f"链 {chain.id}：步 #{s.index} eq={cc['eq']} > max_combo（死配置，L355）")
                    except (TypeError, ValueError):
                        pass
    # count min/max 与 max_combo 矛盾
    for s in chain.steps:
        c = s.condition
        cc = c.get("count") if isinstance(c, Mapping) else None
        if not isinstance(cc, Mapping):
            continue
        mn = cc.get("min")
        mx = cc.get("max")
        try:
            if mn is not None and int(mn) > chain.max_combo:
                _emit(f"链 {chain.id}：步 #{s.index} count.min={mn} > max_combo（死配置，L356）")
            if mx is not None and int(mx) > chain.max_combo:
                _emit(f"链 {chain.id}：步 #{s.index} count.max={mx} > max_combo（死配置，L356）")
        except (TypeError, ValueError):
            pass
    # armor 无代价提示
    for s in chain.steps:
        if s.armor and not s.variant_override:
            _emit(f"链 {chain.id}：步 #{s.index} armor 无任何代价配置（霸体无代价，注意永动机，§10.5）")
    return out


# ---------------------------------------------------------------------------
# 运行时：ComboEngine（无状态；以战斗快照为权威）
# ---------------------------------------------------------------------------


class ComboEngine:
    """连段引擎运行时：读写 `snap["combo_state"][side]` 五字段；纯函数化判定。

    - config：引擎配置（COMBO_DEFAULT_CONFIG 合并覆盖）
    - defs/registry：内容源（kind="skill_chain" 解析链、kind="skill" 解析技能）
    - 约束：技能标签仅作用于玩家侧（1c1a §2.3 作用域）；怪物侧 P1 预留。
    """

    def __init__(
        self,
        defs: Optional[Mapping[str, Any]] = None,
        registry: Any = None,
        resolver: Optional[Callable[[str, str], Any]] = None,
        config: Optional[Mapping[str, Any]] = None,
        marks_lookup: Optional[Callable[[str, str, Mapping[str, Any], Optional[str]], bool]] = None,
    ) -> None:
        self._marks_lookup = marks_lookup   # 印记条件求值注入（P0-1/D1；battle 构造后绑定，转 MarksManager.evaluate）
        if resolver is not None:
            self._resolver = resolver
        elif registry is not None:
            if callable(registry):
                self._resolver = registry  # type: ignore[assignment]
            else:
                resolve = getattr(registry, "resolve", None)
                if callable(resolve):
                    self._resolver = lambda id_, kind: resolve(id_, kind)  # type: ignore[misc]
                else:
                    self._resolver = default_resolver(defs)
        else:
            self._resolver = default_resolver(defs)
        self._defs = dict(defs or {})
        self._config: Dict[str, Any] = dict(COMBO_DEFAULT_CONFIG)
        if config:
            self._config.update(config)

    # ------------------------- 快照访问 -------------------------

    @staticmethod
    def state_of(snap: Mapping[str, Any], side: str) -> ComboState:
        """读取侧内 combo_state（缺省=空闲；对非法形态安全收敛）。"""
        cs = snap.get("combo_state")
        if isinstance(cs, Mapping):
            d = cs.get(side)
            if isinstance(d, Mapping):
                return ComboState.from_dict(d)
        return empty_combo_state()

    @staticmethod
    def write_state(snap: Dict[str, Any], side: str, state: ComboState) -> None:
        """写入侧内 combo_state（按侧嵌套；保留瞬态键如 interrupted）。"""
        cs = snap.setdefault("combo_state", {})
        if not isinstance(cs, dict):
            cs = snap["combo_state"] = {}
        prev = cs.get(side)
        merged: Dict[str, Any] = {}
        if isinstance(prev, dict):
            merged = dict(prev)
        merged.update(state.to_dict())
        cs[side] = merged

    # ------------------------- 配置解析 -------------------------

    def chain_by_id(self, chain_id: str) -> Optional[ChainConfig]:
        d = self._resolver(chain_id, "skill_chain")
        return ChainConfig.from_raw(d) if isinstance(d, Mapping) else None

    def chains_of_skill(self, skill_id: str) -> Tuple[ChainConfig, ...]:
        """技能参与的链（trigger_skill 或任意步 from/to 命中；无 skill_chains 表
        ID 时尝试 `key==skill_id` 的链配置直读）。"""
        out: List[ChainConfig] = []
        # 直读：defs 里 skill_id 本身就是链配置（链 ID==技能参与键的测试捷径不做，
        # 统一走 from/to 命中 + trigger_skill）
        for cid, raw in self._defs.items():
            if not isinstance(raw, Mapping):
                continue
            chain = ChainConfig.from_raw(raw)
            if not chain.id and str(raw.get("id", "")) == "":
                continue
            if (
                chain.trigger_skill == skill_id or chain.involves(skill_id)
            ):
                out.append(chain)
        # registry 路径：按 from/to 反查所有已注册链
        if not out:
            for cid, raw in getattr(self._resolver, "_registry_chains", {}).items():  # pragma: no cover
                pass
        return tuple(out)

    def resolve_skill(self, skill_id: str) -> Mapping[str, Any]:
        d = self._resolver(skill_id, "skill")
        return d if isinstance(d, Mapping) else {}

    def skill_tag(self, skill_id: str) -> str:
        return str(self.resolve_skill(skill_id).get("tag") or "")

    # ------------------------- 条件评估（快照） -------------------------

    def _status_ids(self, snap: Mapping[str, Any], side: str) -> frozenset:
        st = snap.get("status_state")
        if not isinstance(st, Mapping):
            return frozenset()
        insts = st.get(side)
        if not isinstance(insts, list):
            return frozenset()
        ids: set = set()
        for inst in insts:
            if isinstance(inst, Mapping) and inst.get("status_id"):
                ids.add(str(inst["status_id"]))
        return frozenset(ids)

    def condition_ctx(self, side: str, snap: Mapping[str, Any], chain: Optional[ChainConfig] = None) -> ConditionCtx:
        """组装条件求值上下文（声明时快照，1c1a L92 施放后不重评）。"""
        target = "enemy" if side == "player" else "player"
        _self = snap.get(side)
        _tgt = snap.get(target)
        c_self = _self if isinstance(_self, Mapping) else {}
        c_tgt = _tgt if isinstance(_tgt, Mapping) else {}
        tgt_max = float(c_tgt.get("max_hp", 1) or 1)
        state = self.state_of(snap, side)
        return ConditionCtx(
            count=state.count,
            target_hp_pct=(100.0 * float(c_tgt.get("hp", 0) or 0) / tgt_max
                           if tgt_max > 0 else 0.0),
            self_statuses=self._status_ids(snap, side),
            target_statuses=self._status_ids(snap, target),
            round_=int(snap.get("turn", 1)),
        )

    def pending_derivations(self, side: str, snap: Mapping[str, Any]) -> Tuple[DerivationRef, ...]:
        """当前快照满足条件的派生步骤列表（1c1a §2.2 字段 7；多派生全部可用）。

        对所有注册链中「已活跃链 或 未注册但触发技能==动作侧技能」不做动作，
        仅对侧内活跃链的步骤求值；无活跃链 → 空（L92 无链不评估）。
        """
        state = self.state_of(snap, side)
        if not bool(state.chain_id):
            return ()
        chain = self.chain_by_id(state.chain_id)
        if chain is None:
            return ()
        ctx = self.condition_ctx(side, snap)
        out: List[DerivationRef] = []
        for s in chain.steps:
            ok = evaluate_condition(s.condition, ctx, self._marks_lookup)
            reason = ""
            if not ok:
                reason = self._condition_reason(s.condition, ctx)
            out.append(DerivationRef(step=s, ok=ok, reason=reason))
        # 排序：available 在前按 priority 降序（1c2 §1.2 字段 11 仅定序不锁死）
        out.sort(key=lambda r: (0 if r.ok else 1, -r.step.priority, r.step.index))
        return tuple(out)

    def _condition_reason(self, cond: Mapping[str, Any], ctx: ConditionCtx) -> str:
        """条件不满足的原因标注（TC-04「需连段2」置灰；不隐藏）。仅最简提示。"""
        c = cond.get("count") if isinstance(cond, Mapping) else None
        if isinstance(c, Mapping):
            if "eq" in c:
                try:
                    return f"需连段{int(c['eq'])}"
                except (TypeError, ValueError):
                    pass
            parts = []
            if "min" in c:
                parts.append(f"需连段{int(c['min'])}以上")
            if "max" in c:
                parts.append(f"需低段数（≤{int(c['max'])}）")
            if parts:
                return "且".join(parts)
        return "条件不满足"

    # ------------------------- 指令被拒（⑥） -------------------------

    def should_reject(
        self,
        side: str,
        action: Mapping[str, Any],
        snap: Mapping[str, Any],
    ) -> Tuple[bool, str]:
        """⑥ 指令被拒判定（MP/冷却/条件）：不耗回合、不改连段、可反复尝试。

        - action["rejected"]=true（外部预设拒绝通道，含条件不足派生强行使用）→ 拒；
        - config.enforce_mp 开启：mp_cost > 当前 mp → 拒（F-24 递延 M5，engine 可测）；
        - 冷却：action["cooldown_remaining"] > 0 → 拒（冷却体系 M5，预留通道）。
        TC-30/32/49-51 数值断言在此收敛（原子拒绝：条件不足派生整体被拒，不消费）。
        """
        if bool(action.get("rejected", False)):
            return True, str(action.get("reject_reason") or "command_rejected")
        _c = snap.get(side)
        c = _c if isinstance(_c, Mapping) else {}
        if self._config.get("enforce_mp"):
            # MP 门槛：优先 action 显式 mp_cost，缺失时回退技能定义（skill def mp_cost，1a §2.2）
            _sid = str(action.get("skill_id") or "")
            cost = int(action.get(
                "skill_mp_cost", action.get(
                    "mp_cost", self.resolve_skill(_sid).get("mp_cost", 0))) or 0)
            mp = int(c.get("mp", 0) or 0)
            if cost > mp:
                return True, "MP不足"
        cd = int(action.get("cooldown_remaining", 0) or 0)
        if cd > 0:
            return True, "冷却中"
        return False, ""

    def can_execute(self, side: str, action: Mapping[str, Any], snap: Mapping[str, Any]) -> bool:
        rej, _ = self.should_reject(side, action, snap)
        return not rej

    # ------------------------- 计数迁移核心（①/②/④/⑤ + consume） -------------------------

    def _apply_delta(self, state: ComboState, chain: ChainConfig, delta: int) -> ComboState:
        """段数变化核心：+1/+0/+N/归零/消耗 -N 的统一车道（1c1b 主迁移 ①②④⑤）。

        - delta < 0（consume）：count 减 N（最低 0），**立即退出 hold 免疫**
          （count<max → hold=False，L164-165）；
        - 到顶且行为 reset 再收到 combo 类正 delta：先归零重打（0 → delta，
          1c1b ④ / TC-TOP-01）；
        - 到顶且行为 hold：保持 max 不再增长（L156，TC-TOP-04），hold=True。
        归零重打浅层：重注册链（chain_id/name 不变仅清 count）由调用方处理。
        """
        cur = state.count
        maxc = chain.max_combo
        if delta < 0:
            nxt = max(0, cur + delta)
            hold = bool(state.hold and nxt >= maxc)
            return ComboState(
                chain_id=state.chain_id, chain_name=state.chain_name,
                count=nxt, hold=hold, step_index=state.step_index,
            )
        if cur >= maxc:
            if chain.behavior == BEHAVIOR_HOLD:
                return ComboState(
                    chain_id=state.chain_id, chain_name=state.chain_name,
                    count=maxc, hold=True, step_index=state.step_index,
                )
            # reset：下次连段技归零重打 → 0 + delta
            cur = 0
        nxt = cur + delta
        if nxt >= maxc:
            nxt = maxc
        hold = bool(nxt >= maxc and chain.behavior == BEHAVIOR_HOLD)
        return ComboState(
            chain_id=state.chain_id, chain_name=state.chain_name,
            count=nxt, hold=hold, step_index=state.step_index,
        )

    # ------------------------- 清零（1c1c §3.1 清零事件全集） -------------------------

    def clear(self, side: str, snap: Dict[str, Any], reason: str) -> ComboState:
        """侧内连段清零（打断/自断/逃跑成功/战斗结束统一入口，A1/A4/T7）。"""
        state = self.state_of(snap, side)
        cleared = empty_combo_state()
        self.write_state(snap, side, cleared)
        snap.setdefault("combo_events", []).append({
            "type": "combo_clear", "side": side,
            "reason": reason, "count_before": state.count,
        })
        return cleared

    def clear_all(self, snap: Dict[str, Any], reason: str) -> None:
        """双侧清零（战斗结束任何原因，1c1c T7/L182；死亡/胜利/失败/逃跑成功）。"""
        for side in ("player", "enemy"):
            self.clear(side, snap, reason)
        snap["combo_zeroed_at"] = reason

    # ------------------------- 打断 / 霸体（1c2 §2.2 / §2.5） -------------------------

    def is_armored(self, side: str, snap: Mapping[str, Any], armor_active: Optional[Mapping[str, bool]] = None) -> bool:
        """目标当前是否处于霸体：「使用期间」= 行动开始 → 本次结算完成（1c2 §2.2）。

        数据源：战斗层瞬态 armor_active（本回合声明且已进入结算的技能 armor=true）
        + 效果系统免疫矩阵 immune_vs:interrupt（1c2 §1.3 字段 19 归口。
        两个来源任一为真即霸体）。
        """
        if armor_active and bool(armor_active.get(side, False)):
            return True
        return False

    def apply_interrupt(
        self,
        attacker: str,
        target: str,
        snap: Dict[str, Any],
        armor_active: Optional[Mapping[str, bool]] = None,
    ) -> InterruptResult:
        """打断技结算（1c2 §2.2 攻击窗口三条件同时满足才生效）：

        1) 目标「正在连段」= combo_state[target].count > 0（链活跃）；
        2) 目标不处于霸体（armor=true 且尚未结算完成）；
        3) 目标非 hold 到顶免疫态（count==max 且 behavior=hold，L163 被动态）。
        生效 → 目标连段清零（A1）；被打断技自身以无标签普通技能处理自身连段
        （TC-INT-04 也在 battle 层消费）；消息对齐（TC-34/36）。
        """
        t_state = self.state_of(snap, target)
        chain = self.chain_by_id(t_state.chain_id) if t_state.chain_id else None
        # ① 正在连段
        if not t_state.active:
            return InterruptResult(
                False, target, "no_active",
                f"{target} 无活跃连段，打断无效果（仍耗回合/MP）",
                t_state.count, t_state.count,
            )
        # ② 霸体免疫
        if self.is_armored(target, snap, armor_active):
            _c = snap.get(target)
            c = _c if isinstance(_c, Mapping) else {}
            names = str(c.get("name") or target)
            return InterruptResult(
                False, target, "armor",
                f"🛡 {names}（霸体）！无视打断",
                t_state.count, t_state.count,
            )
        # ③ hold 到顶免疫（被动态，仅 combo==max）
        if chain is not None and chain.behavior == BEHAVIOR_HOLD and t_state.count >= chain.max_combo:
            return InterruptResult(
                False, target, "hold_immune",
                f"{target} 连段已到顶（hold），免疫打断",
                t_state.count, t_state.count,
            )
        # 生效：清零
        before = t_state.count
        self.clear(target, snap, "interrupted_by_shield_bash")
        msg = f"⚡ {attacker} 打断 {target} 连段！连段中断"
        return InterruptResult(
            True, target, "cleared", msg, before, 0,
        )

    # ------------------------- 行动主入口：连段语义结算 -------------------------

    def cast_info(
        self,
        side: str,
        action: Mapping[str, Any],
        snap: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """**只读**施放预解析（battle 层结算前调用，不写快照）。

        返回 {skill_id, tag, name, chain_id, chain_name, form_id, derivation,
        step, armor, consume, rejected, reject_reason, is_at_max_reach}。
        - armor：本次施放是否霸体（技能 armor 或派生步 armor，供打断窗口）
        - rejected：⑥ 指令被拒（MP/冷却/条件不足派生），battle 可短路
        - form_id：派生命中时为派生形态（TC-03/TC-21 替换结算）
        - is_at_max_reach：reset 链本次 +1 将达顶（_at_max_derivation 候选）
        与 apply_action 保持同一解析源（_resolve_derivation/链解析），同步维护。
        """
        state = self.state_of(snap, side)
        skill_id = str(action.get("skill_id") or action.get("id") or "")
        skill = self.resolve_skill(skill_id)
        tag = str(action.get("tag") or skill.get("tag") or "")
        armor_skill = bool(action.get("armor", skill.get("armor", False)))
        if tag == TAG_ARMOR:
            armor_skill = True

        chain: Optional[ChainConfig] = None
        if bool(state.chain_id):
            chain = self.chain_by_id(state.chain_id)
        if chain is None:
            chains = self.chains_of_skill(skill_id)
            if chains:
                chain = chains[0]

        form_id = skill_id
        step: Optional[StepConfig] = None
        derivation = False
        consume = 0
        rejected = False
        reject_reason = ""
        if chain is not None and bool(chain.id):
            deriv_info = self._resolve_derivation(side, skill_id, state, chain, snap)
            if deriv_info is not None:
                if deriv_info["rejected"]:
                    rejected, reject_reason = True, deriv_info["reason"]
                elif deriv_info["derived"]:
                    step = deriv_info["step"]
                    derivation = True
        # 指令被拒（⑥ 与派生条件不足均可拒）
        if not rejected:
            rej, reason = self.should_reject(side, action, snap)
            if rej:
                rejected, reject_reason = True, reason

        if step is not None:
            form_id = step.to
            consume = step.consume
        armor = armor_skill or bool(step and step.armor)
        at_max_reach = bool(
            chain is not None
            and tag == TAG_COMBO
            and step is None
            and chain.behavior == BEHAVIOR_RESET
            and state.count + 1 >= chain.max_combo
        )
        return {
            "skill_id": skill_id,
            "tag": tag,
            "name": str(skill.get("name") or skill_id),
            "chain_id": chain.id if chain else None,
            "chain_name": chain.name if chain else None,
            "form_id": form_id,
            "derivation": derivation,
            "step": step,
            "armor": armor,
            "consume": consume,
            "rejected": rejected,
            "reject_reason": reject_reason,
            "is_at_max_reach": at_max_reach,
            "skill_raw": skill,
        }

    def apply_action(
        self,
        side: str,
        action: Mapping[str, Any],
        snap: Dict[str, Any],
        armor_active: Optional[Mapping[str, bool]] = None,
        marks_lookup: Optional[Callable[[str, str, Mapping[str, Any], Optional[str]], bool]] = None,
    ) -> ComboActionResult:
        """玩家侧连段性行动结算（1c1b 主迁移 ①②③④⑤⑥ + A4 无标签自断）。

        action 关键键：type/skill_id/tag/mult/armor/combo_push_amount/hits/
        effects/mp_cost/consume/rejected。非连段行动（guard/item/flee）由
        battle 层短路，不调用本方法（⑧ 防御/道具不打断，自环）。

        marks_lookup：印记条件求值注入（P0-1 / 1d §3.1）——which self/target →
        印记层数（mark_id=None 为该侧总数）；None 时含印记条件 → 不满足（安全失败）。
        返回值含 ok=false(rejected)→ ⑥ 不改连段；derive()/clear 结果供
        battle 层装配消息与伤害形态。
        """
        if marks_lookup is not None:
            self._marks_lookup = marks_lookup
        state = self.state_of(snap, side)
        skill_id = str(action.get("skill_id") or action.get("id") or "")
        tag = str(action.get("tag") or self.skill_tag(skill_id))
        armor_skill = bool(action.get("armor", False))
        if tag == TAG_ARMOR:
            armor_skill = True

        # ⑥ 指令被拒
        rejected, rej_reason = self.should_reject(side, action, snap)
        if rejected:
            return ComboActionResult(
                ok=False, rejected=True, reject_reason=rej_reason,
                count_before=state.count, count_after=state.count,
                chain_id=state.chain_id, chain_name=state.chain_name,
                state=derive_state(state, self.chain_by_id(state.chain_id) if state.chain_id else None),
                messages=(f"指令被拒（{rej_reason}）：不改连段、不耗回合",),
            )

        # 链解析：已有活跃链 或 首次使用注册（trigger_skill/参与技能命中）
        chain = None
        if bool(state.chain_id):
            chain = self.chain_by_id(state.chain_id)
        if chain is None:
            chains = self.chains_of_skill(skill_id)
            if chains:
                chain = chains[0]
                # 注册当前链（L189：连段技使用即注册；旧链进度按链独立存储 ——
                # 单活跃链作用域内，切换链直接覆盖注册）
                state = ComboState(
                    chain_id=chain.id, chain_name=chain.name,
                    count=0, hold=False, step_index=-1,
                )

        if chain is None or not bool(chain.id):
            # 无链：无标签普通技能 → 自己打断自己（A4，L45/L53）。
            # 空闲态（本无链可断，1c1a §1.1）：普通技能无「自断」语义——无操作返回。
            if not state.active:
                return ComboActionResult(
                    ok=True, count_before=state.count, count_after=state.count,
                    chain_id=None, chain_name=None, form_id=skill_id,
                    state=COMBO_IDLE, max_combo=0, at_max=False,
                )
            if tag in (TAG_COMBO, TAG_PRESERVE, TAG_PUSH, TAG_INTERRUPT, TAG_ARMOR):
                # 标记了 combo 但无链可注册：降级无链=普通技能（L343 链删除语义）
                return self._zero_self(side, state, snap,
                                       reason="chain_missing",
                                       msg="连段中断！（原因：链不可用）",
                                       state_val=derive_state(state, None))
            self.clear(side, snap, "plain_skill_no_tag")
            return ComboActionResult(
                ok=True, count_before=state.count, count_after=0,
                chain_id=None, chain_name=None, form_id=skill_id,
                cleared_reason="plain_skill_no_tag",
                state=COMBO_IDLE,
                messages=("连段中断！（原因：使用了普通技能）",),
                max_combo=0, at_max=False,
            )

        # ---- 派生解析（TC-03/04/06/15；声明时快照评估一次，L92）----
        deriv_info = self._resolve_derivation(side, skill_id, state, chain, snap)
        # 派生被拒（条件不足强行使用派生技）：⑥ 整体拒绝，不消费任何资源（TC-32/50/51）
        if deriv_info is not None and deriv_info["rejected"]:
            return ComboActionResult(
                ok=False, rejected=True, reject_reason=deriv_info["reason"],
                count_before=state.count, count_after=state.count,
                chain_id=state.chain_id, chain_name=state.chain_name,
                form_id=skill_id,
                state=derive_state(state, chain),
                messages=(f"命令被拒（{deriv_info['reason']}）：派生不可用，不改连段",),
            )

        step = deriv_info["step"] if deriv_info else None
        is_derivation = deriv_info is not None and deriv_info["derived"]
        auto_replaced = bool(deriv_info and deriv_info.get("auto_replaced"))
        form_id = skill_id
        armor = armor_skill
        consumed = 0
        if step is not None:
            form_id = step.to
            armor = armor or step.armor
            consumed = step.consume
            # variant_override：仅记录供 battle 层消费（本层不贴伤害）

        # ---- 段数变化（工程收敛③：派生步配置优先）----
        #   派生：consume>0 → -N（L74）；否则 step.tag 显式 → +1/+0/+N；皆缺省 +0
        #   保留（L73「count 不变」——TC-03/TC-DEF-04）。循环互派生如需累计在步配
        #   tag=combo 显式声明（TC-15）。非派生：按技能 tag（combo +1 / push +N /
        #   preserve +0 / 无标签与 interrupt·armor → 自断 A4，hold 到顶豁免）。
        before = state.count
        derived_count_override: Optional[int] = None
        if step is not None and consumed > 0:
            new_state = self._apply_delta(state, chain, -consumed)
        elif step is not None and step.tag is not None:
            if step.tag == TAG_COMBO:
                new_state = self._apply_delta(state, chain, 1)
            elif step.tag == TAG_PUSH:
                new_state = self._apply_delta(state, chain, int(action.get("combo_push_amount", 1) or 1))
            else:  # combo_preserve 或其它显式 tag → +0
                new_state = state
        elif step is not None:
            # 派生默认：保留 count 不变（L73）
            new_state = state
        else:
            # 非派生：技能标签语义
            if tag == TAG_COMBO:
                new_state = self._apply_delta(state, chain, 1)
            elif tag == TAG_PUSH:
                new_state = self._apply_delta(state, chain, int(action.get("combo_push_amount", 1) or 1))
            elif tag == TAG_PRESERVE:
                new_state = state
            else:
                # 无标签 / interrupt / armor：普通技能语义
                if chain.behavior == BEHAVIOR_HOLD and state.count >= chain.max_combo:
                    # hold 到顶豁免（TC-TOP-05 / L157 特例）：普通技能不清零
                    new_state = state
                else:
                    # A4 自己打断自己（L45/L53）
                    self.write_state(snap, side, empty_combo_state())
                    snap.setdefault("combo_events", []).append({
                        "type": "combo_clear", "side": side,
                        "reason": "plain_skill_no_tag", "count_before": state.count,
                    })
                    return ComboActionResult(
                        ok=True, count_before=before, count_after=0,
                        chain_id=None, chain_name=None, form_id=skill_id,
                        cleared_reason="plain_skill_no_tag",
                        state=COMBO_IDLE,
                        messages=("连段中断！（原因：使用了普通技能）",),
                        max_combo=chain.max_combo, at_max=False,
                    )

        # ---- 到顶当回合 eq=max 派生（TC-21 / TC-TOP-02，L158）----
        # reset 链：本次 +1 达顶后，按**新快照**（count==max）先判 eq=max 派生并
        # 执行（替换形态），再执行归零重打（count→0，下回合 0→1）。
        if (
            step is None
            and new_state.count >= chain.max_combo
            and chain.behavior == BEHAVIOR_RESET
            and tag == TAG_COMBO
        ):
            max_step = self._at_max_derivation(side, skill_id, chain, snap, new_state)
            if max_step is not None:
                step = max_step
                is_derivation = True
                auto_replaced = True
                derived_count_override = 0   # 达顶归零重打（1c1c §1.1 ③）
                form_id = max_step.to
                armor = armor or max_step.armor
                consumed = max_step.consume

        after = new_state.count if derived_count_override is None else derived_count_override
        # D4（combo 定稿对照 2026-08-19）：派生/自动替换命中步写入 step_index（1c1a §2.1
        # 字段 5「最近执行步骤索引」——原实现从不写 ≥0，互派生形态机进度无载体）
        _step_index = new_state.step_index
        if step is not None:
            _step_index = step.index
        post_state = (
            ComboState(
                chain_id=new_state.chain_id, chain_name=new_state.chain_name,
                count=after, hold=new_state.hold, step_index=_step_index,
            )
            if derived_count_override is not None else
            (ComboState(chain_id=new_state.chain_id, chain_name=new_state.chain_name,
                        count=new_state.count, hold=new_state.hold, step_index=_step_index)
             if step is not None else new_state)
        )
        self.write_state(snap, side, post_state)
        pending_post = tuple(r for r in self.pending_derivations(side, snap))
        st = derive_state(post_state, chain, pending_post, deriving=False)
        msgs: List[str] = []
        if step is not None:
            form_name = self._skill_name(step.to) or step.to
            msgs.append(f"🔥 完美连段！{form_name}")
        if derived_count_override == 0:
            msgs.append(f"连段到顶（{chain.max_combo}），归零重打")
        if post_state.count >= chain.max_combo and chain.behavior == BEHAVIOR_HOLD and consumed > 0:
            msgs.append(f"连段消耗 {consumed} 段，退出 hold 免疫（{post_state.count}/{chain.max_combo}）")

        return ComboActionResult(
            ok=True,
            count_before=before, count_after=after,
            chain_id=post_state.chain_id, chain_name=post_state.chain_name,
            form_id=form_id,
            derivation=is_derivation,
            step=step,
            consume=consumed,
            armor=armor,
            state=st,
            messages=tuple(msgs),
            max_combo=chain.max_combo,
            at_max=after >= chain.max_combo,
        )

    def _at_max_derivation(
        self,
        side: str,
        skill_id: str,
        chain: ChainConfig,
        snap: Mapping[str, Any],
        post_state: ComboState,
    ) -> Optional[StepConfig]:
        """reset 链达顶当回合的 eq=max 派生判定（L158，基于**达顶后新快照**）。

        仅在 count==max 的 replace 步 → 返回该步（每条来自基技能、条件达顶可用）。
        无则 None（本次为纯达顶，下回连段技归零重打）。
        """
        ctx = ConditionCtx(
            count=post_state.count,
            target_hp_pct=self.condition_ctx(side, snap).target_hp_pct,
            self_statuses=self._status_ids(snap, side),
            target_statuses=self._status_ids(snap, self._target_of(side)),
            round_=int(snap.get("turn", 1)),
        )

        def _avail(s: StepConfig) -> bool:
            return evaluate_condition(s.condition, ctx, self._marks_lookup)

        cands = [s for s in chain.steps if s.from_ == skill_id and s.mode == MODE_REPLACE and _avail(s)]
        if not cands:
            return None
        return max(cands, key=lambda s: (s.priority, -s.index))

    @staticmethod
    def _target_of(side: str) -> str:
        return "enemy" if side == "player" else "player"

    def _skill_name(self, skill_id: str) -> str:
        s = self.resolve_skill(skill_id)
        name = s.get("name")
        return str(name) if name else skill_id

    def _zero_self(
        self, side: str, state: ComboState, snap: Dict[str, Any],
        reason: str, msg: str, state_val: str,
    ) -> ComboActionResult:
        self.clear(side, snap, reason)
        return ComboActionResult(
            ok=True, count_before=state.count, count_after=0,
            chain_id=None, chain_name=None,
            cleared_reason=reason, state=state_val,
            messages=(msg,),
        )

    def _resolve_derivation(
        self,
        side: str,
        skill_id: str,
        state: ComboState,
        chain: ChainConfig,
        snap: Mapping[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """派生解析（工程收敛②，返回 dict 或 None）：

        - 返回 None：无派生相关（纯连段/普通技能路径）；
        - 返回 {derived, step, auto_replaced, rejected, reason}：
            derived=True    → 命中派生（路径 a：cast to 且可用；或路径 c：cast
                              from 且 replace 可用自动替换）；
            rejected=True   → 派生条件不足强行使用（路径 b：cast to 但不可用，
                              TC-04；或派生 MP 不足原子拒绝）；
        """
        to_steps = [s for s in chain.steps if s.to == skill_id]
        from_steps = [s for s in chain.steps if s.from_ == skill_id]
        if not to_steps and not from_steps:
            return None

        # 条件求值（声明时快照一次）
        ctx = self.condition_ctx(side, snap)

        def _avail(s: StepConfig) -> bool:
            return evaluate_condition(s.condition, ctx, self._marks_lookup)

        # 路径 a：cast to（派生形态）——命中可用步 → 派生
        if to_steps:
            avail = [s for s in to_steps if _avail(s)]
            if avail:
                pick = max(avail, key=lambda s: (s.priority, -s.index))
                return {"derived": True, "step": pick, "auto_replaced": False,
                        "rejected": False, "reason": ""}
            # 路径 b：cast to 但条件不满足 → 按要求返回被拒（H2 修正，2026-08-19 定稿对照：
            # 原注释称「降级源技能（TC-04 强行使用按原技能）」，但实现=整体被拒——TC-04
            # （强行使用按原技能）∨ TC-32（条件不足派生整体被拒）同场景冲突，已上报仲裁。
            base = to_steps[0]
            return {"derived": False, "step": None, "auto_replaced": False,
                    "rejected": True,
                    "reason": self._condition_reason(base.condition, ctx)}

        # 路径 c：cast from（基技能）——存在可用 replace 步 → 自动替换（TC-03）
        # 门限：仅当预施放 count < max（到顶不自动替换；到顶当回合的 eq=max 派生由
        # _at_max_derivation 在达顶后新快照判定，TC-21/TC-TOP-02）。
        if from_steps and state.count < chain.max_combo:
            avail = [s for s in from_steps if _avail(s)]
            # avail 中仅 replace 自动（enhance/append/unlock 由玩家显式施放 to 触发）。
            replace_avail = [s for s in avail if s.mode == MODE_REPLACE]
            if replace_avail:
                pick = max(replace_avail, key=lambda s: (s.priority, -s.index))
                return {"derived": True, "step": pick, "auto_replaced": True,
                        "rejected": False, "reason": ""}
            return None

        return None
