#!/usr/bin/env python3
"""内容包导出 / 导入 · 命令行版（编辑器重写批11 · 服务器端批量/无网页场景）。

与网页编辑器共用同一实现 `qbot_rpg/content/pack_transfer.py`（不另写一套逻辑），
供不懂网页、或需要在服务器上批量搬运内容包的场景使用：

    # 导出：把 content/<包名> 打成一个可分享的 .ttrpack（默认写到当前目录，含日期文件名）
    python scripts/pack_transfer.py export --pack veinborn
    python scripts/pack_transfer.py export --pack veinborn --file /tmp/共享包.ttrpack

    # 导入：把别人发来的 .ttrpack 装成一个新内容包（默认遇到同名包会拒绝并提示）
    python scripts/pack_transfer.py import --file /tmp/共享包.ttrpack
    python scripts/pack_transfer.py import --file a.ttrpack --rename 我的包副本
    python scripts/pack_transfer.py import --file a.ttrpack --overwrite

参数：`--pack` / `--file` / `--content-root`（默认 <仓库根>/content）。
安全与校验顺序与网页端完全一致：压缩包结构安全（Zip Slip / 符号链接 / 体积上限 /
只收 .json·.md）→ export_meta/manifest 合法 → 过内容校验器（红拦不落盘）→ 冲突处理
（改名 / 覆盖前自动备份）；失败**不留半成品内容包**。

退出码：0 成功；1 失败（人话原因 + 处理办法打到 stderr）。
铁律：零 NoneBot import；不写死任何包名；CLI 是可信的服务端入口（不做角色权限位，
网页端导入的 owner 限制见 `qbot_rpg/web/editor_ops.py::import_pack`）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from qbot_rpg.content import pack_transfer as pt  # noqa: E402


def _content_root(arg: Optional[str]) -> Path:
    return Path(arg) if arg else (_REPO_ROOT / "content")


def _print_errors(res: Dict[str, Any]) -> None:
    """失败结果 → stderr 人话（每条：原因 + 怎么处理）。"""
    message = str(res.get("message") or "操作失败。")
    print("失败：" + message, file=sys.stderr)
    for err in res.get("errors") or []:
        line = "  · " + str(err.get("message") or err.get("code") or "")
        if err.get("how_to_fix"):
            line += "\n    怎么处理：" + str(err["how_to_fix"])
        print(line, file=sys.stderr)
    if res.get("conflict"):
        print("  可用参数：--rename <新包名> 换个名字导入；--overwrite 覆盖（会先自动备份原包）。",
              file=sys.stderr)


def _cmd_export(args: argparse.Namespace) -> int:
    root = _content_root(args.content_root)
    pack_dir = root / str(args.pack)
    if not (pack_dir / pt.MANIFEST_NAME).is_file():
        print(f"失败：内容目录 {root} 下找不到内容包「{args.pack}」（需要 {pt.MANIFEST_NAME}）。",
              file=sys.stderr)
        print("  怎么处理：用 --content-root 指定正确的内容目录，或用 --pack 指定已存在的包名。",
              file=sys.stderr)
        return 1
    out = Path(str(args.file)) if args.file else Path(
        pt.export_filename(str(args.pack), args.pack))
    res = pt.write_pack_archive(pack_dir, out, pack_id=str(args.pack))
    if args.json:
        print(json.dumps({k: v for k, v in res.items() if k != "data"},
                         ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1
    if not res.get("ok"):
        _print_errors(res)
        return 1
    print(f"已导出内容包「{res['pack_name']}」→ {res['path']}")
    print(f"  文件：{res['meta']['file_count']} 个，共 {pt.human_bytes(res['meta']['total_bytes'])}"
          f"；TTR 版本 {res['meta']['ttr_version']}"
          + (f"（{res['meta']['ttr_commit']}）" if res["meta"].get("ttr_commit") else ""))
    print(f"  清单：{', '.join(f['path'] for f in res['files'])}")
    print("把该 .ttrpack 通过 QQ / 网盘发给别人；对方用编辑器「📦 导出/导入 → 导入包」"
          "或本脚本 import 即可。")
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    root = _content_root(args.content_root)
    on_conflict = "overwrite" if args.overwrite else ("rename" if args.rename else "")
    res = pt.import_file(args.file, root, on_conflict=on_conflict, new_id=args.rename)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1
    if not res.get("ok"):
        _print_errors(res)
        return 1
    print("已导入：" + str(res["message"]))
    if res.get("backup"):
        print(f"  原包备份：{root / res['backup']}")
    print(f"  新包目录：{root / res['pack_id']}")
    print("  现在可以在编辑器顶部 pkg= 里选到它。")
    return 0


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pack_transfer.py",
        description="内容包导出 / 导入（.ttrpack；与网页编辑器同一实现）")
    sub = parser.add_subparsers(dest="command", required=True)

    exp = sub.add_parser("export", help="把内容包导出为一个 .ttrpack 文件")
    exp.add_argument("--pack", required=True, help="要导出的内容包名（content/ 下的目录名）")
    exp.add_argument("--file", default=None,
                     help="导出到哪个文件（缺省 = 当前目录/包名-日期.ttrpack）")
    exp.add_argument("--content-root", default=None, help="内容包根目录（缺省 <仓库根>/content）")
    exp.add_argument("--json", action="store_true", help="以 JSON 输出结果（便于脚本消费）")
    exp.set_defaults(func=_cmd_export)

    imp = sub.add_parser("import", help="导入别人分享来的 .ttrpack 为新内容包")
    imp.add_argument("--file", required=True, help="要导入的 .ttrpack 文件")
    imp.add_argument("--content-root", default=None, help="内容包根目录（缺省 <仓库根>/content）")
    imp.add_argument("--rename", default=None, metavar="NEW_ID",
                     help="同名冲突时换个包名导入（不影响已有包）")
    imp.add_argument("--overwrite", action="store_true",
                     help="同名冲突时覆盖已有包（覆盖前自动备份原包）")
    imp.add_argument("--json", action="store_true", help="以 JSON 输出结果（便于脚本消费）")
    imp.set_defaults(func=_cmd_import)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    if args.command == "import" and args.rename and args.overwrite:
        print("失败：--rename 与 --overwrite 只能选一个。", file=sys.stderr)
        return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
