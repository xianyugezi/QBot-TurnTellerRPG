"""内容包自带测试的通用辅助实现（E3 · 框架侧 · ``qbot_rpg/assembly/testing_support.py``）。

**公开面**是 ``qbot_rpg.testing``（其 ``__init__`` 原样转出本模块的名字）。实现放在
装配层，是因为「以该包为内容根装配出可跑指令的 deps」必然接线 ``commands``——而按
``scripts/check_architecture.py`` TC-03，``commands`` 只允许装配层（assembly）依赖；
``qbot_rpg.testing`` 作为测试辅助面转出，不给低层引入 shell 依赖。

依据：``docs/游戏包扩展点_方案_E.md`` §三 E3（测试与构建脚本约定）。

**这是内容包自带测试（``content/<pack>/tests/``）可以依赖的框架辅助面**：任何包、
任何包名都适用，不写死任何包名 / 指令名 / 业务词（判据 = 换个包照样跑）。

提供的能力（全部复用既有装配入口，不另造引擎）：
- :func:`pack_root_from`：从包内任一文件/目录向上找到 ``manifest.json`` → 以该包为内容根；
- :func:`in_memory_db`：内存库（复用既有 ``Database(":memory:")`` 口径）；
- :func:`build_pack_deps` / :func:`pack_app`：以该包为内容根装配出可跑指令的 deps
  （复用 ``bootstrap`` + ``build_router`` + ``AssemblyDeps``），并用内存库；
- :func:`load_pack_ext` / :func:`load_pack_render`：装载该包的指令/渲染扩展，
  **双闸测试开关**（``settings.ext.enabled`` + ``--enable-pack-ext`` 一次开好）；
- :func:`send_command`：把玩家消息喂进完整指令链路，返回玩家可见文本；
- :func:`validate_pack_data`：复用框架整包校验（``build_pack`` 红拦规则），返回人话条目。

只读纪律（沿用 E1/E2 测试口径）：内存库 / 临时目录；本模块自身不写盘。

边界（照方案 §五 / §三·装载安全）：这些辅助**只**为测试方便而开双闸，不代表生产默认；
扩展运行时代码（``content/<pack>/ext/*.py``）仍**只许** import ``qbot_rpg.ext_api`` 稳定面，
其余 ``qbot_rpg.*`` 为内部实现，不承诺兼容（``qbot_rpg.testing`` 是本方案的测试辅助面）。
"""

from __future__ import annotations

import itertools
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Mapping, Optional, Sequence, Tuple

from qbot_rpg.assembly.bootstrap import bootstrap
from qbot_rpg.assembly.context import AssemblyDeps
from qbot_rpg.assembly.pack_ext import PackExtResult, load_pack_extensions
from qbot_rpg.assembly.pack_render import PackRenderResult, load_pack_render_hook
from qbot_rpg.assembly.router_setup import build_router
from qbot_rpg.assembly.runner import run_command
from qbot_rpg.commands.processing import PerPlayerQueue
from qbot_rpg.commands.router import AliasTable, Router
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.loader import PackLoadError, build_pack
from qbot_rpg.storage.connection import Database
from qbot_rpg.storage.repository import Repository

__all__ = [
    "MANIFEST_FILE",
    "PackValidation",
    "build_pack_deps",
    "close_pack_deps",
    "empty_router",
    "ext_settings",
    "in_memory_db",
    "load_pack_ext",
    "load_pack_render",
    "pack_app",
    "pack_root_from",
    "send_command",
    "validate_pack_data",
]

#: 内容包标识文件（与框架装配约定一致；仅此一处用于「以该包为内容根」判定）。
MANIFEST_FILE = "manifest.json"

#: ``send_command`` 的幂等键自增源（同一进程内不重号，避免指令重放）。
_MSG_SEQ = itertools.count(1)


# ---------------------------------------------------------------------------
# 路径 / 内存库
# ---------------------------------------------------------------------------
def pack_root_from(path: Any) -> Path:
    """从包内任一文件或目录向上找到 ``manifest.json`` → 返回该包根目录。

    入参 path: ``__file__`` / 包内目录 / 包根（都可）；出参 Path（绝对）。
    核心逻辑：``.resolve()`` 后自底向上找首个含 ``manifest.json`` 的祖先；找不到 →
    ``FileNotFoundError``（人话提示，不猜路径）。**通用**：不认识包名，只看标识文件。
    """
    start = Path(path).resolve()
    if start.is_file():
        start = start.parent
    for candidate in (start, *start.parents):
        if (candidate / MANIFEST_FILE).is_file():
            return candidate
    raise FileNotFoundError(
        f"从 {start} 向上找不到 {MANIFEST_FILE}，无法确定内容包根目录"
        "（包测试请把文件放在 content/<pack>/ 之内）"
    )


def in_memory_db() -> Database:
    """内存库（复用既有 ``Database(":memory:")`` 口径；调用方负责 ``await close()``）。"""
    return Database(":memory:")


