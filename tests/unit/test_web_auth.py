"""Web 编辑器认证模块单测（M12 · tests/unit/test_web_auth.py · 本路负责新建）。

依据：docs/细化/细化_5a_编辑器契约.md §五 认证 AU-02/03/04/06（契约 L142-146）
+ §6.1 认证端点（L160-163）+ §7.4 验收 TC-17/L245、TC-18/L246：
  - AU-02 首次设密 ≥8 位且含字母数字，弱密码拒绝（L142 / TC-17 ①）；
  - AU-03 随机 token + 过期时间 + 单设备互踢（L143 / TC-18 ①：设备 B 登录 →
    设备 A 会话 401 被踢）；
  - AU-04 登录失败 5 次锁定 15 分钟（L144 / TC-17 ②：第 6 次登录被锁 423）；
  - AU-06 权限语义：me 身份 机主/GM 标记（L146 / L163 200/401）；
  - 语义映射：409=已设密、400=弱密码、401=错密/未认证、423=锁定（L160-163）。

测试对象：qbot_rpg/web/auth.py 的 AuthStore + hash_password/verify_password/
is_weak_password 纯函数。全部注入假时钟（now_fn），零 sleep 实等（禁词回避）、零
NoneBot import、零第三方依赖（mock 仅用 stdlib unittest.mock）。

角色命名对齐 gm_commands.py（ROLE_ADMIN 机主 / ROLE_MANAGER GM）：本模块对外
输出 owner/gm（auth.py ROLE_OWNER/ROLE_GM）。
"""

from __future__ import annotations

import pathlib

import pytest

from qbot_rpg.web.auth import (
    DEFAULT_TOKEN_TTL_SECONDS,
    LOCK_SECONDS,
    MAX_FAIL_COUNT,
    ROLE_GM,
    ROLE_OWNER,
    AuthStore,
    hash_password,
    is_weak_password,
    verify_password,
)

# ---------------------------------------------------------------------------
# 测试基座：假时钟 + 标准场景
# ---------------------------------------------------------------------------

OWNER = "10001"
GM = "20002"


class FakeClock:
    """可控假时钟（epoch 秒）：测试中显式推进，绝不实等。"""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def make_store(
    clock: FakeClock,
    gm_ids=None,
    owner: str = OWNER,
    *,
    ttl: float = DEFAULT_TOKEN_TTL_SECONDS,
    persist=None,
    load=None,
) -> AuthStore:
    """构造已设密 + 时钟注入的 AuthStore 快捷方式。"""
    return AuthStore(
        owner,
        gm_ids or set(),
        now_fn=clock,
        token_ttl_seconds=ttl,
        persist_fn=persist,
        load_fn=load,
    )


# ---------------------------------------------------------------------------
# 纯函数层：hash_password / verify_password / is_weak_password
# ---------------------------------------------------------------------------

def test_hash_verify_roundtrip() -> None:
    """哈希-校验往返：同一密码可验证；错误密码被拒。"""
    encoded = hash_password("abc12345")
    assert encoded.startswith("pbkdf2_sha256$")
    assert verify_password("abc12345", encoded)
    assert not verify_password("wrongpass", encoded)


def test_hash_random_salt() -> None:
    """盐随机：同一密码两次哈希结果不同（防彩虹表，工程补白）。"""
    assert hash_password("abc12345") != hash_password("abc12345")


def test_hash_verify_invalid_encoded() -> None:
    """畸形存储串不抛异常、返回 False（防御坏数据）。"""
    assert not verify_password("abc12345", "")
    assert not verify_password("abc12345", "garbage")
    assert not verify_password("abc12345", "pbkdf2_sha256$abc$zz$zz")
    assert not verify_password("abc12345", "md5$1000$00$00")


def test_is_weak_password() -> None:
    """AU-02 强度判定：<8 位 / 纯字母 / 纯数字 → 弱；含字母+数字且 ≥8 → 通过。"""
    assert is_weak_password("abc123")        # 长度 6 < 8
    assert is_weak_password("abcdefgh")      # 8 位但纯字母无数字
    assert is_weak_password("12345678")      # 8 位但纯数字无字母
    assert not is_weak_password("abc12345")
    assert not is_weak_password("Ab1defgh")  # 含大写字母也算字母


# ---------------------------------------------------------------------------
# AU-02 首次设密（setup_password）
# ---------------------------------------------------------------------------

