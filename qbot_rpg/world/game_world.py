"""全局世界 GameWorld（M3 实装 · 本里程碑结构签名 + 怪物池/野图 BOSS 实装）。

职责（细化_3a §2.1 / §1.2）：地图（细化_2a1a~2a1d）、怪物池（细化_1e 八段 schema）、
野图 BOSS、全体限购（world_stock，细化_4a §1.3）——key=全局，不区分群（3a D-06）。
刷新/补刷见 world/spawn.py（M3）与 world/spawn_weather.py（M3 批次4·路M：天气权重）；会话互斥见
world/session.py（M1/M4）。

M3 实装依据：细化_2a1a_地图schema字段 / 细化_2a1b_通道规则与刷怪 / 细化_2a1c_地图副本衔接 /
细化_2a1d_地图字段扩展 / 细化_2a2_换区追击流程 / 细化_2a3_副本两型流程 / 细化_2b1（发牌员）。
本文件实装（批次4·路M 收口）：
  - monster_pool(map_id)：读该图 spawn 表（注入 maps）→ 过滤当前可出没行（调 spawn 过滤：
    注入 spawn_manager.filter_eligible 优先，缺省 world/spawn_weather.filter_eligible_rows）
    → 返回在场怪物列表（注入 spawn_manager.alive_monsters 优先）；未注入 spawn 管理 → 空
    【工程补白：存储/调度接线由 M4/M6 后续】。
  - get_boss(map_id)：读 maps gate_guard（contract §2.1 / 2a1a §1.7 守门怪）。
WorldState 唯一落点 data/world_state.py（3a D-03），本层只经 storage/repository 读写。

零 NoneBot import（3a R1），不拼用户文案（R4：抛领域异常由壳层翻译）。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, cast

from qbot_rpg.content.map_models import MapDef, parse_maps
from qbot_rpg.world.spawn_weather import _enemy_of, filter_eligible_rows

__all__ = ["GameWorld", "WorldNotFoundError"]

_NOT_IMPL_MSG = "M3 实装：全局世界（细化_2a / 细化_2b）"


class WorldNotFoundError(Exception):
    """地图/世界资源不存在（领域异常，壳层 errors.py 翻译人话；3a R4）。"""


def _index_maps(maps: Any) -> Dict[str, MapDef]:
    """归一注入的 maps 数据 → {map_id: MapDef}；未注入/形态异常 → 空表。

    兼容三种注入形态：
      - {"maps": [...]} modules dict（parse_maps）；
      - {map_id: MapDef | raw dict} 映射；
      - [MapDef | raw dict] 列表/元组。
    零 IO、纯内存归一（M4 接线后可由 storage/repository 提供同一容器）。
    """
    if maps is None:
        return {}
    if isinstance(maps, Mapping):
        inner = maps.get("maps")
        if isinstance(inner, list):  # modules dict 形态
            return {m.id: m for m in parse_maps(maps) if m.id}
        out: Dict[str, MapDef] = {}
        for k, v in maps.items():
            if isinstance(v, MapDef):
                out[v.id or str(k)] = v
            elif isinstance(v, Mapping):
                raw = dict(v)
                if not raw.get("id"):
                    raw["id"] = str(k)
                out[str(k)] = cast(MapDef, MapDef.from_entry(raw))
        return out
    if isinstance(maps, (list, tuple)):
        out = {}
        for v in maps:
            if isinstance(v, MapDef):
                if v.id:
                    out[v.id] = v
            elif isinstance(v, Mapping):
                m = cast(MapDef, MapDef.from_entry(dict(v)))
                if m.id:
                    out[m.id] = m
        return out
    return {}


class GameWorld:
    """全局世界状态（地图/怪物池/野图 BOSS/全体限购；key=全局）。M3 实装。

    monster_pool / get_boss 为本里程碑实装（批次4·路M）；其余方法预留签名（get_map/
    move_to_map/限购/持久化由后续批次 + M4/M6 接线）。
    """

    def __init__(
        self,
        maps: Any = None,
        spawn_manager: Any = None,
        ctx_provider: Any = None,
    ) -> None:
        """依赖注入（M4/M6 接线前由调用方注入，零硬编码绝对路径）：

        - maps: 地图数据容器（MapDef 列表 / {id: def|raw} 映射 / {"maps":[...]} modules dict；
          见 _index_maps）。
        - spawn_manager: 路L SpawnManager 契约（鸭子类型）——filter_eligible(spawn_rows, ctx)
          出没过滤 + alive_monsters(map_id) 在场面查询；未注入 → monster_pool 返回空。
        - ctx_provider: callable(map_id) -> {"season","period","weather","now"} 出没上下文
          （M38 天气按图取值 / M32 季节时段，收口时接 engine/worldtime）。
        """
        self._initialized = False
        self._maps: Dict[str, MapDef] = _index_maps(maps)
        self._spawn_manager: Any = spawn_manager
        self._ctx_provider: Any = ctx_provider

    # -- 内部工具 ------------------------------------------------------------
    def _map(self, map_id: str) -> Optional[MapDef]:
        """按 ID 取地图定义；非法/未知 → None（约定空值，壳层翻译）。"""
        if not isinstance(map_id, str) or not map_id:
            return None
        return self._maps.get(map_id)

    def _spawn_ctx(self, map_id: str) -> Mapping[str, object]:
        """出没上下文（R31/R32：季节/时段全局值、天气按当前图）；提供方异常 → 缺省恒真。"""
        if callable(self._ctx_provider):
            try:
                c = self._ctx_provider(map_id)
                if isinstance(c, Mapping):
                    return dict(c)
            except Exception:
                pass  # 提供方异常 → 缺省上下文（season/period/weather 缺省恒真）
        return {}

    def _filter_spawn_rows(self, m: MapDef, map_id: str) -> List[object]:
        """过滤当前可出没 spawn 行（2a1b R27 全 AND）：调 spawn 过滤。

        注入 spawn_manager.filter_eligible 优先（路L 收口契约，细化_2a4c §3.1 S1）：
          filter_eligible(spawn_row, now) -> bool —— 逐行调用（now 取 spawn 上下文）；
        签名异常/未注入 → 兜底本地 world/spawn_weather.filter_eligible_rows（纯逻辑）。
        """
        rows: Tuple[object, ...] = m.spawn_defs()
        ctx = self._spawn_ctx(map_id)
        fil = getattr(self._spawn_manager, "filter_eligible", None)
        if not callable(fil):
            return filter_eligible_rows(rows, ctx)
        now = ctx.get("now")
        try:
            return [r for r in rows if bool(fil(r, now))]
        except TypeError:
            # 注入方签名与契约不符 → 兜底本地纯逻辑过滤（收口防御）
            return filter_eligible_rows(rows, ctx)

    # -- 地图 -------------------------------------------------------------
    def get_map(self, map_id: str) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def list_maps(self) -> List[Any]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def move_to_map(self, player: Any, map_id: str) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # -- 怪物池 / 野图 BOSS（批次4·路M 实装） ----------------------------------
    def monster_pool(self, map_id: str) -> List[Any]:
        """该图当前在场怪物列表（M3 实装 · 批次4·路M）。

        流程：读该图 spawn 表（注入 maps）→ 过滤当前可出没行（调 spawn 过滤，2a1b R27）
        → 返回在场怪物（注入 spawn_manager.alive_monsters 优先；未提供在场面查询 →
        按可出没行返回占位条目 {enemy, alive}，在场数由存储层 M4 提供）。

        未知地图 / 未注入 spawn 管理 → 空列表（约定值）
        【工程补白：存储/调度接线（world_state.spawn_timers 落盘、alive_monsters 实现）
        由 M4/M6 后续】。
        """
        m = self._map(map_id)
        if m is None or self._spawn_manager is None:
            return []
        eligible = self._filter_spawn_rows(m, map_id)
        alive_fn = getattr(self._spawn_manager, "alive_monsters", None)
        if callable(alive_fn):
            return list(cast(Iterable[Any], alive_fn(map_id)))
        # 管理器未提供在场面查询 → 按可出没行返回占位条目【工程补白】
        return [{"enemy": _enemy_of(r), "alive": 0} for r in eligible]

    def get_boss(self, map_id: str) -> Optional[Any]:
        """该图守门怪（maps.json gate_guard，contract §2.1 / 2a1a §1.7）。未知地图 → None。"""
        m = self._map(map_id)
        if m is None:
            return None
        return m.gate_guard

    def is_boss_alive(self, map_id: str) -> bool:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # -- 全体限购（world_stock） --------------------------------------------
    def world_stock(self, key: str) -> int:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def try_consume_world_stock(self, key: str, count: int) -> bool:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # -- 世界状态持久化（经 storage/repository 注入，M3） --------------------
    def load(self, world_state: Any) -> None:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def to_world_state(self) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def list_stores(self) -> List[Any]:
        """运营商店铺目录（细化_5a 编辑器/运营页只读，M-y 实装；预留签名）。"""
        raise NotImplementedError(_NOT_IMPL_MSG)
