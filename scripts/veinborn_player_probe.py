"""veinborn 模拟玩家全面 probe：run_command 链路发基础/战斗/异常/边界指令，收集回复并判定异常。

只报告不修改。DB 每次全新 /tmp/rpg_veinborn_tester.db。BattlePipeline.send 正文经
monkey-patch 收集（run_command 返回可能只是元数据 message，正文要走 pipeline）。
"""
import asyncio
import json
import os
import sys
import traceback
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["QBotRPG_PACK_DIR"] = "/root/QBot-TurnTellerRPG/content/veinborn"
os.environ["QBotRPG_DB_PATH"] = "/tmp/rpg_veinborn_tester.db"

from qbot_rpg.commands import battle_commands as BC  # noqa: E402
from qbot_rpg.commands import battle_launch_commands as BLC  # noqa: E402

_SENT: list = []
_orig_send = BC.BattlePipeline.send


def _spy_send(self, text, **kw):
    _SENT.append(str(text))
    return _orig_send(self, text, **kw)


BC.BattlePipeline.send = _spy_send

LINES: list = []
NORMAL = "✅ 正常"
SUSPECT = "⚠️ 可疑"
ERROR = "❌ ERROR"


def out(line: str) -> None:
    LINES.append(line)
    print(line, flush=True)


def _summarize(text: str, limit: int = 120) -> str:
    text = str(text or "")
    return text.replace("\n", "⏎")[:limit]