def test_setup_password_first_time_success(clock: FakeClock) -> None:
    """首次设密成功：password_set 变 True，此后登录可用。"""
    store = make_store(clock)
    assert not store.password_set
    res = store.setup_password(OWNER, "abc12345")
    assert res == {"ok": True}
    assert store.password_set


def test_setup_password_weak_rejected(clock: FakeClock) -> None:
    """弱密码拒绝（AU-02 400 语义 / TC-17 ①：设 abc 拒绝）：不写入。"""
    store = make_store(clock)
    res = store.setup_password(OWNER, "abc")
    assert res == {"ok": False, "reason": "weak_password"}
    res = store.setup_password(OWNER, "abcdefgh")  # 纯字母同样弱
    assert res == {"ok": False, "reason": "weak_password"}
    assert not store.password_set


def test_setup_password_already_set_conflict(clock: FakeClock) -> None:
    """重复设密拒绝（409 语义）：已设密后再次 setup 失败。"""
    store = make_store(clock)
    assert store.setup_password(OWNER, "abc12345") == {"ok": True}
    res = store.setup_password(OWNER, "newpass99")
    assert res == {"ok": False, "reason": "already_set"}
    # 原密码仍有效（未被覆盖）
    assert store.verify_password(OWNER, "abc12345")


def test_setup_password_persist_callback(clock: FakeClock) -> None:
    """可选持久化回调：设密后回调收到存储串；load_fn 可恢复（工程补白）。"""
    saved: list[str] = []

    def persist(encoded: str) -> None:
        saved.append(encoded)

    store = make_store(clock, persist=persist)
    store.setup_password(OWNER, "abc12345")
    assert len(saved) == 1
    assert saved[0].startswith("pbkdf2_sha256$")
    # 新实例经 load_fn 恢复 → 会话层可见已设密且旧密码可登录
    restored = make_store(clock, load=lambda: saved[0])
    assert restored.password_set
    assert restored.verify_password(OWNER, "abc12345")


# ---------------------------------------------------------------------------
# AU-03 登录 + token（login / me）
# ---------------------------------------------------------------------------

def test_login_success_issues_token(clock: FakeClock) -> None:
    """密码正确 → 200 语义：随机 token + 过期时间；me 可还原身份。"""
    store = make_store(clock)
    store.setup_password(OWNER, "abc12345")
    res = store.login(OWNER, "abc12345")
    assert res["ok"] is True
    token = res["token"]
    assert isinstance(token, str) and len(token) >= 20
    assert res["expires_at"] == clock.now + DEFAULT_TOKEN_TTL_SECONDS
    me = store.me(token)
    assert me == {
        "ok": True,
        "owner_id": OWNER,
        "role": ROLE_OWNER,
        "expires_at": res["expires_at"],
    }


def test_login_tokens_random(clock: FakeClock) -> None:
    """token 随机性：连续两次登录 token 不同。"""
    store = make_store(clock)
    store.setup_password(OWNER, "abc12345")
    t1 = store.login(OWNER, "abc12345")["token"]
    t2 = store.login(OWNER, "abc12345")["token"]
    assert t1 != t2


def test_login_wrong_password_count(clock: FakeClock) -> None:
    """错误密码 → 401 语义 + 计数；me 无会话 401。"""
    store = make_store(clock)
    store.setup_password(OWNER, "abc12345")
    res = store.login(OWNER, "badpass1")
    assert res["ok"] is False
    assert res["reason"] == "wrong_password"
    assert res["remaining"] == MAX_FAIL_COUNT - 1
    # 未登录时 me → 401 语义
    assert store.me("") == {"ok": False, "reason": "unauthorized"}
    assert store.me("no-such-token") == {"ok": False, "reason": "unauthorized"}


def test_me_gm_role(clock: FakeClock) -> None:
    """AU-06：GM qq_id 登录后 me 返回 gm 角色；机主登录返回 owner。"""
    store = make_store(clock, gm_ids={GM})
    store.setup_password(OWNER, "abc12345")
    gm_token = store.login(GM, "abc12345")["token"]
    assert store.me(gm_token)["role"] == ROLE_GM
    owner_token = store.login(OWNER, "abc12345")["token"]
    assert store.me(owner_token)["role"] == ROLE_OWNER


def test_me_owner_priority_over_gm(clock: FakeClock) -> None:
    """owner 即使误入 gm 集合仍判 owner（机主最高权限，5b 三级）。"""
    store = make_store(clock, gm_ids={OWNER, GM})
    store.setup_password(OWNER, "abc12345")
    token = store.login(OWNER, "abc12345")["token"]
    assert store.me(token)["role"] == ROLE_OWNER


