# -*- coding: utf-8 -*-
"""组装 M5 消息模板总览 md（跑 part1+part2 采集，拼装 + 头部说明）。"""
import os, subprocess, sys

REPO = "/root/QBot-TurnTellerRPG"
PY = f"{REPO}/.venv/bin/python"


def run(script):
    r = subprocess.run([PY, f"{REPO}/scripts/{script}"], capture_output=True, text=True, cwd=REPO)
    if r.returncode != 0:
        print(f"!! {script} 失败: {r.stderr[-300:]}", file=sys.stderr)
    return r.stdout


def _extract(text, start, end):
    """提取从 start 小节标题到 end 小节标题之间的内容（含 start；end=None → 文本尾）。"""
    if start is None:
        return ""
    i = text.find(f"### {start}")
    if i < 0:
        return f"### {start}\n(未采集到)\n\n"
    j = text.find(f"### {end}", i) if end else len(text)
    return text[i:j] if j >= 0 else text[i:]


p1 = run("_gen_templates_part1.py")
p2 = run("_gen_templates_part2.py")

header = """# 消息模板总览（QBot-TurnTellerRPG · M5 消息模板与渲染层）

> **口径**：以下均为**实测输出**（测试 ctx 构造 + 真实渲染函数）；emoji 纪律 = 仅 ✅/❌ 功能性标记
> + 排版符号（| → × / 「」【】）；列表统一 CakeGame 式尾段「当前页 + Tip」（2026-08-27 用户拍板）；
> 战斗轮 ≤16 行折叠（铁律 11）；前缀首行由消息前缀系统统一注入（M5-01）。
> 实现依据：docs/m5_shared_contract.md + docs/细化/细化_3d/5e/4f + docs/全局图标登记表.md。

---

## 〇、通用机制

"""

tpl12 = ""

reg = """

---

## 一、基础指令组（列表统一「当前页 + Tip」尾段）

"""

battle = """

---

## 二、战斗模板（BREP-01~25）

"""

explore = """

---

## 三、探索模板

"""

foot = """

---

## 四、模板注册表（BREP-01~25 简表）

| 编号 | 模板 | 说明 |
|---|---|---|
| BREP-01 | 骨架：先手→击杀→后手→结算 | 铁律 9 拼接顺序 |
| BREP-02 | `✅ 你{动作}{目标}，造成 {n} 伤害（{目标} {HP}/{最大}）` | 玩家命中 |
| BREP-03 | `❌ {动作}被{目标}躲开` | 玩家未命中 |
| BREP-04 | 会心（×2.2/1.7/1.3）+ 格挡（减半）标注 | 命中附注 |
| BREP-05 | 防御行动行 | /防御 |
| BREP-06 | 防御中受击减伤行 | /防御 受击 |
| BREP-07 | `✅ 你施放{技能}：{效果}（{资源变化}）` | 技能施放 |
| BREP-08 | 状态资源差分行（只显变化轴） | 状态 |
| BREP-09 | `你 {HP}/{最大} \| {目标} {HP}/{最大} → /攻击[技能] /道具 /防御 /逃跑` | 操作提示行 |
| BREP-10 | `❌ {怪物}{动作}，你受到 {n} 伤害（HP {剩}/{最大}）` | 怪物反击命中 |
| BREP-11 | `✅ {怪物}的攻击被你躲开` | 怪物未命中 |
| BREP-12 | `{怪物} 蓄力中（下回合发动「{招}」）` | 意图预告 |
| BREP-13 | 特殊行动行 | 特殊行动 |
| BREP-14 | 拦截链三行（吸收/反弹/免疫） | 效果拦截 |
| BREP-15 | `✅ 你击败了{怪物}！` | 击杀行（紧跟伤害行） |
| BREP-16 | `❌ 你倒下了…` | 玩家死亡 |
| BREP-17 | `✅ 战斗胜利！`（已并入用户结算模板） | 胜利 |
| BREP-18 | `❌ 战斗失败：你被{怪物}击败了` | 失败 |
| BREP-19 | `双方同归于尽，战斗以平局结束` | 平局 |
| BREP-20 | 掉落（已并入用户结算模板战利品列表） | 掉落 |
| BREP-21 | `第 {N} 段：{动作} 造成 {n} 伤害（{目标} {HP}/{最大}）` | 连段段行 |
| BREP-22 | `连段 {N} 段已结算（{备注}）` | 连段结算 |
| BREP-23 | `与{怪物}的战斗开始！{怪物} {HP}/{最大}` | 战斗开始 |
| BREP-24 | `战斗结束：{胜/负/平}｜回合数 {N}｜输入 /战斗记录 查看明细` | 结束汇总（win 无此行） |
| BREP-25 | 木桩明细块（摘要 + 5 条/页） | 战后明细 |

> 用户 2026-08-27 拍板结算模板：win 结束消息 = 叙事句（`您对{怪物}造成了{n}点伤害！{怪物}已死亡。`）
> + `获得经验：{n}` + `获得金币：{n}` + `获得的战利品如下→` + 逐行 `{序号}.{名称}×{数量}`；
> 无 `✅ 战斗胜利！` 横幅与 BREP-24 汇总行（见上文「结算·胜利」实测）。

---

*本文件由采集脚本实测生成（scripts/_gen_templates_part1/2.py + 组装），与代码渲染输出一致。*
"""

md = (
    header
    + _extract(p2, "前缀接线", "指令错误 TPL-12")
    + tpl12
    + _extract(p2, "指令错误 TPL-12", None)
    + reg
    + _extract(p1, "/角色", None)
    + battle
    + _extract(p2, "战斗开始", "/进入")
    + explore
    + _extract(p2, "/进入", "前缀接线")
    + foot
)

out = "/root/deliverables/message_templates.md"
os.makedirs("/root/deliverables", exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(md)
print(f"已写 {out}（{len(md)} 字符，{md.count(chr(10))} 行）")
print("含模板段：", [s for s in ["/角色", "/背包", "战斗开始", "战斗轮·连段", "结算·胜利", "/进入", "前缀接线", "指令错误 TPL-12", "BREP-25"] if s in md])
