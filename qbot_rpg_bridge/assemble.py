"""M7 部署装配（qbot_rpg_bridge/assemble.py · 部署接线用 · 长期保留）。

用途：把 QBot-TurnTellerRPG 框架装配成可运行的 deps，注入 qbot_rpg_bridge.plugin
（NoneBot 启动时 on_startup 装配，或 CLI/测试直接 build_app_deps() 手动装配）。

设计依据：
  - qbot_rpg/assembly/bootstrap.py（AssembledApp 装配：loader→registry→GameWorld→world_state）
  - qbot_rpg/assembly/context.py（AssemblyDeps：repo/game_world/registry/settings/queue/...）
  - qbot_rpg/assembly/router_setup.py（build_router：全指令注册 + 配置装载）
  - qbot_rpg/commands/processing.py（PerPlayerQueue(repo)）
  - qbot_rpg/commands/runner.py（run_command 消费 deps.router/queue/permission_store/...）

配置（环境变量）：
  - QBotRPG_PACK_DIR  内容包目录（manifest.json 所在；缺省仓库 content/demo_lv15）
  - QBotRPG_DB_PATH   存档 SQLite 路径（缺省仓库 data/qbot_rpg.db）
  - QBotRPG_SEASON / QBotRPG_PERIOD / QBotRPG_WEATHER 可选环境快照固定值覆盖
    （worldtime 未配置时用固定季节/时段/天气；缺省 秋/黄昏/晴）

NoneBot 接线：register_startup() 在插件加载时注册 on_startup → build_app_deps()；
无 nonebot 环境（CLI/测试）→ build_app_deps() 可独立调用（纯装配）。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Mapping, Optional

from qbot_rpg.assembly.bootstrap import bootstrap
from qbot_rpg.assembly.context import AssemblyDeps
from qbot_rpg.assembly.router_setup import build_router
from qbot_rpg.commands.processing import PerPlayerQueue
from qbot_rpg.engine.worldtime import WorldTime
from qbot_rpg.storage.connection import Database
from qbot_rpg.storage.repository import Repository

__all__ = [
    "DEFAULT_PACK_NAME",
    "build_app_deps",
    "register_startup",
    "resolve_pack_dir",
    "resolve_db_path",
]

# 缺省内容包（仓库 content/ 下；部署时用 QBotRPG_PACK_DIR 覆盖）
DEFAULT_PACK_NAME = "demo_lv15"

# 缺省环境快照（worldtime 未配置时；QBotRPG_SEASON/PERIOD/WEATHER 可覆盖）
_DEF_SEASON = "秋"
_DEF_PERIOD = "黄昏"
_DEF_WEATHER = "晴"


def _repo_root() -> Path:
    """仓库根（本文件在 qbot_rpg_bridge/ 下）。"""
    return Path(__file__).resolve().parent.parent


def resolve_pack_dir(pack_dir: Optional[str] = None) -> Path:
    """内容包目录：入参优先 → 环境变量 QBotRPG_PACK_DIR → 仓库 content/demo_lv15。"""
    if pack_dir:
        p = Path(pack_dir)
    else:
        env = os.environ.get("QBotRPG_PACK_DIR")
        p = Path(env) if env else _repo_root() / "content" / DEFAULT_PACK_NAME
    if not p.is_dir():
        raise FileNotFoundError(f"内容包目录不存在：{p}")
    return p


def resolve_db_path(db_path: Optional[str] = None) -> Path:
    """数据库路径：入参优先 → 环境变量 QBotRPG_DB_PATH → 仓库 data/qbot_rpg.db。"""
    if db_path:
        return Path(db_path)
    env = os.environ.get("QBotRPG_DB_PATH")
    if env:
        return Path(env)
    d = _repo_root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "qbot_rpg.db"


def _load_settings(pack_dir: Path) -> Mapping[str, Any]:
    """包内 settings.json 装载（缺省 {}）。"""
    p = pack_dir / "settings.json"
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _env_snapshot() -> tuple:
    """环境快照：QBotRPG_SEASON/PERIOD/WEATHER 覆盖，缺省 秋/黄昏/晴。"""
    season = os.environ.get("QBotRPG_SEASON") or _DEF_SEASON
    period = os.environ.get("QBotRPG_PERIOD") or _DEF_PERIOD
    weather = os.environ.get("QBotRPG_WEATHER") or _DEF_WEATHER
    return season, period, weather


def _make_time_queries(wt: Optional[WorldTime], settings: Mapping[str, Any]):
    """time_query/weather_query 闭包：worldtime 优先，缺省固定快照。

    make_context 以无参调用（context.py L601/L611 _safe_call），故闭包均为无参；
    worldtime 模式的天气查询用 default_map（或空 map_id）取当前天气。
    """
    def_map = str(settings.get("default_map") or "")
    if wt is not None and wt.is_enabled():
        def _tq() -> tuple:
            try:
                return (str(wt.season_now()), str(wt.period_now()))
            except Exception:  # noqa: BLE001
                s, p, _ = _env_snapshot()
                return (s, p)
        def _wq() -> str:
            try:
                return str(wt.weather_now(def_map))
            except Exception:  # noqa: BLE001
                _, _, w = _env_snapshot()
                return w
        return _tq, _wq
    s, p, w = _env_snapshot()
    return (lambda: (s, p)), (lambda: w)


async def build_app_deps(
    *,
    pack_dir: Optional[str] = None,
    db_path: Optional[str] = None,
    settings: Optional[Mapping[str, Any]] = None,
) -> Any:
    """完整装配：bootstrap → AssembledApp → AssemblyDeps + router + 鸭式字段 → set_deps。

    入参 pack_dir/db_path: 内容包目录与数据库路径（见 resolve_*）；settings: 覆盖。
    出参 deps: AssemblyDeps（含 router/queue/permission_store 等，run_command 消费）；
    并注入 qbot_rpg_bridge.plugin.set_deps（on_message 处理器读取）。
    核心逻辑: Database→Repository→bootstrap→AssemblyDeps→build_router→鸭式字段→set_deps。
    """
    pd = resolve_pack_dir(pack_dir)
    dpath = resolve_db_path(db_path)
    settings_map = _load_settings(pd)
    if settings:
        settings_map = {**settings_map, **settings}
    dpath.parent.mkdir(parents=True, exist_ok=True)
    db = Database(str(dpath))
    repo = Repository(db)
    app = await bootstrap({"pack_dir": str(pd), "repo": repo})
    # worldtime 环境快照（settings 无 worldtime 段 → 固定快照）
    wt_cfg = settings_map.get("worldtime")
    wt = WorldTime(wt_cfg) if isinstance(wt_cfg, Mapping) else WorldTime()
    tq, wq = _make_time_queries(wt, settings_map)
    queue = PerPlayerQueue(repo)
    deps = AssemblyDeps(
        repo=repo,
        game_world=app.game_world,
        registry=app.registry,
        settings=settings_map,
        queue=queue,
        session_mgr=app.session_mgr,
        time_query=tq,
        weather_query=wq,
    )
    # 鸭式字段（run_command 消费；GM 后端归 M12，permission/audit 暂 None）
    deps.router = build_router(deps)  # type: ignore[attr-defined]
    deps.permission_store = None  # type: ignore[attr-defined]
    deps.audit_store = None  # type: ignore[attr-defined]
    deps.audit_hmac_key = None  # type: ignore[attr-defined]
    deps.queue_timeout = None  # type: ignore[attr-defined]

    from qbot_rpg_bridge.plugin import set_deps

    set_deps(deps)
    return deps


# ---------------------------------------------------------------------------
# NoneBot 启动接线（on_startup 装配；无 nonebot 环境 → build_app_deps 独立可用）
# ---------------------------------------------------------------------------
try:  # pragma: no cover —— 无 NoneBot 环境安全跳过
    from nonebot import get_driver  # type: ignore[import-not-found]

    _HAS_NONEBOT = True
except ImportError:  # pragma: no cover
    get_driver = None
    _HAS_NONEBOT = False


def register_startup() -> None:
    """NoneBot on_startup 注册：启动时 build_app_deps() 装配 + set_deps 注入。"""
    if not _HAS_NONEBOT:
        return  # 无 nonebot 环境：CLI/测试手动 build_app_deps()
    assert get_driver is not None  # _HAS_NONEBOT 保证；类型收窄供静态检查
    driver = get_driver()

    @driver.on_startup
    async def _assemble() -> None:  # noqa: ANN202
        await build_app_deps()


if __name__ == "__main__":
    asyncio.run(build_app_deps())
    print("装配完成：build_app_deps() 已注入 qbot_rpg_bridge.plugin")
    # Database 读连接池线程为非 daemon（部署时进程常驻 OK）；CLI 冒烟强制退出
    os._exit(0)  # noqa: PLR1722
