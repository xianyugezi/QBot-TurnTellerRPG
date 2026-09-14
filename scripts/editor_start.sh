#!/usr/bin/env bash
# 内容编辑器一键启动（编辑器重写批7）
#
# 用法：
#   bash scripts/editor_start.sh [--pack 包名] [--content-root 目录] [--role owner|gm]
#                                [--host 地址] [--port 端口] [--python 解释器]
#
# 默认：127.0.0.1:8090，权限位 owner（机主可编辑）。
# 只监听本机；远程使用请走 SSH 隧道（见启动后打印的提示），不要把端口直接开到公网。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

HOST="127.0.0.1"
PORT="8090"
ROLE="owner"
PACK=""
CONTENT_ROOT=""
PYTHON=""

usage() {
  cat <<'EOF'
内容编辑器一键启动

用法：
  bash scripts/editor_start.sh [选项]

选项：
  --pack 包名           打开时默认选中的内容包（缺省：内容目录里第一个）
  --content-root 目录   内容包根目录（缺省：<仓库根>/content）
  --role owner|gm       权限位：owner=机主可编辑（默认）/ gm=只读预览
  --host 地址           监听地址（缺省 127.0.0.1，仅本机）
  --port 端口           监听端口（缺省 8090）
  --python 解释器       指定 Python（缺省：<仓库根>/.venv/bin/python，再退 python3）
  -h, --help            显示本帮助

安全提示：
  默认只监听 127.0.0.1。远程使用推荐 SSH 隧道，不要直接把端口暴露到公网：
    ssh -N -L 8090:127.0.0.1:8090 用户名@服务器地址
EOF
}

die() {
  printf '\n[启动失败] %s\n' "$1" >&2
  shift
  for line in "$@"; do
    printf '           %s\n' "$line" >&2
  done
  exit 1
}

need_val() {
  # $1=选项名；要求还有下一个参数
  if [ "$#" -lt 2 ] || [ -z "${2:-}" ]; then
    die "选项 $1 缺少取值" "例：bash scripts/editor_start.sh $1 <值>"
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --pack)          need_val "$1" "${2:-}"; PACK="$2"; shift 2 ;;
    --content-root)  need_val "$1" "${2:-}"; CONTENT_ROOT="$2"; shift 2 ;;
    --role)          need_val "$1" "${2:-}"; ROLE="$2"; shift 2 ;;
    --host)          need_val "$1" "${2:-}"; HOST="$2"; shift 2 ;;
    --port)          need_val "$1" "${2:-}"; PORT="$2"; shift 2 ;;
    --python)        need_val "$1" "${2:-}"; PYTHON="$2"; shift 2 ;;
    -h|--help)       usage; exit 0 ;;
    *)               die "未知参数：$1" "可用参数见：bash scripts/editor_start.sh --help" ;;
  esac
done

# —— 参数合法性 ——
case "$ROLE" in
  owner|gm) ;;
  *) die "权限位只能是 owner（可编辑）或 gm（只读预览），收到：$ROLE" ;;
esac
case "$PORT" in
  ''|*[!0-9]*) die "端口必须是数字，收到：$PORT" ;;
esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  die "端口超出范围（1-65535）：$PORT"
fi

# —— 宿主脚本 ——
HOST_PY="$SCRIPT_DIR/editor_host.py"
if [ ! -f "$HOST_PY" ]; then
  die "找不到编辑器宿主脚本：$HOST_PY" "请确认在完整仓库里运行本脚本。"
fi

# —— 内容目录 ——
if [ -z "$CONTENT_ROOT" ]; then
  CONTENT_ROOT="$REPO_ROOT/content"
fi
if [ ! -d "$CONTENT_ROOT" ]; then
  die "内容目录不存在：$CONTENT_ROOT" "用 --content-root 指定正确的内容包根目录。"
fi
if [ ! -f "$CONTENT_ROOT/manifest.json" ] && [ -z "$(find "$CONTENT_ROOT" -mindepth 2 -maxdepth 2 -name manifest.json -print -quit 2>/dev/null)" ]; then
  die "内容目录里没有发现任何内容包：$CONTENT_ROOT" "每个内容包应形如 <目录>/<包名>/manifest.json。" "用 --content-root 指定正确的目录。"