# ---------------------------------------------------------------------------
# AU-04 防爆破：5 次失败锁 15 分钟（TC-17 ②）
# ---------------------------------------------------------------------------

def test_login_lock_after_five_failures(clock: FakeClock) -> None:
    """连续错 5 次 → 锁定（423 语义，lock_until=now+15min）；第 6 次正确密码也被拒。"""
    store = make_store(clock)
    store.setup_password(OWNER, "abc12345")
    for i in range(4):
        res = store.login(OWNER, "wrong{}".format(i))
        assert res == {
            "ok": False,
            "reason": "wrong_password",
            "remaining": MAX_FAIL_COUNT - 1 - i,
        }
    # 第 5 次失败 → 触发锁定
    res = store.login(OWNER, "wrong5")
    assert res["ok"] is False
    assert res["reason"] == "locked"
    assert res["lock_until"] == clock.now + LOCK_SECONDS
    # 锁定期内即使密码正确也直接拒（TC-17 ②「第 6 次登录被锁」）
    res = store.login(OWNER, "abc12345")
    assert res == {"ok": False, "reason": "locked", "lock_until": clock.now + LOCK_SECONDS}


def test_login_lock_auto_release_after_15min(clock: FakeClock) -> None:
    """锁定 15 分钟后自动解锁（时钟推进，不实等）：正确密码可再登录。"""
    store = make_store(clock)
    store.setup_password(OWNER, "abc12345")
    for _ in range(MAX_FAIL_COUNT):
        store.login(OWNER, "wrongpass")
    assert store.login(OWNER, "abc12345")["ok"] is False  # 仍在锁定期
    clock.advance(LOCK_SECONDS + 1)
    res = store.login(OWNER, "abc12345")
    assert res["ok"] is True


def test_login_fail_count_reset_after_success(clock: FakeClock) -> None:
    """中途成功登录 → 失败计数清零（不会累计到 5 次）。"""
    store = make_store(clock)
    store.setup_password(OWNER, "abc12345")
    store.login(OWNER, "bad1")
    store.login(OWNER, "bad2")
    assert store.login(OWNER, "abc12345")["ok"] is True
    # 再错 3 次不会锁（若未清零则第 3 次就达 5 次触发锁）
    store.login(OWNER, "bad3")
    store.login(OWNER, "bad4")
    res = store.login(OWNER, "bad5")
    assert res["ok"] is False and res["reason"] == "wrong_password"


def test_login_fail_count_per_owner(clock: FakeClock) -> None:
    """失败计数按 owner 记：GM 错 5 次不影响机主登录。"""
    store = make_store(clock, gm_ids={GM})
    store.setup_password(OWNER, "abc12345")
    for _ in range(MAX_FAIL_COUNT):
        store.login(GM, "wrongpass")
    assert store.login(GM, "abc12345")["reason"] == "locked"
    # 机主不受 GM 锁定影响
    assert store.login(OWNER, "abc12345")["ok"] is True


# ---------------------------------------------------------------------------
# 登出（logout）：token 失效
# ---------------------------------------------------------------------------

def test_logout_invalidates_token(clock: FakeClock) -> None:
    """登出 → token 立即失效：me 401 语义；幂等返回 ok=True（200）。"""
    store = make_store(clock)
    store.setup_password(OWNER, "abc12345")
    token = store.login(OWNER, "abc12345")["token"]
    assert store.me(token)["ok"] is True
    assert store.logout(token) == {"ok": True}
    assert store.me(token) == {"ok": False, "reason": "unauthorized"}
    # 幂等：再登出同一 token 仍 200
    assert store.logout(token) == {"ok": True}
    # 无效 token 登出同样幂等 200
    assert store.logout("ghost-token") == {"ok": True}


# ---------------------------------------------------------------------------
# AU-03 单设备互踢（TC-18 ①）
# ---------------------------------------------------------------------------

def test_single_device_kick(clock: FakeClock) -> None:
    """设备 B 登录成功 → 设备 A 旧 token 立即 401 被踢（TC-18 ①）。"""
    store = make_store(clock)
    store.setup_password(OWNER, "abc12345")
    token_a = store.login(OWNER, "abc12345")["token"]
    assert store.me(token_a)["ok"] is True
    # 设备 B 二次登录
    token_b = store.login(OWNER, "abc12345")["token"]
    assert token_b != token_a
    assert store.me(token_b)["ok"] is True
    assert store.me(token_a) == {"ok": False, "reason": "unauthorized"}


