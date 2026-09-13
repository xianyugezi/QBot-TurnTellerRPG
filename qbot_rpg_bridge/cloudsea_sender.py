# -*- coding: utf-8 -*-
"""九期215（壳层 sender 频控调度器）：战报 30s 合并窗 / 摘要行 / @白名单 4 类。

定位：QQ 壳层（qbot_rpg_bridge）的**纯调度组件**——不做 IO、不 import 引擎，
聚合决策与模板填空全部在本模块；实际发送由宿主（NoneBot 适配层）注入的
``send`` 回调执行。不实例化不调用＝零行为。

D-01 契约（设计稿 08 号战报面）：
- 合并窗：默认 30 秒窗口内的多条普通战报合并为一条（``battle_merge_summary``
  摘要行 + 逐条原文），降低群刷屏；
- @白名单 4 类：``boss_first``（Boss 首破）／``urgent``（紧急事件）／
  ``personal``（个人战报）／``system``（系统公告）——白名单类**不合并、
  即时直发**并可携带 mention；
- emoji 放行经 ``qbot_rpg.core.templates.cloudsea_emoji`` 校验（D-01）。
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

__all__ = ["CloudseaSender", "MENTION_CLASSES"]

#: @白名单 4 类（D-01）：命中即直发不合并
MENTION_CLASSES: Tuple[str, ...] = ("boss_first", "urgent", "personal", "system")

#: 合并窗缺省（任务书明文参数 30 秒；装配层可覆盖）
DEFAULT_MERGE_WINDOW_SEC = 30.0


class CloudseaSender:
    """战报频控调度器：feed() 进件 → 窗满/到期 flush() 合并发送。

    Args:
        send: 宿主发送回调 ``send(text) -> None``（测试注入 list.append）。
        tpl: 模板取值函数 ``tpl(key, ctx) -> str``（接 battle_tpl 的
            ``tpl_of``；缺省走内置 dict 的 battle_merge_summary）。
        merge_window_sec: 合并窗时长（秒）。
        clock: 单调时钟函数（缺省 time.monotonic；测试可注入假钟）。
        emoji_validator: 可选 ``(text) -> (ok, unknown)``（接 D-01 校验器；
            未提供＝不校验）。
    """

    def __init__(
        self,
        send: Callable[[str], None],
        tpl: Optional[Callable[[str, Mapping[str, Any]], str]] = None,
        merge_window_sec: float = DEFAULT_MERGE_WINDOW_SEC,
        clock: Optional[Callable[[], float]] = None,
        emoji_validator: Optional[Callable[[str], Tuple[bool, Tuple[str, ...]]]] = None,
    ) -> None:
        self._send = send
        self._tpl = tpl or self._default_tpl
        self._window = float(merge_window_sec)
        self._clock = clock or time.monotonic
        self._emoji = emoji_validator
        self._buf: List[str] = []
        self._opened_at: Optional[float] = None

    # ---- 内部 ----

    @staticmethod
    def _default_tpl(key: str, ctx: Mapping[str, Any]) -> str:
        defaults = {
            "battle_merge_summary": "▫ 已合并 {n} 条战报（{window_sec} 秒窗）",
            "battle_mention_line": "{mention} {text}",
        }
        if key not in defaults:
            raise KeyError(key)  # 未知 key → 调用侧回退原文（模板缺 key 行为）
        return defaults[key].format(**ctx)

    def _emit(self, text: str) -> None:
        if self._emoji is not None:
            ok, unknown = self._emoji(text)
            if not ok:
                # D-01：越白名单 emoji 剥除后发送（装配期已告警，战斗期零阻断）
                for e in unknown:
                    text = text.replace(e, "")
        self._send(text)

    def _summary_text(self, n: int) -> str:
        try:
            return self._tpl(
                "battle_merge_summary", {"n": n, "window_sec": int(self._window)}
            )
        except Exception:  # noqa: BLE001 模板异常回退内置文案
            return "▫ 已合并 %d 条战报（%d 秒窗）" % (n, int(self._window))

    # ---- 公开 ----

    def feed(self, text: str, cls: Optional[str] = None, mention: str = "") -> None:
        """进件一条战报。

        - cls ∈ MENTION_CLASSES：@白名单类——先 flush 合并窗再直发本条
          （保序：合并摘要先出、白名单行后出，可带 mention 前缀）；
        - 其余（cls=None 或非白名单）：入合并窗。
        """
        now = self._clock()
        if cls in MENTION_CLASSES:
            self.flush(now=now)
            try:
                line = self._tpl("battle_mention_line", {"mention": mention, "text": text})
            except Exception:  # noqa: BLE001 模板缺 key → 原文直发
                line = ("%s %s" % (mention, text)).strip()
            self._emit(line)
            return
        if not self._buf:
            self._opened_at = now
        self._buf.append(text)
        self.flush(now=now)

    def flush(self, now: Optional[float] = None) -> int:
        """窗满/到期/手动合并：窗口内条目逐条 + 摘要行收尾一次发送。"""
        now = self._clock() if now is None else now
        if not self._buf:
            return 0
        expired = self._opened_at is None or (now - self._opened_at) >= self._window
        if not expired:
            return 0
        n = len(self._buf)
        body = "\n".join(self._buf)
        self._emit(body)
        self._emit(self._summary_text(n))
        sent, self._buf, self._opened_at = n, [], None
        return sent

    def pending(self) -> int:
        return len(self._buf)
