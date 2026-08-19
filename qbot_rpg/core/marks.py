"""印记系统状态管理器（M1-批3 · 细化_1d_印记系统契约 落地）。

依据（只引细化节号，不编造行号）：
  - 细化_1d_印记系统契约：§0.3 ADR D-01..D-05、§2.1 marks_state 结构（实例 6 字段
    mark_id / name / count / applier / polarity / remaining_turns?）、§2.2 生命周期、
    §3.1 条件原语 C-1..C-5、§3.2 原子动作 A-1..A-3、§4（D-03 饱和减法）、
    §五 边界（不吃驱散/免疫/反射/解除）、§六 验收 AT-01..AT-20。
  - 《印记系统设计定稿》v1.0：§二 定义 schema（max_stack / appliable_to / polarity /
    element / duration）、§2.1 极性规则、§三 实例与状态（双向表、name 冗余、剩余回合
    入快照）、§4.1 施加（必中/到顶不再涨）、§4.2 消除寻址、§5.1 条件引用、
    §八 数据汇总。

【分工：唯一实现】印记的施加/消除/条件求值/生命周期 tick 的**唯一实现**在本模块；
core/effects.EffectRuntime 的 add_marks / remove_marks / clear_marks 保持公开签名，
作为薄转接层委托 MarksManager（同 marks_state 同一 dict 对象）；effects.execute_action
的 mark_add / mark_remove / clear_marks 分支消费之——避免双实现。battle 层快照流转与
公式 [印记:X] 求值共用同一 MarksManager（同一 marks_state 双向表，§2.1）。

【存储形态】marks_state = {player: [实例], enemy: [实例]}（§2.1 JSON 契约），实例为
dict（可 JSON 序列化）；manager 绑定调用方传入的 dict 对象（copy=False）或自建
（copy=True / from_snapshot）。同 (side, mark_id) 聚合为单实例（§2.1 双向表即单实例/
mark_id），同来源重复=+count 至上限（§4.1），异 mark_id（可来自不同 applier）并存
（§2.1 双向表天然支持）。

零 NoneBot；公共入参用 frozen dataclass；本模块不 import 任何 qbot_rpg 模块
（effects / battle 反向依赖本模块，避免循环）。
"""

from __future__ import annotations

import copy as _copy
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "BATTLE_SIDES",
    "POLARITIES",
    "AddMark",
    "RemoveMark",
    "ClearMarks",
    "MarkCondition",
    "MarksManager",
]

# 战斗侧（细化_1d §0.3 D-05：applier 取值 = "player" | "enemy"；§三 双向表两侧）
BATTLE_SIDES: Tuple[str, str] = ("player", "enemy")

# 极性枚举（细化_1d §1.1 字段 7 / 印记 §2.1）
POLARITIES: Tuple[str, str] = ("positive", "negative")

# marks_state 快照实例字段（细化_1d §2.1 表「实例 6 字段」）
_MARK_INSTANCE_KEYS: Tuple[str, ...] = (
    "mark_id",
    "name",
    "count",
    "applier",
    "polarity",
    "remaining_turns",
)


def _make_resolver(
    registry: Any = None, defs: Optional[Mapping[str, Any]] = None
) -> Callable[[str, str], Any]:
    """归一化「配置来源」为 callable(id, kind) -> Def|dict|None。

    与 effects._make_resolver 同形（镜像实现，避免循环 import）；defs 为
    {id: Def} 映射（批直连测试），registry 可为 registry.resolve 或 callable。
    """
    if registry is not None:
        if callable(registry):
            return registry
        resolve = getattr(registry, "resolve", None)
        if callable(resolve):
            return lambda id_, kind: resolve(id_, kind)
    if defs is not None:
        return lambda id_, _kind: defs.get(id_)
    return lambda _id_, _kind: None