def ext_settings(base: Any = None, *, enabled: bool = True) -> Dict[str, Any]:
    """返回一份可用的 settings 映射：``base`` 浅拷贝 + ``ext.enabled`` 落位。

    入参 base: 现有 settings（Mapping 或 None）；enabled: 第一闸取值。
    出参 dict：新对象，不改 ``base``（含 ``ext`` 子映射也复制一层）。
    """
    settings: Dict[str, Any] = dict(base) if isinstance(base, Mapping) else {}
    ext = settings.get("ext")
    ext_map: Dict[str, Any] = dict(ext) if isinstance(ext, Mapping) else {}
    ext_map["enabled"] = bool(enabled)
    settings["ext"] = ext_map
    return settings


def empty_router() -> Router:
    """空 Router（已挂别名表）：只测「本包声明/装载」而不涉及框架指令时的最小宿主。"""
    router = Router()
    router.aliases = AliasTable.from_config({})  # type: ignore[attr-defined]
    return router


# ---------------------------------------------------------------------------
# 扩展装载（双闸测试开关）
# ---------------------------------------------------------------------------
def load_pack_ext(
    pack_dir: Any,
    *,
    router: Optional[Router] = None,
    settings: Any = None,
    cli: bool = True,
) -> PackExtResult:
    """装载 ``pack_dir`` 的指令扩展（默认把双闸的测试开关打开）。

    入参 pack_dir: 包目录；router: 宿主 Router（缺省空 Router）；settings: 缺省
    ``ext.enabled=True``；cli: 第二闸（测试缺省 True，显式 False 可测关闭态）。
    出参 :class:`~qbot_rpg.assembly.pack_ext.PackExtResult`（装载层承诺不抛）。
    """
    host = router if router is not None else empty_router()
    return load_pack_extensions(
        host,
        pack_dir=pack_dir,
        settings=settings if settings is not None else ext_settings(),
        cli=cli,
    )


