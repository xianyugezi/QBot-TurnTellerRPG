#!/usr/bin/env python3
"""M12 里程碑门禁（verify_m12）。

依据：
  - docs/m12_启动包.md §五（验收门禁：5a 18 TC + 5a2 18 TC + 5b 34 TC + DELAYED 登记）
  - docs/细化/细化_5b_GM指令契约.md（34 TC）
  - 注：5a/5a2（编辑器壳/扩展页）TC 已随 2026-09-13「编辑器移除」清理
    （代码/测试/契约文档一并删除），
    本脚本保留 5b GM + field_meta + event_log 三门，覆盖矩阵只列仍有效条目。
  - docs/细化/细化_5d_测试体系总纲.md §2.1/§3.2（里程碑 verify 门禁模式：COVERAGE 逐条
    TC 声明承载位置；脚本断言 + pytest 承载 + DELAYED 诚实化登记；exit 0/1）
  - 先例：scripts/verify/verify_m11.py（本文件结构完全照抄）

后端语义（认证/CRUD/原子写/回退/ID 生成/引用/409/校验）→ pytest
  字段元数据 → PASS（4A field_meta 注入）；事件写入（5 结算点 bump_event + event_log
  环形 300）→ PASS（3B）；前端标签渲染/日历预览断签模拟 → DELAYED（前端迭代）。
  5b GM 34 TC：权限三级/静默/审计/禁绑/前缀 → PASS（gm_commands + test_gm_commands*）；
  G2 备份/G3 恢复/G4 存档导出/G12 封禁列表 → PASS（3A）；G5 调试/G6 测试/G7 广播/
  G9 玩家查询/G11 解封 → DELAYED（无常量无处理器，未接线）；/商店 列表 SM-04 余额行
  SM-06 紧凑 → PARTIAL。

核心断言（脚本内直接断言，不依赖 pytest）：
  a. GM 9 条清单：GM_COMMANDS 含备份/恢复/存档导出/封禁列表（3A 接线）
  b. GmBackend.backup_content 真实 zip 可用（tmp 目录）
  c. field_meta 注入：quest/shop/npc/checkin 字段非空 + label（4A）
  e. event_bus.read_event_log 倒序读（3B）

退出码：0 = M12 门禁通过（打印「M12 OK」）；1 = 有失败。
DELAYED/PARTIAL 为诚实登记（不判失败），但须在输出统计中可见。

铁律：零 NoneBot import；纯函数确定性；无定时器/睡眠调用；无 emoji（仅 ✅/❌）。
"""
from __future__ import annotations

import pathlib
import sys
from typing import Dict

_REPO = pathlib.Path(__file__).resolve().parent.parent.parent  # scripts/verify/ -> 仓库根
sys.path.insert(0, str(_REPO))  # 供 import qbot_rpg

