"""指令清单生成器（部署检查用）：从 Router + parsers 白名单汇总全部指令 → md。"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

code = '''
import json
from qbot_rpg.assembly.router_setup import build_router
from qbot_rpg.assembly.context import AssemblyDeps
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, DEFAULT_PREFIX_REQUIRED
from qbot_rpg.data.gm_constants import GM_COMMANDS
deps = AssemblyDeps(repo=None, game_world=None, registry=None, settings={})
router = build_router(deps)
reg = sorted(router.names())
unreg = sorted(DEFAULT_WHITELIST - set(reg))
print(json.dumps({"reg": reg, "unreg": unreg,
  "prefix": sorted(DEFAULT_PREFIX_REQUIRED), "gm": sorted(GM_COMMANDS)}))
'''
out = subprocess.run(
    [".venv/bin/python", "-c", code],
    cwd=str(Path(__file__).resolve().parent.parent),
    capture_output=True, text=True).stdout.strip().splitlines()[-1]
d = json.loads(out)

# 来源标注：指令 → (归属系统, 设计来源, 备注)
SRC = {
    # 已注册
    "角色": ("basic 基础", "4f 基础指令", ""),
    "角色详细": ("basic 基础", "4f 基础指令", ""),
    "背包": ("basic 基础", "4f 基础指令 / M5 背包渲染", ""),
    "背包筛选": ("basic 基础", "M5-09 筛选链", ""),
    "装备": ("basic 基础", "M6 装备引擎 EQP-01~12", ""),
    "技能": ("basic 基础", "技能列表", ""),
    "帮助": ("basic 基础", "4f 帮助", ""),
    "注册": ("注册", "4f 注册 REG-01~06", "无参兜底用 QQ 号当名字（用户拍板）"),
    "状态": ("状态", "4f 状态面板", ""),
    "快捷解绑": ("快捷", "4f 快捷解绑", ""),
    "快捷列表": ("快捷", "4f 快捷列表", ""),
    "任务": ("任务", "2b4 任务引擎", ""),
    "商店": ("商店", "商店系统", ""),
    "购买": ("商店", "商店系统", ""),
    "出售": ("商店", "商店系统", ""),
    "签到": ("签到", "签到系统", ""),
    "攻击": ("战斗", "定稿 L92/L108：/攻击 /攻击<序号>", ""),
    "防御": ("战斗", "定稿 L92/L111：/防御 DEF×2 本回合行动", "⚠ 用户疑为幻觉，定稿有 L92/L111"),
    "逃跑": ("战斗", "定稿 L92：/逃跑", ""),
    "道具": ("战斗", "定稿 L92：/道具", "战斗中使用道具"),
    "进入": ("探索", "2a1c 地图移动 /进入 <方向>", ""),
    "休息": ("探索", "休息", ""),
    "对话": ("NPC", "2b1/2b2 NPC 对话", "M7 接线"),
    "日志": ("冒险日志", "3f F-03/04 /日志", "玩家看冒险日志、GM 看系统日志"),
    "调查": ("调查", "3f F-05~07 /调查", "M7 接线"),
    "图鉴": ("图鉴", "3f F-11/12 /图鉴", "M7 接线"),
    # 未注册（白名单有）
    "使用": ("道具使用", "定稿 L1263：/使用 经验药水*10", "⚠ 白名单有但未注册（未接线）"),
    "锁定怪物": ("战斗", "定稿 L1279：/锁定 <序号> 锁定目标进入战斗",
                 "⚠ 白名单有但未注册（未接线）"),
    "快捷绑定": ("快捷", "4f 快捷绑定", "⚠ 白名单有但未注册（未接线？）"),
    "地图": ("地图", "? 需核对", "⚠ 白名单有但未注册（来源待核对）"),
    "怪物": ("怪物", "? 需核对", "⚠ 白名单有但未注册（来源待核对）"),
    "合成": ("制造", "M8 炼金", "未注册（未来）"),
    "炼金": ("制造", "炼金系统定稿", "未注册（M8）"),
    "投料": ("制造", "L17 投料", "未注册（M8）"),
    "拆珠": ("制造", "炼金 拆珠", "未注册（M8）"),
    "调合": ("制造", "炼金 调合", "未注册（M8）"),
    "锻造": ("制造", "M9 锻造", "未注册（M9）"),
    "强化": ("制造", "锻造 强化", "未注册（M9）"),
    "镶嵌": ("制造", "锻造 镶嵌", "未注册（M9）"),
    "采集": ("生活", "采集", "未注册"),
    "雇工": ("生活", "L49 雇工", "未注册"),
    "继承": ("制造", "L42 继承", "未注册"),
    "封禁": ("GM", "GM 指令", "未注册（M12）"),
    "编辑": ("GM", "GM 指令", "未注册（M12）"),
    "设置": ("GM", "GM 指令", "未注册（M12）"),
    "重载": ("GM", "GM 指令", "未注册（M12）"),
}

def row(name, status):
    sys_name, src, note = SRC.get(name, ("?", "⚠ 需核对来源", ""))
    return f"| {name} | {status} | {sys_name} | {src} {note} |"

lines = [
    "# 指令清单（部署检查用 · 全量核对）",
    "",
    "> 生成：2026-08-28 部署全面检查；来源：Router 注册表 + parsers.DEFAULT_WHITELIST",
    "",
    "## 一、当前已注册指令（%d 个，玩家可发）" % len(d["reg"]),
    "",
    "| 指令 | 状态 | 归属系统/设计来源 | 备注 |",
    "|---|---|---|---|",
]
for n in d["reg"]:
    lines.append(row(n, "✅ 已注册"))
lines += [
    "",
    "## 二、白名单有但未注册（%d 个）" % len(d["unreg"]),
    "",
    "| 指令 | 状态 | 归属系统/设计来源 | 备注 |",
    "|---|---|---|---|",
]
for n in d["unreg"]:
    lines.append(row(n, "❌ 未注册"))
lines += [
    "",
    "## 三、需 / 前缀的指令（%d 个）" % len(d["prefix"]),
    "",
    "`" + "` `".join(d["prefix"]) + "`",
    "",
    "## 四、GM 指令（%d 个）" % len(d["gm"]),
    "",
    "`" + "` `".join(d["gm"]) + "`",
    "",
    "## 五、待用户核对项",
    "",
    "1. **防御/逃跑/道具**：三个玩家战斗指令已按用户拍板移除"
    "（定稿 L92/L111/L1364~66 同步删除）；战斗仅剩 /攻击（技能合并）。",
    "2. **使用 / 锁定怪物**：定稿 L1263 / L1279 有，白名单注册了、指令壳未接线——需决定补接或移除。",
    "3. **快捷绑定**：4f 快捷绑定，白名单有但未注册（快捷组只注册解绑/列表）——需核对。",
    "4. **地图 / 怪物**：白名单来源待核对。",
    "",
]
Path("/root/deliverables/command_list_check.md").parent.mkdir(parents=True, exist_ok=True)
Path("/root/deliverables/command_list_check.md").write_text("\n".join(lines), encoding="utf-8")
print("已生成 /root/deliverables/command_list_check.md")
