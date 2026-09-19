"""编辑器通用 CSV 导入 / 导出（编辑器批34 · 框架 §6.7 / §6.11 / §6.12-05 / §6.12-20）。

定位：**编排层**——CSV 纯编解码在 `qbot_rpg/content/csv_codec.py`；本层只负责
「读模块 → 编解码 → 逐行引用校验 → 冲突策略 → 行序插入 → 既有落盘链路」。

复用（不新开机制）：
  · 条目/字段元数据：`qbot_rpg/web/api.py`（`load_pack_modules` / `_module_meta` /
    `_entry_type` / `_display_labels` / `suggest_id`）；
  · 整包校验：`qbot_rpg/content/validator.py::check_pack`；
  · 引用 id 空间：`validator.collect_ref_id_space`（与 R-4 同一注册逻辑）；
  · 写盘：`qbot_rpg/content/atomic_store.py`（`backup_modules` → `write_modules` →
    `read_back_modules`）+ `editor_ops._verify_after_write`（回读复核 / 失败自动回退）。

口径（本批）：
  · 导出只读，不写内容包；UTF-8 带 BOM。
  · 导入行序 = CSV 行序；`mode=append` 追加末尾 / `mode=insert` + `position` 插入指定位置。
  · 逐行引用校验：引用型字段目标必须存在于**候选整包**（含本批新行）→ 缺失逐行报错，
    默认整批拒绝（不落半个文件、不生成备份）。
  · 冲突：同 id 已存在 → `on_conflict=skip`（默认）跳过并在报告列出 / `overwrite` 原地覆盖。
  · 公式注入：由纯编解码层中和（导出前置 `'`；导入裸危险文本中和后写包）。

铁律：零 NoneBot import；文件 IO 只在 atomic_store；不写死任何模块/字段业务名。
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from qbot_rpg.content import atomic_store, csv_codec
from qbot_rpg.content.csv_codec import (
    CsvCodecError,
    CsvSchema,
    DecodedRow,
    UnsupportedModuleError,
)
from qbot_rpg.content.models import FieldMetaTable
from qbot_rpg.content.validator import check_pack, collect_ref_id_space
from qbot_rpg.web import api, editor_ops
from qbot_rpg.web.editor_ops import ROLE_OWNER, _envelope, require_edit

# 导入模式 / 冲突策略（接口参数取值，写进响应供前端回显）。
MODE_APPEND = "append"
MODE_INSERT = "insert"
MODES: Tuple[str, ...] = (MODE_APPEND, MODE_INSERT)
CONFLICT_SKIP = "skip"
CONFLICT_OVERWRITE = "overwrite"
CONFLICTS: Tuple[str, ...] = (CONFLICT_SKIP, CONFLICT_OVERWRITE)
# 导入编码自动检测顺序（§6.11：Excel/WPS 默认 GBK）。utf-8-sig 同时覆盖「无 BOM 的 UTF-8」。
_IMPORT_ENCODINGS: Tuple[str, ...] = ("utf-8-sig", "gb18030")
_FILENAME_SAFE = re.compile(r"[^0-9A-Za-z_.\-]+")


# =====================================================================================
# 小工具
# =====================================================================================
def decode_bytes(raw: object) -> Tuple[str, str]:
    """导入原始字节/文本 → (CSV 文本, 采用编码)。UTF-8(BOM) 优先，回落 GBK(GB18030)。

    编码全不可识别 → `api.BadRequest`（人话提示「另存为 UTF-8」），绝不猜测后丢弃字节。
    """
    if isinstance(raw, str):
        return raw, "utf-8"
    if not isinstance(raw, (bytes, bytearray)):
        raise api.BadRequest("导入内容形态非法（应为 CSV 文件字节）。")
    data = bytes(raw)
    for enc in _IMPORT_ENCODINGS:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise api.BadRequest(
        "CSV 文件编码无法识别（支持 UTF-8 与 GBK）；请在表格软件里另存为 UTF-8 后重试。")


def _module_label(pack_dir: object, manifest: Mapping[str, Any], declared: Sequence[str],
                  module: str) -> str:
    try:
        labels = api._display_labels(manifest, list(declared), pack_dir)
    except Exception:
        labels = {}
    return str(labels.get(module) or module)


def export_filename(pack: object, module: object) -> str:
    """下载文件名（包名 + 模块键；ASCII 安全化，不写死任何业务名）。"""
    safe = _FILENAME_SAFE.sub("_", f"{pack}-{module}") or "module"
    return f"{safe}.csv"


def _entry_extra_keys(etype: str, data: object, schema: CsvSchema) -> List[str]:
    """包数据里出现、元数据未登记的键（决定 extra 列；导出/导入各算一次）。"""
    known = {c.key for c in schema.columns}
    out: List[str] = []
    seen = set()

    def _add(key: object) -> None:
        k = str(key)
        if k in known or k in seen:
            return
        seen.add(k)
        out.append(k)

    if etype == "list" and isinstance(data, list):
        for elem in data:
            if isinstance(elem, Mapping):
                for k in elem:
                    _add(k)
    elif etype == "map_obj" and isinstance(data, Mapping):
        for val in data.values():
            if isinstance(val, Mapping):
                for k in val:
                    _add(k)
    return out


def _module_and_schema(pack: object, module: object, root: Optional[object]):
    """(pack_dir, modules_raw, module, mmeta, etype, data) 只读装配（校验器同源）。"""
    pack_dir, modules_raw = api.load_pack_modules(pack, root)
    mod = api.declared_module(pack, module, root=root)
    mmeta = api._module_meta(mod, pack_dir)
    data = modules_raw.get(mod)
    etype = api._entry_type(mmeta, data)
    return pack_dir, modules_raw, mod, mmeta, etype, data


def _unsupported(module: object, etype: object) -> Dict[str, Any]:
    env = _envelope(phase="csv", pack="", module=str(module), level="red")
    env.update(ok=False, errors=[{
        "level": "red", "code": "csv_module_unsupported", "module": str(module),
        "field": "", "field_key": "", "field_label": "（模块形态）",
        "message": (f"模块「{module}」是「{etype}」形态，没有「每行一条条目」的概念，"
                    "本版 CSV 只支持列表 / 映射形态模块。"),
        "how_to_fix": "单对象模块（如全局设置）请继续用表单编辑；本批不做对象形态 CSV。",
    }], message=f"模块「{module}」不支持 CSV 导入导出。")
    return env


# =====================================================================================
# 导出（只读，不写内容包）
# =====================================================================================
def export_csv(pack: object, module: object, *,
               root: Optional[object] = None) -> Dict[str, Any]:
    """模块 → CSV 文本（含 BOM）；行序 = 内容包里的条目顺序。**绝不写盘**。"""
    pack_dir, modules_raw, mod, mmeta, etype, data = _module_and_schema(pack, module, root)
    if etype not in ("list", "map"):
        env = _unsupported(mod, etype)
        env["pack"] = str(pack)
        return env
    base_schema = csv_codec.schema_for(mmeta, entry_type=etype)
    extras = _entry_extra_keys(etype, data, base_schema)
    schema = csv_codec.schema_for(mmeta, entry_type=etype, extra_keys=extras)

    entries: List[Tuple[str, object]] = []
    if etype == "list":
        for i, elem in enumerate(data if isinstance(data, list) else []):
            eid = elem.get(schema.key_field) if isinstance(elem, Mapping) else None
            key = eid if isinstance(eid, str) and eid else f"#{i}"
            entries.append((key, elem))
    else:
        for key, val in (data if isinstance(data, Mapping) else {}).items():
            entries.append((str(key), val))

    text = csv_codec.encode_csv(schema, entries)
    manifest = api._manifest(pack_dir)
    declared = api._declared_modules(manifest)
    return {
        "ok": True, "phase": "export_csv", "pack": str(pack), "module": mod,
        "module_label": _module_label(pack_dir, manifest, declared, mod),
        "filename": export_filename(pack, mod),
        "text": text, "encoding": "utf-8-sig",
        "count": len(entries), "columns": schema.header_cells(),
        "extra_columns": list(extras),
        "message": f"已导出 {len(entries)} 条（{len(schema.columns)} 列，UTF-8 带 BOM）。",
    }


# =====================================================================================
# 导入：逐行引用校验
# =====================================================================================
def _collect_refs(value: object, col: csv_codec.Column, path: str,
                  out: List[Tuple[str, str, str]]) -> None:
    """按列元数据下钻，收集 (字段路径, 引用目标, 引用 id)。通用，不认业务字段名。"""
    if col is None:
        return
    if col.type == "ref":
        if isinstance(value, str) and value:
            out.append((path, str(col.ref_target or ""), value))
        return
    if col.type == "list" and col.element is not None and isinstance(value, list):
        for i, elem in enumerate(value):
            _collect_refs(elem, col.element, f"{path}.{i}", out)
        return
    if col.type == "obj" and isinstance(value, Mapping):
        for child in col.children:
            if child.key in value:
                _collect_refs(value[child.key], child, f"{path}.{child.key}", out)


def _ref_missing(id_space: Mapping[str, Mapping[str, str]],
                 target: str, ref_id: str) -> bool:
    """引用是否缺失（与校验器 `_check_ref` 同口径）：`stat` 走 Y-7（不当硬缺失）。"""
    if not target:
        return False
    if target == "skill_or_any":
        return not any(ref_id in ids for ids in id_space.values())
    if target.endswith("_or_any"):
        target = target[: -len("_or_any")]
    ids = id_space.get(target, {})
    return ref_id not in ids


def _walk_row_refs(row: DecodedRow, schema: CsvSchema) -> List[Tuple[str, str, str]]:
    if schema.value_mode == "map_scalar":
        return []
    entry = row.entry(schema)
    if not isinstance(entry, Mapping):
        return []
    cols = [c for c in schema.columns if not c.is_key]
    out: List[Tuple[str, str, str]] = []
    for col in cols:
        if col.key in entry:
            _collect_refs(entry[col.key], col, col.key, out)
    return out


def _ref_row_error(row: DecodedRow, path: str, target: str, ref_id: str,
                   schema: CsvSchema) -> Dict[str, Any]:
    top = path.split(".", 1)[0]
    col = schema.column(top)
    label = (col.label if col is not None and col.label else top)
    return {
        "level": "red", "code": "csv_ref_missing", "module": schema.module,
        "line": row.line, "row": row.line - 1, "entry_id": row.key,
        "field": path, "field_key": top, "field_label": label,
        "target": target, "missing": ref_id,
        "message": (f"第 {row.line} 行：字段「{label}」引用了不存在的 {target or '目标'}："
                    f"「{ref_id}」（引用型字段的目标必须已存在）。"),
        "how_to_fix": "请在内容包里先建好被引用的条目，或把这行改成已有的 id 后重试。",
    }


# =====================================================================================
# 导入：行序插入 / 冲突 / 落盘
# =====================================================================================
def _clamp_position(position: object, size: int) -> int:
    if isinstance(position, bool) or not isinstance(position, int):
        try:
            position = int(str(position))
        except (TypeError, ValueError):
            position = 0
    return max(0, min(int(position), size))


def _existing_ids(etype: str, data: object, key_field: str) -> List[str]:
    if etype == "list":
        out = []
        for elem in (data if isinstance(data, list) else []):
            eid = elem.get(key_field) if isinstance(elem, Mapping) else None
            if isinstance(eid, str) and eid:
                out.append(eid)
        return out
    return [str(k) for k in (data if isinstance(data, Mapping) else {})]


def _import_candidate(etype: str, data: object, schema: CsvSchema, rows: Sequence[DecodedRow],
                      *, mode: str, position: int,
                      overwrite_keys: Sequence[str]) -> object:
    """按 CSV 行序构造候选模块内容（不改原数据；overwrite 原地覆盖，新行追加 / 插入）。"""
    over = set(overwrite_keys)
    if etype == "list":
        result = [copy.deepcopy(e) for e in (data if isinstance(data, list) else [])]
        index = {}
        for i, elem in enumerate(result):
            eid = elem.get(schema.key_field) if isinstance(elem, Mapping) else None
            if isinstance(eid, str) and eid:
                index[eid] = i
        new_items: List[object] = []
        for row in rows:
            entry = row.entry(schema)
            entry = dict(entry) if isinstance(entry, Mapping) else {}
            entry[schema.key_field] = row.key
            if row.key in over and row.key in index:
                result[index[row.key]] = entry
            else:
                new_items.append(entry)
        if mode == MODE_INSERT:
            k = _clamp_position(position, len(result))
            return result[:k] + new_items + result[k:]
        return result + new_items
    # map
    result_m: Dict[str, Any] = {str(k): copy.deepcopy(v)
                                for k, v in (data if isinstance(data, Mapping) else {}).items()}
    new_pairs: List[Tuple[str, Any]] = []
    for row in rows:
        val = row.entry(schema)
        if row.key in over and row.key in result_m:
            result_m[row.key] = val
        else:
            new_pairs.append((row.key, val))
    if mode == MODE_INSERT:
        keys = list(result_m.keys())
        k = _clamp_position(position, len(keys))
        out: Dict[str, Any] = {}
        for key in keys[:k]:
            out[key] = result_m[key]
        for key, val in new_pairs:
            out[key] = val
        for key in keys[k:]:
            out[key] = result_m[key]
        return out
    for key, val in new_pairs:
        result_m[key] = val
    return result_m


def import_csv(pack: object, module: object, raw: object, *,
               mode: object = MODE_APPEND, position: object = 0,
               on_conflict: object = CONFLICT_SKIP,
               root: Optional[object] = None, role: object = ROLE_OWNER,
               meta: Optional[FieldMetaTable] = None) -> Dict[str, Any]:
    """模块级 CSV 导入：逐行报错 / 默认整批拒绝 / 冲突默认跳过 / 走既有落盘链路。

    返回统一包络（成功/跳过/失败计数 + 明细 + 备份 + 人话摘要）；任何红拦都**零写入、
    零备份**（先全量校验通过，才进入 `backup_modules → write_modules → 回读复核`）。
    """
    require_edit(role)
    mode_s = str(mode or MODE_APPEND).strip().lower()
    if mode_s not in MODES:
        raise api.BadRequest(f"未知导入模式：{mode!r}（应为 append / insert）。")
    conflict = str(on_conflict or CONFLICT_SKIP).strip().lower()
    if conflict not in CONFLICTS:
        raise api.BadRequest(f"未知冲突策略：{on_conflict!r}（应为 skip / overwrite）。")

    pack_dir, modules_raw, mod, mmeta, etype, data = _module_and_schema(pack, module, root)
    if etype not in ("list", "map"):
        env = _unsupported(mod, etype)
        env["pack"] = str(pack)
        return env
    manifest = api._manifest(pack_dir)
    declared = api._declared_modules(manifest)
    label = _module_label(pack_dir, manifest, declared, mod)
    # 校验用元数据表：显式传入优先，否则取该包的合并表（与 api._module_meta 同源）。
    table = meta if meta is not None else api._pack_meta_table(pack_dir)

    text, encoding = decode_bytes(raw)
    base_schema = csv_codec.schema_for(mmeta, entry_type=etype)
    extras = _entry_extra_keys(etype, data, base_schema)
    schema = csv_codec.schema_for(mmeta, entry_type=etype, extra_keys=extras)
    # 让 schema.module 参与人话提示
    schema = CsvSchema(module=mod, entry_type=schema.entry_type, key_field=schema.key_field,
                       value_mode=schema.value_mode, columns=schema.columns)

    env = _envelope(phase="import_csv", pack=str(pack), module=mod, entry_id="")
    env.update(module_label=label, mode=mode_s, on_conflict=conflict,
               encoding=encoding, added=[], overwritten=[], skipped=[],
               summary={"total": 0, "success": 0, "skipped": 0, "failed": 0})
    try:
        decoded = csv_codec.decode_csv(schema, text)
    except (CsvCodecError, UnsupportedModuleError) as exc:
        env.update(ok=False, level="red", errors=[{
            "level": "red", "code": "csv_decode_failed", "module": mod, "field": "",
            "field_key": "", "field_label": "（CSV 文件）",
            "message": str(exc), "how_to_fix": "请检查文件是否为该模块导出的 CSV（列头与分隔符）。",
        }], message=f"CSV 解析失败：{exc}")
        return env

    errors: List[Dict[str, Any]] = []
    for issue in decoded.issues:
        errors.append({
            "level": "red", "code": "csv_cell_invalid", "module": mod,
            "line": issue.line, "row": issue.line - 1, "entry_id": "",
            "field": issue.field, "field_key": issue.field,
            "field_label": issue.header or issue.field,
            "message": f"第 {issue.line} 行：{issue.message}",
            "how_to_fix": "请按列头的字段类型修正该单元格后重试。",
        })

    existing = _existing_ids(etype, data, schema.key_field)
    existing_set = set(existing)
    seen_csv: Dict[str, int] = {}
    planned: List[DecodedRow] = []          # 待新增（含 overwrite 之外的新行）
    overwrite_keys: List[str] = []
    skipped: List[Dict[str, Any]] = []

    for row in decoded.rows:
        key = row.key
        if not key:
            if etype == "list":
                key = _suggest_key(pack, mod, row, schema, root)
                row = DecodedRow(line=row.line, key=key, values=dict(row.values))
            if not key:
                errors.append({
                    "level": "red", "code": "csv_id_missing", "module": mod,
                    "line": row.line, "row": row.line - 1, "entry_id": "",
                    "field": schema.key_field, "field_key": schema.key_field,
                    "field_label": schema.key_field,
                    "message": (f"第 {row.line} 行：缺少 id（{schema.key_field} 列）。"
                                if etype == "list" else
                                f"第 {row.line} 行：缺少键（{schema.key_field} 列）。"),
                    "how_to_fix": "请补上 id（列表模块留空时会按名称自动生成；无法生成则须手填）。",
                })
                continue
        if key in seen_csv:
            errors.append({
                "level": "red", "code": "csv_id_duplicate", "module": mod,
                "line": row.line, "row": row.line - 1, "entry_id": key,
                "field": schema.key_field, "field_key": schema.key_field,
                "field_label": schema.key_field,
                "message": (f"第 {row.line} 行：id「{key}」在本次 CSV 里重复出现"
                            f"（首次在第 {seen_csv[key]} 行）。"),
                "how_to_fix": "请删掉重复行或改成不同的 id。",
            })
            continue
        seen_csv[key] = row.line
        if key in existing_set:
            if conflict == CONFLICT_SKIP:
                skipped.append({
                    "line": row.line, "entry_id": key,
                    "reason": "同 id 已存在，按默认策略跳过（未覆盖）",
                })
                continue
            overwrite_keys.append(key)
        planned.append(row)

    # 逐行引用校验（只验会被写入的行；引用目标 = 候选整包含本批新行）
    candidate = _import_candidate(etype, data, schema, planned, mode=mode_s,
                                  position=position, overwrite_keys=overwrite_keys)
    candidate_modules = dict(modules_raw)
    candidate_modules[mod] = candidate
    id_space = collect_ref_id_space(candidate_modules, table)
    for row in planned:
        for path, target, ref_id in _walk_row_refs(row, schema):
            if _ref_missing(id_space, target, ref_id):
                errors.append(_ref_row_error(row, path, target, ref_id, schema))

    total = len(decoded.rows)
    env["summary"] = {"total": total, "success": 0,
                      "skipped": len(skipped), "failed": len(errors)}
    env["skipped"] = skipped
    env["notes"] = list(decoded.notes)
    if errors:
        env.update(ok=False, level="red", errors=errors,
                   message=(f"导入失败：{len(errors)} 行有错，整批未写入"
                            f"（成功 0 条 / 跳过 {len(skipped)} 条 / 失败 {len(errors)} 条，"
                            f"共 {total} 行；内容包未改动，也未生成备份）。"))
        return env
    if not planned:
        env.update(ok=True, level="yellow" if skipped else "ok",
                   message=(f"没有可写入的行：{len(skipped)} 行因 id 已存在被跳过"
                            f"（成功 0 条 / 跳过 {len(skipped)} 条 / 失败 0 条，共 {total} 行）。"))
        return env

    # 既有整包校验门禁：红拦 → 零写入零备份
    report = check_pack(candidate_modules, table)
    if report.errors:
        reds = editor_ops._decorate(
            atomic_store.humanize_errors(report.errors),
            {"module": mod, "entry_id": "", "base": {}, "manifest": manifest,
             "declared": declared, "name": label, "slot": None},
            api._check_component(mod, "模块名"), related_only=True)
        env.update(ok=False, level="red", errors=reds,
                   message=(f"整包校验未通过：本次未写入任何文件"
                            f"（成功 0 条 / 跳过 {len(skipped)} 条 / 失败 {len(reds)} 条）。"))
        return env

    backup = atomic_store.backup_modules(pack_dir, [mod])
    if not backup.get("ok"):
        env.update(ok=False, level="red",
                   errors=list(backup.get("errors") or []),
                   message="备份失败，已取消本次导入（内容包未被改动）。")
        return env
    written = atomic_store.write_modules(pack_dir, {mod: candidate})
    if not written.get("ok"):
        env.update(ok=False, level="red",
                   errors=list(written.get("errors") or []),
                   message="写入失败：文件未改动（原子写未完成）。")
        return env

    slot = {"pack_dir": pack_dir, "module": mod, "entry_id": "", "base": {},
            "manifest": manifest, "declared": declared, "name": label, "slot": None}
    verify_errors = editor_ops._verify_after_write(pack, slot, root, table,
                                                  expected={mod: candidate})
    if verify_errors is not None:
        rolled = atomic_store.restore_modules_from_backup(pack_dir, [mod])
        env.update(ok=False, level="red", rolled_back=bool(rolled.get("ok")),
                   errors=verify_errors,
                   message=("写入后复核未通过，已自动回退到上一份备份（本次导入未生效）。"
                            if rolled.get("ok") else
                            "写入后复核未通过，且自动回退失败：请立即用「回退」或手动检查备份。"))
        return env

    added = [r.key for r in planned if r.key not in set(overwrite_keys)]
    env.update(
        ok=True, level=("yellow" if skipped else "ok"),
        added=added, overwritten=list(overwrite_keys),
        written=list(written.get("written") or []),
        backup=atomic_store.backup_status(pack_dir, mod),
        summary={"total": total, "success": len(planned),
                 "skipped": len(skipped), "failed": 0},
        message=(f"导入完成：成功 {len(planned)} 条（新增 {len(added)} / 覆盖 "
                 f"{len(overwrite_keys)}） / 跳过 {len(skipped)} 条 / 失败 0 条"
                 f"（共 {total} 行）。"),
    )
    return env


def _suggest_key(pack: object, module: str, row: DecodedRow, schema: CsvSchema,
                 root: Optional[object]) -> str:
    """id 留空 → 复用既有 `api.suggest_id`（按名称/前缀+序号）；失败返回空串（行级报错）。"""
    name = row.values.get(api._NAME_FIELD)
    try:
        sug = api.suggest_id(pack, module, root=root, name=name)
    except Exception:
        return ""
    out = sug.get("suggested_id")
    return str(out) if isinstance(out, str) and out else ""


__all__ = [
    "CONFLICTS",
    "CONFLICT_OVERWRITE",
    "CONFLICT_SKIP",
    "MODES",
    "MODE_APPEND",
    "MODE_INSERT",
    "decode_bytes",
    "export_csv",
    "export_filename",
    "import_csv",
]
