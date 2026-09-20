#!/usr/bin/env bash
# 内容编辑器 · 一键隧道交付包生成脚本（批63）
#
# 用途：生成「Windows 双击即用 / macOS 双击即用」的 SSH 隧道脚本 + 面向小白的《使用说明》，
#      连同私钥一起打成 zip，交给用户在自己电脑上使用。
#
# 用法：
#   bash scripts/gen_editor_tunnel_kit.sh
#   bash scripts/gen_editor_tunnel_kit.sh --key <私钥文件> --out <zip路径> \
#                                        --server <服务器> --lport <本地端口> --rport <服务器端口>
#
# 默认：
#   私钥     /root/deliverables/id_ed25519_服务器免密私钥.txt
#   输出     /root/deliverables/editor_tunnel_kit.zip
#   服务器   134.175.187.200
#   本地端口 8090（用户电脑监听）
#   服务器端口 8090（服务器上编辑器端口；只监听 127.0.0.1）
#   私钥名   qbot_editor_key（放进用户电脑的 ~/.ssh/ 或 %USERPROFILE%\.ssh\）
#
# 安全：本脚本只复制私钥，绝不回显私钥内容；生成的 zip 内含私钥，请只放自己电脑、不要外传。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

KEY_FILE="/root/deliverables/id_ed25519_服务器免密私钥.txt"
OUT_ZIP="/root/deliverables/editor_tunnel_kit.zip"
WORKDIR="/root/deliverables/editor_tunnel_kit"
SERVER="134.175.187.200"
LPORT="8090"
RPORT="8090"
KEY_NAME="qbot_editor_key"

usage() {
  cat <<'USAGE'
内容编辑器 · 一键隧道交付包生成脚本（批63）

用法：
  bash scripts/gen_editor_tunnel_kit.sh [选项]

选项：
  --key <文件>       私钥文件（默认 /root/deliverables/id_ed25519_服务器免密私钥.txt）
  --out <zip>        输出 zip 路径（默认 /root/deliverables/editor_tunnel_kit.zip）
  --workdir <目录>   解包工作目录（默认 /root/deliverables/editor_tunnel_kit）
  --server <主机>    服务器公网地址（默认 134.175.187.200）
  --lport <端口>     用户电脑本地监听端口（默认 8090）
  --rport <端口>     服务器上编辑器端口（默认 8090）
  --key-name <名字>  私钥在用户电脑上的文件名（默认 qbot_editor_key）
  -h, --help         显示本帮助
USAGE
}

log() { printf '%s\n' "$*"; }
die() { printf '[生成失败] %s\n' "$*" >&2; exit 1; }

while [ "$#" -gt 0 ]; do
  case "$1" in
    --key)      KEY_FILE="${2:?--key 需要取值}";      shift 2 ;;
    --out)      OUT_ZIP="${2:?--out 需要取值}";       shift 2 ;;
    --workdir)  WORKDIR="${2:?--workdir 需要取值}";   shift 2 ;;
    --server)   SERVER="${2:?--server 需要取值}";     shift 2 ;;
    --lport)    LPORT="${2:?--lport 需要取值}";       shift 2 ;;
    --rport)    RPORT="${2:?--rport 需要取值}";       shift 2 ;;
    --key-name) KEY_NAME="${2:?--key-name 需要取值}"; shift 2 ;;
    -h|--help)  usage; exit 0 ;;
    *) die "未知参数：$1（用 --help 看用法）" ;;
  esac
done

for v in LPORT RPORT; do
  eval "p=\$$v"
  case "$p" in ''|*[!0-9]*) die "$v 必须是数字，收到：$p" ;; esac
done

[ -f "$KEY_FILE" ] || die "私钥文件不存在：$KEY_FILE"

# —— 私钥体检（只看结构，不回显内容） ——
if ! grep -qE 'BEGIN OPENSSH PRIVATE KEY|BEGIN (RSA|EC|DSA) PRIVATE KEY' "$KEY_FILE"; then
  die "这个文件看起来不是 OpenSSH 私钥：$KEY_FILE"
fi
KEY_FP="$(ssh-keygen -lf "$KEY_FILE" 2>/dev/null | awk '{print $2}')" || true
[ -n "$KEY_FP" ] && log "私钥指纹：$KEY_FP （仅指纹，非私钥内容）"

