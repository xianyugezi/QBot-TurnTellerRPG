"""内容包渲染钩子通用装载与调用面（E2 · 框架侧 · ``qbot_rpg/assembly/pack_render.py``）。

依据：``docs/游戏包扩展点_方案_E.md`` §三 E2 / §三·装载安全 / §五 不做的事。

职责：**通用地**把一个内容包内自持的渲染钩子（``ext/render.py``）接进玩家可见文本
出口——框架不认识任何包名、业务词或包专属事件名；换任何包、放同样结构的文件，行为
一致（判据 = 换包零改动可用）。

包内约定（相对包目录 ``content/<pack>/``）::

    ext/render.py:
        EVENTS = ("command.reply",)          # 可选：事件白名单（缺省 = 全部已知事件）
        def render(event, data, default_text) -> str | None:
            ...                              # 返回 None / "" = 用框架默认文本

事件（框架稳定名；**只增不减**，包声明未知事件 → 记日志忽略，不阻断）：
- ``command.reply``：一切经 runner sender 闭包发出的指令回复（指令返回、列表、面板…）；
- ``battle.round``：战斗管线经 ``ctx["sender"]`` 直发的战斗正文（结算渲染）。

边界（本批验收核心 · 照方案 §五·2「不允许包代码改结算」）：
- 钩子**只许替换文本**：返回 str 即替换，返回 None/空 = 用默认；
- 传入 ``data`` 是**递归只读快照**（每层都是新建的只读容器；嵌套可变对象一律转
  元组/冻结），且**不含** ctx / Player / 引擎 / repo / db / sender 等任何活对象——
  包代码拿不到可写回结算的句柄；
- 钩子**不得**触发写库/写存档/发起新指令：本面不向钩子提供任何此类能力；
- 钩子异常 / 超时 / 返回非 str → 记日志 + **落默认文本**，进程不崩、不影响其它包；
- 双闸与 E1 完全一致：``settings.ext.enabled`` **且** ``--enable-pack-ext`` /
  ``QBotRPG_ENABLE_PACK_EXT``；未启用时**零文件访问**（不读 ``ext/render.py``、
  不 import 任何包内 Python）。

不做（照方案 §五）：不热加载、不做跨包互调、不允许包代码改结算、不提供网络/子进程/
文件系统 API；钩子只允许**同步纯函数**（禁长任务；超时兜底见
:data:`DEFAULT_RENDER_TIMEOUT`）。
"""

from __future__ import annotations

import dataclasses
import inspect
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from qbot_rpg.assembly.pack_ext import (
    EXT_DIR,
    PackExtError,
    import_ext_module,
    pack_ext_enabled,
    resolve_ext_file,
)
from qbot_rpg.data.logging_utils import get_logger

_logger = get_logger("assembly.pack_render")

__all__ = [
    "RENDER_FILE",
    "DEFAULT_RENDER_TIMEOUT",
    "EVENT_COMMAND_REPLY",
    "EVENT_BATTLE_ROUND",
    "KNOWN_EVENTS",
    "PackRenderError",
    "RenderTimeout",
    "RenderHook",
    "RenderSender",
    "PackRenderResult",
    "build_render_data",
    "load_pack_render_hook",
]

#: 包内渲染钩子实现文件（包目录相对路径；仅此一处，不扫描其它位置）。
RENDER_FILE = "render.py"

#: 渲染钩子同步调用超时（秒）。超时 → 记日志 + 落默认文本（丢弃迟到结果）。
#: 钩子契约是「同步纯函数、快速返回」；此值只是**软兜底**——调用返回后核对耗时，
#: 超预算即丢弃改写。**不做线程抢占**（仓库铁律「零定时器」禁止线程计时用法，
#: 见 tests/unit/test_m43_regression.py 全仓扫描）；因此钩子**必须**自己快速返回，
#: 禁止 sleep / 网络 / 长任务。
DEFAULT_RENDER_TIMEOUT = 0.5

#: 框架稳定事件名（只增不减；包声明未知事件 → 警告 + 忽略）。
EVENT_COMMAND_REPLY = "command.reply"
EVENT_BATTLE_ROUND = "battle.round"
KNOWN_EVENTS: Tuple[str, ...] = (EVENT_COMMAND_REPLY, EVENT_BATTLE_ROUND)


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------
class PackRenderError(PackExtError):
    """渲染钩子装载异常（装载层内部聚合；**不得**抛到装配顶层）。"""


class RenderTimeout(PackRenderError):
    """渲染钩子同步调用超时（由 :meth:`RenderHook.apply` 兜底为默认文本）。"""


