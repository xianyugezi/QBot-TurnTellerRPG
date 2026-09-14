"""内容包扩展稳定 API（``qbot_rpg.ext_api`` · E1）。

=========================== 这是稳定面（Stable Surface） ===========================
内容包内的扩展代码（``content/<pack>/ext/*.py``）**只许 import 本模块**：``import
qbot_rpg.ext_api``（或 ``from qbot_rpg import ext_api``）。本模块导出的名字在 E 方案
的 major 版本内承诺兼容（``EXT_API_VERSION`` 随框架 major 递增）。

**``qbot_rpg.*`` 的其余部分（含子模块、私有名、函数签名）都是内部实现，不承诺兼容**；
包扩展代码直接 import 其它 ``qbot_rpg.*`` 属于越界，框架升级不负责其不破坏。

能力边界（照 docs/游戏包扩展点_方案_E.md §三·装载安全·4 ——「能力约束」）：
- 本面**不提供**网络 / 子进程 / 任意文件系统读写 / 热加载 / 跨包互调；
- 读入口一律是**只读包装**（``player`` / ``settings`` / ``templates`` 为只读映射），
  包代码不得改结算、改数值、改框架状态；
- 包可持久化的只有**该包自己的状态格子**（复用批 D ``player_pack_state``：
  ``async get_state / set_state / patch_state / clear_state``），玩家维度隔离。

失败隔离（§三·装载安全·5）：扩展代码抛出的异常由框架装载层兜底——记日志 + 该次调用
返回「该功能暂不可用」人话提示，进程不崩、其它指令不受影响。**扩展作者不应依赖
异常静默**：请自行捕获可预期错误并返回人见文本。

作者文档（字段表 + 例子）：``docs/内容包扩展_指令.md``。
"""

from __future__ import annotations

import dataclasses
import random
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional

from qbot_rpg.data.logging_utils import get_logger
from qbot_rpg.core.templates import DEFAULT_TEMPLATES, render_template
from qbot_rpg.storage.pack_state import (
    clear_pack_state,
    get_pack_state,
    list_pack_states,
    patch_pack_state,
    set_pack_state,
)

__all__ = [
    "EXT_API_VERSION",
    "ExtApiError",
    "ExtApiUnavailable",
    "ExtContext",
    "log",
    "rng",
    "tpl",
    # 批 D 内容包状态格子（每 玩家 × 内容包 一格；调用方自备 db/player_id/pack_id）
    "get_pack_state",
    "set_pack_state",
    "patch_pack_state",
    "clear_pack_state",
    "list_pack_states",
]

#: 本稳定面的版本（与框架 major 同轨；破坏性变更必须递增）。
EXT_API_VERSION = "1"


class ExtApiError(Exception):
    """扩展 API 层的可预期错误基类（包代码可抛出 / 捕获；装载层也会兜底）。"""


class ExtApiUnavailable(ExtApiError):
    """依赖不可用（如未注入存档、玩家未注册、包状态格子不可写）。"""


#: 扩展默认日志器（建议用 ``ctx.log`` 拿带上包 id 的子日志器）。
log = get_logger("content.ext")


def _readonly(value: Any) -> Mapping:
    """把 Mapping 包成只读映射；非 Mapping → 空只读映射（不抛）。

    只挡顶层键写入；嵌套值是原对象（框架不深拷贝，扩展请勿原地改嵌套结构）。
    """
    if isinstance(value, Mapping):
        return MappingProxyType(dict(value))
    return MappingProxyType({})


def _player_view(player: Any) -> Optional[Mapping]:
    """玩家对象 → 只读快照映射；None / 非 dataclass → None（未注册语义）。

    用 ``dataclasses.asdict`` 深拷贝成普通 dict 再包只读——扩展拿不到可写回存档的
    活对象（框架 runner 会把 ``ctx["player"]`` 原对象落档，故不能把活对象交出去）。
    """
    if player is None:
        return None
    if dataclasses.is_dataclass(player) and not isinstance(player, type):
        try:
            return MappingProxyType(dataclasses.asdict(player))
        except Exception:  # noqa: BLE001 —— 快照失败按不可读兜底，不阻断
            log.warning("玩家快照失败，按只读空映射兜底", exc_info=True)
            return MappingProxyType({})
    if isinstance(player, Mapping):
        return _readonly(player)
    return None


