# -*- coding: utf-8 -*-
"""九期213（战术四件套接线）：态势／钉位／扇区／响应槽编排器——可选加载模块。

红线承诺（`docs/cloudsea/云海转化映射表.md` §三/§五）：
- 零引擎改动：本模块不 import 修改 battle.py/damage.py 任何既有符号；全部经
  九期207 已留的 ``TRIGGER_PROC_HOOKS`` 注册面（``register_trigger_proc_hook``）
  工作——**不调用 :func:`register_cloudsea_tactics` 即零注册、零行为**。
- 无硬编码：共享数字（态势阈值/背击加成/响应槽容量等）一律由装配层 config
  传入；模块内缺省值仅系九期裁决草案值（正式值随 215C/212 落 `12` §号后由
  content/cloudsea 装配注入），不新增 `12` 号常量、不新增机制词。
- 既有行为零变化：钩子返回 None = 不处理；异常不阻断战斗（207 派发器语义）。

四件套（九期排期 §二 G1 213）：
1. 态势：PostureMomentum 计数器 + counterattack_gate 反扑门控（裁决 #5 个人计数）
2. 钉位：PinnedStreak 连续钉位计数（pinned_streak）
3. 扇区：position_bonus 查表（背击 +0.30 双向）+ 三例外短路（裁决 #10：
   F08 滚转态玩家背击免疫／F09 无面向族失效／F11 潜行全 fail）+ 灰度名单
   （裁决 #20：先限异相种/蚀潮）
4. 响应槽编排器：ArmedQueue armed 队列（FIFO + 容量 + 回合衰减；上限语义
   同源 `$C` §O REACTION_MAX 反应值口径，装配层换算）
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional

__all__ = [
    "PostureMomentum",
    "PinnedStreak",
    "position_bonus",
    "ArmedQueue",
    "register_cloudsea_tactics",
]

#: 裁决草案缺省值（正式值由装配层以 `12` 号申报键注入后覆盖）
DEFAULT_POSTURE_THRESHOLD = 3          # 态势达标阈值（个人计数）
DEFAULT_BACK_BONUS = 0.30              # 背击加成（裁决 #11 双向生效）
DEFAULT_ARMED_CAPACITY = 3             # armed 队列容量（§O REACTION_MAX 口径装配换算）
DEFAULT_ARMED_DECAY = 2                # 未触发回合衰减清空窗

_SIDE_FRONT = "front"
_SIDE_BACK = "back"

#: 扇区灰度名单（裁决 #20：position_bonus 先限异相种/蚀潮；bio_class 词面）
GRAYLIST_BIO = ("aberrant", "tainted")

#: 三例外 marks 词（defender_marks 命中即短路，裁决 #10/#14）
MARK_ROLLING = "rolling"        # F08 滚转态：玩家背击免疫短路
MARK_BURROW = "burrowing"       # F11 潜行态：背击全 fail（≤2 拍语义由装配层控）
MARK_NO_FACE = "no_face"        # F09 全向族：背击加成失效（无面向→无背）


class PostureMomentum:
    """态势值个人计数器（裁决 #5：1v1 收敛＝个人计数）。

    达标来源由装配层逐事件 ``register()``（守势达标/调和折算
    ``MIX_POSTURE_CREDIT`` 等语义在调用侧判定）；满阈值即 ``is_full()``。
    """

    def __init__(self, threshold: int = DEFAULT_POSTURE_THRESHOLD) -> None:
        self.threshold = max(1, int(threshold))
        self.value = 0

    def register(self, times: int = 1) -> None:
        self.value += max(0, int(times))

    def reset(self) -> None:
        self.value = 0

    def is_full(self) -> bool:
        return self.value >= self.threshold

    def make_counterattack_proc(self, move_id: str) -> Optional[Dict[str, Any]]:
        """态势满 → 反扑 proc dict（交 execute_proc_action 执行）；未满 → None。

        门控语义：反扑触发即清零计数（一轮一门）。
        """
        if not self.is_full():
            return None
        self.reset()
        return {"type": "counterattack", "move": move_id, "source": "cloudsea_posture"}


class PinnedStreak:
    """钉位连续计数器（pinned_streak：连续 pinned 回合数）。"""

    def __init__(self, threshold: int = 2) -> None:
        self.threshold = max(1, int(threshold))
        self.streak = 0

    def on_round(self, pinned_now: bool) -> None:
        self.streak = self.streak + 1 if pinned_now else 0

    def ready(self) -> bool:
        return self.streak >= self.threshold

    def consume(self) -> int:
        """读取并清零（效果触发一次性）；返回触发时 streak。"""
        s, self.streak = self.streak, 0
        return s

    @staticmethod
    def pinned_from_snapshot(snapshot: Mapping[str, Any], who: str) -> bool:
        """从 battle 快照读 pinned 态（键缺失/结构异形 → False 零行为）。"""
        try:
            mon = snapshot.get("monster") or {}
            marks = mon.get("marks") or {}
            return bool(marks.get("pinned") or (who in (marks.get("pinned_by") or {})))
        except Exception:  # noqa: BLE001 快照异形零行为
            return False


def position_bonus(
    attacker_side: str,
    defender_side: str,
    defender_marks: Any = (),
    graylisted: bool = False,
    back_bonus: float = DEFAULT_BACK_BONUS,
) -> float:
    """扇区位置加成（裁决 #8 侧翼四值 front/left/right/back；#10 三例外）。

    - 灰度未开（``graylisted=False``，即来源非异相种/蚀潮）→ 0.0；
    - 例外短路（优先级高于加成表）：defender 滚转态 → 玩家背击免疫 0；
      defender 潜行态 → 全 fail 0；attacker 无面向族 → 0；
    - 背击双向：attacker=front & defender=back，或 attacker=back &
      defender=front → ``+back_bonus``；其余组合 → 0.0。
    """
    if not graylisted:
        return 0.0
    marks = set(defender_marks or ())
    atk, dfn = (attacker_side or "").lower(), (defender_side or "").lower()
    if MARK_NO_FACE in marks or attacker_side in (None, "", MARK_NO_FACE):
        return 0.0
    back_hit = {atk, dfn} == {_SIDE_FRONT, _SIDE_BACK}
    if back_hit and (MARK_ROLLING in marks or MARK_BURROW in marks):
        return 0.0
    return float(back_bonus) if back_hit else 0.0


class ArmedQueue:
    """响应槽 armed 队列（怪招响应槽编排器，约 200 行面之一）。

    - FIFO：容量满再 arm 挤出最旧（容量语义同源 §O REACTION_MAX，装配换算）；
    - 回合衰减：``tick_round()`` 每回合递减剩余潜伏，归零移除；
    - 触发：``pop_trigger()`` 出队最旧 armed 项（编排器只管队列与衰减，
      触发判定/结算由调用侧经 TRIGGER_PROC_HOOKS proc 面执行）。
    """

    def __init__(self, capacity: int = DEFAULT_ARMED_CAPACITY, decay_rounds: int = DEFAULT_ARMED_DECAY) -> None:
        self.capacity = max(1, int(capacity))
        self.decay_rounds = max(1, int(decay_rounds))
        self._items: List[Dict[str, Any]] = []

    def arm(self, move_id: str, meta: Optional[Mapping[str, Any]] = None) -> None:
        if any(it["move"] == move_id for it in self._items):
            return  # 同招已 armed 不重复
        if len(self._items) >= self.capacity:
            self._items.pop(0)
        self._items.append({"move": move_id, "meta": dict(meta or {}), "ttl": self.decay_rounds})

    def tick_round(self) -> None:
        for it in self._items:
            it["ttl"] -= 1
        self._items[:] = [it for it in self._items if it["ttl"] > 0]

    def pop_trigger(self) -> Optional[Dict[str, Any]]:
        return self._items.pop(0) if self._items else None

    def __len__(self) -> int:
        return len(self._items)


def register_cloudsea_tactics(
    hooks_module: Any,
    *,
    posture_move: str = "",
    pinned_threshold: int = 2,
) -> Dict[str, Any]:
    """把四件套可注册面挂入 207 ``TRIGGER_PROC_HOOKS``（显式装配口）。

    ``hooks_module``＝``qbot_rpg.core.battle``（由调用方传入，模块自身不
    import 引擎）；返回装配句柄 dict 供内容包持有（态势/钉位实例等）。
    不调用本函数 = 零注册、零行为。
    """
    posture = PostureMomentum()
    pinned = PinnedStreak(threshold=pinned_threshold)
    queue = ArmedQueue()

    def _hook(kind: str, ctx: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        if kind != "round_head":
            return None
        snap = (ctx or {}).get("snapshot") or {}
        pinned.on_round(PinnedStreak.pinned_from_snapshot(snap, "monster"))
        queue.tick_round()
        if posture_move and posture.is_full():
            return posture.make_counterattack_proc(posture_move)
        return None

    hooks_module.register_trigger_proc_hook(_hook)
    return {"posture": posture, "pinned": pinned, "armed": queue, "hook": _hook}