mkdir -p "$WORKDIR"
chmod 700 "$WORKDIR" 2>/dev/null || true
rm -f "$WORKDIR/qbot_editor_key" "$WORKDIR"/*.bat "$WORKDIR"/*.command "$WORKDIR/使用说明.txt" 2>/dev/null || true

# —— 1) 私钥：改名后随包交付 ——
install -m 600 "$KEY_FILE" "$WORKDIR/$KEY_NAME"

# —— 2) Windows 双击脚本（UTF-8 生成 → CRLF → GBK，避免中文乱码） ——
cat >"$WORKDIR/.editor_tunnel.bat.utf8" <<'BAT_EOF'
@echo off
setlocal
title 编辑器隧道 - 请不要关闭本窗口
set "KEY=%USERPROFILE%\.ssh\__KEY_NAME__"
set "URL=http://127.0.0.1:__LPORT__"

echo ============================================================
echo    QBot 内容编辑器 - 一键隧道
echo ============================================================
echo.
echo   [1] 正在连接服务器，请等 3-10 秒 ...
echo   [2] 连上后浏览器会自动打开编辑器
echo   [3] 这个黑色窗口【千万不要关闭】，
echo       关掉窗口就等于断开，编辑器就打不开了
echo.
echo ============================================================
echo.

where ssh >nul 2>&1
if errorlevel 1 (
    echo [错误] 你的电脑里找不到 ssh 命令。
    echo        Windows 10/11 一般自带；没有的话请让懂电脑的人帮忙装 OpenSSH。
    echo.
    pause
    exit /b 1
)

if not exist "%KEY%" (
    echo [错误] 找不到钥匙文件：
    echo        %KEY%
    echo.
    echo   请把 "__KEY_NAME__" 放到下面这个文件夹里：
    echo        %USERPROFILE%\.ssh\
    echo   （如果 .ssh 文件夹不存在，请自己新建一个）
    echo   放好后再重新双击本文件。
    echo.
    pause
    exit /b 1
)

netstat -ano | findstr ":__LPORT__ " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [提示] 你电脑的 __LPORT__ 端口已经被别的程序占用了，
    echo        隧道可能开不起来。请先关掉占用它的程序，再重新双击。
    echo.
)

echo 正在建立隧道，连接成功后浏览器会自动打开 ...
echo.

start "" powershell -NoProfile -WindowStyle Hidden -Command "$u='http://127.0.0.1:__LPORT__/'; foreach($i in 1..40){ try{ Invoke-WebRequest -UseBasicParsing -Uri $u -TimeoutSec 1 | Out-Null; Start-Process $u; break } catch { Start-Sleep -Seconds 1 } }"

ssh -N -L 127.0.0.1:__LPORT__:127.0.0.1:__RPORT__ ^
    -i "%KEY%" ^
    -o IdentitiesOnly=yes ^
    -o PreferredAuthentications=publickey ^
    -o ServerAliveInterval=30 ^
    -o ServerAliveCountMax=3 ^
    -o TCPKeepAlive=yes ^
    -o ExitOnForwardFailure=yes ^
    -o StrictHostKeyChecking=accept-new ^
    -o ConnectTimeout=15 ^
    root@__SERVER__

echo.
echo [隧道已断开] 想继续使用，请重新双击本文件。
echo 按任意键关闭本窗口 ...
pause >nul
BAT_EOF
sed -e "s|__KEY_NAME__|$KEY_NAME|g" -e "s|__LPORT__|$LPORT|g" \
    -e "s|__RPORT__|$RPORT|g" -e "s|__SERVER__|$SERVER|g" \
    "$WORKDIR/.editor_tunnel.bat.utf8" | sed 's/$/\r/' | iconv -f UTF-8 -t GBK \
    >"$WORKDIR/编辑器隧道.bat"
rm -f "$WORKDIR/.editor_tunnel.bat.utf8"

# —— 3) macOS 双击脚本（可选） ——
cat >"$WORKDIR/编辑器隧道.command" <<'CMD_EOF'
#!/bin/bash
# QBot 内容编辑器 · 一键隧道（macOS；首次使用请先 chmod +x 本文件）
KEY="$HOME/.ssh/__KEY_NAME__"
URL="http://127.0.0.1:__LPORT__"

echo "============================================================"
echo "  QBot 内容编辑器 - 一键隧道"
echo "============================================================"
echo ""
echo "  [1] 正在连接服务器，请等 3-10 秒 ..."
echo "  [2] 连上后浏览器会自动打开编辑器"
echo "  [3] 这个终端窗口【千万不要关闭】，关掉就等于断开"
echo ""
echo "============================================================"
echo ""

if ! command -v ssh >/dev/null 2>&1; then
  echo "[错误] 找不到 ssh 命令。"
  read -r -p "按回车键关闭 ..." _ || true
  exit 1
fi

if [ ! -f "$KEY" ]; then
  echo "[错误] 找不到钥匙文件：$KEY"
  echo "       请把 __KEY_NAME__ 放到 ~/.ssh/ 目录里，再重新双击本文件。"
  read -r -p "按回车键关闭 ..." _ || true
  exit 1
fi

(
  for _ in $(seq 1 40); do
    if curl -s -o /dev/null --max-time 1 "$URL/"; then
      open "$URL" 2>/dev/null || true
      break
    fi
    sleep 1
  done
) &

ssh -N -L 127.0.0.1:__LPORT__:127.0.0.1:__RPORT__ \
  -i "$KEY" \
  -o IdentitiesOnly=yes \
  -o PreferredAuthentications=publickey \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o TCPKeepAlive=yes \
  -o ExitOnForwardFailure=yes \
  -o StrictHostKeyChecking=accept-new \
  -o ConnectTimeout=15 \
  root@__SERVER__

echo ""
echo "[隧道已断开] 想继续使用，请重新双击本文件。"
read -r -p "按回车键关闭 ..." _ || true
CMD_EOF
sed -e "s|__KEY_NAME__|$KEY_NAME|g" -e "s|__LPORT__|$LPORT|g" \
    -e "s|__RPORT__|$RPORT|g" -e "s|__SERVER__|$SERVER|g" \
    "$WORKDIR/编辑器隧道.command" >"$WORKDIR/.cmd.tmp"
mv "$WORKDIR/.cmd.tmp" "$WORKDIR/编辑器隧道.command"
chmod +x "$WORKDIR/编辑器隧道.command"

# —— 4) 面向小白的《使用说明》（UTF-8 带 BOM，Windows 记事本友好） ——
{
  printf '\xEF\xBB\xBF'
  cat <<'README_EOF'
QBot 内容编辑器 · 一键使用说明（给非技术用户）
================================================

一、这个压缩包里有什么
  1. 编辑器隧道.bat      Windows 用：双击它
  2. 编辑器隧道.command  Mac 用：双击它（可选）
  3. qbot_editor_key     你的"钥匙"文件（等于家门钥匙，别外传）
  4. 使用说明.txt        本文件

二、一次性的准备（只做一次）
  1. 把 qbot_editor_key 放到下面这个文件夹里：
       Windows： C:\Users\你的用户名\.ssh\
       Mac：     ~/.ssh/
     （如果没有 .ssh 这个文件夹，就在同样位置新建一个）
  2. Windows：把"编辑器隧道.bat"复制到桌面。
     Mac：把"编辑器隧道.command"复制到桌面，然后在"终端"里执行一次：
            chmod +x ~/Desktop/编辑器隧道.command

三、每天怎么用（3 步）
  1. 双击桌面上的"编辑器隧道"。
  2. 弹出黑色小窗口后：
       - 连上以后，浏览器会自动打开编辑器；
       - 没有自动打开，就自己打开浏览器，输入： http://127.0.0.1:8090
       - 【千万不要关闭这个黑色窗口】，关掉就等于断线。
  3. 看到左中右三栏 = 成功。改完点"保存"；改错了点"回退到上一份备份"。
     用完了：直接关掉那个黑色窗口即可。

四、常见问题（照着查）
  1) 双击后黑窗口一闪就没了
     -> 多半是没连上。先检查 qbot_editor_key 是否放对了位置；
        也可以右键 .bat 选"以管理员身份运行"，看窗口里的红字提示。
  2) 黑窗口写 Permission denied (publickey)
     -> 钥匙文件位置不对，或文件名被改过。
        确认它在 .ssh\ 文件夹里、名字正好是 qbot_editor_key。
  3) 黑窗口写 Address already in use / bind: ... failed
     -> 你电脑的 8090 端口被别的程序占用了。
        关掉占用它的程序，再重新双击一次。
  4) 黑窗口写 WARNING: UNPROTECTED PRIVATE KEY FILE
     -> 钥匙文件权限太松（Mac 常见）。打开"终端"执行：
        chmod 600 ~/.ssh/qbot_editor_key
  5) 浏览器一直转圈 / 提示"无法访问此网站"
     -> 先看那个黑色窗口还在不在：
        不在 = 重新双击；在 = 等几秒再刷新。仍不行请找管理员。
  6) 黑色窗口不小心被关了
     -> 重新双击一次即可，不会有损失。
  7) 打开后只能看、不能改（只读）
     -> 这是编辑器的身份设置问题，请找管理员。

五、安全提醒（重要）
  1. qbot_editor_key 等于你家的钥匙：只放在自己电脑上，别发群里、别传给别人。
  2. 这个压缩包里有钥匙，请收到后解压到自己电脑，然后把原压缩包删掉。
  3. 黑色窗口开着的时候，外面的人看不到、也进不来，是安全的。
  4. 钥匙丢了或怀疑泄露，请立刻找管理员换一把。
README_EOF
} >"$WORKDIR/使用说明.txt"

# —— 5) 打包 ——
PY="$(command -v python3 || true)"
[ -n "$PY" ] || die "找不到 python3，无法打包"
mkdir -p "$(dirname "$OUT_ZIP")"
rm -f "$OUT_ZIP"
"$PY" - "$WORKDIR" "$OUT_ZIP" <<'PY_EOF'
import os, sys, zipfile
src, out = sys.argv[1], sys.argv[2]
names = sorted(n for n in os.listdir(src) if os.path.isfile(os.path.join(src, n)))
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for n in names:
        z.write(os.path.join(src, n), n)
print("zipped:", ", ".join(names))
PY_EOF

log ""
log "交付包已生成：$OUT_ZIP"
log "工作目录（同样含私钥，注意保管）：$WORKDIR"
log "文件清单："
( cd "$WORKDIR" && ls -la --time-style=long-iso )
log ""
log "安全提醒：zip 内含私钥，请只放在自己电脑、不要外传。私钥内容本脚本从不回显。"
