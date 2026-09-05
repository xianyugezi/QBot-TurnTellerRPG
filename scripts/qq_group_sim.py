#!/usr/bin/env python3
"""QQ 群消息收发模拟器 —— 模拟「群里玩家发消息 → 机器人回复」的完整链路。

与实机差异：不走 NoneBot/NapCat/QQ 网络，直接驱动 qbot_rpg_bridge.plugin._on_message
（真实桥接层：build_event 字段映射 → run_bridge → G3 战斗正文补发 → bot.send 收集），
因此测到的是与 QQ 实机一致的 指令路由/文案/战斗补发 行为。

用法：
  python scripts/qq_group_sim.py                     # 交互 REPL（默认玩家 10001）
  python scripts/qq_group_sim.py 注册 阿伟 脊剑士    # 直接发一条（多条可空格分隔）
  python scripts/qq_group_sim.py --player 20002      # 指定发言人 qid
  python scripts/qq_group_sim.py --file cmds.txt     # 逐行批量执行
  python scripts/qq_group_sim.py --list-players      # 显示群里可用的玩家

REPL 内命令（不是游戏指令，模拟器控制台命令）：
  /player <qid>     切换当前发言人
  /players          列出群成员
  /add <qid> <名?>  添加群成员（新玩家）
  /file <path>      执行文件里的指令（逐行）
  /quit             退出

回复规则：bot.send 被模拟为「追加到回复列表」——一条玩家消息可能触发多条
机器人消息（战斗正文分片等），全部打印。空回复 = 机器人静默（非指令/忽略）。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

os.environ.setdefault("QBotRPG_PACK_DIR", os.path.join(REPO, "content/veinborn"))
os.environ.setdefault("QBotRPG_DB_PATH", "/tmp/qq_group_sim.db")

GROUP_ID = "sim_group_001"
GROUP_NAME = "模拟测试群"


class FakeGroupEvent:
    """模拟 OneBot v11 群消息事件（qbot_rpg_bridge.build_event 消费的属性）。

    注意：不带 author.member_openid（那是 QQ 官方事件特征）——_on_message 靠它
    区分 OneBot/官方通道，本模拟器走 OneBot 通道分支。
    """

    def __init__(self, group_id: str, user_id: str, message: str,
                 message_id: str) -> None:
        self.group_id = group_id
        self.user_id = user_id
        self.message = message
        self.message_id = message_id
        self.group_name = GROUP_NAME

    def get_plaintext(self) -> str:  # NoneBot Message 接口（build_event _msg_to_str 优先调）
        return str(self.message)


class FakeGroupBot:
    """模拟机器人（bot.send 收集回复；分片消息 = 多次 send 调用）。

    OneBot 协议层反转义：框架 cq_escape 把 [ ] & 转成 &#91; &#93; &amp;（防伪造
    [CQ: 段），真实 QQ 客户端显示时反转义回原文——模拟器同样反转义，
    输出与真实群聊看到的一致。
    """

    def __init__(self) -> None:
        self.sent: List[str] = []

    async def send(self, event: Any, message: str) -> None:
        self.sent.append(self._unescape(str(message)))

    @staticmethod
    def _unescape(text: str) -> str:
        return (text.replace("&#91;", "[").replace("&#93;", "]")
                    .replace("&amp;", "&"))


class QQGroupSim:
    """QQ 群模拟器：多玩家 + 机器人回复收集，驱动真实桥接层 _on_message。"""

    def __init__(self, pack_dir: Optional[str] = None) -> None:
        # message_id 全局唯一（时间戳基）：幂等键按 (message_id, group, qid) 判重，
        # 跨进程固定从 1 重计会与旧存档键相撞 → 新指令被误判「已处理」（模拟器审计发现）
        import time as _t
        self._msg_seq = int(_t.time() * 1000) % 100000000
        # 群成员（玩家 qid 集合；存档按 qid 隔离，注册后各自成角色）
        self.players: List[str] = ["10001", "10002", "10003"]
        self.cur_player = "10001"
        self.bot = FakeGroupBot()
        self._deps: Any = None

    # ------------------------------------------------------------------
    # 装配（惰性一次）
    # ------------------------------------------------------------------
    async def _ensure_deps(self) -> Any:
        if self._deps is None:
            from qbot_rpg_bridge.assemble import build_app_deps

            self._deps = await build_app_deps()
            from qbot_rpg_bridge.plugin import set_deps

            set_deps(self._deps)
        return self._deps

    # ------------------------------------------------------------------
    # 核心：玩家发一条消息 → 机器人回复（可多条）
    # ------------------------------------------------------------------
    async def send(self, player_qid: str, text: str) -> List[str]:
        """模拟群成员 player_qid 发送 text，返回机器人回复列表（多条 = 分片/补发）。"""
        await self._ensure_deps()
        self._msg_seq += 1
        event = FakeGroupEvent(GROUP_ID, str(player_qid), text,
                               f"msg_{self._msg_seq}")
        self.bot.sent = []
        from qbot_rpg_bridge.plugin import _on_message

        await _on_message(self.bot, event)
        return list(self.bot.sent)

    # ------------------------------------------------------------------
    # 玩家管理
    # ------------------------------------------------------------------
    def add_player(self, qid: str) -> None:
        if str(qid) not in self.players:
            self.players.append(str(qid))

    def set_player(self, qid: str) -> bool:
        if str(qid) in self.players:
            self.cur_player = str(qid)
            return True
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
async def _run_one(sim: QQGroupSim, qid: str, text: str) -> None:
    replies = await sim.send(qid, text)
    print(f"[{qid}] 发: {text}")
    if not replies:
        print("  (机器人静默——非指令/忽略/会话子词)")
    for i, r in enumerate(replies, 1):
        tag = f"回复{i}" if len(replies) > 1 else "回复"
        print(f"  {tag}: {r}")
    print()


async def _run_file(sim: QQGroupSim, qid: str, path: str) -> None:
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            # 行内可用 "@qid 消息" 指定发言人（默认当前玩家）
            speaker = qid
            if ln.startswith("@"):
                sp, _, rest = ln[1:].partition(" ")
                if sp and rest:
                    speaker, ln = sp.strip(), rest.strip()
            await _run_one(sim, speaker, ln)


async def _repl(sim: QQGroupSim, start_player: str) -> None:
    sim.set_player(start_player)
    print(f"QQ 群模拟器 —— 群: {GROUP_NAME}  当前玩家: {sim.cur_player}")
    print("发游戏指令直接回车（如: 注册 阿伟 脊剑士 / 帮助 / 任务）")
    print("控制台命令: /player <qid> /players /add <qid> /file <p> /quit")
    while True:
        try:
            raw = input(f"[{sim.cur_player}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        if raw == "/quit":
            break
        if raw == "/players":
            print("群成员:", ", ".join(sim.players))
            continue
        if raw.startswith("/player "):
            qid = raw.split()[1]
            if sim.set_player(qid):
                print(f"已切换发言人: {qid}")
            else:
                print(f"群成员里没有 {qid}（/add 添加）")
            continue
        if raw.startswith("/add "):
            qid = raw.split()[1]
            sim.add_player(qid)
            print(f"已添加群成员: {qid}")
            continue
        if raw.startswith("/file "):
            await _run_file(sim, sim.cur_player, raw.split()[1])
            continue
        await _run_one(sim, sim.cur_player, raw)


def main() -> None:
    # stdout 行缓冲（os._exit 强杀前不丢输出——print 缓冲在 _exit 时被丢弃）
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser(description="QQ 群消息收发模拟器")
    ap.add_argument("msgs", nargs="*", help="直接发送的指令（可多条）")
    ap.add_argument("--player", default="10001", help="发言人 qid（默认 10001）")
    ap.add_argument("--file", default=None, help="批量执行文件（逐行一条指令）")
    ap.add_argument("--list-players", action="store_true", help="列出群成员后退出")
    args = ap.parse_args()

    sim = QQGroupSim()
    if args.list_players:
        print("群成员:", ", ".join(sim.players))
        return

    async def amain() -> None:
        if args.file:
            await _run_file(sim, args.player, args.file)
        elif args.msgs:
            for m in args.msgs:
                await _run_one(sim, args.player, m)
        else:
            await _repl(sim, args.player)

    try:
        asyncio.run(amain())
    finally:
        os._exit(0)  # noqa: PLC2701 —— 绕过 aiosqlite worker 线程退出卡死


if __name__ == "__main__":
    main()
