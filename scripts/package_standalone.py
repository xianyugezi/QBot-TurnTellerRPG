# -*- coding: utf-8 -*-
"""云海单机交付打包（九期批次 239 · G6 部署交付）。

与 238 `package_cloudsea.py`（仅内容包 zip）分工：本脚本产出**整机交付**「三步
部署」zip 主形态（236 web 壳启动）：
    dist/cloudsea_standalone.zip
      ├ cloudsea/
      │   ├ qbot_rpg/  qbot_rpg_bridge/        引擎与桥（源码直带）
      │   ├ content/cloudsea/                   云海内容包
      │   ├ content/demo_full/                  冒烟演示包（--no-demo 去除）
      │   ├ scripts/web_shell.py  scripts/deploy_smoke.py
      │   ├ docs/cloudsea/云海转化映射表.md
      │   ├ requirements.txt  README_DEPLOY.md
    三步：pip install -r requirements.txt → python scripts/web_shell.py → 浏览器 127.0.0.1:8010

排除：.git/__pycache__/data/logs/审查_*.md/*.jspace/dist 自身/测试产物/*.db。
冒烟（--smoke）：解包至临时目录 → 关键入口 py_compile → 结构断言（manifest/
requirements/README/web_shell 在位）。
运行：python scripts/package_standalone.py [--out dist] [--no-demo] [--smoke]
"""
from __future__ import annotations

import argparse
import py_compile
import zipfile
from pathlib import Path
from zipfile import ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent
INCLUDE_TREES = ["qbot_rpg", "qbot_rpg_bridge"]
INCLUDE_FILES = ["requirements.txt"]
EXCLUDE_PARTS = {"__pycache__", ".git", "data", "logs", "dist", ".pytest_cache", "node_modules"}
EXCLUDE_FILE_PREFIX = ("审查_",)
EXCLUDE_FILE_SUFFIX = (".jspace", ".db", ".log", ".pyc")

README_DEPLOY = """# 云海猎团 Cloudsea Hunting Corps · 单机部署包（九期交付形态）

## 三步部署
1. `python -m pip install -r requirements.txt`
2. `python scripts/web_shell.py --pack content/cloudsea --db data/cloudsea.db`
3. 浏览器打开 `http://127.0.0.1:8010/`，发 `注册` 开始。

## 自检
- 全流程冒烟：`python scripts/deploy_smoke.py`（按玩家流程逐指令收集回复；
  路径经环境变量 QBotRPG_PACK_DIR / QBotRPG_DB_PATH 或本包缺省）
- 打包自检：`python scripts/package_standalone.py --smoke`

## 说明
- 引擎：QBot-TurnTellerRPG（本地内置，零 NoneBot 单机形态）
- 内容包：`content/cloudsea`（22 模块）；`content/demo_full` 为冒烟演示包
- 存档：`data/`（SQLite，跨天保留；长眠 ≥7 游戏日冻结不删档）
- 词面/机制映射：`docs/cloudsea/云海转化映射表.md`
"""


def _want(rel: Path) -> bool:
    if any(part in EXCLUDE_PARTS for part in rel.parts):
        return False
    name = rel.name
    if name.startswith(EXCLUDE_FILE_PREFIX) or name.endswith(EXCLUDE_FILE_SUFFIX):
        return False
    return True


def build_zip(out_dir: Path, *, with_demo: bool = True) -> Path:
    root = ROOT
    targets: list = []
    for tree in INCLUDE_TREES:
        targets.append(root / tree)
    targets.append(root / "content" / "cloudsea")
    if with_demo:
        demo = root / "content" / "demo_full"
        if demo.exists():
            targets.append(demo)
    for f in INCLUDE_FILES:
        targets.append(root / f)
    targets.append(root / "scripts" / "web_shell.py")
    targets.append(root / "scripts" / "deploy_smoke.py")
    targets.append(root / "scripts" / "package_standalone.py")
    maps = root / "docs" / "cloudsea" / "云海转化映射表.md"
    if maps.exists():
        targets.append(maps)

    out_dir.mkdir(parents=True, exist_ok=True)
    zpath = out_dir / "cloudsea_standalone.zip"
    n = 0
    with zipfile.ZipFile(zpath, "w", ZIP_DEFLATED) as z:
        for t in targets:
            if not t.exists():
                continue
            if t.is_file():
                rel = t.relative_to(root)
                if _want(rel):
                    z.write(t, str(Path("cloudsea") / rel))
                    n += 1
                continue
            for f in sorted(t.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(root)
                    if _want(rel):
                        z.write(f, str(Path("cloudsea") / rel))
                        n += 1
        z.writestr("cloudsea/README_DEPLOY.md", README_DEPLOY)
    print("打包完成：{}（{} 文件，{:.1f} KB）".format(zpath, n, zpath.stat().st_size / 1024))
    return zpath


def smoke(zpath: Path) -> int:
    """解包 → 关键入口 py_compile → 结构断言。返回失败数。"""
    import tempfile
    fails = 0
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(zpath) as z:
            z.extractall(td)
        base = Path(td) / "cloudsea"
        must = ["content/cloudsea/manifest.json", "requirements.txt", "README_DEPLOY.md",
                "scripts/web_shell.py", "scripts/deploy_smoke.py",
                "qbot_rpg/assembly/runner.py", "qbot_rpg_bridge/assemble.py"]
        for rel in must:
            if not (base / rel).exists():
                print("[FAIL] 结构缺 {}".format(rel))
                fails += 1
        for rel in ["scripts/web_shell.py", "scripts/deploy_smoke.py",
                    "qbot_rpg_bridge/assemble.py", "qbot_rpg/assembly/runner.py"]:
            try:
                py_compile.compile(str(base / rel), doraise=True)
            except Exception as e:  # noqa: BLE001
                print("[FAIL] 编译 {} → {}".format(rel, e))
                fails += 1
        import json
        cj = base / "content" / "cloudsea" / "manifest.json"
        if cj.exists():
            manifest = json.loads(cj.read_text(encoding="utf-8"))
            if len(manifest.get("modules", [])) < 20:
                print("[FAIL] manifest 模块数异常（<20）")
                fails += 1
    print("冒烟：{}".format("全绿" if fails == 0 else "{} 项失败".format(fails)))
    return fails


def main() -> int:
    ap = argparse.ArgumentParser(description="云海单机交付打包（239）")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--no-demo", action="store_true", help="不含 demo_full 冒烟演示包")
    ap.add_argument("--smoke", action="store_true", help="打包后解包自检")
    a = ap.parse_args()
    z = build_zip(Path(a.out), with_demo=not a.no_demo)
    if a.smoke:
        return 1 if smoke(z) else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
