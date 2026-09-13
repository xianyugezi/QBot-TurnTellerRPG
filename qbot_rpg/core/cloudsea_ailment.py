# -*- coding: utf-8 -*-
"""九期211（衰减/递增封顶 hook）：云海九态异常积蓄状态机（数值面）。

设计稿 04 §M4.1–M4.2 三律（积蓄→触发→衰减）的框架转译数值核：
- 衰减：全局回合末统一时点 A -= D（G1B 增量裁决，映射表 §6.2/§7）
- 触发：A >= T 触发并清零，T 按态递增（growth_mult），封顶 ×3.0 基准
- 饱和：达每场上限 max_per_battle 后只结算伤害类（腐蚀/爆燃），控制类不再触发

控制类行为接线（麻痹跳过/沉眠休眠等）归 213 战术接线批；本 hook 只维护
buildup/threshold/saturated 数值态并产出 events 流水，供 213/214 消费。
写入点＝207 #4 boss_state 视图三键之 ``ailment_buildup``（快照继承走
phase_changed inherit_boss_state，阶段保留 50% 归 214 侧应用）。

可选加载：内容包未携带 cloudsea statuses / 本模块未被装配层注册 → 全部
入口零操作（TRIGGER_PROC/period 同款承诺，既有行为零变化）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

#: 递增封顶（基准 ×3.0，04 §M4.2 律2）
GROWTH_CAP = 3.0
#: 饱和后仍结算的「伤害类」九态（04 §M4.2 律2）
DAMAGE_KIND = {"ail_corrosion", "ail_detonate"}


class CloudseaAilmentState:
    """单敌九态积蓄容器：{ail_id: {"a": 积蓄, "t": 当前阈值, "count": 触发数}}。"""

    def __init__(self, statuses: Mapping[str, Mapping[str, Any]]) -> None:
        # statuses = content/cloudsea/statuses.json 载入后的 {id: 条目}
        self._spec: Dict[str, Mapping[str, Any]] = {
            str(k): v for k, v in dict(statuses).items()
        }

    def spec(self, ail_id: str) -> Optional[Mapping[str, Any]]:
        return self._spec.get(ail_id)

    def apply_buildup(self, state: Dict[str, Any], ail_id: str, amount: float) -> List[Dict[str, Any]]:
        """积蓄入口（G1B 增量：hits 逐段累加经 per_segment_effects 聚合后走此处）。"""
        events: List[Dict[str, Any]] = []
        spec = self.spec(ail_id)
        if spec is None or amount <= 0:
            return events
        slot = state.setdefault(ail_id, {"a": 0.0, "t": float(spec.get("threshold_T", 0)), "count": 0})
        cap = int(spec.get("max_per_battle", 0))
        saturated = cap > 0 and slot["count"] >= cap
        slot["a"] = float(slot["a"]) + float(amount)
        if slot["a"] >= slot["t"]:
            if saturated and ail_id not in DAMAGE_KIND:
                # 饱和态：控制类不再触发（04 §M4.2 律2），积蓄保留至帽下
                slot["a"] = float(slot["t"])
                events.append({"type": "ail_saturated", "ail": ail_id})
                return events
            slot["a"] = 0.0
            slot["count"] = int(slot["count"]) + 1
            base_t = float(spec.get("threshold_T", 0))
            growth = float(spec.get("growth_mult", 1.0))
            slot["t"] = min(base_t * (growth ** int(slot["count"])), base_t * GROWTH_CAP)
            events.append({"type": "ail_triggered", "ail": ail_id, "count": slot["count"], "next_t": slot["t"]})
        return events

    def tick_round_end(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """全局回合末衰减：A -= D（出手序列≡回合，209 §六）；归零自然消退。"""
        events: List[Dict[str, Any]] = []
        for ail_id, slot in list(state.items()):
            spec = self.spec(ail_id)
            if spec is None:
                continue
            decay = float(spec.get("decay_D", 0))
            if decay <= 0:
                continue
            slot["a"] = max(0.0, float(slot["a"]) - decay)
            if slot["a"] <= 0.0 and int(slot.get("count", 0)) == 0:
                # 零积蓄零触发：条目回收（避免空槽膨胀）
                state.pop(ail_id, None)
                events.append({"type": "ail_idle_removed", "ail": ail_id})
        return events


def tick_from_snapshot(snap: Mapping[str, Any], statuses: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """对快照 boss_state.ailment_buildup 原位 tick（键缺失 → 建空表，零操作语义）。"""
    bs = snap.get("boss_state")
    if not isinstance(bs, dict):
        return []
    state = bs.setdefault("ailment_buildup", {})
    return CloudseaAilmentState(statuses).tick_round_end(state)
