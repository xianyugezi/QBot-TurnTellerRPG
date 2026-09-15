"""编辑器保存链路「原子写盘 + 快照回退 + 变更应用」服务层（M12 批2 路2A · 细化_5a 编辑器契约）。

文件名：qbot_rpg/content/atomic_store.py
创建时间：2026-09-03

功能描述（对齐 docs/细化/细化_5a_编辑器契约.md 四、保存链路 SV-01~08）：
  - apply_module_changes(modules_raw, module_changes, changed_modules) -> {ok, modules}：
    把「待写变更」（{module, entries} 列表 or {module, item_id, removed}）应用到
    modules_raw 的深拷贝副本（纯逻辑，不碰磁盘；返回形态见本模块变更条目规范）
  - apply_removed_to_entries(module, entries, removed_ids) -> {ok, entries}：
    单模块移除清单 → 过滤后的新 entries（供删除落盘前合并级联模块）
  - write_modules(content_dir, module_files) -> {ok, written[]}：
    逐文件先写 .tmp 再 os.replace 原子 rename（SV-06）；任一文件序列化/写入失败
    → 全部不落盘（先校验全部可序列化，坏 JSON 不落盘不触发重载，服务不崩）
  - reload_and_rollback(registry, modules_raw, *, watcher=None, validator=None,
    human_errors=None) -> ReloadResult：写盘后统一触发重载 → 过完整校验器
    check_pack → 成功换新 registry / 失败回退上一份校验通过快照 + 人话错误（SV-07）
  - snapshot_registry(registry) -> RegistrySnapshot：上一份校验通过 registry 快照
    （SV-07「内存保留」：web 层挂长活 ctx 的 registry_store 键，保存前置档）

【工程补白 · 显式标注】
  1) 本层文件 IO 只在 write_modules（temp+rename）；apply_* 纯逻辑，测试用 tmp_path。
  2) 热重载统一入口 = HotReloadWatcher.reload（3e2 同一管线：build_pack 已全量校验
     + 快照回退 + 失败节流）。reload_and_rollback 的「假 validator 注入失败」用于
     校验失败回退语义单测（假 watcher 分支）。mtime 增量：编辑器保存是「全量写盘后
     一次 reload」，SV-06 的 mtime 增量（只重载变更模块）归 watcher/build_pack 的
     parse_cache（TRG-3）；本层记录 changed_modules 清单随 ReloadResult 上报，
     增量逻辑不在此重复实现（标注接口给全量）。
  3) 保存/热重载路径的「拒绝」只发生在加载/热重载阶段（SV-02）：保存（写盘）永远
     成功返回 ok:true；红拦经 reload 的 ReloadResult.errors 携带。
  4) 失败回退 = Registry.from_snapshot(pre)（字节一致，L178/细化_3e2 SNAP-1）；
     pre 取当前有效 registry 快照 = 上一份校验通过档（沿用 hot_reload §4.2 第①步）。

依据（契约行号）：
  - 细化_5a SV-06 L129（原子写盘：先写临时文件再原子 rename；全部文件写完统一触发重载）
  - 细化_5a SV-07 L130（快照回退：内存保留上一份校验通过的 registry 快照；热重载后
    必须过完整校验器，校验失败 = 回退旧 registry + 人话提示，绝不半套配置运行；写入
    非法 JSON 触发重载 → 服务不崩）
  - 细化_5a SV-02 L125（红拦的"拒绝"发生在加载/热重载阶段而非保存阶段）
  - 细化_5a §6.4 L189（/api/reload：全量过校验器→成功换新 registry / 失败回退旧快照）

铁律：零 NoneBot import；纯逻辑优先（文件 IO 只在 write_modules）；全中文注释；
      时钟/文件系统可测（tmp_path）；不真改 content/test_demo（只读）。
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from qbot_rpg.content.hot_reload import ReloadResult
from qbot_rpg.content.models import ValidationReport
from qbot_rpg.content.registry import Registry, RegistrySnapshot
from qbot_rpg.content.validator import check_pack
from qbot_rpg.data.logging_utils import get_logger

_logger = get_logger("content.atomic_store")

# 变更条目规范形状：
#   - {module, entries}：整模块最终 entries（新建/更新/删除的条目数组替换）
#   - {module, item_id, removed}：从模块移除指定条目（删除）
Change = Mapping[str, Any]

# 统一响应包络：{ok: true, data: ...} / {ok: false, errors: [...]}（细化_5a L183）
Result = Dict[str, Any]


# =============================================================================
# 变更应用（纯逻辑：只对深拷贝副本操作，绝不原地改调用方 modules_raw）
# =============================================================================

def _is_changed_module(
    module: str,
    changed_modules: Optional[Sequence[str]],
) -> bool:
    """changed_modules 为空 → 视为全量变更（None/空序列 = 不筛）；否则白名单判断。"""
    if not changed_modules:
        return True
    return module in set(changed_modules)


def _apply_module_entries(
    modules: MutableMapping[str, Any],
    module: str,
    entries: Sequence[Any],
) -> None:
    """整模块 entries 替换（新建/更新/删除聚合后的最终数组形态）。"""
    modules[module] = list(entries)


def _apply_module_remove(
    modules: MutableMapping[str, Any],
    module: str,
    item_id: str,
) -> bool:
    """从模块顶层 list 移除单条目（apply_delete_to_entries 同类语义，纯副本操作）。

    返回是否实际移除（模块缺失/非 list/条目不存在 → False，不报错不崩）。
    """
    raw = modules.get(module)
    if not isinstance(raw, list):
        return False
    kept = [e for e in raw if not (
        isinstance(e, Mapping) and str(e.get("id") or "") == item_id)]
    removed = len(kept) != len(raw)
    if removed:
        modules[module] = kept
    return removed


def apply_module_changes(
    modules_raw: Mapping[str, Any],
    changes: Sequence[Change],
    changed_modules: Optional[Sequence[str]] = None,
) -> Result:
    """把「待写变更」应用到 modules_raw 的深拷贝副本（纯逻辑，零 IO）。

    变更形态（{module, entries} 或 {module, item_id, removed}）：
      - {"module": "enemies", "entries": [...]}：整模块 entries 替换（新增/更新）
      - {"module": "enemies", "item_id": "gust_wolf", "removed": true}：单条目移除

    入参：
      modules_raw：内容包模块原始数据（registry.modules_raw 只读视图或普通 dict）
      changes：待写变更列表（空列表 = 无变更，返回全量副本）
      changed_modules：本次实际变更的模块清单（None/空 = 全量视为变更；非空时只对
        清单内模块应用变更——跨模块级联写盘时用白名单收敛 changed 上报）
    出参（统一包络 L183）：{ok: true, modules: <深拷贝副本>}；结构非法条目跳过不崩。
    """
    modules = copy.deepcopy(dict(modules_raw))
    changed: List[str] = []
    for ch in changes:
        if not isinstance(ch, Mapping):
            continue  # 非法变更条目：跳过不崩（服务不崩铁律）
        module = ch.get("module")
        if not isinstance(module, str) or not module:
            continue
        if not _is_changed_module(module, changed_modules):
            continue  # 变更白名单外：跳过（增量收敛）
        removed = ch.get("removed")
        if removed is True:
            item_id = ch.get("item_id")
            if isinstance(item_id, str) and item_id:
                _apply_module_remove(modules, module, item_id)
                if module not in changed:
                    changed.append(module)
            continue
        entries = ch.get("entries")
        if isinstance(entries, (list, tuple)):
            _apply_module_entries(modules, module, entries)
            if module not in changed:
                changed.append(module)
    return {"ok": True, "modules": modules, "changed_modules": changed}


def apply_removed_to_entries(
    module: str,
    entries: Sequence[Any],
    removed_ids: Sequence[str],
) -> Result:
    """单模块移除清单 → 过滤后的新 entries（删除落盘前合并级联模块用，纯逻辑）。

    与页面级删除的差异：本函数不依赖 ctx/页面映射，
    直接对「模块 entries 数组」做 id 白名单过滤，供级联模块（maps/dungeon/skills）
    在写盘前就地剔除引用条目。条目缺失 → ok:true 原样返回（幂等，不报错）。
    出参：{ok: true, entries: [...]}（统一包络 L183）。
    """
    remove_set = set(removed_ids)
    if not remove_set:
        return {"ok": True, "entries": list(entries)}
    kept = [e for e in entries if not (
        isinstance(e, Mapping) and str(e.get("id") or "") in remove_set)]
    return {"ok": True, "entries": kept}


# =============================================================================
# 原子写盘（SV-06：先写临时文件再原子 rename；唯一文件 IO 落点）
# =============================================================================

def _serialize_json(content: Any) -> str:
    """内容 → JSON 文本（写入前序列化检查：坏 JSON 不落盘不触发重载，SV-07 服务不崩）。

    序列化失败（含 None/非 JSON 类型/循环引用）抛 ValueError（不含原始对象细节）。
    """
    try:
        return json.dumps(content, ensure_ascii=False, indent=2)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"module content not JSON-serializable: {type(exc).__name__}") from exc


_SAFE_MODULE_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"


def _safe_module_name(module: str) -> str:
    """模块文件名白名单：仅允许 [A-Za-z0-9_-]（防路径穿越；非法名拒绝写盘）。

    兼容两种入参形态：`skills`（裸模块名）与 `skills.json`（带后缀）——
    带 .json 后缀时先剥后缀校验主体，再允许整体（_module_filename 原样落盘）。
    """
    if not module:
        raise ValueError(f"invalid module name: {module!r}")
    body = module[:-5] if module.endswith(".json") else module
    if not body or any(c not in _SAFE_MODULE_CHARS for c in body):
        raise ValueError(f"invalid module name: {module!r}")
    return module


def _module_filename(module: str) -> str:
    """模块名 → 文件名：已带 .json 后缀则原样；否则补后缀。"""
    if module.endswith(".json"):
        return module
    return f"{module}.json"


def _cleanup_tmp(tmp_path: Path) -> None:
    """清理残留临时文件（失败路径：写失败/rename 失败不留 .tmp 垃圾）。"""
    try:
        tmp_path.unlink(missing_ok=True)
    except OSError:
        _logger.warning("清理临时文件失败: %s", tmp_path)


def _write_one_atomic(target_path: Path, text: str) -> None:
    """单文件原子写：先写 .tmp 再 os.replace（SV-06 L129）。

    临时文件与目标同目录（保证 rename 同文件系统原子）；写入失败抛 OSError，
    调用方清理 .tmp 后整体返回失败（部分文件已 rename 的由上层标注，不半套运行）。
    """
    tmp_path = target_path.with_name(f"{target_path.name}.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target_path)  # 原子 rename（同目录同文件系统）
    except OSError:
        _cleanup_tmp(tmp_path)
        raise
    finally:
        if tmp_path.exists():
            _cleanup_tmp(tmp_path)  # 正常路径 rename 后已不存在；残留则清理


def write_modules(
    content_dir: Path,
    module_files: Mapping[str, Any],
) -> Result:
    """模块 JSON 原子写盘（SV-06 L129：先写临时文件再原子 rename）。

    入参：
      content_dir：内容包目录（写入 {module}.json；已带 .json 后缀的模块名原样）
      module_files：{模块名: JSON 内容}（内容为 parsed JSON 数据，本函数负责序列化）

    流程（SV-06）：
      ① 全部内容先序列化检查（坏 JSON/不可序列化 → 整体拒绝，零文件落盘，服务不崩）；
      ② 逐文件 .tmp 写 + os.replace 原子 rename（失败清理 .tmp，不残留垃圾）；
      ③ 全部写完返回 {ok: true, written: [已写模块...]}（写盘本身从不因校验拒绝，
         SV-02：红拦的"拒绝"发生在加载/热重载阶段而非保存阶段——统一触发重载由
         reload_and_rollback 承接）。
    出参（统一包络 L183）：{ok: true, written: [...]}；失败 {ok: false, errors: [...]}。
    """
    content_dir = Path(content_dir)
    errors: List[dict] = []
    # ① 预序列化：坏 JSON/非法模块名 → 整体拒绝（不落任何盘，防半套写入）
    prepared: List[Tuple[str, Path, str]] = []
    for module, content in module_files.items():
        if not isinstance(module, str):
            errors.append({"level": "red", "code": "invalid_module",
                           "message": f"模块名非法：{module!r}"})
            continue
        try:
            safe_name = _safe_module_name(module)
        except ValueError as exc:
            errors.append({"level": "red", "code": "invalid_module", "message": str(exc)})
            continue
        try:
            text = _serialize_json(content)
        except ValueError as exc:
            errors.append({"level": "red", "code": "invalid_json",
                           "message": f"模块「{module}」内容不是合法 JSON：{exc}"})
            continue
        prepared.append((module, content_dir / _module_filename(safe_name), text))
    if errors:
        return {"ok": False, "errors": errors}  # 坏 JSON 不落盘不触发重载（SV-07）
    # ② 逐文件原子写（任一失败 → 返回失败；.tmp 由 _write_one_atomic 清理）
    written: List[str] = []
    for module, target_path, text in prepared:
        try:
            _write_one_atomic(target_path, text)
        except OSError as exc:
            return {"ok": False, "errors": [{
                "level": "red", "code": "write_failed",
                "message": f"写入模块「{module}」失败：{type(exc).__name__}",
            }]}
        written.append(module)
    return {"ok": True, "written": written}


# =============================================================================
# 写前备份 / 回退（编辑器重写批2：.bak + 原子恢复；仍属本层唯一文件 IO 落点）
# =============================================================================

def backup_status(content_dir: Path, module: str) -> Dict[str, Any]:
    """备份状态（回退入口的可见性数据；不读内容，只 stat）。

    出参：{module, path（相对内容包的备份文件名）, exists, size, mtime_ns}。
    模块名非法 → {exists: False, error}（不抛，供界面显示「无备份」）。
    """
    try:
        safe = _safe_module_name(module)
    except ValueError as exc:
        return {"module": str(module), "path": "", "exists": False,
                "size": 0, "mtime_ns": 0, "error": str(exc)}
    filename = _module_filename(safe)
    bak = Path(content_dir) / f"{filename}.bak"
    try:
        st = bak.stat()
    except OSError:
        return {"module": safe, "path": f"{filename}.bak", "exists": False,
                "size": 0, "mtime_ns": 0}
    return {"module": safe, "path": f"{filename}.bak", "exists": True,
            "size": st.st_size, "mtime_ns": st.st_mtime_ns}


def backup_modules(content_dir: Path, modules: Sequence[str]) -> Result:
    """写前自动备份（编辑器重写批2）：把当前 {module}.json 复制为 {module}.json.bak。

    语义：
      · 覆盖式备份——同一模块多次保存时，.bak 恒为「上一份已落盘内容」；
      · 目标文件不存在（全新模块）→ 跳过（无旧内容可备份，不算失败）；
      · 备份文件经 _write_one_atomic 原子落盘（不留半截 .bak）；
      · 任一备份失败 → 返回 ok:false（调用方据此取消本次写入，不落半套）。
    出参：{ok: true, backups: [备份文件名...], skipped: [模块名...]}。
    """
    content_dir = Path(content_dir)
    backups: List[str] = []
    skipped: List[str] = []
    for module in modules:
        try:
            safe = _safe_module_name(module)
        except ValueError as exc:
            return {"ok": False, "errors": [{
                "level": "red", "code": "invalid_module", "message": str(exc)}]}
        filename = _module_filename(safe)
        src = content_dir / filename
        if not src.is_file():
            skipped.append(safe)
            continue
        try:
            text = src.read_text(encoding="utf-8")
            _write_one_atomic(content_dir / f"{filename}.bak", text)
        except (OSError, UnicodeDecodeError) as exc:
            return {"ok": False, "errors": [{
                "level": "red", "code": "backup_failed",
                "message": f"备份模块「{safe}」失败：{type(exc).__name__}（已取消写入）",
            }]}
        backups.append(f"{filename}.bak")
    return {"ok": True, "backups": backups, "skipped": skipped}


def restore_modules_from_backup(content_dir: Path, modules: Sequence[str]) -> Result:
    """从 .bak 回退（编辑器重写批2）：{module}.json.bak → {module}.json（原子写）。

    · 无备份的模块进 missing（不算整体失败，除非全部缺失）；
    · 恢复本身经 _write_one_atomic（原子替换，读方不会看到半截文件）；
    · .bak 恢复后保留（可重复回退）；写入失败返回 ok:false + 人话错误。
    出参：{ok: true, restored: [模块名...], missing: [模块名...]}。
    """
    content_dir = Path(content_dir)
    restored: List[str] = []
    missing: List[str] = []
    errors: List[dict] = []
    for module in modules:
        try:
            safe = _safe_module_name(module)
        except ValueError as exc:
            errors.append({"level": "red", "code": "invalid_module", "message": str(exc)})
            continue
        filename = _module_filename(safe)
        bak = content_dir / f"{filename}.bak"
        if not bak.is_file():
            missing.append(safe)
            continue
        try:
            text = bak.read_text(encoding="utf-8")
            _write_one_atomic(content_dir / filename, text)
        except (OSError, UnicodeDecodeError) as exc:
            errors.append({"level": "red", "code": "restore_failed",
                           "message": f"从备份恢复模块「{safe}」失败：{type(exc).__name__}"})
            continue
        restored.append(safe)
    if errors:
        return {"ok": False, "errors": errors}
    if not restored:
        return {"ok": False, "errors": [{
            "level": "red", "code": "no_backup",
            "message": "没有可回退的备份：" + "、".join(missing or [str(m) for m in modules]),
        }]}
    return {"ok": True, "restored": restored, "missing": missing}


# =============================================================================
# 快照回退（SV-07：内存保留上一份校验通过的 registry 快照；失败回退 + 人话提示）
# =============================================================================

def snapshot_registry(registry: Registry) -> RegistrySnapshot:
    """当前有效 registry 快照（SV-07「内存保留」；保存前置档）。

    Registry.snapshot() 为深拷贝（registry.py L122-133），调用方（web 层）把返回
    快照挂长活 ctx 的 registry_store 键：保存链路先置档，热重载失败时回退此档。
    与 hot_reload watcher 内部 N=2 快照的差异：本接口是编辑器保存语义的「上一份
    校验通过」档（多一层冗余，回退对象由调用方显式持有）。
    """
    return registry.snapshot()


def restore_registry(registry: Registry, snap: RegistrySnapshot) -> None:
    """用快照回退 registry（失败路径；单引用原子替换，绝不半套配置运行，SV-07 L130）。"""
    registry.restore(snap)


def _fallback_snapshot(registry: Registry) -> RegistrySnapshot:
    """兜底快照源：registry 当前有效档（无外部快照时用，沿用 hot_reload §4.2 ①）。"""
    return registry.snapshot()


def reload_and_rollback(
    registry: Registry,
    modules_raw: Mapping[str, Any],
    *,
    watcher: Any = None,
    validator: Optional[Callable[[Mapping[str, Any]], ValidationReport]] = None,
    human_errors: Optional[List[dict]] = None,
    previous_snapshot: Optional[RegistrySnapshot] = None,
) -> ReloadResult:
    """写盘后统一触发重载 → 过完整校验器 → 成功换新 registry / 失败回退旧快照（SV-07）。

    入参：
      registry：当前生效 Registry（失败路径回退目标/成功路径替换对象）
      modules_raw：写盘后的新模块数据（{模块名: parsed JSON}；校验器数据源）
      watcher：HotReloadWatcher 实例（热重载统一入口）。None 时本函数走
        「validator 注入」旁路（单测用假 validator/假 watcher，纯逻辑可测）。
      validator：完整校验器（缺省 check_pack；Signature: modules -> ValidationReport）。
        仅 watcher 为 None 时生效（watcher 路径由 watcher.reload 走 build_pack 全量校验）。
      human_errors：人话错误收集器（list in-place 追加，供 web 层翻译 ReloadResult
        errors → 细化_5a L183 包络 errors[]；None 则不收集）
      previous_snapshot：保存前置档（snapshot_registry 产物）。None 时回退目标 =
        registry 当前有效档快照（沿用 hot_reload §4.2 第①步语义）。

    流程（SV-07 / 细化_5a 4.1 链路图 L116）：
      ① 先快照当前有效 registry（回退对象，绝不半套配置运行）
      ② watcher 路径：await watcher.reload() 同一热重载管线（build_pack 全量校验 +
         内部快照回退 + 失败节流，3e2 F2/F3）；失败 → ReloadResult.ok=false + restored
      ③ validator 旁路（watcher=None）：check_pack(modules_raw) 全量校验——errors 非空
         → 回退旧快照 + 组装 ReloadResult（restored=true）；通过 → registry 换新（指针级）
      ④ 人话收集：human_errors 非空时把校验 errors 翻译为 {level/code/message} 追加
        （人话文案模板对齐细化_5a SV-05：报错含条目名/字段名可读信息）
    出参：ReloadResult（与 /重载 同一结构化结果，hot_reload.py L91-118）。
    """
    if previous_snapshot is None:
        previous_snapshot = _fallback_snapshot(registry)

    if watcher is not None:
        # watcher 路径：统一走 hot_reload 同一条管线（含全量校验 + 内部快照回退）
        return _reload_via_watcher(watcher, human_errors)

    # validator 旁路（纯逻辑可测）：全量校验 → 通过换新 / 失败回退旧快照
    check = validator if validator is not None else check_pack
    try:
        report = check(dict(modules_raw))
    except Exception as exc:  # 校验器意外异常 → 按校验失败处理（服务不崩铁律）
        _logger.exception("atomic_store 校验意外异常（回退旧 registry）")
        report = ValidationReport(errors=())
        return _rollback_result(registry, previous_snapshot, modules_raw,
                                 unexpected=exc, human_errors=human_errors)
    if report.ok:
        # 通过 → 指针级替换（同目录校验通过后 registry 整体换新；模块数据同步）
        _apply_validated_modules(registry, previous_snapshot, modules_raw)
        return ReloadResult(
            pack_id=registry.pack_id,
            ok=True,
            changed_modules=tuple(sorted(k for k in modules_raw if k != "manifest")),
            warnings=report.warnings,
            errors=(),
            restored=False,
            paused=False,
            generation=registry.generation,
            note="atomic_store validator path: new modules validated and mounted",
        )
    return _rollback_result(registry, previous_snapshot, modules_raw,
                            report=report, human_errors=human_errors)


def _apply_validated_modules(
    registry: Registry,
    previous_snapshot: RegistrySnapshot,
    modules_raw: Mapping[str, Any],
) -> None:
    """校验通过 → registry 换新（单引用原子替换，期间旧引用继续服务，D-03）。"""
    # registry 无公开写入口（Registry 仅引用替换式 restore/mount），本层经快照回退
    # 通道重建新档：以「旧快照 + 新 modules_raw」构建新 registry 快照并 restore——
    # 单引用原子替换（CPython 单引用写），读方 resolve 无 torn 状态（registry.py L135-151）。
    snap = RegistrySnapshot(
        pack_id=registry.pack_id or previous_snapshot.pack_id,
        generation=registry.generation + 1,
        tables=copy.deepcopy(dict(previous_snapshot.tables)),
        names=copy.deepcopy(dict(previous_snapshot.names)),
        modules_raw=copy.deepcopy(dict(modules_raw)),
        manifest=registry.manifest or previous_snapshot.manifest,
        schema_version=(
            registry.schema_version
            if registry.schema_version is not None
            else previous_snapshot.schema_version
        ),
    )
    restore_registry(registry, snap)


def _rollback_result(
    registry: Registry,
    snap: RegistrySnapshot,
    modules_raw: Mapping[str, Any],
    *,
    report: Optional[ValidationReport] = None,
    unexpected: Optional[Exception] = None,
    human_errors: Optional[List[dict]] = None,
) -> ReloadResult:
    """校验失败/意外异常 → 回退旧快照 + 人话错误（SV-07：绝不半套配置运行）。"""
    restore_registry(registry, snap)
    errors = report.errors if report is not None else ()
    warnings = report.warnings if report is not None else ()
    note = ""
    if unexpected is not None:
        note = f"unexpected validator error: {type(unexpected).__name__}"
    if human_errors is not None:
        human_errors.extend(_humanize_errors(errors) if errors else [{
            "level": "red", "code": "reload_failed",
            "message": "配置校验未通过，已回退到上一份可用配置（本次保存未生效）",
        }])
    return ReloadResult(
        pack_id=registry.pack_id,
        ok=False,
        changed_modules=(),
        warnings=warnings,
        errors=errors,
        restored=True,
        paused=False,
        generation=registry.generation,
        note=note + " rolled back to last validated snapshot (SV-07)",
    )


# =====================================================================================
# 批14 #5：校验错误的「三段式人话」规则库（为什么 / 怎么办）
# -------------------------------------------------------------------------------------
# 纯展示层翻译：规则码 + 结构化参数 → 面向非技术作者的解释与动作，**不改任何校验判定**
# （errors/warnings 的条数、kind、field 一律不变，只多带展示字段）。
# 覆盖最常见的通用规则（类型 / 枚举 / 必填 / 引用 / 重复 ID / 范围 / 未知键 / 区间倒置…）；
# 未命中的规则回退用校验器自带的 `msg`/原文，绝不臆造判定。
# =====================================================================================
_TYPE_ZH = {
    "str": "文本", "text": "文本", "int": "整数", "float": "数字", "number": "数字",
    "bool": "开关（是/否）", "list": "列表", "obj": "对象", "map": "键值表",
    "formula": "公式（文本）", "NoneType": "空", "none": "空", "dict": "对象",
    "list[str]": "文本列表",
}


def _zh_type(name: object) -> str:
    raw = str(name or "").strip()
    if not raw:
        return "内容"
    return _TYPE_ZH.get(raw, raw)


def _fmt_value(value: object) -> str:
    if value is None:
        return "空"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float) and float(value).is_integer():
        return str(int(value))
    return str(value)


def _fmt_list(values: object, limit: int = 12) -> str:
    rows = [_fmt_value(v) for v in (values or [])]  # type: ignore[union-attr]
    if len(rows) > limit:
        rows = rows[:limit] + ["…"]
    return "、".join(rows) if rows else "（空）"


def _range_text(detail: Mapping[str, object]) -> str:
    lo, hi = detail.get("range_min"), detail.get("range_max")
    if lo is not None and hi is not None:
        return f"{_fmt_value(lo)} ~ {_fmt_value(hi)}"
    if lo is not None:
        return f"不小于 {_fmt_value(lo)}"
    if hi is not None:
        return f"不大于 {_fmt_value(hi)}"
    return "要求的范围"


def _guide_unknown_key(detail: Mapping[str, object]) -> Tuple[str, str]:
    keys = detail.get("keys") or detail.get("key") or []
    allowed = detail.get("allowed") or []
    if not isinstance(keys, list):
        keys = [keys]
    why = f"这里多出了这个内容不认识的键：{_fmt_list(keys)}。"
    if allowed:
        why += f"此处允许的键是：{_fmt_list(allowed)}。"
    return why, ("删掉多余的键，或改成上面允许的键名；键名要与内容里的其它地方对应。")


# rule 码 → (为什么, 怎么办)。每条都只描述「期望什么 + 具体动作」，不出现技术术语。
RULE_GUIDE: Dict[str, Any] = {
    "type": lambda d: (
        f"这里应该填{_zh_type(d.get('expect'))}，现在填的是{_zh_type(d.get('got'))}。",
        f"把它改成{_zh_type(d.get('expect'))}再保存。"),
    "enum": lambda d: (
        f"这里只能选固定的几个值，现在填的是「{_fmt_value(d.get('got'))}」，不在可选范围内。",
        f"改成下面之一：{_fmt_list(d.get('enum'))}。"),
    "required_missing": lambda d: (
        f"必填的「{_fmt_value(d.get('name'))}」还没有填。",
        f"补上「{_fmt_value(d.get('name'))}」再保存。"),
    "ref_missing": lambda d: (
        f"这里指向的「{_fmt_value(d.get('ref'))}」在内容里找不到"
        + (f"（它应该指向：{_fmt_value(d.get('ref_target'))}）" if d.get("ref_target") else "")
        + "。",
        "先到对应的地方把这项建出来，或改选一个已经存在的目标。"),
    "ref_not_str": lambda d: (
        f"这里应该填一个目标的名字（文本），现在填的是{_zh_type(d.get('got'))}。",
        "改成一个已存在的目标名字。"),
    "id_duplicate": lambda d: (
        f"标识「{_fmt_value(d.get('id'))}」重复了：同一类内容里必须唯一"
        + (f"（另一处已用在 {_fmt_value(d.get('previous_module'))}）"
           if d.get("previous_module") else "") + "。",
        "把其中一个改成不重复的标识（建议英文小写 + 下划线）。"),
    "negative": lambda d: (
        f"这个数不能是负数，现在填的是 {_fmt_value(d.get('value'))}。",
        "改成 0 或正整数。"),
    "not_a_number": lambda d: (
        f"这里需要能参与运算的数字，现在填的是 {_fmt_value(d.get('value'))}。",
        "改成一个正常的数字（不要是无穷大或非数字）。"),
    "out_of_common_range": lambda d: (
        f"{_fmt_value(d.get('value'))} 超出了一般的取值范围（{_range_text(d)}）。"
        "这只是提醒，不会拦住保存。",
        "确认是有意为之可以忽略；若想保险，改成范围内的数。"),
    "dead_range": lambda d: (
        f"下限「{_fmt_value(d.get('lo_key'))}」= {_fmt_value(d.get('lo'))} 比"
        f"上限「{_fmt_value(d.get('hi_key'))}」= {_fmt_value(d.get('hi'))} 还大，这样区间是空的。",
        "把下限调小，或把上限调大。"),
    "module_structure": lambda d: (
        f"这个文件的整体结构不对：应该是{_zh_type(d.get('expect'))}。",
        "把这个文件改成要求的整体结构后重试（可参考同类的其它文件）。"),
    "entry_not_object": lambda d: (
        f"这一条内容应该是一组「名称: 值」，现在却是{_zh_type(d.get('got'))}。",
        "把这一条改成一组「名称: 值」的写法。"),
    "key_invalid": lambda d: (
        f"键名「{_fmt_value(d.get('key'))}」不符合命名要求"
        + (f"（要求：{_fmt_value(d.get('key_regex'))}）" if d.get("key_regex") else "") + "。",
        "把键名改成允许的写法（通常为英文小写 + 下划线）。"),
    "formula_safety": lambda d: (
        "这段公式里含有不允许的写法，出于安全考虑不能保存。",
        "只用普通的加减乘除、括号和已登记的名字，不要调用外部函数。"),
    "zero_unlimited": lambda d: (
        "这里填了 0，它的含义是「不限制」。",
        "确认这是想要的效果；若要限制数量，请填一个大于 0 的数。"),
    "probability_extreme": lambda d: (
        f"概率 {_fmt_value(d.get('value'))} 偏极端"
        + ("（偏高）" if d.get("hint") == "high" else "（偏低）") + "，实际效果可能和预期差很多。",
        "确认无误可以忽略；否则调整到更常见的概率区间。"),
    "stat_key_unregistered": lambda d: (
        f"属性名「{_fmt_value(d.get('ref'))}」当前没有登记过，可能不会被识别。",
        "改成已登记的属性名，或先在属性表里把它登记好。"),
    "reset_eq_mismatch": lambda d: (
        f"重置方式选了「等于」，但重置值 {_fmt_value(d.get('value'))} 和上限 "
        f"{_fmt_value(d.get('max'))} 对不上。",
        "把重置值改成与上限一致，或换一种重置方式。"),
    "battle_revert_conflict": lambda d: (
        "「战斗中」与「结束后还原」这两个选项不能同时选。",
        "取消其中一个。"),
}


def _why_how(rule: str, kind: str, detail: Mapping[str, object],
             raw: str) -> Tuple[str, str]:
    """规则码 + 结构化参数 → (为什么, 怎么办)；未命中的规则回退校验器自带说明。"""
    if rule in RULE_GUIDE:
        try:
            why, how = RULE_GUIDE[rule](detail)
            return str(why), str(how)
        except Exception:  # 参数形态意外 → 回退，不因翻译失败丢错误
            pass
    if rule.endswith("unknown_key") or rule.endswith("_unknown_field") or rule == "unknown_key":
        return _guide_unknown_key(detail)
    # 兜底：校验器自带的 msg 通常是中文人话；退而用原文。
    why = str(detail.get("msg") or detail.get("message") or raw or "这项内容不符合要求。")
    return why, "按上面的说明改成符合要求的内容后重试。"


def _humanize(items: Sequence[Any], *, level: str, verb: str) -> List[dict]:
    """PackError/PackWarning 结构化 detail → 人话条目（细化_5a L183 包络 errors[] 形态）。

    人话模板对齐细化_5a SV-05（报错含模块/条目名可读信息；规则 ⑤ 模板 L165-168）；
    校验器 PackError.detail 为结构化参数（D-06：validator 不拼用户体验文案，翻译归本层）。
    红拦（PackError）与黄提示（PackWarning）结构同形，仅 level/verb 不同，故共用本函数。

    批14 #5：每条额外给**三段式**展示字段 `why`（为什么）/ `how`（怎么办）与 `rule` 规则码；
    面板层再补 `where`（哪里）。`message` / `code` / `module` / `field` 原样保留（排查用）。
    """
    out: List[dict] = []
    for e in items:
        module = getattr(e, "module", "")
        field = getattr(e, "field", "")
        detail = dict(getattr(e, "detail", {}) or {})
        message = str(detail.get("message") or detail.get("error") or detail.get("msg")
                      or detail.get("rule") or getattr(e, "kind", "") or "配置不合法")
        rule = str(detail.get("rule") or "")
        why, how = _why_how(rule, str(getattr(e, "kind", "") or ""), detail, message)
        out.append({
            "level": level,
            "code": str(getattr(e, "kind", "") or "validation"),
            "rule": rule,
            "module": str(module),
            "field": str(field),
            "raw": message,
            "why": why,
            "how": how,
            "message": f"模块「{module}」{verb}：{message}"
                      + (f"（位置：{field}）" if field else ""),
        })
    return out


def humanize_errors(errors: Sequence[Any]) -> List[dict]:
    """红拦人话条目（编辑器/命令层展示用；level=red）。"""
    return _humanize(errors, level="red", verb="配置校验未通过")


def humanize_warnings(warnings: Sequence[Any]) -> List[dict]:
    """黄提示人话条目（编辑器展示用；level=yellow，不阻断保存）。"""
    return _humanize(warnings, level="yellow", verb="有需要注意的取值")


# 兼容内部旧名（v1 私有翻译入口；对外请用 humanize_errors）。
_humanize_errors = humanize_errors


def _reload_via_watcher(
    watcher: Any,
    human_errors: Optional[List[dict]],
) -> ReloadResult:
    """经 HotReloadWatcher.reload 统一管线触发热重载（3e2 F2/F3：内部已含全量校验 +
    快照回退 + 失败节流）。watcher 为热重载权威入口，失败回退由 watcher 内部 N=2 档完成。

    watcher.reload 为 async（hot_reload.py L194-200），本函数同步上下文不可 await：
    调用方（web 层 asyncio.to_thread 内跑保存链路）应传入已包好的同步触发闭包——
    watcher 参数若为 HotReloadWatcher 实例，本函数在无运行事件循环时用 asyncio.run
    驱动；运行事件循环中由调用方传「async 已跑完的 ReloadResult」或同步包装器。
    假 watcher（单测）：提供 reload() -> ReloadResult 同步方法即可注入失败分支。
    """
    # 假 watcher（单测注入）：reload 为同步方法 → 直接调用
    reload_fn = getattr(watcher, "reload", None)
    if reload_fn is None:
        raise TypeError("watcher 必须提供 reload()（HotReloadWatcher 或假 watcher）")
    result = reload_fn()
    if human_errors is not None and not result.ok:
        human_errors.extend(_humanize_errors(result.errors) if result.errors else [{
            "level": "red", "code": "reload_failed",
            "message": "配置校验未通过，已回退到上一份可用配置（本次保存未生效）",
        }])
    return result


def check_pack_errors_human(modules_raw: Mapping[str, Any]) -> List[dict]:
    """校验前置人话错误（web 层保存前预检用，可独立于 reload 路径调用）。"""
    report = check_pack(dict(modules_raw))
    return _humanize_errors(report.errors)


__all__ = [
    "apply_module_changes",
    "apply_removed_to_entries",
    "backup_modules",
    "backup_status",
    "check_pack_errors_human",
    "humanize_errors",
    "humanize_warnings",
    "reload_and_rollback",
    "restore_modules_from_backup",
    "restore_registry",
    "snapshot_registry",
    "write_modules",
]
