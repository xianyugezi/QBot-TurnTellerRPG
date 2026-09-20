#!/usr/bin/env bash
# 内容编辑器 · systemd 常驻服务部署脚本（批63）
#
# 用途：把 scripts/editor_host.py 注册成 systemd 常驻服务（默认名 qbot-editor），
#      设为开机自启，挂了自动拉起。服务只监听 127.0.0.1，公网不可直达；
#      远程使用请走 SSH 隧道（配套脚本：scripts/gen_editor_tunnel_kit.sh）。
#
# 用法：
#   sudo bash scripts/deploy_editor_service.sh              # 安装 + 开机自启 + 立即启动
#   sudo bash scripts/deploy_editor_service.sh --no-start   # 只安装/启用，不立即启动
#   sudo bash scripts/deploy_editor_service.sh --status     # 查看状态（active/内存等）
#   sudo bash scripts/deploy_editor_service.sh --uninstall  # 停止 + 取消自启 + 删 unit（回滚）
#   sudo bash scripts/deploy_editor_service.sh --help
#
# 可覆盖的环境变量（一般不用改）：
#   EDITOR_SERVICE_NAME  服务名（默认 qbot-editor）
#   EDITOR_REPO          仓库根（默认 = 本脚本所在目录的上一级）
#   EDITOR_VENV_PY       解释器（默认 <仓库>/.venv/bin/python）
#   EDITOR_HOST          监听地址（默认 127.0.0.1；请勿改成 0.0.0.0，那会把编辑器裸奔到公网）
#   EDITOR_PORT          监听端口（默认 8090）
#   EDITOR_ROLE          权限位 owner|gm（默认 owner）
#   EDITOR_PACK          默认内容包（默认 veinborn；显式置空 = 用内容目录第一个）
#   EDITOR_CONTENT_ROOT  内容根（默认 <仓库>/content）
#   EDITOR_MEMORY_MAX    内存上限（默认 512M）
#
# 说明：本脚本只写 /etc/systemd/system/<服务名>.service，不改仓库任何功能代码。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${EDITOR_REPO:-$(cd "$SCRIPT_DIR/.." && pwd)}"

SERVICE_NAME="${EDITOR_SERVICE_NAME:-qbot-editor}"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
VENV_PY="${EDITOR_VENV_PY:-$REPO_ROOT/.venv/bin/python}"
HOST="${EDITOR_HOST:-127.0.0.1}"
PORT="${EDITOR_PORT:-8090}"
ROLE="${EDITOR_ROLE:-owner}"
PACK="${EDITOR_PACK-veinborn}"
CONTENT_ROOT="${EDITOR_CONTENT_ROOT:-$REPO_ROOT/content}"
MEMORY_MAX="${EDITOR_MEMORY_MAX:-512M}"

log() { printf '%s\n' "$*"; }
die() { printf '[部署失败] %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
内容编辑器 · systemd 常驻服务部署脚本（批63）

用法：
  sudo bash scripts/deploy_editor_service.sh              # 安装 + 开机自启 + 立即启动
  sudo bash scripts/deploy_editor_service.sh --no-start   # 只安装/启用，不立即启动
  sudo bash scripts/deploy_editor_service.sh --status     # 查看状态（active/内存等）
  sudo bash scripts/deploy_editor_service.sh --uninstall  # 停止 + 取消自启 + 删 unit（回滚）

可覆盖的环境变量：EDITOR_SERVICE_NAME / EDITOR_REPO / EDITOR_VENV_PY / EDITOR_HOST /
EDITOR_PORT / EDITOR_ROLE / EDITOR_PACK / EDITOR_CONTENT_ROOT / EDITOR_MEMORY_MAX
USAGE
}

case "${1:-install}" in
  --uninstall|uninstall|--remove|remove) MODE=uninstall ;;
  --status|status)                       MODE=status ;;
  --no-start)                            MODE=install-nostart ;;
  install|"")                            MODE=install ;;
  -h|--help)                             usage; exit 0 ;;
  *) die "未知参数：$1（用 --help 看用法）" ;;
