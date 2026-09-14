"""内容包扩展通用装载器（E1 · 框架侧 · ``qbot_rpg/assembly/pack_ext.py``）。

依据：``docs/游戏包扩展点_方案_E.md`` §三 E1 / §三·装载安全 / §五 不做的事。

职责：**通用地**把一个内容包内自持的指令扩展装进既有 ``Router``——框架不认识任何
包名、指令名或业务词；换任何包、放同样结构的文件，行为一致（判据 = 换包零改动可用）。

约定（相对包目录 ``content/<pack>/``）：
- ``commands.json``：声明指令名单；
- ``ext/commands.py``：实现 handler（``def <handler>(ctx, parsed) -> str``）。

装载安全（双闸 · 两道必须**同时**打开；任一未开 = 不启用）：
1. ``settings.ext.enabled``（**缺省 false**；settings 来自包内 settings.json 或装配注入）；
2. 启动参数 ``--enable-pack-ext``（或等价环境变量 ``QBotRPG_ENABLE_PACK_EXT``；
   NoneBot 侧与 CLI 侧都能传，见 ``qbot_rpg_bridge/assemble.py``）。

未启用 → **完全不读包内 ext/、不 import 任何包内 Python**（只在返回前做零文件访问）。

其它安全线：
- 只从**该包目录内**加载：拒绝 ``..`` 组件、拒绝符号链接、解析后必须仍在包目录内；
- 重名**一律拒绝**：与框架既有指令名/别名冲突、或包内自冲突 → 记日志 + **整个扩展
  降级为不生效**（不注册任何一条，不做 ``replace=True``），报错说清「谁与谁冲突」；
- 能力最小：handler 只经 ``qbot_rpg.ext_api`` 稳定面读写（见该模块）；
- 失败隔离：声明非法 / 路径非法 / import 失败 / handler 运行异常 → 都不得抛到顶层，
  机器人照常启动；调用异常时玩家看到模板键 ``ext_command_unavailable`` 的人话提示。

不做（照方案 §五）：不热加载、不做跨包互调、不允许覆盖框架指令、不允许包代码改结算。
"""

from __future__ import annotations

import importlib.util
import inspect
import itertools
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from qbot_rpg.commands.router import PERM_GM, PERM_USER, AliasEntry, CommandSpec
from qbot_rpg.data.logging_utils import get_logger
from qbot_rpg.ext_api import EXT_API_VERSION, ExtContext

_logger = get_logger("assembly.pack_ext")

__all__ = [
    "CLI_FLAG",
    "ENV_ENABLE",
    "DECL_FILE",
    "EXT_DIR",
    "IMPL_FILE",
    "HANDLER_ERROR_TPL_KEY",
    "PackExtError",
    "PackExtPathError",
    "PackExtDeclarationError",
    "PackExtResult",
    "resolve_cli_enabled",
    "settings_enabled",
    "pack_ext_enabled",
    "resolve_ext_file",
    "import_ext_module",
    "load_pack_extensions",
]

# 声明文件 / 实现文件（包目录相对路径；仅此两处，不扫描其它位置）
DECL_FILE = "commands.json"
EXT_DIR = "ext"
IMPL_FILE = "commands.py"

# 启动参数（CLI 侧）与等价环境变量（NoneBot 侧推荐通道）
CLI_FLAG = "--enable-pack-ext"
ENV_ENABLE = "QBotRPG_ENABLE_PACK_EXT"

# handler 调用异常时的兜底模板键（框架全量表键；内容包可在 templates.json 覆盖）
HANDLER_ERROR_TPL_KEY = "ext_command_unavailable"

# 声明允许字段（未知字段 = 拼错，拒绝并提示，防静默失效）
_ALLOWED_KEYS = frozenset({"name", "aliases", "usage", "help", "handler", "gm_only"})

# 模块名清洗用（非标识符字符 → _）
_MOD_RE = re.compile(r"[^0-9A-Za-z_]+")