def rng(*parts: Any) -> random.Random:
    """确定性随机源：以 ``parts`` 为种子构造 ``random.Random``（同参同序列）。

    用法：同一玩家同一局可复现（如 ``ext_api.rng(ctx.pack_id, ctx.player_id, "用途标签")``）。
    传不同 ``parts`` 得到独立序列；禁止用时间/系统随机做种子（破坏可复现）。
    """
    seed = "\x00".join(str(p) for p in parts)
    return random.Random(seed)


def tpl(key: str, data: Optional[Mapping[str, Any]] = None,
        *, templates: Optional[Mapping[str, Any]] = None) -> str:
    """按模板 key 渲染玩家可见文本（含既有「包内 templates.json 覆盖」语义）。

    ``templates`` 缺省 = 框架内置全量表；传 ``ctx.templates`` 即带该包覆盖。
    缺 key / 缺占位符键都不抛（缺 key → 空串；缺占位符 → 原样保留），见
    ``qbot_rpg.core.templates``。
    """
    table = templates if isinstance(templates, Mapping) else DEFAULT_TEMPLATES
    return render_template(table, str(key), dict(data or {}))


class ExtContext:
    """传给扩展 handler 的上下文（``handler(ctx, parsed)`` 的第一个参数）。

    只读入口（未装配/未注册一律安全缺省，不抛）：
      ``pack_id`` / ``player_id`` / ``group_id`` / ``user_id`` / ``channel`` /
      ``message`` / ``registered`` / ``is_gm`` / ``pack_version``
      ``player``（只读映射或 None）/ ``settings`` / ``templates``（均为只读映射）
      ``parsed``（框架 ParsedCommand 原对象：``.command`` / ``.args`` / ``.tokens`` /
      ``.raw``）；便捷只读视图 ``command`` / ``args``（元组）/ ``args_text``（空格连接）
      ``registry`` / ``repo`` / ``db``（引擎内部入口，E 方案不承诺其稳定性）

    便捷方法：
      ``tpl(key, data)`` 模板渲染（自动带本包覆盖）；
      ``rng`` 只读属性（按 包+玩家 确定性播种）；
      ``log`` 只读属性（``qbot_rpg.content.ext.<pack_id>`` 子日志器）；
      包状态读写（异步；仅本包格子）：
        ``await ctx.get_state()`` / ``await ctx.set_state(obj)`` /
        ``await ctx.patch_state(obj)`` / ``await ctx.clear_state()``。
    """

    # -- 构造（仅供框架装载层调用）-------------------------------------------
    def __init__(
        self,
        *,
        pack_id: str,
        pack_version: str = "",
        ctx: Optional[Mapping[str, Any]] = None,
        parsed: Any = None,
    ) -> None:
        self._ctx: Mapping[str, Any] = ctx if isinstance(ctx, Mapping) else {}
        self._pack_id = str(pack_id or "")
        self._pack_version = str(pack_version or "")
        self._parsed = parsed

    # -- 只读标量 -------------------------------------------------------------
    @property
    def pack_id(self) -> str:
        """当前内容包 id（运行时不透明字符串，框架不解释其含义）。"""
        return self._pack_id

    @property
    def pack_version(self) -> str:
        """当前内容包版本（manifest.version；缺失 → 空串）。"""
        return self._pack_version

    @property
    def player_id(self) -> str:
        """当前玩家 id（qq_id / user_id；未注册/缺失 → 空串）。"""
        return str(self._ctx.get("qq_id") or self._ctx.get("qid")
                   or self._ctx.get("user_id") or "")

    @property
    def group_id(self) -> str:
        return str(self._ctx.get("group_id") or "")

    @property
    def user_id(self) -> str:
        return str(self._ctx.get("user_id") or "")

    @property
    def channel(self) -> str:
        return str(self._ctx.get("channel") or "")

    @property
    def message(self) -> str:
        return str(self._ctx.get("message") or "")

    @property
    def registered(self) -> bool:
        return bool(self._ctx.get("registered"))

    @property
    def is_gm(self) -> bool:
        return bool(self._ctx.get("is_gm"))

    # -- 只读结构 -------------------------------------------------------------
    @property
    def player(self) -> Optional[Mapping]:
        """玩家只读快照（未注册 → None）；改它不会写回存档。"""
        return _player_view(self._ctx.get("player"))

    @property
    def settings(self) -> Mapping:
        """settings.json 只读映射（缺失 → 空映射）。"""
        return _readonly(self._ctx.get("settings"))

    @property
    def templates(self) -> Mapping:
        """本包模板表只读映射（= 默认表 + 本包 templates.json 覆盖）。"""
        tpls = self._ctx.get("templates")
        return _readonly(tpls) if isinstance(tpls, Mapping) else DEFAULT_TEMPLATES

    @property
    def parsed(self) -> Any:
        """框架解析产物原对象（``.command`` / ``.args`` / ``.tokens`` / ``.raw``）。"""
        return self._parsed

    @property
    def command(self) -> str:
        """实际命中的指令名（别名/快捷展开后 = 原指令名）。"""
        return str(getattr(self._parsed, "command", "") or "")

    @property
    def args(self) -> tuple:
        """位置参数元组（ParsedCommand.args；缺失 → 空元组）。"""
        raw = getattr(self._parsed, "args", None)
        if raw is None:
            return ()
        try:
            return tuple(str(a) for a in raw)
        except TypeError:
            return ()

    @property
    def args_text(self) -> str:
        """参数原串（参数之间以单空格连接；无参 → 空串）。"""
        return " ".join(self.args)

    @property
    def registry(self) -> Any:
        return self._ctx.get("registry")

    @property
    def repo(self) -> Any:
        return self._ctx.get("repo")

    @property
    def db(self) -> Any:
        """存档 Database（异步 API）；未装配 → None。"""
        return getattr(self.repo, "db", None)

    # -- 便捷能力 -------------------------------------------------------------
    def tpl(self, key: str, data: Optional[Mapping[str, Any]] = None) -> str:
        """渲染模板（自动带本包 ``templates.json`` 覆盖）。"""
        return tpl(key, data, templates=self.templates)

    @property
    def rng(self) -> random.Random:
        """按（包 id, 玩家 id）确定性播种的随机源（同 ctx 同序列）。"""
        return rng(self._pack_id, self.player_id)

    @property
    def log(self):
        """带包 id 的子日志器（``qbot_rpg.content.ext.<pack_id>``）。"""
        return get_logger(f"content.ext.{self._pack_id or 'unknown'}")

    # -- 包状态（复用批 D 的 player_pack_state；异步）--------------------------
    def _state_keys(self) -> tuple:
        """(db, player_id, pack_id)；缺失 → ExtApiUnavailable。"""
        if self.db is None:
            raise ExtApiUnavailable("存档未装配，内容包状态不可用（需在装配后调用）")
        pid = self.player_id
        if not pid:
            raise ExtApiUnavailable("玩家未注册，内容包状态不可用")
        if not self._pack_id:
            raise ExtApiUnavailable("内容包 id 缺失，内容包状态不可用")
        return self.db, pid, self._pack_id

    async def get_state(self) -> Dict[str, Any]:
        """读本包为当前玩家存的状态（不存在 / 损坏 → ``{}``，不抛）。"""
        try:
            db, pid, pack = self._state_keys()
        except ExtApiUnavailable:
            return {}
        return await get_pack_state(db, pid, pack)

    async def set_state(self, state: Mapping[str, Any]) -> None:
        """覆盖写本包为当前玩家存的状态（必须是 JSON 对象）。"""
        db, pid, pack = self._state_keys()
        await set_pack_state(db, pid, pack, state)

    async def patch_state(self, patch: Mapping[str, Any]) -> Dict[str, Any]:
        """浅合并写本包为当前玩家存的状态，返回合并结果（仅顶层键合并）。"""
        db, pid, pack = self._state_keys()
        return await patch_pack_state(db, pid, pack, patch)

    async def clear_state(self) -> None:
        """清空本包为当前玩家存的状态（幂等）。"""
        db, pid, pack = self._state_keys()
        await clear_pack_state(db, pid, pack)


def __getattr__(name: str) -> Any:
    """拒绝未导出名（更清晰的 ImportError 文案，指向稳定面）。"""
    raise AttributeError(
        f"qbot_rpg.ext_api 未导出 {name!r}；本模块是内容包扩展**稳定面**，"
        "只有 __all__ 列出的名字承诺兼容（其余 qbot_rpg.* 为内部实现，不承诺兼容）"
    )
