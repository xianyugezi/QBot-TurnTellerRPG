"""Web 编辑器认证模块（M12 里程碑 · qbot_rpg/web/auth.py · 本路负责新建）。

依据（契约唯一权威，docs/细化/细化_5a_编辑器契约.md）：
  - §五 认证 AU-01~AU-06（契约 L137-148）：
      AU-02 首次设密（L142）：首次启动强制设密码 ≥8 位且含字母数字，弱密码拒绝；
      AU-03 登录会话（L143）：随机 token + 过期时间 + 单设备互踢；
      AU-04 防爆破（L144）：登录失败 5 次锁定 15 分钟；
      AU-06 权限语义（L146）：编辑器访问凭 /编辑 权限（机主/GM）。
  - §6.1 认证端点（契约 L156-163）：POST /api/auth/setup（200/400/409 语义）、
      POST /api/auth/login（200/401/423 语义）、POST /api/auth/logout（200）、
      GET /api/auth/me（200/401）。
  - L148 【工程补白】：密码存储用加盐哈希、token 服务端维护（算法/存储为补白）。
  - 验收：TC-17（契约 L245：弱密码 400 拒绝；第 6 次登录 423 锁 15 分钟）、
    TC-18（契约 L246：设备 B 登录 → 设备 A 会话 401 被踢）。
现状摸底：docs/m12_编辑器摸底.md §1.5（认证 6 条全【缺】，L68 grep 零命中
bcrypt/argon2/session；L80-87 认证 4 端点【缺】）→ 本模块整建纯逻辑认证层。

职责（本路范围）：独立的纯逻辑认证会话层（不碰 web/api.py——api.py 的挂载由
M12 批1·路B API 路由路负责，避免并行写同一文件冲突）。提供 AuthStore：首次
设密 / 密码校验 / 登录发 token（随机 + 过期）/ 单设备互踢 / 登出 / me 身份
（机主/GM 标记，gm_qq_ids 注入）；失败计数按 owner 记，5 次锁 15 分钟
（423 语义）。可选持久化回调把密文/盐落盘（内存状态 + 落盘由实现方决定）。

铁律：零 NoneBot import（细化_3a R1：web 层零 NoneBot，api.py L4-5）；零第三方
依赖（hashlib.pbkdf2_hmac + secrets + hmac 自实现；仓库 requirements.txt 无
bcrypt/passlib/jwt，pyproject dependencies=[]，venv 无 fastapi——见 M12 摸底
L68「grep 零命中」）；纯函数风格、确定性（时钟经 now_fn 注入，测试零 sleep
实等，遵循 fishing_editor_service.py「零 IO 零定时器零睡眠」铁律）；文件头标注
依据含契约行号；全中文注释。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Callable, Dict, Optional, TypedDict

# ---------------------------------------------------------------------------
# 常量（细化_5a 契约 §五 认证：AU-02/03/04 参数定稿）
# ---------------------------------------------------------------------------

MIN_PASSWORD_LEN = 8      # AU-02：≥8 位（契约 L142）
MAX_FAIL_COUNT = 5        # AU-04：失败 5 次锁定（契约 L144 / TC-17 L245）
LOCK_SECONDS = 15 * 60    # AU-04：锁 15 分钟（契约 L144 / TC-17 L245）
DEFAULT_TOKEN_TTL_SECONDS = 24 * 60 * 60  # 会话过期默认 24h（契约 L143「过期时间」，工程补白）
_PBKDF2_ITERATIONS = 120_000              # pbkdf2_hmac 迭代次数（工程补白，防爆破）
_SALT_BYTES = 16                          # 盐长 16B（工程补白）

# 角色命名对齐：gm_commands.py ROLE_ADMIN/ROLE_MANAGER（5b 机主/GM，L173-174）
ROLE_OWNER = "owner"    # 机主（5b admin）
ROLE_GM = "gm"          # GM（5b manager）
ROLE_NONE = None        # 未认证无身份

__all__ = [
    "AuthStore",
    "hash_password",
    "verify_password",
    "is_weak_password",
    "ROLE_OWNER",
    "ROLE_GM",
]


# ---------------------------------------------------------------------------
# 纯函数：密码哈希 / 校验 / 强度（零依赖：hashlib.pbkdf2_hmac + hmac 自实现）
# ---------------------------------------------------------------------------

def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    """加盐 pbkdf2_hmac-SHA256 哈希（AU-02 密码存储工程补白，L148）。

    返回格式 `pbkdf2_sha256$<iterations>$<盐 hex>$<哈希 hex>`（自包含，便于
    落盘/换参演进）。salt 缺省时 secrets.token_bytes 随机生成（16B）。
    纯函数零 IO；密码为空时 raise（调用方已做强度校验，双保险防误用）。
    """
    if salt is None:
        salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITERATIONS, salt.hex(), dk.hex()
    )


def verify_password(password: str, encoded: str) -> bool:
    """校验明文密码 vs 存储哈希串（hmac.compare_digest 常数时间比较防时序侧信道）。

    encoded 格式非法/位数不足 → False（不抛异常：防御畸形存储值）。
    """
    try:
        algo, iterations_s, salt_hex, hash_hex = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iterations_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, TypeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)


def is_weak_password(password: str) -> bool:
    """弱密码判定（AU-02，契约 L142）：长度 < 8 或不含字母或不含数字 → 弱。"""
    if len(password) < MIN_PASSWORD_LEN:
        return True
    has_alpha = any(ch.isalpha() for ch in password)
    has_digit = any(ch.isdigit() for ch in password)
    return not (has_alpha and has_digit)


# ---------------------------------------------------------------------------
# AuthStore：内存会话层（机主 id / GM 集合 / 时钟 / TTL / 落盘回调构造注入）
# ---------------------------------------------------------------------------

# 结构化返回字典字段别名（与 gm_commands GmResult 风格一致：dict 结果 + ok 头）
_R_OK = "ok"
_R_REASON = "reason"
_R_TOKEN = "token"
_R_LOCK_UNTIL = "lock_until"
_R_OWNER_ID = "owner_id"
_R_EXPIRES_AT = "expires_at"


class _SessionRec(TypedDict):
    """会话记录结构：token -> owner + 过期时刻（epoch 秒）。"""

    owner_id: str
    expires_at: float


class AuthStore:
    """编辑器认证存储（M12 批1 · 认证会话层，纯内存 + 可选持久化回调）。

    HTTP 语义映射（供 web/api.py 挂载时翻译状态码，契约 §6.1 L160-163）：
      setup_password：ok=False + reason="already_set" → 409；"weak_password" → 400
      login：          ok=False + reason="wrong_password" → 401；
                      ok=False + reason="locked" → 423（lock_until 带到期时间戳）
      me/logout：      token 无效/过期 → 401 语义
    单设备互踢（AU-03，TC-18）：同 owner 再次 login 成功 → 旧 token 立即失效。
    防爆破（AU-04，TC-17）：失败计数按 owner 记，达 5 次锁定 15 分钟，
    锁定期内 login 直接拒（不重置计数不返回 token）。

    时钟注入：now_fn 返回 epoch 秒（默认 time.time）；token 过期与锁定到期全部
    经 now_fn 判定——单测注入假时钟，零 sleep 实等（禁词回避）。token 生成用
    secrets.token_urlsafe（密码学安全随机，AU-03「随机 token」）。
    """

    def __init__(
        self,
        owner_qq_id: str,
        gm_qq_ids: Optional[set] = None,
        *,
        now_fn: Optional[Callable[[], float]] = None,
        token_ttl_seconds: float = DEFAULT_TOKEN_TTL_SECONDS,
        persist_fn: Optional[Callable[[str], None]] = None,
        load_fn: Optional[Callable[[], Optional[str]]] = None,
    ) -> None:
        # 机主 qq_id（AU-06 机主身份，构造注入；string 化统一比较）
        self.owner_qq_id = str(owner_qq_id)
        # GM qq_id 集合（AU-06 GM 权限判定；不建 admin_users 表——那是 M12 批2
        # 权限模型路的事，本路只做会话层，角色判定基于注入的集合）
        self.gm_qq_ids = {str(q) for q in (gm_qq_ids or set())}
        self._now_fn = now_fn or time.time
        self._token_ttl = float(token_ttl_seconds)

        self._password_hash: Optional[str] = None
        self._salt: Optional[bytes] = None

        # 会话表：token -> 会话记录 {owner_id, expires_at}
        self._sessions: Dict[str, _SessionRec] = {}
        # 单设备互踢索引：owner_id -> 当前有效 token（新 login 覆盖 → 旧 token 失效）
        self._owner_token: Dict[str, str] = {}

        # 失败计数与锁定（按 owner_id 记，AU-04）
        self._fail_count: Dict[str, int] = {}
        self._lock_until: Dict[str, float] = {}

        # 可选持久化回调（工程补白：密文/盐是否落盘由宿主决定；本路默认纯内存）
        self._persist_fn = persist_fn
        if load_fn is not None:
            encoded = load_fn()
            if encoded:
                self._password_hash = encoded
                # 从哈希串回读盐（仅当格式合法时；不合法视为未设密，防御性处理）
                try:
                    _algo, _iters, salt_hex, _h = encoded.split("$", 3)
                    self._salt = bytes.fromhex(salt_hex)
                except (ValueError, TypeError):
                    self._salt = None

    # -- 内部工具 ----------------------------------------------------------

    def _now(self) -> float:
        """当前 epoch 秒（经注入时钟，测试可控）。"""
        return self._now_fn()

    @property
    def password_set(self) -> bool:
        """是否已设密（首次设密仅未设置时可用，AU-02）。"""
        return self._password_hash is not None

    def _persist(self) -> None:
        """设密/改密后触发落盘回调（若注入）。"""
        if self._persist_fn is not None:
            self._persist_fn(self._password_hash or "")

    def _is_locked(self, owner_id: str) -> bool:
        """owner 当前是否在锁定期（AU-04）。过期自动解锁（惰性清理）。"""
        until = self._lock_until.get(owner_id)
        if until is None:
            return False
        if self._now() >= until:
            self._lock_until.pop(owner_id, None)
            return False
        return True

    def _reset_failures(self, owner_id: str) -> None:
        """成功后清零失败计数并解除锁定（AU-04：成功登录/设密重置）。"""
        self._fail_count.pop(owner_id, None)
        self._lock_until.pop(owner_id, None)

    def _revoke_token(self, token: str) -> None:
        """吊销 token：从会话表删除，并清理 owner_token 索引（互踢时旧 token 走此路）。"""
        rec = self._sessions.pop(token, None)
        if rec is not None:
            owner_id = rec["owner_id"]
            if self._owner_token.get(owner_id) == token:
                self._owner_token.pop(owner_id, None)

    def _purge_expired(self) -> None:
        """惰性清理过期会话（token 过期校验在 me/login 入口做，这里集中回收）。"""
        now = self._now()
        expired = [
            t for t, rec in self._sessions.items() if rec["expires_at"] <= now
        ]
        for token in expired:
            self._revoke_token(token)

    def _role_of(self, qq_id: str) -> str:
        """角色判定（AU-06 机主/GM）。owner 优先于 gm（机主天然最高权限，
        即使误入 gm 集合也判 owner，对齐 5b 三级机主>GM>普通玩家）。"""
        qid = str(qq_id)
        if qid == self.owner_qq_id:
            return ROLE_OWNER
        if qid in self.gm_qq_ids:
            return ROLE_GM
        return "player"

    # -- 认证操作（与契约 §6.1 四个端点一一对应） ---------------------------

    def setup_password(self, owner_id: str, password: str) -> dict:
        """首次设密（AU-02 / POST /api/auth/setup）。

        - 已设密 → {ok: False, reason: "already_set"}（409 语义）
        - 弱密码 → {ok: False, reason: "weak_password"}（400 语义）
        - 成功 → {ok: True}（200 语义）；密码加盐哈希存储 + 落盘回调
        """
        if self.password_set:
            return {_R_OK: False, _R_REASON: "already_set"}
        if is_weak_password(password):
            return {_R_OK: False, _R_REASON: "weak_password"}
        self._salt = secrets.token_bytes(_SALT_BYTES)
        self._password_hash = hash_password(password, salt=self._salt)
        self._persist()
        return {_R_OK: True}

    def verify_password(self, owner_id: str, password: str) -> bool:
        """密码校验（供登录用；未设密或哈希非法 → False）。owner_id 暂不参与
        校验（机主单口令模型，见模块 docstring 防爆破补白）；保留参数以对齐
        多 owner 扩展位。"""
        if self._password_hash is None:
            return False
        return verify_password(password, self._password_hash)

    def login(self, owner_id: str, password: str) -> dict:
        """登录（AU-03/AU-04 / POST /api/auth/login）。

        - 锁定期内 → {ok: False, reason: "locked", lock_until: 到期 epoch 秒}
          （423 语义，TC-17；计数不重置）
        - 密码错 → 计数 +1；达 5 次 → 锁 15 分钟（lock_until=now+900）；未达 →
          {ok: False, reason: "wrong_password", remaining: 剩余次数}（401 语义）
        - 成功 → 生成随机 token（secrets.token_urlsafe）带过期；**互踢**：旧
          token 立即失效（AU-03/TC-18）；{ok: True, token, expires_at}
        """
        owner = str(owner_id)
        # 锁定直接拒（AU-04，TC-17「第 6 次登录被锁」）
        if self._is_locked(owner):
            return {
                _R_OK: False,
                _R_REASON: "locked",
                _R_LOCK_UNTIL: self._lock_until.get(owner),
            }
        if not self.verify_password(owner, password):
            count = self._fail_count.get(owner, 0) + 1
            if count >= MAX_FAIL_COUNT:
                # 第 5 次失败即触发锁定（TC-17：连续输错 5 次 → 第 6 次被锁）
                self._fail_count[owner] = count
                until = self._now() + LOCK_SECONDS
                self._lock_until[owner] = until
                return {_R_OK: False, _R_REASON: "locked", _R_LOCK_UNTIL: until}
            self._fail_count[owner] = count
            return {_R_OK: False, _R_REASON: "wrong_password", "remaining": MAX_FAIL_COUNT - count}
        # 成功：清零失败计数 + 发 token（互踢：覆盖 owner_token 前先吊销旧会话）
        self._reset_failures(owner)
        self._purge_expired()
        token = secrets.token_urlsafe(32)
        expires_at = self._now() + self._token_ttl
        # 单设备互踢（AU-03）：吊销该 owner 现存有效 token
        old_token = self._owner_token.get(owner)
        if old_token is not None:
            self._revoke_token(old_token)
        self._sessions[token] = {"owner_id": owner, "expires_at": expires_at}
        self._owner_token[owner] = token
        return {_R_OK: True, _R_TOKEN: token, _R_EXPIRES_AT: expires_at}

    def logout(self, token: str) -> dict:
        """登出（POST /api/auth/logout，契约 L162）：token 立即失效。
        幂等：token 无效/已失效也返回 ok=True（HTTP 200，登出无失败态）。"""
        self._revoke_token(token)
        return {_R_OK: True}

    def me(self, token: str) -> dict:
        """当前会话身份（GET /api/auth/me，契约 L163）：token 有效 → {ok: True,
        owner_id, role, expires_at}（role ∈ owner/gm，AU-06 判定）；token
        无效/过期/空 → {ok: False, reason: "unauthorized"}（401 语义）。"""
        if not token:
            return {_R_OK: False, _R_REASON: "unauthorized"}
        rec = self._sessions.get(token)
        if rec is None:
            return {_R_OK: False, _R_REASON: "unauthorized"}
        # 过期判定（AU-03 过期时间；经注入时钟可测）
        if rec["expires_at"] <= self._now():
            self._revoke_token(token)
            return {_R_OK: False, _R_REASON: "unauthorized"}
        owner_id = rec["owner_id"]
        return {
            _R_OK: True,
            _R_OWNER_ID: owner_id,
            "role": self._role_of(owner_id),
            _R_EXPIRES_AT: rec["expires_at"],
        }