esac

[ "$(id -u)" -eq 0 ] || die "需要 root 权限，请用 sudo 运行。"

if [ "$MODE" = status ]; then
  systemctl --no-pager --full status "$SERVICE_NAME" || true
  printf 'is-enabled: '; systemctl is-enabled "$SERVICE_NAME" 2>/dev/null || true
  printf 'is-active: ';  systemctl is-active  "$SERVICE_NAME" 2>/dev/null || true
  systemctl show -p MemoryCurrent -p MainPID "$SERVICE_NAME" 2>/dev/null || true
  exit 0
fi

if [ "$MODE" = uninstall ]; then
  systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
  rm -f "$UNIT_PATH"
  systemctl daemon-reload
  systemctl reset-failed "$SERVICE_NAME" 2>/dev/null || true
  log "已卸载 $SERVICE_NAME（unit 已删除、自启已取消）。"
  exit 0
fi

# —— 前置检查 ——
[ -x "$VENV_PY" ] || die "找不到可执行解释器：$VENV_PY（用 EDITOR_VENV_PY 指定）"
"$VENV_PY" -c 'import uvicorn, fastapi' >/dev/null 2>&1 \
  || die "解释器缺少依赖（uvicorn/fastapi）：$VENV_PY"
[ -f "$REPO_ROOT/scripts/editor_host.py" ] \
  || die "找不到编辑器宿主：$REPO_ROOT/scripts/editor_host.py"
[ -d "$CONTENT_ROOT" ] || die "内容目录不存在：$CONTENT_ROOT"
case "$ROLE" in owner|gm) ;; *) die "EDITOR_ROLE 只能是 owner 或 gm，收到：$ROLE" ;; esac
case "$PORT" in ''|*[!0-9]*) die "EDITOR_PORT 必须是数字，收到：$PORT" ;; esac

PACK_ARG=""
if [ -n "$PACK" ]; then PACK_ARG=" --pack $PACK"; fi

# —— 生成 unit（全文；由本脚本统一产出，保证可复现） ——
cat >"$UNIT_PATH" <<EOF
# ${UNIT_PATH}
# QBot 内容编辑器常驻服务（批63 部署产物）
# 由 scripts/deploy_editor_service.sh 生成；要改配置请改脚本里的变量后重跑，勿只改本文件。
# 只监听 ${HOST}:${PORT}（本机），公网不可直达；远程使用请走 SSH 隧道。
[Unit]
Description=QBot Content Editor (FastAPI/uvicorn on ${HOST}:${PORT})
After=network.target

[Service]
Type=simple
WorkingDirectory=${REPO_ROOT}
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=${VENV_PY} ${REPO_ROOT}/scripts/editor_host.py --host ${HOST} --port ${PORT} --role ${ROLE}${PACK_ARG} --content-root ${CONTENT_ROOT}
Restart=always
RestartSec=3
# 服务器无 Swap：给一个宽松内存上限，防极端情况拖垮整机
MemoryMax=${MEMORY_MAX}
# 停机时清掉整个 cgroup，避免残留子进程占住端口
KillMode=control-group
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOF

chmod 644 "$UNIT_PATH"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null

if [ "$MODE" = install ]; then
  if ss -ltn 2>/dev/null | grep -qE "[:.]${PORT}[[:space:]]"; then
    log "[提示] 端口 ${PORT} 当前已被占用；服务可能起不来。"
    log "        若那是手工起的编辑器，请先停掉（例如：pkill -f '\\.venv/bin/python .*scripts/editor_host\\.py'）再重试。"
  fi
  systemctl restart "$SERVICE_NAME"
  log "已安装并启动：$SERVICE_NAME（unit：$UNIT_PATH）"
else
  log "已安装并设为开机自启（未启动）：$SERVICE_NAME（unit：$UNIT_PATH）"
fi
printf 'is-enabled: '; systemctl is-enabled "$SERVICE_NAME"