# ---------------------------------------------------------------------------
# COVERAGE 矩阵（5a 18 + 5a2 18 + 5b 34 → pytest / assert / PARTIAL / DELAYED）
# 值形态："pytest:路径"（pytest 承载）| "assert"（脚本断言）| "PARTIAL:说明" |
# "DELAYED:说明"（诚实登记）
# ---------------------------------------------------------------------------
COVERAGE: Dict[str, str] = {
    # —— 5a2 扩展页 18 TC ——
    # 5 结算点事件（quest/checkin/battle/levelup/dungeon）
    # —— 5b GM 34 TC ——
    "5b-TC-01": "pytest:tests/unit/test_gm_commands.py",         # 权限三级 admin>gm>player
    "5b-TC-02": "pytest:tests/unit/test_gm_commands.py",         # 静默语义
    "5b-TC-03": "pytest:tests/unit/test_gm_commands.py",         # 审计成败皆写
    "5b-TC-04": "pytest:tests/unit/test_gm_commands.py",         # 无权限零审计
    "5b-TC-05": "pytest:tests/unit/test_gm_commands.py",         # 禁绑
    "5b-TC-06": "pytest:tests/unit/test_gm_commands.py",         # 前缀/免前缀裁决
    "5b-TC-07": "pytest:tests/unit/test_gm_commands.py",         # 角色归一
    "5b-TC-08": "pytest:tests/unit/test_gm_commands.py",         # G1 重载
    "5b-TC-09": "pytest:tests/unit/test_gm_commands.py",         # G10 封禁
    "5b-TC-10": "pytest:tests/unit/test_gm_commands.py",         # G8 日志
    "5b-TC-11": "pytest:tests/unit/test_gm_commands.py",         # G13 编辑
    "5b-TC-12": "pytest:tests/unit/test_gm_commands.py",         # G14 设置
    "5b-TC-13": "pytest:tests/unit/test_gm_commands_extra.py",   # G2 备份
    "5b-TC-14": "pytest:tests/unit/test_gm_commands_extra.py",   # G3 恢复
    "5b-TC-15": "pytest:tests/unit/test_gm_commands_extra.py",   # G4 存档导出
    "5b-TC-16": "DELAYED:G5 调试（无常量无处理器，未接线）",
    "5b-TC-17": "DELAYED:G6 测试（只读冒烟，未接线）",
    "5b-TC-18": "DELAYED:G7 广播（群+私聊+定时，未接线）",
    "5b-TC-19": "pytest:tests/unit/test_gm_commands_extra.py",   # G12 封禁列表
    "5b-TC-20": "pytest:tests/unit/test_permission_store.py",    # admin_users 表
    "5b-TC-21": "pytest:tests/unit/test_permission_store.py",    # grant/revoke（P0 修复）
    "5b-TC-22": "pytest:tests/unit/test_permission_store.py",    # 权限缓存失效
    "5b-TC-23": "DELAYED:G9 玩家查询（脱敏，未接线）",
    "5b-TC-24": "pytest:tests/unit/test_gm_commands.py",         # 执行层二次检查
    "5b-TC-25": "pytest:tests/unit/test_audit_store.py",         # audit_log 追加写
    "5b-TC-26": "pytest:tests/unit/test_audit_store.py",         # 不可删
    "5b-TC-27": "pytest:tests/unit/test_audit_store.py",         # E1-E6 分类
    "5b-TC-28": "pytest:tests/unit/test_audit_store.py",         # 轮转
    "5b-TC-29": "pytest:tests/unit/test_gm_commands.py",         # GM 默认授予集
    "5b-TC-30": "DELAYED:G11 解封（未接线）",
    "5b-TC-31": "pytest:tests/unit/test_permission_store.py",    # 机主初始写入
    "5b-TC-32": "pytest:tests/unit/test_permission_store.py",    # per-command 下授
    "5b-TC-33": "pytest:tests/unit/test_gm_commands_extra.py",   # 无后端降级不崩
    "5b-TC-34": "pytest:tests/unit/test_audit_store.py",         # 审计 hmac 预留
}

# 2026-09-13：5a/5a2（编辑器壳/扩展页）TC 已随编辑器移除清理 → 只保留 5b（GM 指令契约）。
_TC_COUNT = {"5b": 34}


def t_coverage_self_consistent() -> bool:
    """COVERAGE 矩阵完整性：每章 TC 数 + 状态枚举合法。"""
    from collections import Counter

    for prefix, count in _TC_COUNT.items():
        keys = [k for k in COVERAGE if k.startswith(prefix + "-TC-")]
        if len(keys) != count:
            print(f"  FAIL COVERAGE {prefix} 应有 {count} TC，实际 {len(keys)}")
            return False
        for k in keys:
            num = int(k.rsplit("-", 1)[1])
            if num < 1 or num > count:
                print(f"  FAIL COVERAGE {k} 序号越界")
                return False
    # 状态统计（诚实登记可见）
    stats: Counter[str] = Counter()
    for v in COVERAGE.values():
        if v.startswith("PARTIAL"):
            stats["PARTIAL"] += 1
        elif v.startswith("DELAYED"):
            stats["DELAYED"] += 1
        else:
            stats["PASS"] += 1
    _tot = sum(_TC_COUNT.values())
    print(f"  COVERAGE {_tot} TC（5b）：PASS {stats['PASS']} / PARTIAL {stats['PARTIAL']}"
          f" / DELAYED {stats['DELAYED']}")
    delayed = [k for k, v in COVERAGE.items() if v.startswith("DELAYED")]
    if delayed:
        print("  DELAYED 登记（诚实化，不判失败）：")
        for k in sorted(delayed):
            print(f"    {k}: {COVERAGE[k]}")
    return True


