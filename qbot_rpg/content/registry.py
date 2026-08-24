"""内容包注册表：ID 全局唯一注册 / 引用 O(1) 查询 / 快照-回退 / 原子引用替换（双快照由 HotReloadWatcher 维护 N=2）。

依据：
  - 细化_3e_loader校验接线 §1.3（效果家族 effects→statuses→marks 先注册，L136）
  - 细化_3e_loader校验接线 §1.5（D 阶段挂载：整体构建后一次性替换内存引用，期间旧引用继续服务，L175）
  - 细化_3e_loader校验接线 §5.1（snapshot()/restore(snap)/resolve(id,kind) 接口）
  - 细化_3e2_热重载契约 D-03（指针级原子替换）、D-04（快照 N=2 档）、SNAP-1/SNAP-4（快照内容 = 完整注册表 + 名称冗余）
  - 细化_3e2_热重载契约 OLD-2（ID+名称冗余，防热重载失效；resolve_name 供对局快照构建）
  - 细化_3a_架构分层契约 §4.2 line 254（效果注册表三表统一 / 行动注册表 / 派生链注册表）

零 NoneBot；仅依赖 qbot_rpg.content.models / qbot_rpg.data.types。
"""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple

from qbot_rpg.content.models import Manifest

# Def 类型（Any 防 data/ 层 Agent 并行写码期间的循环引用；本模块不 import Def 具体类）
AnyDef = object


@dataclass(frozen=True)
class RegistrySnapshot:
    """校验通过的 registry 快照（热重载回退对象；包含完整注册表 + 名称冗余 + 原始数据）。

    细化_3e2 SNAP-4：快照 = 全部注册表 + 各模块原始数据 + schema_version / manifest 版本。
    表结构为不可变 Mapping，restore 时引用替换即原子（CPython 单引用写入）。
    """

    pack_id: str
    generation: int
    tables: Mapping[str, Mapping[str, AnyDef]]  # kind -> id -> Def
    names: Mapping[str, str]  # id -> 显示名（旧局旧配置名冗余，L177/L186）
    modules_raw: Mapping[str, object]  # 各模块原始数据（解析结果）
    manifest: Optional[Manifest] = None
    schema_version: Optional[int] = None


