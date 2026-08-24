"""内容包加载器：A→B→C→D 五段管线（细化_3e §1.1），阻断式抛错（D-01/D-02/D-06）。

依据：
  - 细化_3e_loader校验接线 §1.2（manifest 硬约束：必填字段 / 声明才加载 / 声明缺失=黄提示 Y-6 继续）
  - 细化_3e_loader校验接线 §1.3（注册顺序 effects→statuses→marks→skill_chains→action→其余，L136）
  - 细化_3e_loader校验接线 §1.5（D 挂载：仅 report.ok 时构建 registry；原子引用替换由上层/HotReloadWatcher 负责）
  - 细化_3e_loader校验接线 §1.6（load_pack 整体走 asyncio.to_thread，>50ms 禁止阻塞事件循环，D-05）
  - 细化_3e_loader校验接线 §1.7（PackLoadError 领域异常携带结构化 errors，人话由 commands 层翻译）
  - 细化_3e2_热重载契约 TRG-3（mtime 增量：未变更模块复用解析结果，引用存在性仍全量重跑）

零 NoneBot；仅依赖 qbot_rpg.content.models/validator/registry/field_meta + qbot_rpg.data.types。
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.models import (
    BaseDef,
    DEF_CLASSES,
    FieldMetaTable,
    Manifest,
    Pack,
    PackError,
    PackWarning,
    ValidationReport,
)
from qbot_rpg.content.registry import Registry
from qbot_rpg.content.validator import check_pack

# -------------------------------------------------------------------------------------
# 模块注册顺序（细化_3e §1.3：顺序即依赖；效果家族先注册，供 traits/items/skills/enemies 引用）
# -------------------------------------------------------------------------------------
FIXED_REGISTER_ORDER: Tuple[str, ...] = ("effects", "statuses", "marks", "skill_chains", "action")


class PackLoadError(Exception):
    """阻断式聚合异常：任一红拦 → 整包拒绝挂载，携带全量 errors（D-01/D-02/D-06）。

    人话文案由 commands 层按 PackError.detail 结构化参数翻译（禁止 loader 拼用户体验文案）。
    """

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        self.errors: Tuple[PackError, ...] = report.errors
        super().__init__(f"pack load blocked by {len(report.errors)} red-block error(s)")

    @property
    def pack_errors(self) -> Tuple[PackError, ...]:
        return self.errors


def file_signature(path: Path) -> Optional[Tuple[int, int, str]]:
    """mtime(ns) + size + sha256 三重签名（细化_3e2 TRG-2：mtime 快筛 / 哈希防伪造/同秒覆盖）。

    文件不存在返回 None；内容变更（哈希兜底 mtime 精度不足）会改变签名。
    """
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, h.hexdigest())


def _ordered_declared(declared: List[str]) -> List[str]:
    """注册顺序：固定优先序 ∩ 声明集合 → 其余按声明顺序（细化_3e §1.3）。"""
    result: List[str] = []
    for m in FIXED_REGISTER_ORDER:
        if m in declared:
            result.append(m)
    for m in declared:
        if m not in result:
            result.append(m)
    return result


def _build_registry(
    pack_id: str,
    manifest: Manifest,
    modules: Mapping[str, object],
    generation: int,
) -> Registry:
    """D 阶段：从校验通过的数据整体构建新 registry（独立对象，D-02/D-03）。"""
    tables: Dict[str, Dict[str, object]] = {}
    names: Dict[str, str] = {}
    for module_name in _ordered_declared(list(manifest.modules)):
        data = modules.get(module_name)
        if data is None:
            continue
        if isinstance(data, list):
            for idx, entry in enumerate(data):
                if not isinstance(entry, Mapping):
                    continue
                eid = str(entry.get("id", ""))
                if not eid:
                    continue
                _register_def(tables, names, module_name, eid, entry)
        elif isinstance(data, Mapping) and module_name in ("stats", "formula"):
            # map 形态模块：键 = ID
            for eid, value in data.items():
                _register_def(tables, names, module_name, str(eid), value)
    return Registry.build(
        pack_id=pack_id,
        generation=generation,
        tables=tables,
        names=names,
        modules_raw=copy.deepcopy(dict(modules)),
        manifest=manifest,
    )


def _register_def(
    tables: Dict[str, Dict[str, object]],
    names: Dict[str, str],
    module_name: str,
    eid: str,
    entry: object,
) -> None:
    kind = _KIND_FOR_MODULE.get(module_name, module_name)
    cls = DEF_CLASSES.get(kind, BaseDef)
    if isinstance(entry, Mapping):
        # P1-3：显式传 eid（map 形态键 = ID 时值对象无 id 键，否则 Def.id 空串）
        d = cls.from_entry(entry, id_override=eid)  # id/name/raw 深拷贝
    else:
        d = BaseDef(id=eid, name=eid, raw={"_expr": copy.deepcopy(entry)})  # formula 字符串值等
    tables.setdefault(kind, {})[eid] = d
    names[eid] = d.name


# 模块 → 注册表 kind（细化_3e §5.2 / 细化_3a §4.2：效果注册表三表统一/行动注册表/派生链注册表）
_KIND_FOR_MODULE: Mapping[str, str] = {
    "effects": "effect",
    "statuses": "status",
    "marks": "mark",
    "skill_chains": "skill_chain",
    "action": "action",
    "items": "item",
    "equipment": "equipment",
    "traits": "trait",
    "enemies": "enemy",
    "maps": "map",
    "stats": "stat",
    "npc": "npc",
    "formula": "formula",
    "conditional": "conditional",  # 条件加成规则（细化_3b §3.2）
}


# -------------------------------------------------------------------------------------
# 构建核心（可被 load_pack 与热重载复用；增量缓存在此生效）
# -------------------------------------------------------------------------------------
def build_pack(
    pack_dir: Path,
    meta: Optional[FieldMetaTable] = None,
    parse_cache: Optional[Dict[str, Dict[str, object]]] = None,
    generation: int = 1,
) -> Tuple[Pack, Tuple[str, ...]]:
    """五段管线 A→B→C→D 同步实现。

    parse_cache（可选，热重载 TRG-3）：module -> {"sig": signature, "data": parsed}；
    mtime/size/hash 未变的模块复用解析结果，不改动则跳过 IO/解析；
    整包校验仍全量重跑（引用关系跨模块，跳过会漏悬空引用）。
    返回 (Pack, changed_modules)；任一红拦抛 PackLoadError（携带全量 errors）。
    """
    pack_dir = Path(pack_dir)
    cache = parse_cache if parse_cache is not None else {}
    changed: List[str] = []
    errors: List[PackError] = []
    warnings: List[PackWarning] = []

    # ---- A 阶段：manifest（细化_3e §1.2；缺文件 = 整包不可用直接阻断）----
    manifest_path = pack_dir / "manifest.json"
    manifest_sig = file_signature(manifest_path)
    if manifest_sig is None:
        errors.append(PackError("manifest", "manifest.json", "R-5",
                                dict(rule="manifest_missing")))
        return _raise_if_blocked(ValidationReport(errors=tuple(errors), warnings=tuple(warnings)))
    try:
        manifest_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        errors.append(PackError("manifest", "manifest.json", "R-5",
                                dict(rule="manifest_invalid_json", error=str(e))))
        return _raise_if_blocked(ValidationReport(errors=tuple(errors), warnings=tuple(warnings)))

    # manifest 自身结构校验（P1-2：顶层非 Mapping 直接报 R-5 module_structure 并早停，
    # 防 Manifest.from_dict 抛 AttributeError 绕过 PackLoadError 错误模型）。
    # P1-1：不再对 manifest 做独立 check_pack + errors.extend——C 阶段全量校验已含
    # manifest（validator._ordered_defined_modules 会再校验一次），提前校验会造成
    # 同一批 manifest 红拦在 combined.errors 重复上报（破坏 D-01「一次给全量」）。
    if not isinstance(manifest_raw, Mapping):
        manifest_check = check_pack({"manifest": manifest_raw},
                                    meta or default_field_meta_table())
        _raise_if_blocked(ValidationReport(errors=manifest_check.errors,
                                           warnings=manifest_check.warnings))
    manifest = Manifest.from_dict(manifest_raw)

    # ---- B 阶段：按声明顺序 + 注册顺序加载（缺失文件 → Y-6 继续；未声明文件不加载）----
    modules: Dict[str, object] = {}
    declared = list(manifest.modules)
    for module_name in _ordered_declared(declared):
        mpath = pack_dir / f"{module_name}.json"
        sig = file_signature(mpath)
        if sig is None:
            # 声明但缺失：不拒绝，旧包照常玩（细化_3e §1.2 / Y-6）
            warnings.append(PackWarning(module_name, f"{module_name}.json", "Y-6",
                                        dict(rule="module_missing", module=module_name)))
            cache.pop(module_name, None)
            continue
        cached = cache.get(module_name)
        if cached is not None and cached.get("sig") == sig:
            modules[module_name] = cached["data"]  # mtime 未变：复用解析结果（TRG-3）
            continue
        try:
            parsed = json.loads(mpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            # 单模块 JSON 语法坏 → R-5，继续收全量（TC-01 语义：整包阻断但一次给全）
            errors.append(PackError(module_name, f"{module_name}.json", "R-5",
                                    dict(rule="invalid_json", module=module_name, error=str(e))))
            cache.pop(module_name, None)
            changed.append(module_name)
            continue
        modules[module_name] = parsed
        cache[module_name] = {"sig": sig, "data": parsed}
        changed.append(module_name)

    # ---- C 阶段：全量校验（黄提示 Y-6 合并；任一红拦阻断）----
    modules["manifest"] = manifest_raw
    report = check_pack(modules, meta or default_field_meta_table())
    combined = ValidationReport(
        errors=tuple(errors) + report.errors,
        warnings=tuple(warnings) + report.warnings,
    )
    if not combined.ok:
        _raise_if_blocked(combined)

    # ---- D 阶段：挂载构建 registry（仅 report.ok，D-02）----
    registry = _build_registry(pack_dir.name, manifest, modules, generation)
    return (
        Pack(pack_id=pack_dir.name, manifest=manifest, modules=modules, report=combined,
             registry=registry),
        tuple(changed),
    )


def _raise_if_blocked(report: ValidationReport) -> Tuple[Pack, Tuple[str, ...]]:
    """工具函数：errors 非空 → 抛 PackLoadError；否则返回占位（实际不会走到）。"""
    if not report.ok:
        raise PackLoadError(report)
    raise AssertionError("_raise_if_blocked called with ok report")  # pragma: no cover


# -------------------------------------------------------------------------------------
# 异步公共入口（细化_3e §5.1 接口）
# -------------------------------------------------------------------------------------
async def load_pack(
    pack_dir: Path, meta: Optional[FieldMetaTable] = None, generation: int = 1
) -> Pack:
    """A→B→C→D 全流程（to_thread 内执行，§1.6 D-05）；report.errors 非空 → 抛 PackLoadError。

    返回挂载完成的 Pack（含 registry）。
    """
    meta_t = meta if meta is not None else default_field_meta_table()
    pack, _changed = await asyncio.to_thread(build_pack, Path(pack_dir), meta_t, None, generation)
    return pack


__all__ = ["PackLoadError", "load_pack", "build_pack", "file_signature", "FIXED_REGISTER_ORDER"]