def load_pack_render(
    pack_dir: Any, *, settings: Any = None, cli: bool = True, timeout: float = 0.5
) -> PackRenderResult:
    """装载 ``pack_dir`` 的渲染钩子（默认把双闸的测试开关打开；口径同 :func:`load_pack_ext`）。"""
    return load_pack_render_hook(
        pack_dir,
        settings=settings if settings is not None else ext_settings(),
        cli=cli,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# 以该包为内容根的装配
# ---------------------------------------------------------------------------
def _load_pack_settings(pack_dir: Path) -> Dict[str, Any]:
    """读包内 ``settings.json``（缺失/损坏 → ``{}``；与部署装配同口径）。"""
    path = pack_dir / "settings.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(data) if isinstance(data, Mapping) else {}


async def build_pack_deps(
    pack_dir: Any,
    *,
    settings: Any = None,
    db: Optional[Database] = None,
    enable_pack_ext: bool = True,
) -> AssemblyDeps:
    """以 ``pack_dir`` 为内容根装配出可跑指令的 deps（复用既有装配入口）。

    入参 pack_dir: 包目录（``manifest.json`` 所在）；settings: 覆盖包内 settings.json；
    db: 复用既有库（缺省新建内存库，由本辅助持有）；enable_pack_ext: 测试开关——
    True（缺省）= 双闸都开（``ext.enabled=True`` + ``cli=True``）。
    出参 AssemblyDeps（含 ``router`` / ``pack_ext_result`` / ``pack_render_result`` /
    ``pack_render_hook`` 与 runner 需要的鸭式字段）。

    核心逻辑：``bootstrap``（loader 校验 + registry + GameWorld + session）→
    ``build_router``（全框架指令）→ 装载本包指令扩展与渲染钩子（失败隔离不抛）。
    **不写真实内容包 / 玩家库**：默认内存库；包内文件只读。
    """
    pd = Path(pack_dir)
    if not (pd / MANIFEST_FILE).is_file():
        raise FileNotFoundError(
            f"{pd} 不是内容包目录（缺 {MANIFEST_FILE}）；包测试请用 pack_root_from(__file__)"
        )

    settings_map = _load_pack_settings(pd)
    if isinstance(settings, Mapping):
        settings_map.update(settings)
    settings_map = ext_settings(settings_map, enabled=bool(enable_pack_ext))

    owned = db is None
    database = db if db is not None else in_memory_db()
    repo = Repository(database)
    app = await bootstrap({"pack_dir": str(pd), "repo": repo})
    deps = AssemblyDeps(
        repo=repo,
        game_world=app.game_world,
        registry=app.registry,
        settings=settings_map,
        queue=PerPlayerQueue(repo),
        session_mgr=app.session_mgr,
    )
    deps.router = build_router(deps)  # type: ignore[attr-defined]
    deps.pack_ext_result = load_pack_extensions(  # type: ignore[attr-defined]
        deps.router, pack_dir=pd, settings=settings_map, cli=bool(enable_pack_ext)
    )
    deps.pack_render_result = load_pack_render_hook(  # type: ignore[attr-defined]
        pd, settings=settings_map, cli=bool(enable_pack_ext)
    )
    deps.pack_render_hook = deps.pack_render_result.hook  # type: ignore[attr-defined]
    # runner 消费的鸭式字段（部署装配在此接 GM 后端；测试缺省 None 即安全兜底）
    deps.permission_store = None  # type: ignore[attr-defined]
    deps.audit_store = None  # type: ignore[attr-defined]
    deps.audit_hmac_key = None  # type: ignore[attr-defined]
    deps.queue_timeout = None  # type: ignore[attr-defined]
    deps.testing_db_owned = owned  # type: ignore[attr-defined]
    return deps


async def close_pack_deps(deps: Any) -> None:
    """关掉 :func:`build_pack_deps` **自己创建**的内存库（外部传入的库不动）。"""
    if not getattr(deps, "testing_db_owned", False):
        return
    db = getattr(getattr(deps, "repo", None), "db", None)
    close = getattr(db, "close", None)
    if callable(close):
        await close()


@asynccontextmanager
async def pack_app(
    pack_dir: Any,
    *,
    settings: Any = None,
    enable_pack_ext: bool = True,
) -> AsyncIterator[AssemblyDeps]:
    """``async with pack_app(pack_root) as deps:`` —— 装配 + 自动关内存库。

    入参同 :func:`build_pack_deps`（db 固定由本辅助创建）。出参 deps 的异步上下文。
    """
    deps = await build_pack_deps(
        pack_dir, settings=settings, db=None, enable_pack_ext=enable_pack_ext
    )
    try:
        yield deps
    finally:
        await close_pack_deps(deps)


async def send_command(
    deps: Any,
    message: str,
    *,
    user_id: str = "u1",
    group_id: str = "g1",
    channel: str = "group",
    message_id: Optional[str] = None,
    **event_extra: Any,
) -> str:
    """把一条玩家消息喂进完整指令链路（``run_command``），返回玩家可见文本。

    入参 deps: :func:`build_pack_deps` / :func:`pack_app` 产物；message: 原始消息；
    其余为事件字段（``user_id`` / ``group_id`` / ``channel`` 有缺省；``message_id``
    缺省自增，避免幂等重放）。出参 str（未命中/空回 → 空串）。
    """
    event: Dict[str, Any] = {
        "group_id": group_id,
        "user_id": user_id,
        "message": str(message),
        "channel": channel,
        "message_id": str(message_id) if message_id else f"testing-{next(_MSG_SEQ)}",
    }
    event.update(event_extra)
    return await run_command(event, deps)


# ---------------------------------------------------------------------------
# 整包数据校验（复用框架 loader 的红拦规则）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PackValidation:
    """一次整包数据校验的结果（供包构建脚本打印摘要，不依赖框架内部错误模型）。"""

    ok: bool
    errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    modules: int = 0
    entries: Mapping[str, int] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        """人话摘要（单行）。"""
        state = "通过" if self.ok else "未通过"
        return (
            f"整包校验{state}：红拦 {len(self.errors)} / 黄提示 {len(self.warnings)}；"
            f"模块 {self.modules} 个"
        )


def _humanize_items(items: Sequence[Any]) -> Tuple[str, ...]:
    """PackError/PackWarning → 人话条目（``模块.字段 [规则] 细节``；不抛）。"""
    out = []
    for item in items:
        module = str(getattr(item, "module", "") or "")
        field_path = str(getattr(item, "field", "") or "")
        kind = str(getattr(item, "kind", "") or "")
        detail = getattr(item, "detail", None)
        detail_text = ""
        if isinstance(detail, Mapping):
            detail_text = json.dumps(dict(detail), ensure_ascii=False, sort_keys=True)
        where = f"{module}.{field_path}" if field_path else module
        out.append(f"{where} [{kind}] {detail_text}".strip())
    return tuple(out)


def validate_pack_data(pack_dir: Any) -> PackValidation:
    """用框架 loader 的红拦规则校验 ``pack_dir``（只读；返回人话条目，不抛）。

    入参 pack_dir: 包目录。出参 :class:`PackValidation`（``ok`` / ``errors`` /
    ``warnings`` / ``modules`` / ``entries``）。核心逻辑：``build_pack``（A→B→C→D +
    校验）成功 → ok；``PackLoadError`` → 汇总其 report；其它异常 → 归入 errors。
    """
    pd = Path(pack_dir)
    try:
        pack, _changed = build_pack(pd, default_field_meta_table())
    except PackLoadError as exc:
        report = exc.report
        return PackValidation(
            ok=False,
            errors=_humanize_items(report.errors),
            warnings=_humanize_items(report.warnings),
        )
    except Exception as exc:  # noqa: BLE001 —— 非红拦异常（如 IO/权限）也算校验失败
        return PackValidation(ok=False, errors=(f"{type(exc).__name__}: {exc}",))

    modules = dict(pack.modules) if isinstance(pack.modules, Mapping) else {}
    counts: Dict[str, int] = {}
    for name, body in modules.items():
        if isinstance(body, (list, tuple)):
            counts[str(name)] = len(body)
        elif isinstance(body, Mapping):
            counts[str(name)] = len(body)
    return PackValidation(
        ok=True,
        warnings=_humanize_items(pack.report.warnings),
        modules=len(modules),
        entries=counts,
    )