# ---------------------------------------------------------------------------
# 公共接口（frozen dataclass：原子动作 / 条件原语）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AddMark:
    """mark_add 原子动作（细化_1d §3.2 A-1 / 印记 §4.1）。

    side 为解析后的具体战斗侧（"player"/"enemy"）；相对语义 self/enemy（独立于
    技能伤害 target）由上层 _resolve_side 先行解析（对齐 effects 既有接口）。
    """

    side: str
    mark: str                     # mark_id（印记定义引用键）
    count: int = 1                # ≥1
    applier: Optional[str] = None  # 施加方战斗侧（D-05）；None→默认 "player"


@dataclass(frozen=True)
class RemoveMark:
    """mark_remove 原子动作（细化_1d §3.2 A-2 / 印记 §4.2）。

    寻址 = side + polarity 过滤（+可选 mark 精确指定，D-02）；按层数消；超量=饱和
    减法至 0（D-03，不报错）。
    """

    side: str                     # marks_on 解析后侧
    polarity: str = "positive"    # positive|negative 过滤
    count: int = 1
    mark: Optional[str] = None    # 可选精确指定（D-02）


@dataclass(frozen=True)
class ClearMarks:
    """clear_marks 原子动作（细化_1d §3.2 A-3 / 印记 §4.2）：整组清空（无 count）。"""

    side: str
    polarity: str = "positive"
    mark: Optional[str] = None