def test_kick_does_not_affect_other_owner(clock: FakeClock) -> None:
    """互踢只作用同 owner：GM 二次登录不踢机主会话。"""
    store = make_store(clock, gm_ids={GM})
    store.setup_password(OWNER, "abc12345")
    owner_token = store.login(OWNER, "abc12345")["token"]
    store.login(GM, "abc12345")
    store.login(GM, "abc12345")  # GM 互踢自己旧会话
    assert store.me(owner_token)["ok"] is True  # 机主会话不受影响


def test_login_after_kick_old_token_cannot_relogin() -> None:
    """被踢后旧 token 无法再 me；但可重新登录拿新 token（恢复正常流程）。"""
    # 使用真实时钟也可以，但为确定性仍注入假时钟
    clock = FakeClock()
    store = make_store(clock)
    store.setup_password(OWNER, "abc12345")
    t1 = store.login(OWNER, "abc12345")["token"]
    store.login(OWNER, "abc12345")
    assert store.me(t1)["ok"] is False
    t3 = store.login(OWNER, "abc12345")
    assert t3["ok"] is True


# ---------------------------------------------------------------------------
# AU-03 token 过期（注入过期时间验证；默认 TTL 24h）
# ---------------------------------------------------------------------------

def test_token_expiry(clock: FakeClock) -> None:
    """token 过期 → me 401 语义（时钟推进越过 TTL，不实等）。"""
    store = make_store(clock)
    store.setup_password(OWNER, "abc12345")
    token = store.login(OWNER, "abc12345")["token"]
    assert store.me(token)["ok"] is True
    clock.advance(DEFAULT_TOKEN_TTL_SECONDS + 1)
    assert store.me(token) == {"ok": False, "reason": "unauthorized"}


def test_token_expiry_custom_ttl(clock: FakeClock) -> None:
    """自定义 TTL（可配）：TTL=60s 时 59s 有效、61s 过期。"""
    store = make_store(clock, ttl=60.0)
    store.setup_password(OWNER, "abc12345")
    token = store.login(OWNER, "abc12345")["token"]
    clock.advance(59)
    assert store.me(token)["ok"] is True
    clock.advance(2)
    assert store.me(token) == {"ok": False, "reason": "unauthorized"}


# ---------------------------------------------------------------------------
# 完整链路回归（TC-17 走查）
# ---------------------------------------------------------------------------

def test_tc17_full_flow(clock: FakeClock) -> None:
    """TC-17 链路：首次设密（弱→强）→ 错 5 次 → 锁定 423 → 15 分钟后恢复登录。"""
    store = make_store(clock)
    # ① 弱密码拒绝
    assert store.setup_password(OWNER, "abc")["reason"] == "weak_password"
    assert store.setup_password(OWNER, "abc12345")["ok"] is True
    # ② 连续输错 5 次（第 5 次即锁）
    for _ in range(MAX_FAIL_COUNT):
        store.login(OWNER, "nope123")
    # ③ 第 6 次（正确密码）被锁：423 语义
    locked = store.login(OWNER, "abc12345")
    assert locked["reason"] == "locked"
    assert locked["lock_until"] == clock.now + LOCK_SECONDS
    # ④ 15 分钟后解锁可登录
    clock.advance(LOCK_SECONDS)
    assert store.login(OWNER, "abc12345")["ok"] is True


def test_store_zero_third_party_and_nonebot() -> None:
    """铁律：auth 模块不 import nonebot/第三方库（静态白名单检查，防回归）。

    只扫 import/from 语句行（docstring 提及依赖名属正常说明，不误伤）——
    依赖清单 requirements.txt 亦无这些包（M12 摸底 L68 grep 零命中），
    认证为 stdlib-only（hashlib/secrets/hmac）。
    """
    src = pathlib.Path(__file__).resolve().parents[2] / "qbot_rpg" / "web" / "auth.py"
    import_lines = [
        line.strip()
        for line in src.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith(("import ", "from "))
    ]
    banned_modules = ("bcrypt", "jwt", "fastapi", "nonebot", "passlib", "argon2")
    for line in import_lines:
        for mod in banned_modules:
            assert mod not in line, "auth.py 禁入依赖出现在 import 行：{}".format(line)
    # stdlib-only 落实：仅 hashlib/hmac/secrets/time/typing 家族（hashlib 抽查在列）
    assert any(line.startswith("import hashlib") for line in import_lines)
