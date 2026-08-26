"""统一发送出口壳 Sender（M4 实装 · 依据：m4_shared_contract §2.2 + 细化_3d + 2026-08-27 裁决②）。

职责（细化_3a §1.3 / §5.3 壳层发送职责 · 唯一发送出口）：
  - CQ 转义（cq_escape：对 message_format 纯字符串做段级转义防注入，【框架】L1622/【规则】L510）
  - 长度预算分条（segment_by_length：QQ 4000 字上限，超长分两条发送不吞消息，【规则】L507/S5）
  - 失败重试 + 风控退避（指数退避，不无限重发，【规则】L503/L523）
  - 禁止裸 send：所有发送路径必须收敛本出口（【规则】L523）
  - 页码非法（0/负数/非数字）→ TPL-12 统一报错 + 页脚指引（3d §2.2 + 2026-08-27 用户裁决②）

铁律（m4_shared_contract §0）：零 NoneBot import（发送目标以 send_text 回调注入，可脱离平台单测）；
纯函数（cq_escape / segment_by_length / format_tpl12~14）；模板字符串不硬编码路径。
错误模板统一 TPL-12/13/14（3d D-04 唯一文案源 = commands/errors.py，本模块只引用不重写、
不自造三要素句式）；装饰性 emoji 禁用（3d §四 D-01），错误文案仅用 ❌ 功能性标记。
"""
from __future__ import annotations

from time import sleep as _time_sleep
from typing import Any, Callable, List, Optional

# 同包兄弟模块（commands/errors.py）内的相对导入：唯一文案源 TPL-12/13/14（3d D-04）。
# 不用绝对导入 `qbot_rpg.commands.errors`——G0 架构门禁（test_g0_architecture
# test_commands_web_not_depended）会把任何指向 commands 的绝对导入边判为反向依赖；
# 相对导入不产生 `qbot_rpg.commands` 前缀边（同层兄弟引用，架构合规）。
from .errors import (
    TPL_ERR_BAD_COMMAND,
    TPL_ERR_CONDITION,
    TPL_ERR_LACK_RESOURCE,
)
from qbot_rpg.core.message_format.list_render import render_footer

__all__ = [
    "BACKOFF_BASE",
    "DEFAULT_LENGTH_BUDGET",
    "MAX_RETRIES",
    "Sender",
    "SenderSendError",
    "cq_escape",
    "format_tpl12",
    "format_tpl13",
    "format_tpl14",
    "page_error_tpl12",
    "segment_by_length",
]

# 单条消息长度预算（字符；QQ 文本上限 4000 字，超长分两条发送不吞消息，3a §5.3/规则 L507）
DEFAULT_LENGTH_BUDGET: int = 4000

# 单条发送失败重试次数（指数退避，不无限重发，规则 L503/L523）
MAX_RETRIES: int = 3

# 指数退避基数（秒：第 n 次重试等待 backoff_base ** n）
BACKOFF_BASE: float = 2.0


class SenderSendError(RuntimeError):
    """发送失败：重试耗尽仍失败（不无限重发）。"""


def cq_escape(text: str) -> str:
    """CQ 码段级转义（防注入，框架 L1622 / 规则 L510）。纯函数。

    顺序：``&`` → ``&amp;`` → ``[`` → ``&#91;`` → ``]`` → ``&#93;``（OneBot v11 文本段转义，
    使正文中的半角方括号/与号无法拼出伪造 ``[CQ:`` 段）。
    """
    return text.replace("&", "&amp;").replace("[", "&#91;").replace("]", "&#93;")


def segment_by_length(
    text: str,
    budget: int = DEFAULT_LENGTH_BUDGET,
) -> List[str]:
    """按长度预算分条（QQ 4000 字上限；顺序不颠倒、不吞内容，3a S5 / 规则 L507）。

    - 超长自动分两条发送（框架 L1346），不截断语义（渲染层不截断，3a S5）。
    - 空文本返回空列表（无内容可发）。
    """
    if budget <= 0:
        raise ValueError(f"budget 必须 > 0，got {budget}")
    if not text:
        return []
    if len(text) <= budget:
        return [text]
    return [text[i:i + budget] for i in range(0, len(text), budget)]


def format_tpl12(fragment: str) -> str:
    """TPL-12 指令出错（3d §5.1）：``❌ 指令不正确：{原指令片段}。输入 /帮助 查看可用指令。``

    原指令片段截取前 20 字符，超过截断加 ``…``（3d §5.1 防刷屏）。文案唯一源 errors.py（D-04）。
    """
    clipped = fragment[:20] + ("…" if len(fragment) > 20 else "")
    return TPL_ERR_BAD_COMMAND.format(fragment=clipped)