@dataclass(frozen=True)
class MarkCondition:
    """印记条件原语（细化_1d §3.1 C-1..C-5）。

    kind ∈ {"marks_total", "marks_set", "marks_any", "marks_single"}；方言
    "self_marks"/"target_marks" 对齐 §3.1 键名（二者等价于单印阈值，求值侧由
    调用方映射到具体表：self→施加者侧，target→技能目标侧）。rule 形如：
      {"min": N} / {"max": N}（至少其一，V-2 要求 min/max 至少一个）
      {"all": ["地","水","火","风"]}（marks_set 齐备，每类 ≥1）
    mark_id 用于 marks_single 定位（取 count），缺省回退 mark_id 作为 name 匹配。
    """

    kind: str
    rule: Mapping[str, Any]
    side: str = "player"
    mark_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class MarksManager:
    """印记状态管理器（细化_1d §2.1/§2.2/§3）：per-actor 双向表运行期状态。

    - 绑定 marks_state dict 对象（copy=False；effects/battle 快照同一对象）；
    - 施加/消除/条件/生命周期 tick 唯一实现；
    - 快照 JSON 序列化（to_snapshot / to_json / from_snapshot / from_json，
      中断恢复与热重载落点，AT-07/AT-08）；
    - resolve() 产出 {印记名: 层数} 供公式引擎 [印记:名] 参数化占位符
      （_PARAM_RULES "我方印记:"/"对方印记:" → slot["marks"][名]）。
    """

    def __init__(
        self,
        marks_state: Optional[Mapping[str, Any]] = None,
        *,
        copy: bool = False,
        resolver: Any = None,
        defs: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if marks_state is None:
            self.marks_state: Dict[str, Any] = {"player": [], "enemy": []}
        elif copy:
            self.marks_state = _copy.deepcopy(dict(marks_state))
        else:
            # copy=False：绑定调用方 dict 对象（effects/battle 共享同一实例）
            self.marks_state = (
                marks_state if isinstance(marks_state, dict) else dict(marks_state)
            )
        self._resolver: Callable[[str, str], Any] = _make_resolver(resolver, defs)
        for side in BATTLE_SIDES:
            self.ensure(side)

    # ---------------- 结构 / 定义查询 ----------------

    def ensure(self, side: str) -> None:
        """确保 per-actor 双向表结构存在（细化_1d §2.1 / 印记 §三）。"""
        if side not in BATTLE_SIDES:
            raise ValueError(f"未知战斗侧：{side}（仅 player/enemy，D-05）")
        if side not in self.marks_state or not isinstance(self.marks_state[side], list):
            self.marks_state[side] = []

    def instances(self, side: str) -> List[Dict[str, Any]]:
        """给定侧的印记实例列表（§2.1 双向表；list 元素为 JSON dict）。"""
        self.ensure(side)
        return self.marks_state[side]  # type: ignore[return-value]

    def definition(self, mark_id: str) -> Optional[Any]:
        """印记定义（经 resolver；None=未注册，热重载删定义后按「无印记」降级，§九）。"""
        if not mark_id:
            return None
        return self._resolver(mark_id, "mark")

    @staticmethod
    def _def_is_obj(d: Any) -> bool:
        """判别 Def 实例（.raw/.name）还是裸 dict。"""
        return hasattr(d, "raw") or hasattr(d, "name")

    @staticmethod
    def _def_raw(d: Any) -> Mapping[str, Any]:
        return d.raw if hasattr(d, "raw") else (d if isinstance(d, Mapping) else {})

    def _def_name(self, d: Any, mark_id: str) -> str:
        if d is None:
            return mark_id
        name = getattr(d, "name", None) or (d.get("name") if isinstance(d, Mapping) else None)
        return str(name) if name else mark_id

    def max_stack_of(self, mark_id: str) -> int:
        """印记叠加上限（细化_1d §1.1 字段 5 / 印记 §二：≥1；0=不限；未注册按 0 不限）。"""
        d = self.definition(mark_id)
        if d is None:
            return 0
        raw = self._def_raw(d)
        try:
            v = int(raw.get("max_stack") or 0)
        except (TypeError, ValueError):
            v = 0
        return max(0, v)

    def polarity_of(self, mark_id: str) -> str:
        """印记定义极性（细化_1d §1.1 字段 7 / 印记 §2.1；缺省 positive 兜底）。"""
        d = self.definition(mark_id)
        if d is None:
            return "positive"
        p = str((self._def_raw(d)).get("polarity") or "positive")
        return p if p in POLARITIES else "positive"

    def duration_of(self, mark_id: str) -> str:
        """印记 duration（细化_1d §1.1 字段 9：battle / turns:N；缺省 battle）。"""
        d = self.definition(mark_id)
        if d is None:
            return "battle"
        return str(self._def_raw(d).get("duration") or "battle")

    # ---------------- 原子动作（细化_1d §3.2 / 印记 §4） ----------------

    def apply_add(self, cmd: AddMark) -> Tuple[bool, int]:
        """mark_add：施加必中；重复=+count 至上限（max_stack，0=不限，到顶不再涨）。

        实例冗余存储 name/polarity（D-04 防热重载）、applier（D-05）；限时印记
        记 remaining_turns（§2.1 字段 6）。返回 (成功?, max_stack)。
        """
        side, mark_id, count = cmd.side, cmd.mark, max(1, int(cmd.count))
        inst = self._find_instance(side, mark_id)
        max_stack = self.max_stack_of(mark_id)
        if inst is not None:
            # 同来源更新：聚合到已有实例（§4.1 重复+=；到顶不再涨）
            old = int(inst.get("count", 0))
            inst["count"] = max_stack if (max_stack and old + count > max_stack) else old + count
            return True, max_stack
        d = self.definition(mark_id)
        new_inst: Dict[str, Any] = {
            "mark_id": mark_id,
            "name": self._def_name(d, mark_id),
            "count": count if not max_stack else min(count, max_stack),
            "applier": cmd.applier or "player",
            "polarity": self.polarity_of(mark_id),
        }
        if d is not None:
            dur = self.duration_of(mark_id)
            if dur.startswith("turns:"):
                try:
                    new_inst["remaining_turns"] = int(dur.split(":", 1)[1])
                except (ValueError, IndexError):
                    pass
        self.instances(side).append(new_inst)
        return True, max_stack

    def apply_remove(self, cmd: RemoveMark) -> int:
        """mark_remove：寻址 = side + polarity 过滤（+可选 mark，D-02）；FIFO 按层数消；
        超量=饱和减法至 0（D-03，不报错）。返回移除总层数。"""
        remaining = max(0, int(cmd.count))
        removed = 0
        survivors: List[Dict[str, Any]] = []
        for inst in self.instances(cmd.side):
            if (
                remaining > 0
                and inst.get("polarity") == cmd.polarity
                and (cmd.mark is None or inst.get("mark_id") == cmd.mark)
            ):
                cur = int(inst.get("count", 0))
                sub = min(cur, remaining)
                cur -= sub
                removed += sub
                remaining -= sub
                if cur > 0:
                    inst["count"] = cur
                    survivors.append(inst)
            else:
                survivors.append(inst)
        self.marks_state[cmd.side] = survivors
        return removed

    def apply_clear(self, cmd: ClearMarks) -> int:
        """clear_marks：整组清空（无 count 语义，与 mark_remove 层数消区分，AT-12）。"""
        survivors = [
            inst
            for inst in self.instances(cmd.side)
            if not (
                inst.get("polarity") == cmd.polarity
                and (cmd.mark is None or inst.get("mark_id") == cmd.mark)
            )
        ]
        n = len(self.instances(cmd.side)) - len(survivors)
        self.marks_state[cmd.side] = survivors
        return n

    def _find_instance(self, side: str, mark_id: str) -> Optional[Dict[str, Any]]:
        for inst in self.instances(side):
            if inst.get("mark_id") == mark_id:
                return inst
        return None

    # ---------------- 生命周期（细化_1d §2.2 / 印记 §三） ----------------

    def tick_turn(self, side: str) -> int:
        """回合结束统一 tick：限时印记 remaining_turns -1，归零移除（§2.2/§三「剩余
        回合记入快照」）；battle 型无 remaining_turns 不受影响。返回移除条数。"""
        removed = 0
        for inst in self.instances(side):
            rt = inst.get("remaining_turns")
            if isinstance(rt, int) and rt > 0:
                inst["remaining_turns"] = rt - 1
        survivors: List[Dict[str, Any]] = []
        for inst in self.instances(side):
            rt = inst.get("remaining_turns")
            if isinstance(rt, int) and rt <= 0:
                removed += 1
                continue
            survivors.append(inst)
        self.marks_state[side] = survivors
        return removed

    # ---------------- 条件原语（细化_1d §3.1 C-1..C-5） ----------------

    def count(self, side: str, mark_id: str) -> int:
        """指定印记层数（C-1 self_marks / C-2 target_marks 的取值）。"""
        inst = self._find_instance(side, mark_id)
        return int(inst["count"]) if inst is not None else 0

    def count_by_name(self, side: str, name: str) -> int:
        """按冗余 name（中文显示名）查层数；公式 [印记:名] 与热重载降级用（§2.1 冗余）。"""
        for inst in self.instances(side):
            if inst.get("name") == name or inst.get("mark_id") == name:
                return int(inst.get("count", 0))
        return 0

    def total(self, side: str) -> int:
        """全部印记层数之和（C-3 marks_total；公式 [印记总数]）。"""
        return sum(int(inst.get("count", 0)) for inst in self.instances(side))

    def distinct(self, side: str) -> int:
        """当前持有印记的种类数（C-5 marks_any）。"""
        return len(self.instances(side))

    def has_all(self, side: str, names: Sequence[str]) -> bool:
        """齐备：同时持有列表内全部印记（每类 ≥1，C-4 marks_set）；名/ID 均可匹配。"""
        return all(self.count_by_name(side, n) >= 1 for n in names)

    def evaluate(self, kind: str, side: str, rule: Mapping[str, Any],
                 mark_id: Optional[str] = None) -> bool:
        """条件求值（细化_1d §3.1 公共语义：基于施放前快照一次，结算后不重评）。

        rule 为 dict：{"min":N,"max":M}（至少其一，V-2）/ {"all":[名...]}。
        """
        if rule is None:
            rule = {}
        if kind in ("self_marks", "target_marks", "marks_single"):
            key = mark_id or str(rule.get("mark") or rule.get("mark_id") or "")
            value = self.count_by_name(side, key) if key else self.total(side)
            lo = rule.get("min")
            hi = rule.get("max")
            if lo is not None and not (value >= int(lo)):
                return False
            if hi is not None and not (value <= int(hi)):
                return False
            return True
        if kind == "marks_total":
            value = self.total(side)
            lo = rule.get("min")
            hi = rule.get("max")
            if lo is not None and not (value >= int(lo)):
                return False
            if hi is not None and not (value <= int(hi)):
                return False
            return True
        if kind == "marks_set":
            return self.has_all(side, list(rule.get("all") or []))
        if kind == "marks_any":
            value = self.distinct(side)
            lo = rule.get("min")
            hi = rule.get("max")
            if lo is not None:
                if not (value >= int(lo)):
                    return False
            if hi is not None:
                if not (value <= int(hi)):
                    return False
            return True
        raise ValueError(f"未知印记条件原语 kind：{kind!r}（细化_1d §3.1 仅五型）")

    def eval_condition(self, cond: MarkCondition) -> bool:
        """frozen 条件对象求值（等价 evaluate，供 frozen 接口调用）。"""
        return self.evaluate(cond.kind, cond.side, dict(cond.rule), cond.mark_id)

    # ---------------- 公式视图（印记 → 公式引擎 [印记:名]） ----------------

    def resolve(self, side: str) -> Dict[str, int]:
        """{印记名: 层数}（仅持有者；公式 [我/对方印记:名] 参数化占位符取值源）。"""
        out: Dict[str, int] = {}
        for inst in self.instances(side):
            name = str(inst.get("name") or inst.get("mark_id") or "")
            if name:
                out[name] = int(inst.get("count", 0))
        return out

    def resolve_ids(self, side: str) -> Dict[str, int]:
        """{mark_id: 层数}（按引用键；条件/消除寻址）。"""
        return {str(inst.get("mark_id", "")): int(inst.get("count", 0)) for inst in self.instances(side)}

    def formula_view(self, side: str) -> Dict[str, object]:
        """战斗层 EvaluatorCtx 侧映射补充：marks（按名）+ marks_total（总层数）。"""
        return {"marks": self.resolve(side), "marks_total": self.total(side)}

    # ---------------- 快照往返（开关 §2.3 / 印记 §三：中断恢复全量还原） ----------------

    def to_snapshot(self) -> Dict[str, Any]:
        """深拷贝出口：marks_state 双向表（§2.1 契约；含 remaining_turns）。"""
        return _copy.deepcopy(self.marks_state)

    def to_dict(self) -> Dict[str, Any]:
        return self.to_snapshot()

    def to_json(self) -> str:
        return json.dumps(self.marks_state, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_snapshot(cls, data: Mapping[str, Any], resolver: Any = None,
                      defs: Optional[Mapping[str, Any]] = None) -> "MarksManager":
        ms: Dict[str, Any] = {"player": [], "enemy": []}
        if isinstance(data, Mapping):
            for side in BATTLE_SIDES:
                lst = data.get(side)
                ms[side] = list(lst) if isinstance(lst, list) else []
        # copy=False 绑定新建 dict（data 不再被引用，安全）
        mgr = cls(ms, resolver=resolver, defs=defs)
        return mgr

    @classmethod
    def from_json(cls, raw: str, resolver: Any = None,
                  defs: Optional[Mapping[str, Any]] = None) -> "MarksManager":
        return cls.from_snapshot(json.loads(raw), resolver=resolver, defs=defs)

    def __eq__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, MarksManager):
            return NotImplemented
        return self.to_json() == other.to_json()