# ---------------------------------------------------------------------------
# 只读快照（绝不把引擎内部可变对象递给包代码）
# ---------------------------------------------------------------------------
def _freeze(value: Any) -> Any:
    """递归只读化：Mapping → 只读映射、序列 → 元组、集合 → frozenset。

    每层容器都是**新建**的，包代码改不到框架原对象；标量原样；其余不可序列化对象
    一律转 ``str``（宁可给字符串，也不把活对象交出去）。返回值可直接跨线程传递。
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(v) for v in value)
    return str(value)


def _player_snapshot(player: Any) -> Optional[Mapping]:
    """玩家对象 → 递归只读快照映射；None / 非 dataclass 且非 Mapping → None。"""
    if player is None:
        return None
    if dataclasses.is_dataclass(player) and not isinstance(player, type):
        try:
            return _freeze(dataclasses.asdict(player))
        except Exception:  # noqa: BLE001 —— 快照失败按只读空映射兜底，不阻断
            _logger.warning("玩家快照失败，按只读空映射兜底", exc_info=True)
            return _freeze({})
    if isinstance(player, Mapping):
        return _freeze(player)
    return None


def build_render_data(
    *,
    event: str,
    pack_id: str,
    command: str = "",
    ctx: Optional[Mapping[str, Any]] = None,
    outcome: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """构造传给钩子的 ``data``：递归只读快照，**不含任何活对象/引擎句柄**。

    字段（稳定面；只增不减）：

    ============  =================  ==========================================
    键            类型               含义
    ============  =================  ==========================================
    ``event``     str                框架事件名（与钩子首参一致）
    ``pack_id``   str                当前内容包 id（目录名）
    ``command``   str                命中的指令名；未知 → 空串
    ``channel``   str                消息来源渠道（group/private…）
    ``group_id``  str                群 id；私聊/缺失 → 空串
    ``player_id`` str                玩家 id；未注册 → 空串
    ``registered``bool               玩家是否已注册
    ``player``    只读映射 / None    玩家快照（字段可读，改无效）
    ``outcome``   只读映射           指令结果摘要（``{"ok": bool}``）；无 → 空映射
    ============  =================  ==========================================
    """
    source: Mapping[str, Any] = ctx if isinstance(ctx, Mapping) else {}
    return _freeze(
        {
            "event": str(event),
            "pack_id": str(pack_id or ""),
            "command": str(command or ""),
            "channel": str(source.get("channel") or ""),
            "group_id": str(source.get("group_id") or ""),
            "player_id": str(
                source.get("qq_id") or source.get("qid") or source.get("user_id") or ""
            ),
            "registered": bool(source.get("registered")),
            "player": _player_snapshot(source.get("player")),
            "outcome": dict(outcome) if isinstance(outcome, Mapping) else {},
        }
    )


# ---------------------------------------------------------------------------
# 钩子（调用隔离：异常/超时/非 str → 默认文本）
# ---------------------------------------------------------------------------
class RenderHook:
    """一个内容包的渲染钩子（已校验的纯函数 + 事件白名单 + 调用隔离）。

    本类只被框架装载层构造；包作者不直接接触。``events=None`` 表示「全部已知事件」。
    """

    def __init__(
        self,
        fn: Callable[..., Any],
        *,
        pack_id: str,
        events: Optional[FrozenSet[str]] = None,
        timeout: float = DEFAULT_RENDER_TIMEOUT,
    ) -> None:
        self._fn = fn
        self._pack_id = str(pack_id or "")
        self._events = events
        self._timeout = float(timeout or 0)

    @property
    def pack_id(self) -> str:
        """钩子归属的内容包 id。"""
        return self._pack_id

    @property
    def events(self) -> Optional[FrozenSet[str]]:
        """声明的事件白名单；``None`` = 全部已知事件。"""
        return self._events

    @property
    def timeout(self) -> float:
        """同步调用超时秒数（<=0 = 不设超时）。"""
        return self._timeout

    def applies(self, event: str) -> bool:
        """该事件是否落在本钩子白名单内（未命中 → 框架**不调用**钩子函数）。"""
        name = str(event)
        if self._events is None:
            return name in KNOWN_EVENTS
        return name in self._events

    def _invoke(self, event: str, data: Mapping[str, Any], default_text: str) -> Any:
        """同步调用钩子；耗时超预算（timeout>0）→ :class:`RenderTimeout`。

        软超时：调用返回后核对 ``time.monotonic()`` 耗时，超预算即**丢弃结果**。这是
        与仓库「零定时器」铁律兼容的兜底方式——不引入线程/计时器抢占；钩子须快速返回。
        """
        if self._timeout <= 0:
            return self._fn(event, data, default_text)
        started = time.monotonic()
        out = self._fn(event, data, default_text)
        elapsed = time.monotonic() - started
        if elapsed > self._timeout:
            raise RenderTimeout(
                f"内容包渲染钩子超时（{elapsed:.3f}s > {self._timeout}s，"
                f"事件 {event}，包 {self._pack_id}）"
            )
        return out

    def apply(self, event: str, data: Mapping[str, Any], default_text: str) -> str:
        """调用钩子并归一返回值：**任何**异常/超时/非 str → 原样返回默认文本。

        返回 ``None`` 或空串 = 用默认；返回非空 str = 替换文本。本方法承诺不抛。
        """
        default = "" if default_text is None else str(default_text)
        if not self.applies(event):
            return default
        try:
            out = self._invoke(event, data, default)
        except Exception:  # noqa: BLE001 —— 失败隔离：钩子异常/超时不阻断发送
            _logger.exception(
                "内容包渲染钩子异常/超时（包 %s，事件 %s），落默认文本",
                self._pack_id, event,
            )
            return default
        if out is None or out == "":
            return default
        if isinstance(out, str):
            return out
        if inspect.iscoroutine(out):
            out.close()  # 不支持 async 钩子：关掉协程，避免 "never awaited" 警告
        _logger.warning(
            "内容包渲染钩子（包 %s，事件 %s）返回非 str（%s），落默认文本",
            self._pack_id, event, type(out).__name__,
        )
        return default


# ---------------------------------------------------------------------------
# 结果
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PackRenderResult:
    """一次渲染钩子装载的结果（装配日志/测试断言用；永不含业务键）。"""

    pack_id: str
    enabled: bool = False
    ok: bool = True
    loaded: bool = False
    events: Tuple[str, ...] = ()
    errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    hook: Optional[RenderHook] = field(default=None, compare=False)


# ---------------------------------------------------------------------------
# 声明解析
# ---------------------------------------------------------------------------
def _parse_events(raw: Any, warnings: List[str]) -> Optional[FrozenSet[str]]:
    """解析 ``EVENTS`` 声明：缺省 → ``None``（全部已知事件）。

    形态非法（单个字符串 / 非字符串数组 / 含非字符串项）→ :class:`PackRenderError`
    （整包渲染钩子不装，与 E1 声明非法同口径）；未知事件名 → 警告 + 忽略（只增不减
    的向前兼容：包为更新框架写的声明不该把旧框架整包打死）。
    """
    if raw is None:
        return None
    if isinstance(raw, str) or not isinstance(raw, (list, tuple, set, frozenset)):
        raise PackRenderError(
            "EVENTS 必须是字符串数组（如 ('command.reply',)）；"
            f"单个字符串/其它类型非法，实际 {type(raw).__name__}"
        )
    declared: List[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise PackRenderError(f"EVENTS 含非字符串项 {item!r}，拒绝装载")
        if item not in KNOWN_EVENTS:
            warnings.append(
                f"EVENTS 声明了未知事件『{item}』（本框架已知 {list(KNOWN_EVENTS)}），已忽略"
            )
            continue
        declared.append(item)
    return frozenset(declared)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def load_pack_render_hook(
    pack_dir: Any,
    *,
    settings: Any = None,
    cli: Optional[bool] = None,
    argv: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
    timeout: float = DEFAULT_RENDER_TIMEOUT,
) -> PackRenderResult:
    """装载 ``pack_dir`` 内容包自持的渲染钩子（双闸 + 路径约束 + 失败隔离）。

    入参：
      - pack_dir: 内容包目录（``manifest.json`` 所在）；
      - settings: 装配 settings（第一闸 ``settings.ext.enabled``）；
      - cli: 第二闸（``None`` = 读 ``argv``/``env``；显式 bool 供装配注入与测试）；
      - argv/env: 便于测试注入的启动参数/环境变量；
      - timeout: 钩子同步调用兜底超时秒数（<=0 = 不设超时）。

    出参 :class:`PackRenderResult`（``.hook`` 为已隔离的 :class:`RenderHook` 或
    ``None``）。**本函数承诺不抛**；未启用直接返回且**零文件访问**。
    """
    try:
        pack_path = Path(pack_dir)
    except (TypeError, ValueError) as exc:
        _logger.error("内容包渲染钩子装载失败：pack_dir 非法 %r（%s）", pack_dir, exc)
        return PackRenderResult(pack_id="", enabled=False, ok=False, errors=(str(exc),))

    pack_id = pack_path.name

    # ---- 双闸：任一未开 = 不启用（不读 ext/render.py、不 import 任何包内 Python）----
    if not pack_ext_enabled(settings, cli=cli, argv=argv, env=env):
        _logger.info(
            "内容包渲染钩子未启用（settings.ext.enabled 与 --enable-pack-ext 需同时为真）"
            "→ %s 未读取", pack_path,
        )
        return PackRenderResult(pack_id=pack_id, enabled=False, ok=True)

    # ---- 启用后的每一步都不许抛到顶层（失败隔离，与 E1 同口径）----
    try:
        return _load_enabled(pack_path, pack_id, timeout)
    except PackExtError as exc:
        _logger.error("内容包『%s』渲染钩子装载失败，降级为不生效：%s", pack_id, exc)
        return PackRenderResult(pack_id=pack_id, enabled=True, ok=False, errors=(str(exc),))
    except Exception as exc:  # noqa: BLE001 —— 最后一道防线，绝不中断装配
        _logger.exception("内容包『%s』渲染钩子装载出现未预期异常，降级为不生效", pack_id)
        return PackRenderResult(
            pack_id=pack_id, enabled=True, ok=False,
            errors=(f"未预期异常 {type(exc).__name__}: {exc}",),
        )


def _load_enabled(pack_path: Path, pack_id: str, timeout: float) -> PackRenderResult:
    """启用路径：路径校验 → 动态 import → 校验 ``render`` → 解析 ``EVENTS``。"""
    warnings: List[str] = []
    impl_path = resolve_ext_file(pack_path, EXT_DIR, RENDER_FILE)
    if not impl_path.is_file():
        _logger.info(
            "内容包『%s』已启用但无 %s/%s，视为无渲染钩子", pack_id, EXT_DIR, RENDER_FILE
        )
        return PackRenderResult(
            pack_id=pack_id, enabled=True, ok=True, warnings=("无渲染钩子文件",)
        )

    module = import_ext_module(impl_path, pack_id, kind="ext_render")
    fn = getattr(module, "render", None)
    if not callable(fn):
        raise PackRenderError(
            f"{EXT_DIR}/{RENDER_FILE} 未导出可调用的 render(event, data, default_text)；"
            f"实际 render={type(fn).__name__}"
        )
    events = _parse_events(getattr(module, "EVENTS", None), warnings)
    hook = RenderHook(fn, pack_id=pack_id, events=events, timeout=timeout)
    _logger.info(
        "内容包『%s』渲染钩子装载完成：事件 %s",
        pack_id,
        sorted(hook.events) if hook.events is not None else list(KNOWN_EVENTS),
    )
    return PackRenderResult(
        pack_id=pack_id,
        enabled=True,
        ok=True,
        loaded=True,
        events=tuple(sorted(hook.events)) if hook.events is not None else KNOWN_EVENTS,
        warnings=tuple(warnings),
        hook=hook,
    )


# ---------------------------------------------------------------------------
# 发送代理（ctx["sender"] 直发文本走同一钩子面）
# ---------------------------------------------------------------------------
class RenderSender:
    """把渲染钩子套在真实 Sender 外层的**只读**代理（仅 ``ctx["sender"]`` 用）。

    战斗管线等经 ``ctx["sender"]`` 直发的正文与 runner 闭包**同一出口**：``send`` 只
    换文本（过钩子），不改 Sender 的 CQ 转义/分片/重试语义，返回值原样透传。
    未装钩子 / 钩子未声明该事件时，框架**不构造本代理**（``ctx["sender"]`` 仍是原
    Sender 实例）。
    """

    def __init__(
        self,
        sender: Any,
        hook: RenderHook,
        *,
        event: str,
        ctx: Optional[Mapping[str, Any]] = None,
        command: str = "",
    ) -> None:
        self._sender = sender
        self._hook = hook
        self._event = str(event)
        self._command = str(command or "")
        self._ctx: Mapping[str, Any] = ctx if isinstance(ctx, Mapping) else {}

    def send(self, text: Any, *args: Any, **kwargs: Any) -> Any:
        """过钩子后转发真实 Sender（默认文本 = 传进来的最终文本）。"""
        default = "" if text is None else str(text)
        data = build_render_data(
            event=self._event, pack_id=self._hook.pack_id,
            command=self._command, ctx=self._ctx,
        )
        rendered = self._hook.apply(self._event, data, default)
        return self._sender.send(rendered, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """其余属性透传真实 Sender（转义/分片/重试等语义不变）。"""
        return getattr(self._sender, name)