class Registry:
    """ID 全局唯一注册表。

    不变式：任何时刻 `self._tables` 指向一份完整校验通过的表集合（半套配置禁止，L178）。
    restore()/mount() 不允许直接改表内容，只做引用替换（单引用原子写）。
    """

    __slots__ = (
        "_pack_id",
        "_generation",
        "_tables",
        "_names",
        "_modules_raw",
        "_manifest",
        "_schema_version",
        "_lock",
    )

    def __init__(
        self,
        pack_id: str = "",
        generation: int = 0,
        tables: Optional[Mapping[str, Mapping[str, AnyDef]]] = None,
        names: Optional[Mapping[str, str]] = None,
        modules_raw: Optional[Mapping[str, object]] = None,
        manifest: Optional[Manifest] = None,
        schema_version: Optional[int] = None,
    ) -> None:
        self._pack_id = pack_id
        self._generation = generation
        self._tables: Mapping[str, Mapping[str, AnyDef]] = tables if tables is not None else {}
        self._names: Mapping[str, str] = names if names is not None else {}
        self._modules_raw: Mapping[str, object] = modules_raw if modules_raw is not None else {}
        self._manifest = manifest
        self._schema_version = schema_version
        self._lock = threading.Lock()

    # ---- 读路径（无锁：内存引用读取，原子替换保证一致性，细化_3e §4.6）----
    def resolve(self, id: str, kind: str) -> AnyDef:
        """引用查表（红拦 R-4 用，O(1) 字典）。kind 见 data/types.RegistryKind。"""
        return self._tables.get(kind, {}).get(id)  # type: ignore[misc]

    def resolve_name(self, id: str) -> Optional[str]:
        """ID → 显示名（旧局旧配置：对局快照冗余存储名称，重载后展示仍用旧名，L177/L186）。"""
        return self._names.get(id)

    def all_ids(self, kind: str) -> Tuple[str, ...]:
        return tuple(self._tables.get(kind, {}).keys())

    @property
    def pack_id(self) -> str:
        return self._pack_id

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def schema_version(self) -> Optional[int]:
        return self._schema_version

    @property
    def manifest(self) -> Optional[Manifest]:
        return self._manifest

    def contains(self, id: str) -> bool:
        """ID 是否在任一命名空间注册（跨表引用宽松查询）。"""
        for ids in self._tables.values():
            if id in ids:
                return True
        return False

    # ---- 快照 / 回退（细化_3e §5.1 / 细化_3e2 SNAP-1~3 / D-04）----
    def snapshot(self) -> RegistrySnapshot:
        """深拷贝当前生效 registry（热重载回退用）。"""
        with self._lock:
            return RegistrySnapshot(
                pack_id=self._pack_id,
                generation=self._generation,
                tables=copy.deepcopy(dict(self._tables)),
                names=copy.deepcopy(dict(self._names)),
                modules_raw=copy.deepcopy(dict(self._modules_raw)),
                manifest=self._manifest,
                schema_version=self._schema_version,
            )

    def restore(self, snap: RegistrySnapshot) -> None:
        """回退：用快照重建表集合后单引用原子替换（失败路径，热重载 §4.4）。

        单锁内完成构建 + 引用替换；替换动作在 CPython 为单引用写，读方（resolve）无 torn 状态。
        """
        with self._lock:
            new_tables = copy.deepcopy(dict(snap.tables))
            new_names = copy.deepcopy(dict(snap.names))
            new_raw = copy.deepcopy(dict(snap.modules_raw))
            self._pack_id = snap.pack_id
            self._generation = snap.generation
            self._schema_version = snap.schema_version
            self._manifest = snap.manifest
            self._tables = new_tables
            self._names = new_names
            self._modules_raw = new_raw

    @classmethod
    def from_snapshot(cls, snap: RegistrySnapshot) -> "Registry":
        """由快照重建全新 Registry 对象（指针级替换用，D-03）。"""
        reg = cls.__new__(cls)
        reg._pack_id = snap.pack_id
        reg._generation = snap.generation
        reg._tables = copy.deepcopy(dict(snap.tables))
        reg._names = copy.deepcopy(dict(snap.names))
        reg._modules_raw = copy.deepcopy(dict(snap.modules_raw))
        reg._manifest = snap.manifest
        reg._schema_version = snap.schema_version
        reg._lock = threading.Lock()
        return reg

    # ---- 构建（loader D 阶段调用）----
    @classmethod
    def build(
        cls,
        pack_id: str,
        generation: int,
        tables: Mapping[str, Mapping[str, AnyDef]],
        names: Mapping[str, str],
        modules_raw: Mapping[str, object],
        manifest: Optional[Manifest],
    ) -> "Registry":
        """整体构建新 registry（独立对象；校验通过后才调用，D-02）。"""
        return cls(
            pack_id=pack_id,
            generation=generation,
            tables=tables,
            names=names,
            modules_raw=modules_raw,
            manifest=manifest,
            schema_version=manifest.schema_version if manifest else None,
        )

    # ---- 一致性自检（细化_3e2 自检 A 子集）----
    def integrity_check(self) -> Optional[str]:
        """返回 None=通过；否则返回断言失败原因。热重载后必须通过。

        覆盖细化_3e2 自检 A（3e2 L215）可静态判定的两项：
          ① modules 声明 ⊇ 已加载模块（manifest 声明的模块必须都被构建进来）；
          ② schema_version 与 manifest 声明一致。
        名称冗余（OLD-2）已由 _names 检查。
        跨表 ID 唯一性（自检 A 第三项）由 validator 按 field_meta NAMESPACES
        前置拦截（validator._register_id），registry 侧不重复实现（防循环依赖）。
        P1-1（2026-08-24 M0 复查）：原实现 kind 内重复检查对 dict 恒不可达
        （dict 键天然唯一），已删除；补上述可判定断言。
        """
        # ① modules 声明 ⊇ 已加载（modules_raw 已含 manifest 键）
        if self._manifest is not None:
            declared = set(self._manifest.modules or ())
            loaded = {k for k in self._modules_raw if k != "manifest"}
            missing = declared - loaded
            if missing:
                return f"declared modules 未加载: {sorted(missing)!r}（自检 A）"
        # ② schema_version 一致
        if self._manifest is not None and self._schema_version != self._manifest.schema_version:
            return (
                f"schema_version 不一致: registry={self._schema_version}, "
                f"manifest={self._manifest.schema_version}（自检 A）"
            )
        # 名称冗余（OLD-2）：每个 id 必须有显示名
        for kind, ids in self._tables.items():
            for did in ids:
                names = self._names.get(did)
                if names is None:
                    return f"id {did!r} in kind {kind!r} has no redundant name"
        return None

    def __repr__(self) -> str:  # pragma: no cover
        kinds = ", ".join(f"{k}:{len(v)}" for k, v in self._tables.items())
        return f"<Registry pack={self._pack_id!r} gen={self._generation} {{{kinds}}}>"


__all__ = ["Registry", "RegistrySnapshot"]
