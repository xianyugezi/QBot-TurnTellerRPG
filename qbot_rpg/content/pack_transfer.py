"""内容包导出 / 导入（编辑器重写批11 · 让作者之间互相分享内容包）。

对外两个动作（编辑器 `/api/pack/{pack}/export`、`/api/pack/import` 与 CLI
`scripts/pack_transfer.py` 共用本层，写盘链路唯一）：

    export_pack_dir(pack_dir, ...)  -> {ok, data(bytes), filename, meta, files}
        把包目录下全部数据文件（`*.json`）+ 可选 `*.md` 打成一个 zip 字节流，
        另附 `export_meta.json`（包 id / 名称 / 版本 / TTR 版本或提交号 / 导出时间 /
        文件清单与 sha256）。**不改内容包、不写任何文件**（下载落盘由宿主负责）。

    import_archive(data, content_root, ...) -> {ok, pack_id, written, ...}
        分享来的 zip → ①结构安全 ②export_meta/manifest 合法 ③过现有内容校验器
        ④包 id 冲突处理（改名 / 覆盖且先备份）→ 通过才落盘；落盘 = 先在
        `<content-root>/.ttrpack_tmp_*` 写全文件，再 `os.replace` 原子搬成
        `content/<pack_id>`（**新建一个包目录**，失败不留半成品）。

安全防护（本批重点，逐条实现）：
  1. **Zip Slip**：条目名先经 `_safe_entry_name` —— 拒绝绝对路径、盘符、`\\`、
     NUL、`.`/`..` 段、非扁平（多层目录）；**符号链接条目一律拒绝**（按 external_attr
     的文件类型位判定）→ 任何条目都不可能写到目标目录之外。
  2. **文件类型白名单**：只收 `.json` / `.md`；`.py/.sh/.exe/.so/...` 与无后缀一律拒绝。
  3. **体积上限**：压缩包体积 / 单文件解压后 / 解压后总量 / 条目数 四项上限 +
     单文件压缩比上限（防 zip bomb），超限给人话报错。
  4. **完整性**：`export_meta.json` 的文件清单逐条比对 sha256 与大小；出现未登记文件、
     清单缺文件、哈希不符一律拒绝（防半路篡改）。
  5. **过校验器**：`qbot_rpg.content.validator.check_pack`（现有唯一校验入口，**不新写规则**）
     红拦 → 不落盘；黄提示放行但如实返回。
  6. **失败不留残留**：全部校验在内存里完成后才写盘；写盘只落在临时目录，成功才原子搬迁，
     `finally` 清理临时目录；覆盖前把旧包整体原子移到 `.ttrpack_backups/`（失败自动复原）。

铁律：零 NoneBot import；内容层不 import web 层；权限位由调用方（editor_ops / CLI）判定，
本层不做角色判断（导出对只读身份也允许，导入是否放行由写层 require_edit 决定）。
通用性：不写死任何包名 / 模块名 / 业务字段名；换任意包零改动可用
（判断标准见 docs/编辑器重写_需求与约束.md 第〇节）。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Tuple

from qbot_rpg.content import atomic_store
from qbot_rpg.content import field_meta_pack as pack_meta
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack

# -------------------------------------------------------------------------------------
# 格式常量
# -------------------------------------------------------------------------------------
TTRPACK_EXT = ".ttrpack"
EXPORT_META_NAME = "export_meta.json"
MANIFEST_NAME = "manifest.json"
FIELD_META_NAME = "field_meta.json"
FORMAT_NAME = "ttrpack"
FORMAT_VERSION = 1
ALLOWED_SUFFIXES: Tuple[str, ...] = (".json", ".md")
# 与 web/api.py 同一包名规则（首字符非点，杜绝 `..` / 隐藏名）。
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")
# 备份目录（内容根下隐藏目录；顶层无 manifest.json，不会被包列表当成内容包）。
BACKUP_DIRNAME = ".ttrpack_backups"
TMP_PREFIX = ".ttrpack_tmp_"


@dataclass(frozen=True)
class TransferLimits:
    """导入体积/条目上限（人话报错用；导出不受限——本地可信数据）。"""

    max_archive_bytes: int = 64 * 1024 * 1024     # 压缩包本身 ≤ 64 MB
    max_total_bytes: int = 256 * 1024 * 1024       # 解压后总量 ≤ 256 MB
    max_file_bytes: int = 32 * 1024 * 1024         # 单文件解压后 ≤ 32 MB
    max_entries: int = 1024                        # 条目数 ≤ 1024
    max_ratio: int = 200                           # 单文件压缩比 ≤ 200:1（防 zip bomb）


DEFAULT_LIMITS = TransferLimits()


# -------------------------------------------------------------------------------------
# 人话报错
# -------------------------------------------------------------------------------------
def human_bytes(n: int) -> str:
    """字节数 → 人话（B / KB / MB / GB）。"""
    step = 1024.0
    val = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if val < step or unit == "GB":
            return f"{val:.0f} {unit}" if unit == "B" else f"{val:.1f} {unit}"
        val /= step
    return f"{val:.1f} GB"


def _err(code: str, message: str, how_to_fix: str = "") -> Dict[str, Any]:
    """统一错误条目（与 editor_ops 包络同形：level/code/message/how_to_fix）。"""
    return {
        "level": "red", "code": code, "module": "", "field": "", "entry_id": "",
        "field_key": "", "field_label": "（内容包）", "related": True,
        "message": message, "how_to_fix": how_to_fix,
    }


def _fail(code: str, message: str, how_to_fix: str = "", **extra: Any) -> Dict[str, Any]:
    """失败包络：{ok:false, message, errors[]} + 该场景附加字段（conflict/pack_id…）。"""
    env: Dict[str, Any] = {
        "ok": False, "phase": "import", "errors": [_err(code, message, how_to_fix)],
        "warnings": [], "message": message,
    }
    env.update(extra)
    return env


# -------------------------------------------------------------------------------------
# 基本信息
# -------------------------------------------------------------------------------------
def ttr_version() -> str:
    """TTR 版本号（qbot_rpg 包版本；导出元信息用）。"""
    from qbot_rpg import __version__  # 延迟 import，避免无谓的包初始化
    return str(__version__ or "")


def ttr_commit(repo_root: Optional[object] = None) -> str:
    """TTR 提交号（尽力而为：优先环境变量 TTR_COMMIT，其次 git short HEAD；取不到空串）。

    不抛异常——导出绝不因拿不到提交号失败（元信息如实留空即可）。
    """
    env = str(os.environ.get("TTR_COMMIT") or "").strip()
    if env:
        return env
    root = Path(str(repo_root)) if repo_root is not None else Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        return ""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _now_utc(now: Optional[datetime]) -> datetime:
    return now.astimezone(timezone.utc) if now is not None else datetime.now(timezone.utc)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ascii_slug(text: object) -> str:
    """包中文名 → 文件名可用 ASCII 片段（取不出 → 空串，回退用包 id）。"""
    out = re.sub(r"[^A-Za-z0-9_-]+", "-", str(text or "")).strip("-")
    return out[:48]


def export_filename(pack_id: str, pack_name: object = "", now: Optional[datetime] = None) -> str:
    """下载文件名：含包名与日期（如 `pack-id-20260914.ttrpack`）。"""
    date = _now_utc(now).strftime("%Y%m%d")
    slug = _ascii_slug(pack_name) or _ascii_slug(pack_id) or "pack"
    stem = f"{slug}-{pack_id}" if slug and slug != pack_id else pack_id
    if not _SAFE_COMPONENT.match(stem):
        stem = pack_id if _SAFE_COMPONENT.match(pack_id) else "pack"
    return f"{stem}-{date}{TTRPACK_EXT}"


# =====================================================================================
# 导出
# =====================================================================================
def _read_json_file(path: Path) -> Optional[object]:
    """读 JSON（不存在 → None；坏 JSON → 抛 ValueError 带人话）。"""
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise ValueError(f"读取/解析 JSON 失败：{path.name}（{exc}）") from exc


def collect_export_files(pack_dir: Path) -> List[Tuple[str, bytes]]:
    """包目录下要导出的文件（顶层、非符号链接、`*.json` / `*.md`，排除预留 export_meta）。

    只取**顶层**文件：内容包的数据文件形态就是 `content/<包>/<模块>.json`（扁平），
    子目录与 `.bak` / `.tmp` 备份一律不进包。返回 [(文件名, 原始字节)]，按文件名排序。
    """
    out: List[Tuple[str, bytes]] = []
    for path in sorted(Path(pack_dir).iterdir(), key=lambda p: p.name):
        if path.name == EXPORT_META_NAME:
            continue
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        out.append((path.name, path.read_bytes()))
    return out


def export_pack_dir(pack_dir: object, *, pack_id: Optional[str] = None,
                    now: Optional[datetime] = None, ttr_ver: Optional[str] = None,
                    ttr_commit_hash: Optional[str] = None) -> Dict[str, Any]:
    """把内容包目录打成一个 `.ttrpack`（zip 字节流）+ `export_meta.json`。只读，不写盘。

    出参：{ok, pack_id, pack_name, filename, data(bytes), meta(dict), files[{path,size,sha256}]}。
    """
    pdir = Path(str(pack_dir))
    pid = str(pack_id or pdir.name)
    if not _SAFE_COMPONENT.match(pid):
        return _fail("pack_id_invalid", f"包名非法，无法导出：{pid!r}。",
                     "请确认内容包目录名只含字母、数字、下划线、点或短横线。")
    try:
        manifest = _read_json_file(pdir / MANIFEST_NAME)
    except ValueError as exc:
        return _fail("manifest_invalid", str(exc), "请先修正 manifest.json 的 JSON 语法再导出。")
    if not isinstance(manifest, Mapping):
        return _fail("manifest_invalid", f"内容包缺少合法 manifest.json：{pid}。",
                     "内容包目录下必须有 manifest.json（对象）。")

    try:
        payload = collect_export_files(pdir)
    except OSError as exc:
        return _fail("read_failed", f"读取内容包文件失败：{type(exc).__name__}。",
                     "请检查文件权限或磁盘状态后重试。")

    stamp = _now_utc(now)
    files = [{"path": name, "size": len(raw), "sha256": _sha256(raw)} for name, raw in payload]
    meta: Dict[str, Any] = {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "pack_id": pid,
        "pack_name": str(manifest.get("name", "") or pid),
        "pack_version": str(manifest.get("version", "") or ""),
        "ttr_version": str(ttr_ver if ttr_ver is not None else ttr_version()),
        "ttr_commit": str(ttr_commit_hash if ttr_commit_hash is not None else ttr_commit()),
        "exported_at": stamp.isoformat(),
        "generator": "QBot-TurnTellerRPG content editor",
        "file_count": len(files),
        "total_bytes": sum(f["size"] for f in files),
        "files": files,
    }
    meta_bytes = json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")

    zip_date = (stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second)
    if zip_date[0] < 1980:  # zip 时间戳下限；异常时钟回退到固定值，不影响内容
        zip_date = (1980, 1, 1, 0, 0, 0)
    buf = io.BytesIO()
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, raw in payload:
                zf.writestr(_zip_info(name, zip_date), raw)
            zf.writestr(_zip_info(EXPORT_META_NAME, zip_date), meta_bytes)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return _fail("export_failed", f"打包失败：{type(exc).__name__}。",
                     "请检查磁盘空间后重试。")

    return {
        "ok": True, "phase": "export", "pack_id": pid,
        "pack_name": meta["pack_name"],
        "filename": export_filename(pid, meta["pack_name"], now=stamp),
        "data": buf.getvalue(), "meta": meta, "files": files,
        "errors": [], "warnings": [],
        "message": f"已导出内容包「{meta['pack_name']}」（{len(files)} 个文件）。",
    }


def _zip_info(name: str, date_time: Tuple[int, int, int, int, int, int]) -> zipfile.ZipInfo:
    """构造 zip 条目（固定权限 0644；日期来自导出时间，便于测试确定化）。"""
    zi = zipfile.ZipInfo(name, date_time=date_time)
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o644 << 16
    return zi


def write_pack_archive(pack_dir: object, file_path: object, *, pack_id: Optional[str] = None,
                       now: Optional[datetime] = None, ttr_ver: Optional[str] = None,
                       ttr_commit_hash: Optional[str] = None) -> Dict[str, Any]:
    """导出并**原子写**到指定文件（CLI 用）；写入前先出字节流，失败不产生半截文件。"""
    result = export_pack_dir(pack_dir, pack_id=pack_id, now=now, ttr_ver=ttr_ver,
                             ttr_commit_hash=ttr_commit_hash)
    if not result.get("ok"):
        return result
    target = Path(str(file_path))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(result["data"])
        os.replace(tmp, target)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except (OSError, UnboundLocalError):
            pass
        return _fail("write_failed", f"写入导出文件失败：{type(exc).__name__}。",
                     "请检查目标目录是否存在、是否有写权限与磁盘空间。")
    result = dict(result)
    result["path"] = str(target)
    return result


# =====================================================================================
# 导入 · ① zip 结构安全
# =====================================================================================
class _Reject(Exception):
    """导入拒绝（人话 message + code + how_to_fix），在内存校验阶段抛出。"""

    def __init__(self, code: str, message: str, how_to_fix: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.how_to_fix = how_to_fix


def _safe_entry_name(name: str) -> PurePosixPath:
    """zip 条目名安全判定（Zip Slip 防护）：不合法即 `_Reject`。

    拒绝：空名 / 绝对路径 / 盘符 / 反斜杠 / NUL / 首尾空白 / `.`·`..` 段。
    返回**相对路径**（可能多层，随后由 `_flatten_entries` 要求扁平）；
    任何一段都不可能是 `..`，因此拼出的目标路径永不可能越出目标目录。
    """
    if not isinstance(name, str) or not name:
        raise _Reject("bad_entry", "压缩包里有非法条目名（空名）。",
                      "请用编辑器「导出此包」重新导出的文件。")
    if "\x00" in name:
        raise _Reject("bad_entry", "压缩包条目名含非法空字符，已拒绝。",
                      "该文件可能被篡改；请让分享者重新导出。")
    if "\\" in name:
        raise _Reject("bad_entry", f"压缩包条目名含反斜杠（不允许）：{name!r}。",
                      "请用编辑器「导出此包」重新导出的文件。")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise _Reject("zip_slip", f"压缩包条目使用了绝对路径（可能想写到目标目录之外）：{name!r}。",
                      "这是危险文件，请勿导入；请让分享者用编辑器「导出此包」重新导出。")
    if name != name.strip():
        raise _Reject("bad_entry", f"压缩包条目名首尾含空白字符：{name!r}。",
                      "请用编辑器「导出此包」重新导出的文件。")
    parts = PurePosixPath(name.replace("\\", "/")).parts
    for part in parts:
        if part in ("", "."):
            raise _Reject("bad_entry", f"压缩包条目路径含空或「.」段：{name!r}。",
                          "请用编辑器「导出此包」重新导出的文件。")
        if part == "..":
            raise _Reject("zip_slip", f"压缩包条目想越出目标目录（含 `..`）：{name!r}。",
                          "这是危险文件，请勿导入；请让分享者用编辑器重新导出。")
    return PurePosixPath(*parts)


def _is_symlink_entry(zi: zipfile.ZipInfo) -> bool:
    """条目是否为符号链接（按 Unix 文件类型位判定；未记录类型位的视为普通文件）。"""
    mode = (zi.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _check_entry(zi: zipfile.ZipInfo) -> PurePosixPath:
    """单条目安全 + 类型校验 → 相对路径；不合法抛 `_Reject`。"""
    path = _safe_entry_name(zi.filename)
    name = path.name
    if _is_symlink_entry(zi):
        raise _Reject("symlink", f"压缩包里的「{name}」是符号链接，已拒绝。",
                      "符号链接可能指向目标目录之外；请让分享者用编辑器重新导出。")
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise _Reject(
            "bad_file_type",
            f"内容包只允许 .json / .md 文件，压缩包里出现不允许的文件：{name}。",
            "可执行文件 / 脚本 / 二进制一律拒绝；请让分享者用编辑器「导出此包」重新导出。")
    return path


def _check_sizes(entries: List[zipfile.ZipInfo], limits: TransferLimits) -> None:
    """体积/条目数上限（含压缩比），超限抛 `_Reject`（人话）。"""
    if len(entries) > limits.max_entries:
        raise _Reject("too_many_entries",
                      f"压缩包条目数超过上限（上限 {limits.max_entries} 个，"
                      f"实际 {len(entries)} 个）。",
                      "请确认这是内容包文件；必要时联系分享者精简内容。")
    total = 0
    for zi in entries:
        size = int(zi.file_size)
        csize = int(zi.compress_size)
        if size > limits.max_file_bytes:
            raise _Reject("file_too_large",
                          f"文件「{zi.filename}」解压后超过单文件上限"
                          f"（上限 {human_bytes(limits.max_file_bytes)}，"
                          f"实际 {human_bytes(size)}）。",
                          "内容包文件不应这么大；请确认这是内容包而不是别的大文件。")
        if csize > 0 and size > csize * limits.max_ratio:
            raise _Reject("ratio_too_high",
                          f"文件「{zi.filename}」压缩比异常（{size}:{csize}），"
                          f"疑似压缩炸弹，已拒绝。",
                          "这是危险文件，请勿导入。")
        total += size
        if total > limits.max_total_bytes:
            raise _Reject("total_too_large",
                          f"解压后总大小超过上限"
                          f"（上限 {human_bytes(limits.max_total_bytes)}）。",
                          "请确认这是内容包文件；必要时联系分享者精简内容。")
    return None


def _read_entry_bytes(zf: zipfile.ZipFile, zi: zipfile.ZipInfo,
                      limit: int) -> bytes:
    """分块读取条目（读取时二次卡上限，防声明的 file_size 与实际不符）。"""
    chunks: List[bytes] = []
    got = 0
    with zf.open(zi, "r") as fh:
        while True:
            block = fh.read(65536)
            if not block:
                break
            got += len(block)
            if got > limit:
                raise _Reject("file_too_large",
                              f"文件「{zi.filename}」解压后超过单文件上限，已停止读取。",
                              "内容包文件不应这么大；请确认文件来源。")
            chunks.append(block)
    return b"".join(chunks)


# =====================================================================================
# 导入 · ② export_meta / manifest 合法性 + 完整性
# =====================================================================================
def _check_export_meta(raw: object) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """校验 export_meta.json → (meta, {path: {sha256,size}})；不合法抛 `_Reject`。"""
    if not isinstance(raw, Mapping):
        raise _Reject("export_meta_invalid", "export_meta.json 形态非法（应为对象）。",
                      "请让分享者用编辑器「导出此包」重新导出。")
    meta = dict(raw)
    if str(meta.get("format") or "") != FORMAT_NAME:
        raise _Reject("export_meta_invalid",
                      f"export_meta.json 的 format 不是 {FORMAT_NAME!r}"
                      f"（实际 {meta.get('format')!r}），可能不是内容包文件。",
                      "请确认选择的是编辑器导出的 .ttrpack 文件。")
    ver = meta.get("format_version")
    if not isinstance(ver, int) or isinstance(ver, bool) or ver != FORMAT_VERSION:
        raise _Reject("format_version",
                      f"不支持的导出格式版本：{ver!r}（本编辑器支持 {FORMAT_VERSION}）。",
                      "请升级编辑器，或让分享者用较新版本重新导出。")
    pid = str(meta.get("pack_id") or "")
    if not _SAFE_COMPONENT.match(pid):
        raise _Reject("pack_id_invalid",
                      f"export_meta.json 里的包标识非法：{pid!r}。",
                      "请让分享者用编辑器「导出此包」重新导出。")
    if not str(meta.get("exported_at") or ""):
        raise _Reject("export_meta_invalid", "export_meta.json 缺少导出时间（exported_at）。",
                      "请让分享者用编辑器「导出此包」重新导出。")
    raw_files = meta.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise _Reject("export_meta_invalid",
                      "export_meta.json 缺少文件清单（files）。",
                      "请让分享者用编辑器「导出此包」重新导出。")
    listing: Dict[str, Dict[str, Any]] = {}
    for item in raw_files:
        if not isinstance(item, Mapping):
            raise _Reject("export_meta_invalid", "export_meta.json 的文件清单有条目形态非法。",
                          "请让分享者用编辑器重新导出。")
        path = str(item.get("path") or "")
        digest = str(item.get("sha256") or "")
        size = item.get("size")
        if not path or not re.fullmatch(r"[0-9a-f]{64}", digest) \
                or not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise _Reject("export_meta_invalid",
                          f"export_meta.json 的文件清单条目非法：{item!r}。",
                          "请让分享者用编辑器重新导出。")
        if path in listing:
            raise _Reject("export_meta_invalid",
                          f"export_meta.json 的文件清单有重复条目：{path}。",
                          "请让分享者用编辑器重新导出。")
        listing[path] = {"sha256": digest, "size": size}
    return meta, listing


def _verify_integrity(payload: Mapping[str, bytes], listing: Mapping[str, Mapping[str, Any]],
                      pid: str) -> None:
    """清单 ↔ 实际文件逐条比对 sha256/大小；缺失/多余/不符 → `_Reject`。"""
    actual = {name: raw for name, raw in payload.items() if name != EXPORT_META_NAME}
    for path, want in listing.items():
        if path not in actual:
            raise _Reject("integrity_missing",
                          f"文件清单里的「{path}」在压缩包里找不到（文件可能不完整）。",
                          "请让分享者重新发送完整文件。")
        got = actual[path]
        if len(got) != want["size"] or _sha256(got) != want["sha256"]:
            raise _Reject("integrity_mismatch",
                          f"校验不一致：文件「{path}」的内容与导出时不同"
                          f"（可能被改动或传输损坏）。",
                          f"请让分享者重新导出内容包「{pid}」后再试。")
    extra = sorted(set(actual) - set(listing))
    if extra:
        raise _Reject("integrity_extra",
                      "压缩包里出现未登记在 export_meta.json 里的文件：" + "、".join(extra) + "。",
                      "该文件可能被篡改；请让分享者重新导出。")


def _check_manifest(raw: object) -> Dict[str, Any]:
    """manifest.json 合法性（对象；modules 若存在必须是字符串数组）。"""
    if not isinstance(raw, Mapping):
        raise _Reject("manifest_invalid",
                      "内容包缺少合法 manifest.json（应为对象）。",
                      "请让分享者用编辑器「导出此包」重新导出。")
    manifest = dict(raw)
    mods = manifest.get("modules")
    if mods is not None and (not isinstance(mods, list)
                             or any(not isinstance(m, str) for m in mods)):
        raise _Reject("manifest_invalid",
                      "manifest.json 的 modules 必须是字符串数组。",
                      "请让分享者修正 manifest.json 后重新导出。")
    return manifest


def _parse_json_payload(name: str, raw: bytes) -> object:
    """解析 payload 里的 JSON；坏 JSON → `_Reject`（人话，带文件名）。"""
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise _Reject("bad_json", f"文件「{name}」不是合法 JSON：{exc}。",
                      "请让分享者修正该文件后重新导出。") from exc


def _modules_from_payload(manifest: Mapping[str, Any],
                          payload: Mapping[str, bytes]) -> Tuple[Dict[str, Any], List[str]]:
    """按 manifest.modules 取模块数据（同 web/api.load_pack_modules 口径）。"""
    declared = [str(m) for m in (manifest.get("modules") or []) if isinstance(m, str) and m]
    modules: Dict[str, Any] = {}
    for mod in declared:
        fname = f"{mod}.json"
        if fname not in payload:
            continue
        modules[mod] = _parse_json_payload(fname, payload[fname])
    return modules, declared


def _decorate_validation_errors(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """校验红拦 → 导入场景的人话（补 how_to_fix；引用缺失单独给更具体的建议）。"""
    out: List[Dict[str, Any]] = []
    for item in items:
        row = dict(item)
        row["field_label"] = row.get("field_label") or "（内容包）"
        if str(row.get("code")) == "R-4":
            row["how_to_fix"] = ("这条引用指向的条目在包里不存在；请让分享者在原包里补上"
                                 "目标条目（或先删掉该引用）后重新导出。")
        else:
            row["how_to_fix"] = "请在原包里修正该问题后重新导出，或联系分享者处理。"
        out.append(row)
    return out


# =====================================================================================
# 导入 · ③④ 校验通过后落盘（临时目录 → 原子搬成 content/<id>；覆盖先备份）
# =====================================================================================
def _flatten_entries(named: List[Tuple[zipfile.ZipInfo, PurePosixPath]]
                     ) -> List[Tuple[zipfile.ZipInfo, str]]:
    """剥掉「统一的一层顶层目录」（手动压缩整包目录的常见形态），再要求条目扁平。

    例：`mypack/manifest.json` + `mypack/data.json` → `manifest.json` + `data.json`；
    混杂多层（`a/x.json` 与 `b/y.json`）或包里还有更深目录 → 拒绝（内容包是扁平的）。
    """
    paths = [p for _zi, p in named]
    firsts = {p.parts[0] for p in paths}
    if len(firsts) == 1 and all(len(p.parts) > 1 for p in paths):
        paths = [PurePosixPath(*p.parts[1:]) for p in paths]
    out: List[Tuple[zipfile.ZipInfo, str]] = []
    for (zi, original), path in zip(named, paths):
        if len(path.parts) != 1:
            raise _Reject("nested_path",
                          f"压缩包条目不是扁平文件（含子目录）：{original.as_posix()!r}。",
                          "内容包格式为扁平文件；请让分享者用编辑器「导出此包」重新导出。")
        out.append((zi, path.name))
    return out


def _extract_payload(buf: bytes, limits: TransferLimits
                     ) -> Tuple[Dict[str, bytes], Dict[str, Any], Dict[str, Any], str]:
    """内存里完成 ①②：结构安全 + 元信息合法 + 完整性 → (payload, meta, manifest, pack_id)。"""
    if not buf:
        raise _Reject("empty", "导入文件是空的（0 字节）。",
                      "请确认选择的是分享来的 .ttrpack 文件。")
    if len(buf) > limits.max_archive_bytes:
        raise _Reject("archive_too_large",
                      f"压缩包体积超过上限（上限 {human_bytes(limits.max_archive_bytes)}，"
                      f"实际 {human_bytes(len(buf))}）。",
                      "请确认选择的是内容包文件。")
    try:
        zf = zipfile.ZipFile(io.BytesIO(buf))
    except (zipfile.BadZipFile, OSError) as exc:
        raise _Reject("bad_zip",
                      f"这不是一个有效的压缩包（.ttrpack/.zip）：{type(exc).__name__}。",
                      "请确认文件完整下载、且是编辑器导出的 .ttrpack 文件。") from exc

    with zf:
        infos = [zi for zi in zf.infolist() if not zi.is_dir() and not zi.filename.endswith("/")]
        if not infos:
            raise _Reject("empty", "压缩包里没有任何文件。",
                          "请确认文件完整下载后再试。")
        _check_sizes(infos, limits)
        named: List[Tuple[zipfile.ZipInfo, PurePosixPath]] = []
        for zi in infos:
            named.append((zi, _check_entry(zi)))
        flat = _flatten_entries(named)
        seen: Dict[str, zipfile.ZipInfo] = {}
        for zi, name in flat:
            if name in seen:
                raise _Reject("duplicate_entry",
                              f"压缩包里出现重复文件：{name}。",
                              "请让分享者用编辑器「导出此包」重新导出。")
            seen[name] = zi

        if EXPORT_META_NAME not in seen:
            raise _Reject("export_meta_missing",
                          "压缩包里缺少 export_meta.json（这可能不是编辑器导出的内容包）。",
                          "请让分享者用编辑器「导出此包」导出的文件。")
        if MANIFEST_NAME not in seen:
            raise _Reject("manifest_missing",
                          "压缩包里缺少 manifest.json（不是完整的内容包）。",
                          "请让分享者用编辑器「导出此包」重新导出。")

        payload: Dict[str, bytes] = {}
        for name, zi in seen.items():
            payload[name] = _read_entry_bytes(
                zf, zi, min(limits.max_file_bytes, limits.max_total_bytes))
        total = sum(len(v) for v in payload.values())
        if total > limits.max_total_bytes:
            raise _Reject("total_too_large",
                          f"解压后总大小超过上限"
                          f"（上限 {human_bytes(limits.max_total_bytes)}）。",
                          "请确认选择的是内容包文件。")

    meta_raw = _parse_json_payload(EXPORT_META_NAME, payload[EXPORT_META_NAME])
    meta, listing = _check_export_meta(meta_raw)
    pid = str(meta["pack_id"])
    _verify_integrity(payload, listing, pid)
    manifest = _check_manifest(_parse_json_payload(MANIFEST_NAME, payload[MANIFEST_NAME]))
    for name in payload:
        if name.endswith(".json") and name not in (EXPORT_META_NAME, MANIFEST_NAME):
            _parse_json_payload(name, payload[name])  # 其它 JSON 也必须是合法 JSON
    return payload, meta, manifest, pid


def _build_meta_table(payload: Mapping[str, bytes], pid: str):
    """包内 field_meta.json（若有）→ 字段元数据表；非法 → `_Reject`。"""
    base = default_field_meta_table()
    if FIELD_META_NAME not in payload:
        return base
    raw = _parse_json_payload(FIELD_META_NAME, payload[FIELD_META_NAME])
    try:
        decl = pack_meta.parse_field_meta(raw, pid)
    except pack_meta.PackFieldMetaError as exc:
        raise _Reject("field_meta_invalid", str(exc),
                      "请让分享者修正 field_meta.json 后重新导出。") from exc
    return pack_meta.merge_field_meta_table(base, decl)


def _resolve_target(content_root: Path, pid: str, on_conflict: str,
                    new_id: object) -> Tuple[str, Optional[Dict[str, Any]]]:
    """包 id 冲突处理 → (最终包 id, 失败包络 or None)。

    on_conflict：""（默认，冲突即报错并给出可选项）/ "rename"（需 new_id）/ "overwrite"。
    """
    target = content_root / pid
    nid = str(new_id or "").strip()
    if on_conflict not in ("", "rename", "overwrite"):
        return pid, _fail("bad_conflict_option",
                          f"未知的冲突处理方式：{on_conflict!r}。",
                          "请选择「换个名字导入」或「覆盖现有包」。")
    if on_conflict == "rename":
        if not nid:
            return pid, _fail("rename_required",
                              "选择「换个名字导入」时必须提供新的包名。",
                              "请填一个新的包名（英文/数字/下划线）。")
        if not _SAFE_COMPONENT.match(nid):
            return pid, _fail("rename_invalid",
                              f"新的包名非法：{nid!r}。",
                              "包名只能用字母、数字、下划线、点或短横线，且不能以点开头。")
        if nid == pid and target.exists():
            return pid, _fail("rename_same",
                              f"新的包名与原来的包名相同：{nid}。",
                              "请换一个不同的包名。")
        if (content_root / nid).exists():
            return pid, _fail("rename_exists",
                              f"包名「{nid}」已存在，不能再占用。",
                              "请换一个包名，或选择「覆盖现有包」。")
        return nid, None
    if target.exists() and on_conflict != "overwrite":
        return pid, _fail(
            "pack_exists",
            f"已经存在同名内容包「{pid}」，本次没有导入任何东西。",
            "你可以选择「换个名字导入」（原包不受影响），或「覆盖现有包」"
            "（原包会先自动备份到内容目录的 .ttrpack_backups/ 下再替换）。",
            conflict=True, pack_id=pid, existing=True)
    return pid, None


def import_archive(data: object, content_root: object, *, on_conflict: str = "",
                   new_id: object = None, now: Optional[datetime] = None,
                   limits: TransferLimits = DEFAULT_LIMITS) -> Dict[str, Any]:
    """导入一个 `.ttrpack` 字节流（分享文件）→ 校验 → 落盘为新包。**原子、可回退、不留残留**。

    出参：成功 {ok:true, pack_id, pack_name, written[], file_count, backup, overwritten,
    overwritten_from, meta, warnings[], message}；失败 {ok:false, errors[], message}
    （冲突时附加 conflict/pack_id）。
    """
    root = Path(str(content_root))
    if not root.is_dir():
        return _fail("content_root_missing",
                     f"内容目录不存在：{root}。",
                     "请确认编辑器/命令行的内容目录参数正确。")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        return _fail("bad_input", "导入数据形态非法（应为文件字节流）。",
                     "请在界面上重新选择分享来的 .ttrpack 文件。")
    # ①②③ 全在内存完成；任何一步不过都不会碰磁盘
    try:
        payload, meta, manifest, pid = _extract_payload(bytes(data), limits)
    except _Reject as exc:
        return _fail(exc.code, exc.message, exc.how_to_fix)
    try:
        table = _build_meta_table(payload, pid)
        modules, _declared = _modules_from_payload(manifest, payload)
        report = check_pack(modules, table)
    except _Reject as exc:
        return _fail(exc.code, exc.message, exc.how_to_fix)
    except Exception as exc:  # 校验器意外异常也不得落盘（服务不崩）
        return _fail("validate_failed",
                     f"内容校验时发生意外错误：{type(exc).__name__}。",
                     "请让分享者确认内容包可用后重试。")
    warnings = atomic_store.humanize_warnings(report.warnings)
    if report.errors:
        human = _decorate_validation_errors(atomic_store.humanize_errors(report.errors))
        return {
            "ok": False, "phase": "import", "pack_id": pid,
            "pack_name": str(manifest.get("name", "") or pid),
            "errors": human, "warnings": warnings,
            "message": (f"内容校验未通过（{len(human)} 条红拦）：本次未写入任何文件。"),
        }

    # ④ 冲突处理（到此为止都还没写盘）
    final_id, failure = _resolve_target(root, pid, on_conflict, new_id)
    if failure is not None:
        failure["pack_name"] = str(manifest.get("name", "") or pid)
        return failure
    target = root / final_id

    written = sorted(name for name in payload if name != EXPORT_META_NAME)
    stamp = _now_utc(now)
    backup_rel = ""
    overwritten = target.exists()
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix=TMP_PREFIX, dir=str(root)))
    except OSError as exc:
        return _fail("write_failed", f"创建临时目录失败：{type(exc).__name__}。",
                     "请检查内容目录是否可写、磁盘是否已满。")
    moved = False
    backup_dir: Optional[Path] = None
    try:
        for name in written:
            (tmp_dir / name).write_bytes(payload[name])
        if overwritten:
            backup_dir = root / BACKUP_DIRNAME / final_id / stamp.strftime("%Y%m%dT%H%M%S%fZ")
            backup_dir.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, backup_dir)  # 旧包整体原子移走（失败则下面不会搬新包）
            backup_rel = str(backup_dir.relative_to(root))
        os.replace(tmp_dir, target)  # 新包整体原子搬入
        moved = True
    except OSError as exc:
        if backup_dir is not None and backup_dir.exists() and not target.exists():
            try:
                os.replace(backup_dir, target)  # 复原旧包（覆盖失败的兜底）
            except OSError:
                backup_rel = str(backup_dir.relative_to(root))
        return _fail("write_failed", f"写入内容包失败：{type(exc).__name__}。",
                     "本次没有留下半成品内容包；请检查磁盘空间与目录权限后重试。")
    finally:
        if not moved:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    msg = f"已导入内容包「{meta.get('pack_name') or final_id}」（id={final_id}），" \
          f"共 {len(written)} 个文件；现在可以在顶部 pkg= 里选它。"
    if overwritten:
        msg = (f"已覆盖同名内容包「{pid}」（id 仍为 {final_id}），共 {len(written)} 个文件；"
               f"原包已备份到 {BACKUP_DIRNAME}/{backup_rel.split('/')[1]}/ 下可找回。")
    if final_id != pid:
        msg = f"包名「{pid}」已存在，已按新名字「{final_id}」导入，共 {len(written)} 个文件。"
    return {
        "ok": True, "phase": "import", "pack_id": final_id,
        "original_pack_id": pid,
        "pack_name": str(meta.get("pack_name") or manifest.get("name", "") or final_id),
        "written": written, "file_count": len(written),
        "overwritten": overwritten, "backup": backup_rel,
        "meta": meta, "warnings": warnings, "errors": [],
        "message": msg,
    }


def import_file(file_path: object, content_root: object, *, on_conflict: str = "",
                new_id: object = None, now: Optional[datetime] = None,
                limits: TransferLimits = DEFAULT_LIMITS) -> Dict[str, Any]:
    """CLI 用：按路径读 `.ttrpack`（先查体积上限）再 `import_archive`。"""
    path = Path(str(file_path))
    if not path.is_file():
        return _fail("file_missing", f"找不到导入文件：{path}。",
                     "请确认文件路径是否正确。")
    try:
        size = path.stat().st_size
    except OSError as exc:
        return _fail("read_failed", f"读取文件失败：{type(exc).__name__}。",
                     "请确认文件可读。")
    if size > limits.max_archive_bytes:
        return _fail("archive_too_large",
                     f"压缩包体积超过上限（上限 {human_bytes(limits.max_archive_bytes)}，"
                     f"实际 {human_bytes(size)}）。",
                     "请确认选择的是内容包文件。")
    try:
        data = path.read_bytes()
    except OSError as exc:
        return _fail("read_failed", f"读取文件失败：{type(exc).__name__}。",
                     "请确认文件可读。")
    return import_archive(data, content_root, on_conflict=on_conflict, new_id=new_id,
                          now=now, limits=limits)


__all__ = [
    "ALLOWED_SUFFIXES",
    "BACKUP_DIRNAME",
    "DEFAULT_LIMITS",
    "EXPORT_META_NAME",
    "FORMAT_NAME",
    "FORMAT_VERSION",
    "FIELD_META_NAME",
    "MANIFEST_NAME",
    "TTRPACK_EXT",
    "TransferLimits",
    "collect_export_files",
    "export_filename",
    "export_pack_dir",
    "human_bytes",
    "import_archive",
    "import_file",
    "ttr_commit",
    "ttr_version",
    "write_pack_archive",
]