fi

# —— 默认包展示（不改变宿主行为；宿主自己也会取第一个） ——
DEFAULT_PACK=""
for d in "$CONTENT_ROOT"/*/; do
  if [ -f "$d/manifest.json" ]; then
    DEFAULT_PACK="$(basename "$d")"
    break
  fi
done
if [ -n "$PACK" ] && [ ! -f "$CONTENT_ROOT/$PACK/manifest.json" ]; then
  AVAILABLE="$(cd "$CONTENT_ROOT" && for d in */; do [ -f "$d/manifest.json" ] && basename "$d"; done | paste -sd ',' -)"
  die "内容包不存在或缺少 manifest.json：$PACK" "可用内容包：${AVAILABLE:-（无）}" "用 --pack 指定正确的包名。"
fi

# —— Python 解释器 ——
if [ -n "$PYTHON" ]; then
  if [ ! -x "$PYTHON" ] && ! command -v "$PYTHON" >/dev/null 2>&1; then
    die "指定的 Python 不可用：$PYTHON"
  fi
elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
elif [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
  PYTHON="$VIRTUAL_ENV/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  die "找不到 Python 解释器" "安装 Python 3，或用 --python 指定解释器路径。"
fi

# —— 依赖 ——
if ! "$PYTHON" -c 'import uvicorn, fastapi' >/dev/null 2>&1; then
  die "Python 环境缺少依赖（uvicorn / fastapi）" "解释器：$PYTHON" "安装：$PYTHON -m pip install uvicorn fastapi"
fi

# —— 端口可用性（给人话报错；启动竞态极小，真冲突时宿主也会再报一次） ——
if ! PORT_ERR="$("$PYTHON" - "$HOST" "$PORT" <<'PY' 2>&1
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
bind_host = "" if host in ("0.0.0.0", "::") else host
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    sock.bind((bind_host, port))
except OSError as exc:
    print(exc)
    sys.exit(1)
finally:
    sock.close()
PY
)"; then
  die "端口 $HOST:$PORT 不可用：${PORT_ERR:-已被占用}" \
      "换一个端口：bash scripts/editor_start.sh --port 8091" \
      "或先停掉占用该端口的进程。"
fi

# —— 打印信息 ——
echo "内容编辑器启动中……"
echo "  内容包根目录： $CONTENT_ROOT"
echo "  默认内容包：   ${PACK:-${DEFAULT_PACK:-（无）}}"
echo "  权限位：       $ROLE （owner=机主可编辑 / gm=只读预览）"
echo "  Python：       $PYTHON"
echo "  访问地址：     http://$HOST:$PORT/"
echo ""
echo "如何安全暴露（不要直接把端口开到公网）："
echo "  1) 本机使用：浏览器直接打开上面的「访问地址」。"
echo "  2) 远程使用（推荐）：在你自己电脑上建 SSH 隧道，再打开本机地址"
echo "       ssh -N -L $PORT:127.0.0.1:$PORT 用户名@服务器地址"
echo "  3) 内网使用：确认处在可信内网后，可加 --host 0.0.0.0 让同网段访问。"
echo ""
echo "按 Ctrl+C 停止。"
echo ""

ARGS=(--host "$HOST" --port "$PORT" --role "$ROLE")
if [ -n "$PACK" ]; then
  ARGS+=(--pack "$PACK")
fi
if [ -n "$CONTENT_ROOT" ]; then
  ARGS+=(--content-root "$CONTENT_ROOT")
fi

"$PYTHON" "$HOST_PY" "${ARGS[@]}"
CODE=$?

if [ "$CODE" -eq 0 ] || [ "$CODE" -eq 130 ]; then
  echo
  echo "编辑器已停止。"
  exit 0
fi

die "编辑器未能正常启动（退出码 $CODE）" \
    "常见原因与处理：" \
    "  · 端口被占用：换 --port，或先停掉占用进程" \
    "  · 内容目录 / 包名不对：核对 --content-root / --pack" \
    "  · 依赖缺失：$PYTHON -m pip install uvicorn fastapi" \
    "  · 其它：看上面 uvicorn 打印的报错原文。"
