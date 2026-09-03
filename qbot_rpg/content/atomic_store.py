"""编辑器保存链路「原子写盘 + 快照回退 + 变更应用」服务层（M12 批2 路2A · 细化_5a 编辑器契约）。

文件名：qbot_rpg/content/atomic_store.py
创建时间：2026-09-03

功能描述（对齐 docs/细化/细化_5a_编辑器契约.md 四、保存链路 SV-01~08）：
  - apply_module_changes(modules_raw, module_changes, changed_modules) -> {ok, modules}：
    把「待写变更」（{module, entries} 列表 or {module, item_id, removed}）应用到
    modules_raw 的深拷贝副本（纯逻辑，不碰磁盘；pages_crud 批1 返回形态直接消费）
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

# 变更条目规范形状（pages_crud 批1 交付形态）：
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

    变更形态（pages_crud 批1 交付，{module, entries} 或 {module, item_id, removed}）：
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

    与 apply_delete_to_entries（pages_crud）的差异：本函数不依赖 ctx/页面映射，
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


def _humanize_errors(errors: Sequence[Any]) -> List[dict]:
    """PackError 结构化 detail → 人话 errors（细化_5a L183 包络 errors[] 形态）。

    人话模板对齐细化_5a SV-05（报错含模块/条目名可读信息；规则 ⑤ 模板 L165-168）；
    校验器 PackError.detail 为结构化参数（D-06：validator 不拼用户体验文案，翻译归本层）。
    """
    out: List[dict] = []
    for e in errors:
        module = getattr(e, "module", "")
        field = getattr(e, "field", "")
        detail = dict(getattr(e, "detail", {}) or {})
        message = str(detail.get("message") or detail.get("error") or detail.get("rule")
                      or getattr(e, "kind", "") or "配置不合法")
        out.append({
            "level": "red",
            "code": str(getattr(e, "kind", "") or "validation"),
            "field": str(field),
            "message": f"模块「{module}」配置校验未通过：{message}"
                      + (f"（位置：{field}）" if field else ""),
        })
    return out


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
    "check_pack_errors_human",
    "reload_and_rollback",
    "restore_registry",
    "snapshot_registry",
    "write_modules",
]