async def main() -> None:
    from qbot_rpg_bridge.assemble import build_app_deps
    from qbot_rpg.assembly import runner as R

    if os.path.exists("/tmp/rpg_veinborn_tester.db"):
        os.remove("/tmp/rpg_veinborn_tester.db")
    deps = await build_app_deps()

    async def say(text: str, *, user: str = "u_player", group: str = "g1",
                  label: str = "") -> tuple:
        """发一条指令；返回 (return_value, sent_bodies)。"""
        _SENT.clear()
        ev = {"group_id": group, "user_id": user, "message": text,
              "message_id": str(uuid.uuid4()), "channel": "group",
              "group_name": "测试群"}
        try:
            rv = await asyncio.wait_for(R.run_command(ev, deps), timeout=25)
        except Exception as e:
            rv = f"[异常 {type(e).__name__}] {e}"
            _SENT.append(f"[run_command raised] {traceback.format_exc()}")
        rv_s = str(rv or "")
        sent_s = " | ".join(_SENT)
        return rv_s, sent_s

    def report(label: str, text: str, rv: str, sent: str, flag: str = "",
               note: str = "") -> None:
        body = sent if sent.strip() else rv
        body_s = _summarize(body)
        mark = flag or (ERROR if "[异常" in rv or "Traceback" in sent else NORMAL)
        extra = f" [{note}]" if note else ""
        out(f"{mark} {label} → 回复: {body_s}{extra}")
        out(f"    return={_summarize(rv, 200)}")

    def verdict(text: str, rv: str, sent: str) -> str:
        body = sent if sent.strip() else rv
        if "[异常" in rv or "Traceback" in sent or "❌" in body and "开战失败" in body:
            return ERROR
        if not body.strip():
            return SUSPECT
        return NORMAL

    def mark(text: str, rv: str, sent: str, flag: str = "", note: str = "") -> str:
        mark = flag or verdict(text, rv, sent)
        report(text, text, rv, sent, mark, note)
        return mark

    # ============================================================
    # 组 1：基础指令（未注册先测 /帮助 豁免，再注册）
    # ============================================================
    out("=" * 20 + " 组1 基础（未注册视角先行） " + "=" * 20)
    mark("/帮助", *await say("/帮助"))
    mark("/状态", *await say("/状态"))          # 未注册 → 应注册门槛
    mark("/背包", *await say("/背包"))
    mark("/装备", *await say("/装备"))
    mark("/技能", *await say("/技能"))
    mark("/地图", *await say("/地图"))
    mark("/图鉴", *await say("/图鉴"))
    mark("/签到", *await say("/签到"))
    mark("/注册", *await say("/注册"))           # 无参 → QQ号兜底名
    mark("/注册 岩脊", *await say("/注册 岩脊"))   # 重复注册 → 幂等

    # ============================================================
    # 组 2：注册后基础
    # ============================================================
    out("=" * 20 + " 组2 注册后基础 " + "=" * 20)
    mark("/状态", *await say("/状态"))
    mark("/背包", *await say("/背包"))
    mark("/装备", *await say("/装备"))
    mark("/技能", *await say("/技能"))
    mark("/技能 脊斩", *await say("/技能 脊斩"))
    mark("/地图", *await say("/地图"))
    mark("/签到", *await say("/签到"))
    mark("/签到", *await say("/签到"))          # 同一天二次签到
    mark("/图鉴", *await say("/图鉴"))
    mark("/图鉴 怪物", *await say("/图鉴 怪物"))
    mark("/图鉴 怪物册", *await say("/图鉴 怪物册"))
    mark("/图鉴 物品", *await say("/图鉴 物品"))
    mark("/图鉴 物品册", *await say("/图鉴 物品册"))
    mark("/图鉴 怪物 1", *await say("/图鉴 怪物 1"))
    mark("/图鉴 怪物 99", *await say("/图鉴 怪物 99"))
    mark("/图鉴 不存在册", *await say("/图鉴 不存在册"))
    mark("/角色", *await say("/角色"))

    # ============================================================
    # 组 3：战斗全流程
    # ============================================================
    out("=" * 20 + " 组3 战斗全流程 " + "=" * 20)
    mark("/攻击", *await say("/攻击"))           # 战斗外
    mark("/锁定", *await say("/锁定"))           # 开战（无参→当前地图第一只活动怪）
    mark("/锁定", *await say("/锁定"))           # 已在战斗中
    mark("/攻击", *await say("/攻击"))           # 无参 → 普攻=basic 脊斩
    mark("/攻击 脊斩", *await say("/攻击 脊斩"))
    mark("/攻击 桩移", *await say("/攻击 桩移"))
    mark("/攻击 贯核击", *await say("/攻击 贯核击"))
    mark("/攻击 不存在的技能", *await say("/攻击 不存在的技能"))
    mark("/攻击 999", *await say("/攻击 999"))
    mark("/攻击 脊挡", *await say("/攻击 脊挡"))
    # 连打直到结束（最多 15 轮）
    done = False
    for i in range(15):
        _SENT.clear()
        rv, _s2 = await say("/攻击 脊斩")
        joined = " | ".join(_SENT)
        rep = _summarize(joined or rv, 160)
        blob = joined + str(rv)
        if any(f in blob for f in ("战斗结束", "胜利", "win", "lose", "已死亡", "战败", "逃跑", "逃走")):
            out(f"✅ 轮{i+1} → {rep}")
            done = True
            break
        if not joined.strip():
            out(f"⚠️ 轮{i+1} 无 pipeline 输出 → return={_summarize(rv, 160)}")
            continue
        out(f"  轮{i+1} → {rep}")
    out(f"   战斗结束? done={done}")
    mark("/锁定", *await say("/锁定"))           # 结束后重新开战
    mark("/攻击 脊斩", *await say("/攻击 脊斩"))   # 战后再打一轮看状态
    mark("/攻击", *await say("/攻击"))
    # 测试逃跑路径
    mark("/锁定", *await say("/锁定"))           # 又一次开战（此前可能未结束）
    mark("/攻击 999", *await say("/攻击 999"))
    mark("/逃跑", *await say("/逃跑"))
    mark("/锁定", *await say("/锁定"))

    # ============================================================
    # 组 4：乱发
    # ============================================================
    out("=" * 20 + " 组4 乱发/异常输入 " + "=" * 20)
    mark("/不存在指令", *await say("/不存在指令"))
    mark("空消息", *await say(""))
    mark("/锁定 999", *await say("/锁定 999"))
    mark("/注册 角色名超长" + "长" * 50, *await say("/注册 角色名超长" + "长" * 50))
    mark("/注册 名#特殊@字符！", *await say("/注册 名#特殊@字符！"))
    mark("Hello 非指令", *await say("Hello 非指令"))
    mark("/攻击 疾风狼", *await say("/攻击 疾风狼"))  # 地图怪物名但未开战

    # ============================================================
    # 结果写盘
    # ============================================================
    out("=" * 20 + " 汇总 " + "=" * 20)
    bugs = [l for l in LINES if l.startswith(("❌", "⚠️"))]
    ok_n = len([l for l in LINES if l.startswith("✅")])
    out(f"总指令行 {len(LINES)}，✅ {ok_n}，⚠️ {len([l for l in LINES if l.startswith('⚠️')])}，❌ {len([l for l in LINES if l.startswith('❌')])}")

    Path("/tmp/veinborn_bug_report.txt").write_text(
        "\n".join(LINES), encoding="utf-8")
    print("\n报告已落盘 /tmp/veinborn_bug_report.txt")


if __name__ == "__main__":
    asyncio.run(main())
