"""怪物阶段表解析器（M2 怪物体系 · B3 路：HP 阈值→阶段切换 / 阶段专属行动表 /
phase_changed 联动状态机转换事件 / enter_action 入强制队列 / 阶段切换演出文案）。

依据：细化_1f_怪物AI状态机.md（①1.1 边界声明：phases 阶段表=配置载体，阈值只写
phases 单处，状态机不重复声明血量阈值；phase_changed 触发可联动状态机转换；
①1.3 驱动口径裁决：状态机转换一律走 phase_changed 联动，TC-04；③3.3 阶段转换
演出） + docs/m2_shared_contract.md 第五节（ai_state.phase/boss_phase 键；L1
状态机切换） + 第八节铁律。

纯函数无 IO（铁律 2：零 NoneBot import；平台无关）。PhaseTable 解析一次配置后
只读复用（无状态可变——_phases 构造后只读）。

工程收敛（设计文档未显式定义处，显式标注供审查）：
  1. 阶段号 = 1 基序号（BOSS 1/2/3，contract §五）。phases 条目按 threshold 降序；
     阶段 n 覆盖 HP% 区间 (threshold[n+1], threshold[n]]——阈值处归**下**阶段
     （60% 整 → 阶段 2、30% 整 → 阶段 3，与 TC-04「阶段2 阈值 60」及 hp_below
     「严格小于」口径互补不冲突）。
  2. 默认阈值 (100, 60, 30) = 细化_1f 三阶段 100-60/60-30/30-0 边界；
     配置传入 phases=[{threshold, ...}] 即覆盖默认。
  3. resolve_phase(hp_pct, max_hp, phases)：max_hp 传且 >0 时第一参数按**绝对 HP**
     换算为百分比（hp/max_hp×100）；否则第一参数按 0-100 百分比直读。
  4. 阶段条目可选键：threshold（HP% 上界）/ actions（阶段专属行动表）/
     enter_action（入强制队列；str 或 {action}） / broadcast（演出文案，含
     {monster} 占位）/ name（阶段名）。未知键忽略（校验器兜底，此处不拦截）。
     定稿 phases 形态 {hp_from, hp_to, behavior}（副本定稿 L241-246：hp_from=高血端
     上限、hp_to=低血端下限）在 threshold 缺失时归一（hp_from→threshold，hp_to 兜底，
     审查批次3 P2-5），避免定稿形态配置被忽略而恒阶段 1。
  5. phase_changed 事件形态 {type:"phase_changed", value, phase, from}——与
     monster_ai._eval_condition 内建 phase_changed（phase >= value 即成立）兼容：
     主 agent 切 ai_state.phase 后 evaluate_transitions 即可联动；或直接把事件
     当 transition.condition 传入。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = [
    "PhaseTable",
    "resolve_phase",
    "phase_changed_event",
    "DEFAULT_THRESHOLDS",
]

# 默认三阶段阈值（1f ①1.1 边界声明收敛：60/30 双阈值；100-60/60-30/30-0）
DEFAULT_THRESHOLDS: tuple = (100, 60, 30)


class PhaseTable:
    """phases 阶段表解析器（配置载体，1f ①1.1 边界声明）。

    一次解析 phases 配置，之后只读复用。提供：当前阶段号解析、阶段专属行动表、
    阶段切换联动事件、enter_action 强制队列条目、阶段切换演出文案。
    """

    def __init__(
        self,
        phases: Optional[Sequence[Mapping[str, Any]]] = None,
        monster_name: str = "",
        default_thresholds: Sequence[float] = DEFAULT_THRESHOLDS,
    ) -> None:
        """phases=阶段配置列表 [{threshold, actions?, enter_action?, broadcast?,
        name?}]（缺省 → 按 default_thresholds 生成 3 阶段）；monster_name=演出文案
        占位。条目按 threshold 降序排序（工程收敛 1）。"""
        self._monster_name = monster_name or ""
        raw: List[Dict[str, Any]] = (
            [dict(p) for p in phases]
            if phases is not None
            else [{"threshold": float(t)} for t in default_thresholds]
        )
        for p in raw:
            p.setdefault("actions", [])
            # 审查批次3 P2-5：定稿 phases 形态 {hp_from, hp_to, behavior} 归一 → threshold
            # （副本定稿 L241-246：hp_from=高血端上限、hp_to=低血端下限；threshold 缺失时
            #  显式映射 hp_from→threshold（hp_to 兜底），保留既有「阈值处归下阶段」区间语义）
            if not _is_num(p.get("threshold")):
                hi = p.get("hp_from")
                lo = p.get("hp_to")
                norm = hi if _is_num(hi) else (lo if _is_num(lo) else None)
                if norm is not None:
                    p["threshold"] = float(norm)
        # threshold 降序；同 threshold 保序（工程收敛 1）
        raw.sort(key=lambda p: -float(p.get("threshold", 0.0)))
        self._phases: List[Dict[str, Any]] = raw

    # ------------------------------------------------------------ 解析查询

    @property
    def count(self) -> int:
        """阶段数。"""
        return len(self._phases)

    @property
    def phases(self) -> List[Dict[str, Any]]:
        """解析后的阶段表（threshold 降序；只读视图——调用方不得改写）。"""
        return list(self._phases)

    def phase(self, n: int) -> Optional[Dict[str, Any]]:
        """1 基阶段号 → 阶段条目；越界 → None。"""
        if not self._phases or n < 1 or n > len(self._phases):
            return None
        return dict(self._phases[n - 1])

    def resolve_phase(self, hp_pct: float, max_hp: Optional[float] = None) -> int:
        """HP → 当前阶段号（1 基；工程收敛 3 的 max_hp 换算）。

        100-60/60-30/30-0 边界（默认阈值）：61→1 / 60→2 / 31→2 / 30→3 / 0→3。
        空表 → 1。
        """
        pct = _to_pct(hp_pct, max_hp)
        if not self._phases:
            return 1
        idx = len(self._phases) - 1
        for i, p in enumerate(self._phases):
            if pct <= float(p.get("threshold", 0.0)):
                idx = i
            else:
                break
        return idx + 1

    # ------------------------------------------------------------ 阶段专属内容

    def actions_for(self, n: int) -> List[Dict[str, Any]]:
        """阶段专属行动表（1f ①1.1「HP 阈值→行动表切换」）；越界 → []。"""
        p = self.phase(n)
        if not p:
            return []
        acts = p.get("actions") or []
        return [dict(a) for a in acts] if isinstance(acts, (list, tuple)) else []

    def enter_action_for(self, n: int) -> Optional[str]:
        """进入阶段 n 的 enter_action（入强制队列，L2 消费；contract §五 L1 行）。

        enter_action 支持 str（action id）或 {action: id}；未配 → None。
        """
        p = self.phase(n)
        if not p:
            return None
        ea = p.get("enter_action")
        if isinstance(ea, Mapping):
            return str(ea.get("action")) if ea.get("action") else None
        return str(ea) if ea else None

    def broadcast_for(
        self, n: int, monster_name: Optional[str] = None
    ) -> Optional[str]:
        """阶段切换演出文案（1f ③3.3 阶段转换演出；公开）。

        条目 broadcast 含 "{monster}" 占位替换；未配 → None。
        """
        p = self.phase(n)
        if not p:
            return None
        text = p.get("broadcast")
        if text is None:
            return None
        name = monster_name if monster_name is not None else self._monster_name
        return str(text).replace("{monster}", name)

    # ------------------------------------------------------------ 切换联动

    def phase_changed_event(
        self, old_phase: int, new_phase: int
    ) -> Optional[Dict[str, Any]]:
        """phase_changed 联动状态机转换事件（1f ①1.1 / TC-04 驱动口径）。

        返回 {type:"phase_changed", value, phase, from}——与 monster_ai 内建
        phase_changed 条件（phase >= value 即成立）兼容；old==new 或越界 → None。
        """
        if old_phase == new_phase:
            return None
        if not self._phases:
            return None
        if new_phase < 1 or new_phase > len(self._phases):
            return None
        return {
            "type": "phase_changed",
            "value": new_phase,
            "phase": new_phase,
            "from": old_phase,
        }

    def detect_transition(
        self,
        hp_pct: float,
        max_hp: Optional[float] = None,
        prev_phase: Optional[int] = None,
    ) -> Dict[str, Any]:
        """阶段切换检测（一次算全联动输出）。

        prev_phase 传快照旧阶段号做变更判定；缺省 → 以 1 为旧（视作首帧）。

        Returns:
            {phase, changed, event, enter_action, broadcast}——changed=True 时
            event=phase_changed 事件、enter_action=新阶段强制队列行动、broadcast=
            新阶段演出文案（主 agent 接线：changed → ai_state.phase 更新 +
            forced_queue.append(enter_action) + evaluate_transitions 联动）。
        """
        new_phase = self.resolve_phase(hp_pct, max_hp)
        old_phase = prev_phase if prev_phase is not None else 1
        changed = old_phase != new_phase
        event = self.phase_changed_event(old_phase, new_phase) if changed else None
        return {
            "phase": new_phase,
            "changed": changed,
            "event": event,
            "enter_action": self.enter_action_for(new_phase) if changed else None,
            "broadcast": self.broadcast_for(new_phase) if changed else None,
        }


# ================================================================ 模块级函数


def resolve_phase(
    hp_pct: float,
    max_hp: Optional[float] = None,
    phases: Optional[Sequence[Mapping[str, Any]]] = None,
) -> int:
    """HP → 当前阶段号（1 基；100-60/60-30/30-0 边界）。

    独立于 PhaseTable 的便捷函数：phases 缺省 → 默认三阶段阈值 (100,60,30)；
    max_hp 传且 >0 → hp_pct 按绝对 HP 换算百分比（工程收敛 3）。
    """
    return PhaseTable(phases).resolve_phase(hp_pct, max_hp)


def phase_changed_event(old_phase: int, new_phase: int) -> Optional[Dict[str, Any]]:
    """phase_changed 联动状态机转换事件（默认阈值表；工程收敛 5 形态）。"""
    return PhaseTable().phase_changed_event(old_phase, new_phase)


# ================================================================ 内部


def _is_num(value: Any) -> bool:
    """数值校验（排除 bool——bool 是 int 子类；审查批次3 P2-5 键形态归一用）。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _to_pct(hp_pct: float, max_hp: Optional[float]) -> float:
    """工程收敛 3：max_hp 传且 >0 → 绝对 HP 换算百分比；否则按百分比直读。"""
    try:
        v = float(hp_pct)
    except (TypeError, ValueError):
        v = 0.0
    if max_hp is not None:
        try:
            m = float(max_hp)
        except (TypeError, ValueError):
            m = 0.0
        if m > 0:
            return v / m * 100.0
    return v