def format_tpl13(name: str, current: object, required: object) -> str:
    """TPL-13 条件不满足（3d §5.2）：``❌ 条件不满足：{条件名}（当前 {当前值}，需要 {需求值}）``。"""
    return TPL_ERR_CONDITION.format(name=name, current=current, required=required)


def format_tpl14(resource: str, amount: object, current: object) -> str:
    """TPL-14 资源不足（3d §5.3）：``❌ 资源不足：需要 {资源}{数量}，当前 {当前值}``。

    失败无副作用（不扣款不消耗，3d §5.3）；同动作多资源只报第一个不满足（配置声明顺序）。
    """
    return TPL_ERR_LACK_RESOURCE.format(resource=resource, amount=amount, current=current)


def page_error_tpl12(fragment: str, command: str, total_pages: int, total: int) -> str:
    """列表页码非法（0/负数/非数字）→ TPL-12 统一报错 + 页脚 TPL-08 指引（3d §2.2 + 裁决②）。

    附当前页脚（3d §2.2「附当前页脚 TPL-08」：以第 1 页为当前页指引翻页）。
    注意：超总页数不走此路——裁决② 为夹取最后一页 + 「已到最后一页」（见 list_render.resolve_page）。
    """
    msg = format_tpl12(fragment)
    footer = render_footer(1, total_pages, total, command)
    return f"{msg}\n{footer}" if footer else msg


class Sender:
    """统一发送出口（唯一发送路径；发送目标以 send_text 回调注入，零 NoneBot import）。

    :param send_text: 实际发送回调 ``send_text(text: str, *, to: Any) -> None``；失败应抛异常。
                      缺省（None）= 记录到 ``self.delivered``（测试/无平台环境直发收集）。
    :param max_retries: 单条失败重试次数（默认 3，指数退避，不无限重发）。
    :param backoff_base: 退避基数（秒，默认 2.0 → 2/4/8…）。
    :param retry_sleep: 睡眠函数（默认系统 sleep；测试注入恒 0 避免真实等待）。

    M4 接线：绑定 NoneBot bot 时把 ``bot.send`` 包成 ``send_text`` 注入；本类零 nonebot import。
    """

    def __init__(
        self,
        send_text: Optional[Callable[..., None]] = None,
        *,
        max_retries: int = MAX_RETRIES,
        backoff_base: float = BACKOFF_BASE,
        retry_sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        if max_retries < 0:
            raise ValueError(f"max_retries 必须 >= 0，got {max_retries}")
        if backoff_base <= 0:
            raise ValueError(f"backoff_base 必须 > 0，got {backoff_base}")
        self._send_text = send_text
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._sleep: Callable[[float], None] = (
            retry_sleep if retry_sleep is not None else _time_sleep
        )
        self._client: Any = None  # 兼容旧占位签名（M4 接线可绑定 NoneBot bot）
        self._delivered: List[str] = []

    @property
    def delivered(self) -> List[str]:
        """缺省 send_text 模式下的已发送段记录（顺序不颠倒）。"""
        return list(self._delivered)

    def send(
        self,
        text: str,
        *,
        to: Any = None,
        budget: int = DEFAULT_LENGTH_BUDGET,
    ) -> List[str]:
        """CQ 转义 → 长度分条 → 逐条发送（失败重试 + 指数退避）。

        :return: 实际发送成功的段列表（顺序不颠倒，S5 不吞内容）。
        :raises SenderSendError: 某段重试耗尽仍失败（不无限重发）。
        """
        escaped = cq_escape(text)
        segments = segment_by_length(escaped, budget)
        delivered: List[str] = []
        for seg in segments:
            self._send_one(seg, to=to)
            delivered.append(seg)
        return delivered

    def _send_one(self, text: str, *, to: Any) -> None:
        attempt = 0
        while True:
            try:
                if self._send_text is not None:
                    self._send_text(text, to=to)
                else:
                    self._delivered.append(text)
                return
            except Exception:
                attempt += 1
                if attempt > self._max_retries:
                    raise SenderSendError(
                        f"发送失败：重试 {self._max_retries} 次后放弃（{text[:20]}…）"
                    ) from None
                self._sleep(self._backoff_base ** attempt)