# 同名包重复装载时给模块名追加的自增后缀（避免 sys.modules 复用旧实现）
_LOAD_SEQ = itertools.count(1)


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------
class PackExtError(Exception):
    """内容包扩展装载异常基类（装载层内部聚合；**不得**抛到装配顶层）。"""


class PackExtPathError(PackExtError):
    """路径非法：含 ``..`` 组件 / 符号链接 / 解析后逃逸包目录。"""


class PackExtDeclarationError(PackExtError):
    """``commands.json`` 非法：字段缺失/类型错/未知字段/重名冲突。"""


# ---------------------------------------------------------------------------
# 双闸判定
# ---------------------------------------------------------------------------
def _truthy(value: Any) -> bool:
    """环境变量/字符串真值：1/true/yes/on（大小写不敏感）；其它假。"""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "y"}


def settings_enabled(settings: Any) -> bool:
    """第一闸：``settings.ext.enabled`` 是否为真（缺省 false）。"""
    if not isinstance(settings, Mapping):
        return False
    ext = settings.get("ext")
    if not isinstance(ext, Mapping):
        return False
    return _truthy(ext.get("enabled"))


def resolve_cli_enabled(
    argv: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    """第二闸：启动参数 ``--enable-pack-ext`` 或环境变量是否出现。

    ``argv`` 缺省 ``sys.argv``；``env`` 缺省 ``os.environ``。任一命中即为真——
    两种通道面向不同部署形态（CLI 用参数；NoneBot 进程用环境变量最稳）。
    """
    args = list(sys.argv if argv is None else argv)
    environ = os.environ if env is None else env
    if CLI_FLAG in args:
        return True
    return _truthy(environ.get(ENV_ENABLE))


def pack_ext_enabled(
    settings: Any,
    *,
    cli: Optional[bool] = None,
    argv: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    """双闸合取：``settings.ext.enabled`` **且** 启动参数/环境变量都开才启用。

    ``cli`` 显式给定时不再读 argv/env（供装配注入与测试）；缺省 ``None`` = 自动解析。
    """
    gate_cli = resolve_cli_enabled(argv, env) if cli is None else bool(cli)
    return settings_enabled(settings) and gate_cli


# ---------------------------------------------------------------------------
# 结果
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PackExtResult:
    """一次内容包扩展装载的结果（装配日志/测试断言用；永不含业务键）。"""

    pack_id: str
    enabled: bool = False
    ok: bool = True
    registered: Tuple[str, ...] = ()
    aliases: Tuple[str, ...] = ()
    errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()

    @property
    def loaded(self) -> bool:
        """是否真的装入了至少一条指令。"""
        return bool(self.registered)


# ---------------------------------------------------------------------------
# 路径约束（只从包目录内加载）
# ---------------------------------------------------------------------------
def _reject_dotdot(path: Path, what: str) -> None:
    if ".." in path.parts:
        raise PackExtPathError(f"{what} 路径含 '..'，拒绝加载：{path}")


def _resolve_within(pack_root: Path, *parts: str) -> Path:
    """把 ``parts`` 拼到包根下并断言不逃逸、不经符号链接。

    入参 pack_root: 包目录；parts: 相对片段（固定字面量，不接受外部路径）。
    出参 Path: 解析后的绝对路径。核心逻辑：① 片段本身禁 ``..``；② 包根路径禁 ``..``；
    ③ 逐段禁止符号链接（``is_symlink``）；④ ``resolve()`` 后必须仍在包根之内。
    """
    for part in parts:
        if part in ("", ".", "..") or "/" in part or "\\" in part:
            raise PackExtPathError(f"非法路径片段 {part!r}，拒绝加载（只允许包内固定文件名）")
    _reject_dotdot(pack_root, "内容包目录")
    root = pack_root.resolve()
    candidate = pack_root.joinpath(*parts)
    # 逐段拒绝符号链接（含中间目录），防「链接到包外」
    probe = pack_root
    for part in parts:
        probe = probe / part
        if probe.is_symlink():
            raise PackExtPathError(
                f"路径 {probe} 是符号链接，拒绝加载（扩展只允许包内真实文件）"
            )
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PackExtPathError(
            f"路径 {candidate} 解析到包目录之外（{resolved} ∉ {root}），拒绝加载"
        ) from exc
    return resolved


def resolve_ext_file(pack_root: Any, *parts: str) -> Path:
    """包内固定扩展文件的路径解析（公开包装；供 E2 渲染装载器复用同一路径约束）。

    入参 pack_root: 包目录；parts: 相对固定文件名片段。出参 Path（绝对）。
    核心逻辑: 委托 :func:`_resolve_within` —— 禁 ``..`` / 符号链接 / 逃逸包目录。
    """
    return _resolve_within(Path(pack_root), *parts)


# ---------------------------------------------------------------------------
# 声明解析与校验
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Decl:
    """一条已校验的指令声明（内部中间物）。"""

    name: str
    aliases: Tuple[str, ...]
    usage: str
    help: str
    handler: str
    gm_only: bool


def _is_token(value: Any) -> bool:
    """指令名/别名合法性：非空 str、无空白、无斜杠、首尾无空白。"""
    return (
        isinstance(value, str)
        and value != ""
        and value == value.strip()
        and "/" not in value
        and not any(ch.isspace() for ch in value)
    )


def _validate_one(raw: Any, idx: int, errors: List[str]) -> Optional[_Decl]:
    """校验单条声明；非法 → 记 errors 并返回 None（不抛，聚合后统一拒绝）。"""
    where = f"commands[{idx}]"
    if not isinstance(raw, Mapping):
        errors.append(f"{where}: 必须是对象，实际 {type(raw).__name__}")
        return None
    unknown = sorted(k for k in raw if k not in _ALLOWED_KEYS)
    if unknown:
        errors.append(f"{where}: 未知字段 {unknown}（允许字段 {sorted(_ALLOWED_KEYS)}）")
    name = raw.get("name")
    if not _is_token(name):
        errors.append(f"{where}.name: 必须是非空、无空白/斜杠的字符串，实际 {name!r}")
    handler = raw.get("handler")
    if not isinstance(handler, str) or not handler.isidentifier():
        errors.append(
            f"{where}.handler: 必须是合法 Python 函数名（标识符），实际 {handler!r}"
        )
    aliases_raw = raw.get("aliases", [])
    aliases: List[str] = []
    if aliases_raw is not None:
        if not isinstance(aliases_raw, (list, tuple)):
            errors.append(f"{where}.aliases: 必须是字符串数组，实际 {type(aliases_raw).__name__}")
        else:
            for j, alias in enumerate(aliases_raw):
                if not _is_token(alias):
                    errors.append(
                        f"{where}.aliases[{j}]: 必须是非空、无空白/斜杠的字符串，实际 {alias!r}"
                    )
                else:
                    aliases.append(alias)
    usage = raw.get("usage", "")
    if usage is not None and not isinstance(usage, str):
        errors.append(f"{where}.usage: 必须是字符串，实际 {type(usage).__name__}")
    help_text = raw.get("help", "")
    if help_text is not None and not isinstance(help_text, str):
        errors.append(f"{where}.help: 必须是字符串，实际 {type(help_text).__name__}")
    gm_only = raw.get("gm_only", False)
    if not isinstance(gm_only, bool):
        errors.append(f"{where}.gm_only: 必须是布尔值，实际 {type(gm_only).__name__}")
    if errors and not _is_token(name):
        return None
    if name is None or handler is None:
        return None
    return _Decl(
        name=str(name),
        aliases=tuple(aliases),
        usage=str(usage or ""),
        help=str(help_text or ""),
        handler=str(handler),
        gm_only=bool(gm_only),
    )


def parse_declarations(doc: Any) -> List[_Decl]:
    """解析 ``commands.json`` 文档 → 声明列表；任何非法 → :class:`PackExtDeclarationError`。

    ``doc`` 形态：``{"commands": [ {…}, … ]}``；``commands`` 缺省/空数组 = 无指令。
    """
    errors: List[str] = []
    if not isinstance(doc, Mapping):
        raise PackExtDeclarationError(
            f"{DECL_FILE} 顶层必须是对象，实际 {type(doc).__name__}"
        )
    raw_cmds = doc.get("commands", [])
    if raw_cmds is None:
        raw_cmds = []
    if not isinstance(raw_cmds, list):
        raise PackExtDeclarationError(
            f"{DECL_FILE}.commands 必须是数组，实际 {type(raw_cmds).__name__}"
        )
    decls: List[_Decl] = []
    for idx, raw in enumerate(raw_cmds):
        decl = _validate_one(raw, idx, errors)
        if decl is not None:
            decls.append(decl)
    if errors:
        raise PackExtDeclarationError("；".join(errors))
    return decls


def _check_conflicts(
    decls: Sequence[_Decl],
    framework_names: Sequence[str],
    framework_aliases: Mapping[str, str],
) -> None:
    """重名预检：框架既有名/别名、包内自冲突 → 聚合报错（谁与谁冲突）。

    ``framework_aliases`` = {别名: 归属指令名}（含装配级 AliasTable 与各 CommandSpec
    自带 aliases 两处）。报错信息必须指认冲突双方；**不做 replace=True**，不做静默覆盖。
    """
    errors: List[str] = []
    seen_names: Dict[str, str] = {}
    seen_aliases: Dict[str, str] = {}
    fw_names = set(framework_names)
    fw_alias_names = set(framework_aliases)
    for decl in decls:
        if decl.name in fw_names:
            errors.append(
                f"指令『{decl.name}』与框架既有指令『{decl.name}』冲突，拒绝注册"
                "（内容包不得重名/覆盖框架指令）"
            )
        if decl.name in fw_alias_names:
            target = framework_aliases.get(decl.name) or "框架指令"
            errors.append(
                f"指令『{decl.name}』与框架既有别名『{decl.name}』（指向指令『{target}』）冲突，"
                "拒绝注册"
            )
        if decl.name in seen_names:
            errors.append(
                f"指令『{decl.name}』与包内指令『{decl.name}』重复声明，拒绝注册"
            )
        seen_names.setdefault(decl.name, decl.name)
        for alias in decl.aliases:
            if alias == decl.name:
                errors.append(f"指令『{decl.name}』的别名与指令名相同，拒绝注册")
            if alias in fw_names:
                errors.append(
                    f"指令『{decl.name}』的别名『{alias}』与框架既有指令『{alias}』冲突，"
                    "拒绝注册"
                )
            if alias in fw_alias_names:
                target = framework_aliases.get(alias) or "框架指令"
                errors.append(
                    f"指令『{decl.name}』的别名『{alias}』与框架既有别名『{alias}』"
                    f"（指向指令『{target}』）冲突，拒绝注册"
                )
            if alias in seen_names:
                errors.append(
                    f"指令『{decl.name}』的别名『{alias}』与包内指令『{alias}』冲突，拒绝注册"
                )
            if alias in seen_aliases:
                errors.append(
                    f"指令『{decl.name}』的别名『{alias}』与包内指令"
                    f"『{seen_aliases[alias]}』的别名重复，拒绝注册"
                )
            seen_aliases.setdefault(alias, decl.name)
    if errors:
        raise PackExtDeclarationError("；".join(errors))


# ---------------------------------------------------------------------------
# 动态 import（只从包目录内）
# ---------------------------------------------------------------------------
def _import_ext_impl(impl_path: Path, pack_id: str, kind: str = "ext") -> Any:
    """从包内文件路径动态加载实现模块；失败 → :class:`PackExtError`。

    模块名含包 id（便于测试断言「未启用时从未 import」）+ 自增后缀（重复装载不命中
    旧模块）。``kind`` 区分扩展种类（E1 指令 ``ext`` / E2 渲染 ``ext_render``），
    缺省 ``ext`` 与 E1 模块名逐字一致。装载失败会清掉半成品 sys.modules 条目，
    避免污染后续 import。
    """
    seq = next(_LOAD_SEQ)
    clean_kind = _MOD_RE.sub("_", kind) or "ext"
    mod_name = f"qbot_rpg_content_{clean_kind}_{_MOD_RE.sub('_', pack_id) or 'pack'}_{seq}"
    spec = importlib.util.spec_from_file_location(mod_name, impl_path)
    if spec is None or spec.loader is None:
        raise PackExtError(f"无法为 {impl_path} 构造 import spec（文件形态异常）")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 —— import 失败必须降级不炸装配
        sys.modules.pop(mod_name, None)
        raise PackExtError(
            f"内容包『{pack_id}』扩展实现 {impl_path} import 失败："
            f"{type(exc).__name__}: {exc}"
        ) from exc
    return module


def import_ext_module(impl_path: Any, pack_id: str, kind: str = "ext") -> Any:
    """动态 import 包内扩展模块（公开包装；供 E2 渲染装载器复用同一隔离 import）。

    入参 impl_path: 包内已解析的 .py 路径；pack_id: 包 id；kind: 扩展种类标识。
    出参 模块对象；失败 → :class:`PackExtError`（装载层会降级，不炸装配）。
    """
    return _import_ext_impl(Path(impl_path), pack_id, kind=kind)


def _make_handler(
    fn: Callable[..., Any],
    *,
    pack_id: str,
    pack_version: str,
    command_name: str,
) -> Callable[..., Any]:
    """把包内 ``def handler(ctx, parsed)`` 适配为 Router 的 ``handler(parsed, ctx=…)``。

    适配 + 隔离：构造 :class:`~qbot_rpg.ext_api.ExtContext` 作第一实参；同步/异步
    handler 都支持；运行期任何异常 → 记日志 + 返回模板键 ``ext_command_unavailable``
    的人话提示（进程不崩、其它指令不受影响）。
    """

    async def _handler(parsed: Any, ctx: Any = None) -> Any:
        ectx = ExtContext(
            pack_id=pack_id, pack_version=pack_version, ctx=ctx, parsed=parsed
        )
        try:
            out = fn(ectx, parsed)
            if inspect.isawaitable(out):
                out = await out
            return out
        except Exception:  # noqa: BLE001 —— 失败隔离：单条指令异常不拖垮内核
            ectx.log.exception(
                "内容包扩展指令『%s』(包 %s) handler 异常，降级为默认提示",
                command_name, pack_id,
            )
            try:
                return ectx.tpl(HANDLER_ERROR_TPL_KEY, {})
            except Exception:  # noqa: BLE001 —— 连兜底渲染都失败则空串，绝不抛
                return ""

    _handler.__name__ = f"pack_ext_{_MOD_RE.sub('_', pack_id)}_{command_name}"
    return _handler


def _pack_version(pack_root: Path) -> str:
    """读 manifest.version（缺失/损坏 → 空串；仅供 ctx.pack_version 展示）。"""
    try:
        doc = json.loads((pack_root / "manifest.json").read_text(encoding="utf-8"))
        if isinstance(doc, Mapping):
            return str(doc.get("version") or "")
    except (OSError, ValueError):
        pass
    return ""


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def load_pack_extensions(
    router: Any,
    *,
    pack_dir: Any,
    settings: Any = None,
    cli: Optional[bool] = None,
    argv: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> PackExtResult:
    """把 ``pack_dir`` 内容包自持的指令扩展装进 ``router``（通用、幂等安全、失败隔离）。

    入参：
      - router: 已注册框架指令的 ``Router``（重名冲突用 ``register(replace=False)`` 再兜底）；
      - pack_dir: 内容包目录（``manifest.json`` 所在）；
      - settings: 装配 settings（第一闸 ``settings.ext.enabled``）；
      - cli: 第二闸（``None`` = 读 ``argv``/``env``；显式 bool 供装配注入与测试）；
      - argv/env: 便于测试注入的启动参数/环境变量。

    出参 :class:`PackExtResult`。**本函数承诺不抛**：未启用直接返回；声明非法 / 路径
    非法 / import 失败 / 注册冲突 → 记日志 + 整个扩展降级不生效（``ok=False``），
    机器人照常启动，其它包与框架功能不受影响。

    语义要点：未启用时**零文件访问**（连 ``commands.json`` 都不读，更不碰 ``ext/``）。
    """
    try:
        pack_path = Path(pack_dir)
    except (TypeError, ValueError) as exc:
        _logger.error("内容包扩展装载失败：pack_dir 非法 %r（%s）", pack_dir, exc)
        return PackExtResult(pack_id="", enabled=False, ok=False, errors=(str(exc),))

    pack_id = pack_path.name

    # ---- 双闸：任一未开 = 不启用（完全不读包内 ext/，不 import 任何包内 Python）----
    if not pack_ext_enabled(settings, cli=cli, argv=argv, env=env):
        _logger.info(
            "内容包扩展未启用（settings.ext.enabled 与 %s 需同时为真）→ %s 未读取",
            CLI_FLAG, pack_path,
        )
        return PackExtResult(pack_id=pack_id, enabled=False, ok=True)

    # ---- 启用后的每一步都不许抛到顶层（失败隔离）----
    try:
        return _load_enabled(router, pack_path, pack_id)
    except PackExtError as exc:
        _logger.error("内容包『%s』扩展装载失败，降级为不生效：%s", pack_id, exc)
        return PackExtResult(
            pack_id=pack_id, enabled=True, ok=False, errors=(str(exc),)
        )
    except Exception as exc:  # noqa: BLE001 —— 最后一道防线，绝不中断装配
        _logger.exception("内容包『%s』扩展装载出现未预期异常，降级为不生效", pack_id)
        return PackExtResult(
            pack_id=pack_id, enabled=True, ok=False,
            errors=(f"未预期异常 {type(exc).__name__}: {exc}",),
        )


def _framework_names_and_aliases(router: Any) -> Tuple[List[str], Dict[str, str]]:
    """框架既有指令名 + 别名（别名 → 归属指令名），供重名预检。

    别名两处来源都要覆盖：① 装配级 ``router.aliases``（AliasTable，含 settings 配置）；
    ② 各 ``CommandSpec.aliases``（如指令壳自带别名）。两处都不在 Router.register 的
    重名检查范围内，故必须在装载前显式预检。
    """
    names = list(router.names())
    aliases: Dict[str, str] = {}
    table = getattr(router, "aliases", None)
    by_alias = getattr(table, "_by_alias", None)
    if isinstance(by_alias, Mapping):
        for alias, entry in by_alias.items():
            aliases[str(alias)] = str(getattr(entry, "command", "") or "")
    getter = getattr(router, "get", None)
    if callable(getter):
        for name in names:
            spec = getter(name)
            for alias in getattr(spec, "aliases", None) or []:
                aliases.setdefault(str(alias), str(name))
    return names, aliases


def _load_enabled(router: Any, pack_path: Path, pack_id: str) -> PackExtResult:
    """启用路径：读声明 → 校验 → 冲突预检 → 动态 import → 原子注册。

    任一步失败抛 :class:`PackExtError`（由 ``load_pack_extensions`` 统一降级）。
    注册采用「先全部准备、后连续注册 + 失败回滚」，保证**整包原子**：要么全生效，
    要么一条都不留。
    """
    warnings: List[str] = []

    # ① 声明文件（包内固定名，路径校验）
    decl_path = _resolve_within(pack_path, DECL_FILE)
    if not decl_path.is_file():
        _logger.info(
            "内容包『%s』已启用但无 %s，视为无扩展指令（不读 ext/）", pack_id, DECL_FILE
        )
        return PackExtResult(pack_id=pack_id, enabled=True, ok=True, warnings=("无声明文件",))

    try:
        doc = json.loads(decl_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PackExtDeclarationError(f"{DECL_FILE} 不可读/非合法 JSON：{exc}") from exc

    decls = parse_declarations(doc)
    if not decls:
        return PackExtResult(pack_id=pack_id, enabled=True, ok=True, warnings=("commands 为空",))

    # ② 重名预检（框架名 + 框架别名 + 包内自冲突）
    fw_names, fw_aliases = _framework_names_and_aliases(router)
    _check_conflicts(decls, fw_names, fw_aliases)

    # ③ 实现文件（包内固定名 ext/commands.py，路径校验）
    impl_path = _resolve_within(pack_path, EXT_DIR, IMPL_FILE)
    if not impl_path.is_file():
        raise PackExtError(
            f"内容包『{pack_id}』声明了 {len(decls)} 条指令，但缺少实现文件 "
            f"{EXT_DIR}/{IMPL_FILE}，拒绝注册"
        )
    module = _import_ext_impl(impl_path, pack_id)

    # ④ handler 齐备性预检（缺任一 → 整包拒绝，避免半装）
    missing = [d.handler for d in decls if not callable(getattr(module, d.handler, None))]
    if missing:
        raise PackExtDeclarationError(
            f"实现文件 {EXT_DIR}/{IMPL_FILE} 缺少 handler 函数：{sorted(set(missing))}"
        )

    # ⑤ 构造 spec（handler 经 ext_api 适配 + 异常隔离）
    version = _pack_version(pack_path)
    prepared: List[Tuple[_Decl, CommandSpec]] = []
    for decl in decls:
        fn = getattr(module, decl.handler)
        spec = CommandSpec(
            decl.name,
            handler=_make_handler(
                fn, pack_id=pack_id, pack_version=version, command_name=decl.name
            ),
            whitelisted=True,
            is_gm=decl.gm_only,
            permission=PERM_GM if decl.gm_only else PERM_USER,
        )
        prepared.append((decl, spec))

    # ⑥ 原子注册：失败回滚已注册项（含别名）
    table = getattr(router, "aliases", None)
    alias_add = getattr(table, "add", None)
    alias_remove = getattr(table, "remove", None)
    registered: List[str] = []
    added_aliases: List[str] = []
    try:
        for decl, spec in prepared:
            router.register(spec)  # replace=False：与框架重名再兜底一次
            registered.append(spec.name)
            if alias_add is not None:
                for alias in decl.aliases:
                    alias_add(AliasEntry(command=decl.name, alias=alias))
                    added_aliases.append(alias)
            elif decl.aliases:
                warnings.append(f"『{decl.name}』别名未装载（别名表不支持动态追加）")
    except Exception as exc:  # noqa: BLE001 —— 冲突/注册异常 → 整包回滚
        for alias in reversed(added_aliases):
            if alias_remove is not None:
                alias_remove(alias)
        for name in reversed(registered):
            router.unregister(name)
        raise PackExtDeclarationError(
            f"注册到 Router 失败（已回滚整包）：{type(exc).__name__}: {exc}"
        ) from exc

    _logger.info(
        "内容包『%s』扩展装载完成：指令 %s；别名 %s（%s）",
        pack_id, list(registered), added_aliases, f"ext_api v{EXT_API_VERSION}",
    )
    return PackExtResult(
        pack_id=pack_id,
        enabled=True,
        ok=True,
        registered=tuple(registered),
        aliases=tuple(added_aliases),
        warnings=tuple(warnings),
    )