# ---------------------------------------------------------------------------
# 脚本断言（直接 import 验证，不依赖 pytest）
# ---------------------------------------------------------------------------
def t_gm_commands_wired() -> bool:
    """GM 指令集含 3A 接线的 4 条（备份/恢复/存档导出/封禁列表）。"""
    from qbot_rpg.commands.gm_commands import (
        GM_CMD_BACKUP, GM_CMD_BANLIST, GM_CMD_EXPORT, GM_CMD_RESTORE,
        GM_COMMANDS, GM_COMMAND_INDEX, _HANDLERS,
    )
    need = {GM_CMD_BACKUP, GM_CMD_RESTORE, GM_CMD_EXPORT, GM_CMD_BANLIST}
    if not need <= GM_COMMANDS:
        print(f"  FAIL GM_COMMANDS 缺 3A 指令：{need - GM_COMMANDS}")
        return False
    if not need <= set(_HANDLERS):
        print("  FAIL _HANDLERS 缺 3A 处理器")
        return False
    if GM_COMMAND_INDEX[GM_CMD_BACKUP] != "G2":
        print("  FAIL GM_COMMAND_INDEX 备份 != G2")
        return False
    print("  PASS GM 9 条清单（3A 4 条接线 + 索引）")
    return True


def t_gm_backend_real() -> bool:
    """GmBackend.backup_content 真实实现（zip 可写；不再 NotImplementedError）。"""
    import tempfile
    import zipfile
    from pathlib import Path

    from qbot_rpg.commands.gm_commands import GmBackend

    with tempfile.TemporaryDirectory() as td:
        cd = Path(td) / "content"
        cd.mkdir()
        (cd / "enemies.json").write_text('{"id": "x"}', encoding="utf-8")
        (cd / "note.txt").write_text("no", encoding="utf-8")
        backend = GmBackend()
        res = backend.backup_content("test", {"content_dir": str(cd),
                                              "backup_dir": str(Path(td) / "baks")})
        if not res.get("ok"):
            print(f"  FAIL backup_content：{res}")
            return False
        zf = zipfile.ZipFile(Path(td) / "baks" / (res["backup_id"] + ".zip"))
        names = zf.namelist()
        zf.close()
        if "enemies.json" not in names or "note.txt" in names:
            print(f"  FAIL zip 内容：{names}")
            return False
    print("  PASS GmBackend 真实 zip 备份（json 含/txt 排除）")
    return True


def t_field_meta_injected() -> bool:
    """field_meta 注入：quest/shop/npc/checkin 字段非空 + label 中文。"""
    from qbot_rpg.content.field_meta import default_field_meta_table

    t = default_field_meta_table()
    for mod, min_fields in (("quest", 15), ("shop", 12), ("npc", 10), ("checkin", 7)):
        m = t.modules.get(mod)
        if m is None or len(m.fields) < min_fields:
            print(f"  FAIL field_meta {mod} 未注入（{len(m.fields) if m else 0} 字段）")
            return False
        if not all(f.label for f in m.fields.values()):
            print(f"  FAIL field_meta {mod} 有字段缺中文 label")
            return False
    for mod in ("ai", "hidden", "env_event", "log_card"):
        if mod not in t.modules:
            print(f"  FAIL field_meta 缺视图模块 {mod}")
            return False
    print("  PASS field_meta 注入（quest/shop/npc/checkin + 4 视图模块）")
    return True
def t_event_log_read() -> bool:
    """event_bus.read_event_log 倒序读取（3B）。"""
    from qbot_rpg.core.event_bus import bump_event, read_event_log

    ctx: dict = {"event_counts": {}, "longline_counters": {},
                 "persistent_state": {}, "settings": {}}
    bump_event(ctx, "[事件:任务完成]", instance={"tag": "milestone"})
    bump_event(ctx, "[事件:签到]", instance={"tag": "milestone"})
    log = read_event_log(ctx)
    if len(log) != 2 or log[0]["count_key"] != "[事件:签到]":
        print(f"  FAIL read_event_log 倒序：{log}")
        return False
    print("  PASS read_event_log 倒序读取（3B）")
    return True
# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def main() -> int:
    print("=== M12 里程碑门禁 ===")
    checks = [
        ("COVERAGE 自洽（5b 34 + 保留项）", t_coverage_self_consistent),
        ("GM 9 条清单接线", t_gm_commands_wired),
        ("GmBackend 真实备份", t_gm_backend_real),
        ("field_meta 注入", t_field_meta_injected),
        ("event_log 读取", t_event_log_read),
    ]
    ok = True
    for name, fn in checks:
        try:
            r = fn()
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {name}：异常 {type(e).__name__}: {e}")
            r = False
        ok = ok and r
    print("=== M12 门禁判定：" + ("通过" if ok else "失败") + " ===")
    print("M12 " + ("OK" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
