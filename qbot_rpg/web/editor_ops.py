"""编辑器写入层（编辑器重写批2 · 编辑与保存）：草稿补丁 → 现有校验器 → 备份 → 原子落盘 → 回退。

唯一写入链路（宿主与单测共用同一函数，界面不得绕开本层直接写盘）：

    validate_entry(...)   —— 只跑校验器：红拦/黄提示分选，绝不写盘（`/…/validate`）
    save_entry(...)       —— 红拦不落盘；通过则「先备份 .bak → atomic_store 原子写 → 回读复核」
                             （复核失败自动回退备份，绝不假成功）（`/…/save`）
    module_backup(...)    —— 备份状态（回退入口的可见性）（`/…/backup`）
    rollback_module(...)  —— 从上一份 .bak 原子恢复（`/…/rollback`）

设计要点（对齐 docs/编辑器重写_实现方案.md §一/§三/§四 批2）：
  · 校验复用现有 **唯一的** 校验入口 `qbot_rpg.content.validator.check_pack`，本层**不新写规则**；
    红拦阻断落盘，黄提示放行但在响应里标出。
  · 落盘复用 `qbot_rpg/content/atomic_store.py`：list 模块走「变更条目形态」
    （`apply_module_changes` 的 {module, entries}），map/object 模块直写整段 JSON；
    两者都经 `write_modules`（临时文件 + 原子 rename）。
  · 写前自动备份：`backup_modules` 生成 `<模块>.json.bak`；回退 = `restore_modules_from_backup`。
  · 权限位沿用 `qbot_rpg.content.permission_store` 的角色语义：机主（owner）可编辑 /
    GM（gm）只读预览；只读角色在**写入前**一律 `Forbidden(403)`，不依赖前端隐藏按钮。
  · 本层零业务字段名：控件映射与字段提示全部来自字段元数据（通用性判断标准见需求第〇节）。

铁律：零 NoneBot import；文件 IO 只在 atomic_store；时钟/文件系统可测。
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from qbot_rpg.content import atomic_store
from qbot_rpg.content.models import FieldMeta, FieldMetaTable
from qbot_rpg.content.permission_store import (
    ROLE_ADMIN_OUT,
    ROLE_GM_DB,
    ROLE_MANAGER_OUT,
    ROLE_OWNER_DB,
)
from qbot_rpg.content.validator import check_pack
from qbot_rpg.web import api

# 编辑器角色（沿用 permission_store 落库角色字面：owner=机主 / gm=GM）。
ROLE_OWNER: str = ROLE_OWNER_DB
ROLE_GM: str = ROLE_GM_DB
ALL_ROLES: Sequence[str] = (ROLE_OWNER, ROLE_GM)
EDITABLE_ROLES = frozenset({ROLE_OWNER})

_ROLE_LABELS: Dict[str, str] = {
    ROLE_OWNER: "机主 · 可编辑",
    ROLE_GM: "GM · 只读预览",
}
# commands 层对外归一角色（admin/manager）→ 编辑器角色（管理员=机主 / 管理=GM）
_OUT_TO_ROLE: Dict[str, str] = {
    ROLE_ADMIN_OUT: ROLE_OWNER,
    ROLE_MANAGER_OUT: ROLE_GM,
}


# =====================================================================================
# 权限位（机主可编辑 / GM 只读预览）
# =====================================================================================
def normalize_role(role: object) -> str:
    """任意角色表示 → 编辑器角色（owner/gm）；未知身份安全失败为只读（gm）。"""
    raw = str(role or "").strip().lower()
    if raw in ALL_ROLES:
        return raw
    if raw in _OUT_TO_ROLE:
        return _OUT_TO_ROLE[raw]
    return ROLE_GM


def is_editable(role: object) -> bool:
    """当前身份是否可编辑（机主 True / GM 只读 False）。"""
    return normalize_role(role) in EDITABLE_ROLES


def require_edit(role: object) -> None:
    """写入前置权限断言：只读角色 → Forbidden(403)，绝不落盘。"""
    if not is_editable(role):
        raise api.Forbidden(
            "当前身份为只读预览，不能写入内容；请切换为可编辑身份后重试。")


def session_info(role: object) -> Dict[str, Any]:
    """会话身份信息（顶栏身份/权限开关的数据源）。"""
    r = normalize_role(role)
    return {
        "role": r,
        "label": _ROLE_LABELS.get(r, r),
        "editable": is_editable(r),
        "roles": [
            {"value": x, "label": _ROLE_LABELS.get(x, x), "editable": is_editable(x)}
            for x in ALL_ROLES
        ],
    }


# =====================================================================================
# 响应包络（统一 {ok, errors, warnings} 形态；错误/提示均为「人话」条目）
# =====================================================================================
def _envelope(**kw: Any) -> Dict[str, Any]:
    env: Dict[str, Any] = {
        "ok": False,
        "phase": "validate",
        "pack": "",
        "module": "",
        "entry_id": "",
        "level": "ok",
        "errors": [],
        "warnings": [],
        "changed_fields": [],
        "written": [],
        "restored": [],
        "backup": None,
        "rolled_back": False,
        "message": "",
        "meta_source": api.META_SOURCE,
    }
    env.update(kw)
    return env


def _scope_prefix(slot: Mapping[str, Any]) -> str:
    """条目在字段路径里的前缀（校验器 field 形如 `模块.<槽位>.<字段…>`）。"""
    s = slot.get("slot")
    if s is None:
        return str(slot.get("module") or "")
    return f"{slot.get('module')}.{s}"


def _field_key(field: str, prefix: str, module: str) -> str:
    """从校验器字段路径里取「条目内字段键」（首段；无则空串）。"""
    f = str(field or "")
    if f == prefix or f in ("", module):
        return ""
    for head in (prefix + ".", module + "."):
        if f.startswith(head):
            rest = f[len(head):]
            if head == module + "." and "." in rest:
                rest = rest.split(".", 1)[1]  # 去掉槽位段
            return rest
    return f


def _decorate(items: Sequence[Mapping[str, Any]], slot: Mapping[str, Any],
              prefix: str, *, related_only: bool) -> List[Dict[str, Any]]:
    """校验条目 → 界面人话条目：补 条目/字段中文名 + 「怎么改」提示 + 是否与本次改动相关。

    · related：字段路径落在本次改动条目内（或为模块级提示）；
    · how_to_fix：优先用字段元数据自带提示（类型/必填/枚举/引用/范围），不新写规则。
    """
    module = str(slot.get("module") or "")
    base = slot.get("base")
    base = base if isinstance(base, Mapping) else {}
    out: List[Dict[str, Any]] = []
    for it in items:
        field = str(it.get("field") or "")
        fk = _field_key(field, prefix, module)
        root_key = fk.split(".", 1)[0] if fk else ""
        fm = base.get(root_key) if root_key else None
        entry_related = field == prefix or field.startswith(prefix + ".")
        module_related = field == module or field.startswith(module + ".")
        related = bool(entry_related or module_related)
        if related_only and not related:
            continue
        label = (fm.label if isinstance(fm, FieldMeta) and fm.label else root_key) or "（条目级）"
        item = dict(it)
        item.update({
            "module": module,
            "entry_id": str(slot.get("entry_id") or ""),
            "field_key": fk,
            "field_label": label,
            "related": related,
            "how_to_fix": api._hint(fm) if isinstance(fm, FieldMeta) else "",
        })
        if not item["how_to_fix"]:
            item["how_to_fix"] = "请按该字段的类型与取值要求修正后重试。"
        out.append(item)
    return out


# =====================================================================================
# 补丁应用（只改「现有条目的字段值」；批6 才做增删条目）
# =====================================================================================
def _apply_patch(subject: object, patch: Mapping[str, Any],
                 allowed: Sequence[str]) -> object:
    """把字段补丁应用到条目副本（纯逻辑，绝不改原数据）。

    · patch 值非 None → 覆盖该字段；值为 None → 删除该字段（回到「未声明」态）；
    · 补丁键必须在「元数据声明 ∪ 条目已有键」内，否则 BadRequest（不静默丢弃、不写脏键）；
    · 标量条目（object 模块的顶层标量键）：取补丁单值整体替换。
    """
    allow = set(allowed)
    unknown = sorted(str(k) for k in patch if k not in allow)
    if unknown:
        raise api.BadRequest("补丁含未登记字段（已拒绝写入）：" + "、".join(unknown))
    if isinstance(subject, Mapping):
        new = copy.deepcopy(dict(subject))
        for k, v in patch.items():
            if v is None:
                new.pop(str(k), None)
            else:
                new[str(k)] = copy.deepcopy(v)
        return new
    if not patch:
        return copy.deepcopy(subject)
    value = copy.deepcopy(list(patch.values())[-1])
    return subject if value is None else value


def _build_new_content(slot: Mapping[str, Any], new_subject: object) -> object:
    """用改后的条目替换模块数据里的对应槽位（深拷贝；原数据不动）。"""
    data = slot.get("data")
    pos = slot.get("slot")
    if isinstance(data, list) and isinstance(pos, int):
        content = copy.deepcopy(data)
        content[pos] = new_subject
        return content
    if isinstance(data, Mapping) and isinstance(pos, str):
        content = copy.deepcopy(dict(data))
        content[pos] = new_subject
        return content
    return copy.deepcopy(new_subject)


def _modules_with(modules_raw: Mapping[str, Any], module: str,
                  new_content: object) -> Dict[str, Any]:
    """写入后的整包视图（校验数据源）：list 模块走「变更条目形态」，其余直拷贝替换。

    atomic_store.apply_module_changes 的 entries 契约是数组（既有测试固定该语义），
    故 map/object 模块不在其列，直接对整包副本替换该模块段（同为纯逻辑）。
    """
    if isinstance(new_content, list):
        applied = atomic_store.apply_module_changes(
            modules_raw, [{"module": module, "entries": new_content}],
            changed_modules=[module])
        return applied["modules"]
    new_modules = copy.deepcopy(dict(modules_raw))
    new_modules[module] = copy.deepcopy(new_content)
    return new_modules


def _plan(pack: object, module: object, entry_id: object, patch: object,
          root: Optional[object], meta: Optional[FieldMetaTable]) -> Any:
    """定位条目 → 应用补丁 → 生成整包视图 → 跑现有校验器（纯计算，绝不写盘）。"""
    if not isinstance(patch, Mapping):
        raise api.BadRequest("改动内容形态非法（应为「字段 → 值」对象）。")
    slot = api.entry_slot(pack, module, entry_id, root=root)
    subject = slot["subject"]
    allowed: List[str] = [str(k) for k in slot["base"]]
    if isinstance(subject, Mapping):
        allowed += [str(k) for k in subject]
    new_subject = _apply_patch(subject, patch, allowed)
    new_content = _build_new_content(slot, new_subject)
    _pack_dir, modules_raw = api.load_pack_modules(pack, root=root)
    new_modules = _modules_with(modules_raw, slot["module"], new_content)
    report = check_pack(new_modules, meta)
    return slot, new_content, report


def _split_report(report: Any, slot: Mapping[str, Any]) -> Any:
    prefix = _scope_prefix(slot)
    reds = _decorate(atomic_store.humanize_errors(report.errors), slot, prefix,
                     related_only=False)
    yellows = _decorate(atomic_store.humanize_warnings(report.warnings), slot, prefix,
                        related_only=True)
    return reds, yellows


def _related_to_slot(items: Sequence[Mapping[str, Any]], slot: Mapping[str, Any],
                     module: str) -> List[Dict[str, Any]]:
    """把「已装饰」的提示再收敛到目标槽位：条目级（`模块.<槽位>.*`）或模块级（`模块`）。

    `_decorate` 的 related 判定含 module_related（`field.startswith(模块 + ".")`），会把
    **同模块其他条目**的提示也算成相关；新增/删除时那会造成一串与本次操作无关的黄提示。
    本过滤只保留目标槽位自身与真正的模块级提示（不改变任何校验规则）。
    """
    prefix = _scope_prefix(slot)
    out: List[Dict[str, Any]] = []
    for it in items:
        field = str(it.get("field") or "")
        if field == module or field == prefix or field.startswith(prefix + "."):
            out.append(dict(it))
    return out


# =====================================================================================
# 校验（不落盘）
# =====================================================================================
def validate_entry(pack: object, module: object, entry_id: object, patch: object, *,
                   root: Optional[object] = None, role: object = ROLE_OWNER,
                   meta: Optional[FieldMetaTable] = None) -> Dict[str, Any]:
    """保存前预检：跑现有校验器，返回红拦/黄提示（绝不写盘）。

    红拦非空 → ok=false（界面据此阻断保存）；黄提示 → 仍 ok=true，界面标出。
    """
    slot, _content, report = _plan(pack, module, entry_id, patch, root, meta)
    reds, yellows = _split_report(report, slot)
    level = "red" if not report.ok else ("yellow" if yellows else "ok")
    return _envelope(
        ok=bool(report.ok), phase="validate", pack=str(pack), module=str(slot["module"]),
        entry_id=str(entry_id), level=level, errors=reds, warnings=yellows,
        changed_fields=sorted(str(k) for k in (patch or {})),
        message=("校验通过。" if report.ok and not yellows
                 else ("校验通过（有黄提示）。" if report.ok else "校验未通过（红拦）。")),
    )


# =====================================================================================
# 落盘（备份 → 原子写 → 回读复核）
# =====================================================================================
def _verify_after_write(pack: object, ground_slot: Mapping[str, Any],
                        root: Optional[object], meta: Optional[FieldMetaTable],
                        tolerate: Optional[Callable[[Any], bool]] = None
                        ) -> Optional[List[Dict[str, Any]]]:
    """回读落盘结果 + 整包复校：通过 → None；不通过 → 人话红拦（用于触发自动回退）。

    `tolerate`：可选的「容忍判定」——返回 True 的红拦不计入复核失败。
    仅供「删除被引用条目」这类**产品明确允许**的场景使用（见 delete_entry）；默认 None
    = 一律不容忍，批2 保存链语义零变化。
    """
    try:
        _pack_dir, modules = api.load_pack_modules(pack, root=root)
        report = check_pack(modules, meta)
    except Exception as exc:  # 读回失败也算复核失败（不得假成功）
        return [{"level": "red", "code": "verify_failed", "module": str(ground_slot.get("module")),
                 "field": "", "entry_id": str(ground_slot.get("entry_id")),
                 "field_key": "", "field_label": "（整包）", "related": True,
                 "message": f"写入后回读复核失败：{type(exc).__name__}",
                 "how_to_fix": "请检查磁盘状态后重试；必要时用「回退」恢复上一份备份。"}]
    raw_errors = list(report.errors)
    if tolerate is not None:
        raw_errors = [e for e in raw_errors if not tolerate(e)]
    if not raw_errors:
        return None
    prefix = _scope_prefix(ground_slot)
    return _decorate(atomic_store.humanize_errors(raw_errors), ground_slot, prefix,
                     related_only=False)


def save_entry(pack: object, module: object, entry_id: object, patch: object, *,
               root: Optional[object] = None, role: object = ROLE_OWNER,
               meta: Optional[FieldMetaTable] = None) -> Dict[str, Any]:
    """编辑落盘唯一入口：红拦不落盘 → 备份 → 原子写 → 回读复核。

    任一环节失败都返回 ok=false 且**不假成功**：
      · 红拦 → 零文件改动；
      · 备份失败 → 取消写入（包未被改动）；
      · 写入失败 → 原子写未完成（文件未改动）；
      · 复核失败 → 自动回退到备份（rolled_back 标出，回退失败也如实上报）。
    """
    require_edit(role)
    slot, new_content, report = _plan(pack, module, entry_id, patch, root, meta)
    reds, yellows = _split_report(report, slot)
    env = _envelope(
        phase="save", pack=str(pack), module=str(slot["module"]), entry_id=str(entry_id),
        errors=reds, warnings=yellows, changed_fields=sorted(str(k) for k in (patch or {})),
    )
    if not report.ok:
        env.update(level="red", message="校验未通过：本次未写入任何文件（红拦）。")
        return env

    pack_dir = slot["pack_dir"]
    mod = str(slot["module"])

    backup = atomic_store.backup_modules(pack_dir, [mod])
    if not backup.get("ok"):
        env.update(level="red", message="备份失败，已取消本次写入（内容包未被改动）。")
        env["errors"] = list(backup.get("errors") or []) + env["errors"]
        return env

    written = atomic_store.write_modules(pack_dir, {mod: new_content})
    if not written.get("ok"):
        env.update(level="red", message="写入失败：文件未改动（原子写未完成）。")
        env["errors"] = list(written.get("errors") or []) + env["errors"]
        return env

    verify_errors = _verify_after_write(pack, slot, root, meta)
    if verify_errors is not None:
        rolled = atomic_store.restore_modules_from_backup(pack_dir, [mod])
        env.update(level="red", rolled_back=bool(rolled.get("ok")))
        env["errors"] = verify_errors + env["errors"]
        env["message"] = ("写入后复核未通过，已自动回退到上一份备份（本次改动未生效）。"
                          if rolled.get("ok") else
                          "写入后复核未通过，且自动回退失败：请立即用「回退」或手动检查备份。")
        return env

    env.update(
        ok=True, level=("yellow" if yellows else "ok"),
        written=list(written.get("written") or []),
        backup=atomic_store.backup_status(pack_dir, mod),
        message=("已保存（含黄提示，可继续修改）。" if yellows else "已保存。"),
    )
    return env


# =====================================================================================
# 批6：新增条目（模块级）——建议 ID 唯一性 → 元数据默认值 → 批2 同一落盘链路
# =====================================================================================
def _plan_create(pack: object, module: object, entry_id: str, patch: object,
                 root: Optional[object], meta: Optional[FieldMetaTable]) -> Any:
    """新增条目的纯计算规划：定位模块 → 补默认值/补丁 → 生成整包视图 → 跑校验器。"""
    if not isinstance(patch, Mapping):
        raise api.BadRequest("改动内容形态非法（应为「字段 → 值」对象）。")
    info = api.new_entry_slot(pack, module, entry_id, root=root)
    etype = str(info["entry_type"])
    id_field = str(info["id_field"])
    allowed = [str(k) for k in info["base"]]
    if etype == "list":
        allowed.append(id_field)
    subject = _apply_patch(info["subject"], patch, allowed)
    subject = dict(subject) if isinstance(subject, Mapping) else {}
    if etype == "list":
        subject[id_field] = entry_id
    data = info["data"]
    content: object
    if etype == "list":
        content = list(data) if isinstance(data, list) else []
        content.append(subject)
    elif isinstance(data, Mapping):
        content = copy.deepcopy(dict(data))
        content[entry_id] = subject
    else:
        content = {entry_id: subject}
    _pack_dir, modules_raw = api.load_pack_modules(pack, root=root)
    new_modules = _modules_with(modules_raw, str(info["module"]), content)
    report = check_pack(new_modules, meta)
    return info, content, report


def create_entry(pack: object, module: object, entry_id: object, patch: object, *,
                 root: Optional[object] = None, role: object = ROLE_OWNER,
                 meta: Optional[FieldMetaTable] = None) -> Dict[str, Any]:
    """新增条目唯一入口：ID 唯一性红拦 → 校验 → 备份 → 原子写 → 回读复核（同批2 链路）。

    · ID 为空/非法/同模块或同命名空间重复 → ok=false 且零文件改动（红拦）；
    · 其余字段按元数据 default 初始化后再叠加 patch（未登记字段 BadRequest，不写脏键）；
    · 校验红拦不落盘；通过则备份 .bak → 原子写 → 回读复核，失败自动回退。
    """
    require_edit(role)
    eid = str(entry_id or "").strip()
    check = api.check_entry_id(pack, module, eid, root=root, meta=meta)
    env = _envelope(phase="create", pack=str(pack), module=str(module), entry_id=eid,
                    changed_fields=sorted(str(k) for k in (patch or {})))
    if not check.get("ok"):
        env.update(level="red", message=str(check.get("message") or "ID 校验未通过。"))
        env["errors"] = [{
            "level": "red", "code": "id_invalid", "module": str(module),
            "field": "", "entry_id": eid, "field_key": "", "field_label": "（条目 ID）",
            "related": True, "message": str(check.get("message") or ""),
            "how_to_fix": str(check.get("how_to_fix") or ""),
        }]
        env["id_check"] = check
        return env

    info, content, report = _plan_create(pack, module, eid, patch, root, meta)
    reds, yellows = _split_report(report, info)
    # 黄提示只留新条目自身（同模块其他条目的黄提示与本次新增无关）
    yellows = _related_to_slot(yellows, info, str(info["module"]))
    env = _envelope(phase="create", pack=str(pack), module=str(info["module"]),
                    entry_id=eid, errors=reds, warnings=yellows,
                    changed_fields=sorted(str(k) for k in (patch or {})))
    if not report.ok:
        env.update(level="red", message="校验未通过：本次未新增任何内容（红拦）。")
        return env

    pack_dir = info["pack_dir"]
    mod = str(info["module"])
    backup = atomic_store.backup_modules(pack_dir, [mod])
    if not backup.get("ok"):
        env.update(level="red", message="备份失败，已取消本次新增（内容包未被改动）。")
        env["errors"] = list(backup.get("errors") or []) + env["errors"]
        return env

    written = atomic_store.write_modules(pack_dir, {mod: content})
    if not written.get("ok"):
        env.update(level="red", message="写入失败：文件未改动（原子写未完成）。")
        env["errors"] = list(written.get("errors") or []) + env["errors"]
        return env

    verify_errors = _verify_after_write(pack, info, root, meta)
    if verify_errors is not None:
        rolled = atomic_store.restore_modules_from_backup(pack_dir, [mod])
        env.update(level="red", rolled_back=bool(rolled.get("ok")))
        env["errors"] = verify_errors + env["errors"]
        env["message"] = ("写入后复核未通过，已自动回退到上一份备份（本次新增未生效）。"
                          if rolled.get("ok") else
                          "写入后复核未通过，且自动回退失败：请立即用「回退」或手动检查备份。")
        return env

    env.update(
        ok=True, level=("yellow" if yellows else "ok"),
        written=list(written.get("written") or []),
        backup=atomic_store.backup_status(pack_dir, mod),
        message=f"已新增条目「{eid}」。",
    )
    return env


# =====================================================================================
# 批6：删除条目（含「被引用检查」；引用者默认黄提示、不拦）
# =====================================================================================
def _remove_entry(data: object, slot: object, entry_id: object) -> object:
    """从模块数据里移除条目（深拷贝；list 按下标，map/object 按键）。"""
    if isinstance(data, list) and isinstance(slot, int):
        out = copy.deepcopy(data)
        if 0 <= slot < len(out):
            del out[slot]
        return out
    if isinstance(data, Mapping):
        out = copy.deepcopy(dict(data))
        out.pop(str(entry_id), None)
        return out
    return copy.deepcopy(data)


def _is_dangling_to(entry_id: object) -> Callable[[Any], bool]:
    """容忍判定：仅「指向被删条目的 R-4 引用缺失」不算复核失败。

    产品语义（需求 §三/批6）：删除被引用条目默认不拦、只黄提示 → 删除后遗留的悬空引用
    不是本次写入的失败；其余任何红拦仍照常阻断/回退。
    """
    tgt = str(entry_id)

    def _pred(error: Any) -> bool:
        kind = str(getattr(error, "kind", "") or "")
        detail = dict(getattr(error, "detail", {}) or {})
        return kind == "R-4" and str(detail.get("ref") or "") == tgt

    return _pred


def reference_warnings(referrers: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """引用者 → 界面黄提示条目（人话：谁、哪个字段引用了它）。"""
    out: List[Dict[str, Any]] = []
    for r in referrers:
        label = str(r.get("field_label") or r.get("field") or "")
        out.append({
            "level": "yellow", "code": "entry_referenced",
            "module": str(r.get("module") or ""), "field": str(r.get("field") or ""),
            "entry_id": str(r.get("entry_id") or ""), "field_key": str(r.get("field") or ""),
            "field_label": label, "related": True,
            "message": (f"{r.get('module_label') or r.get('module')}「{r.get('entry_name')}」的"
                        f"「{label}」引用了它（值 = {r.get('value')}）。"),
            "how_to_fix": ("如需保持引用完整，请先修改或删除这些引用者；"
                           "也可用「回退到上一份备份」撤销本次删除。"),
        })
    return out


def delete_entry(pack: object, module: object, entry_id: object, *,
                 root: Optional[object] = None, role: object = ROLE_OWNER,
                 meta: Optional[FieldMetaTable] = None) -> Dict[str, Any]:
    """删除条目唯一入口：被引用检查（黄提示）→ 校验 → 备份 → 原子写 → 回读复核。

    · 先扫描「谁引用了它」并作为黄提示返回（默认**不拦**）；
    · 仅「指向被删条目的引用缺失（R-4）」被容忍；其余红拦一律不落盘；
    · 删除前自动备份 .bak，落盘失败/复核失败自动回退（可再用「回退」恢复）。
    """
    require_edit(role)
    slot = api.entry_slot(pack, module, entry_id, root=root)
    mod = str(slot["module"])
    referrers = api.reference_scan(pack, mod, entry_id, root=root, meta=meta)
    new_content = _remove_entry(slot["data"], slot["slot"], entry_id)
    _pack_dir, modules_raw = api.load_pack_modules(pack, root=root)
    new_modules = _modules_with(modules_raw, mod, new_content)
    report = check_pack(new_modules, meta)
    tolerate = _is_dangling_to(entry_id)
    blocking = [e for e in report.errors if not tolerate(e)]
    prefix = _scope_prefix(slot)
    ref_warnings = reference_warnings(referrers)
    yellows = _decorate(atomic_store.humanize_warnings(report.warnings), slot, prefix,
                        related_only=True)
    yellows = _related_to_slot(yellows, slot, mod)
    env = _envelope(phase="delete", pack=str(pack), module=mod, entry_id=str(entry_id),
                    warnings=ref_warnings + yellows, referrers=referrers)
    if blocking:
        env.update(level="red", message="删除后整包校验出现新的红拦：本次未写入任何文件。")
        env["errors"] = _decorate(atomic_store.humanize_errors(blocking), slot, prefix,
                                  related_only=False)
        return env

    pack_dir = slot["pack_dir"]
    backup = atomic_store.backup_modules(pack_dir, [mod])
    if not backup.get("ok"):
        env.update(level="red", message="备份失败，已取消本次删除（内容包未被改动）。")
        env["errors"] = list(backup.get("errors") or []) + env["errors"]
        return env

    written = atomic_store.write_modules(pack_dir, {mod: new_content})
    if not written.get("ok"):
        env.update(level="red", message="写入失败：文件未改动（原子写未完成）。")
        env["errors"] = list(written.get("errors") or []) + env["errors"]
        return env

    verify_errors = _verify_after_write(pack, slot, root, meta, tolerate=tolerate)
    if verify_errors is not None:
        rolled = atomic_store.restore_modules_from_backup(pack_dir, [mod])
        env.update(level="red", rolled_back=bool(rolled.get("ok")))
        env["errors"] = verify_errors + env["errors"]
        env["message"] = ("删除后回读复核未通过，已自动回退到上一份备份（本次删除未生效）。"
                          if rolled.get("ok") else
                          "删除后复核未通过，且自动回退失败：请立即用「回退」或手动检查备份。")
        return env

    msg = f"已删除条目「{entry_id}」。"
    if referrers:
        msg += f" 有 {len(referrers)} 个条目仍引用它（黄提示，未拦截）。"
    env.update(
        ok=True, level=("yellow" if (ref_warnings or yellows) else "ok"),
        written=list(written.get("written") or []),
        backup=atomic_store.backup_status(pack_dir, mod),
        message=msg,
    )
    return env


# =====================================================================================
# 备份可见性 / 回退
# =====================================================================================
def module_backup(pack: object, module: object, *,
                  root: Optional[object] = None) -> Dict[str, Any]:
    """模块备份状态（回退入口可见性；只读）。"""
    pack_dir = api._pack_dir(pack, root)
    mod = api.declared_module(pack, module, root=root)
    status = atomic_store.backup_status(pack_dir, mod)
    return {"pack": str(pack), "module": mod, **status}


def rollback_module(pack: object, module: object, *,
                    root: Optional[object] = None, role: object = ROLE_OWNER,
                    meta: Optional[FieldMetaTable] = None) -> Dict[str, Any]:
    """回退到上一份备份（.bak → 原子恢复 → 复核）；只读身份拒绝。"""
    require_edit(role)
    pack_dir = api._pack_dir(pack, root)
    mod = api.declared_module(pack, module, root=root)
    status = atomic_store.backup_status(pack_dir, mod)
    env = _envelope(phase="rollback", pack=str(pack), module=mod)
    if not status.get("exists"):
        env.update(level="red", message="没有可回退的备份。")
        env["errors"] = [{
            "level": "red", "code": "no_backup", "module": mod, "field": "",
            "entry_id": "", "field_key": "", "field_label": "（模块级）", "related": True,
            "message": f"模块「{mod}」没有备份文件（{status.get('path')} 不存在）。",
            "how_to_fix": "先保存一次以生成备份，之后才能回退。",
        }]
        return env

    restored = atomic_store.restore_modules_from_backup(pack_dir, [mod])
    if not restored.get("ok"):
        env.update(level="red", message="回退失败：文件未被改动。")
        env["errors"] = list(restored.get("errors") or [])
        return env

    verify_errors = _verify_after_write(pack, {"module": mod, "entry_id": ""}, root, meta)
    if verify_errors is not None:
        env.update(level="red", message="回退后的内容未通过校验，请检查备份。")
        env["errors"] = verify_errors
        return env

    env.update(
        ok=True, level="ok", rolled_back=True,
        restored=list(restored.get("restored") or []),
        backup=atomic_store.backup_status(pack_dir, mod),
        message="已回退到上一份备份。",
    )
    return env


__all__ = [
    "ALL_ROLES",
    "EDITABLE_ROLES",
    "ROLE_GM",
    "ROLE_OWNER",
    "create_entry",
    "delete_entry",
    "is_editable",
    "module_backup",
    "normalize_role",
    "reference_warnings",
    "require_edit",
    "rollback_module",
    "save_entry",
    "session_info",
    "validate_entry",
]
