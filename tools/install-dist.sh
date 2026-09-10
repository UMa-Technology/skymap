#!/usr/bin/env bash
#
# install-dist.sh —— 把 dist.zip 三件套装进一个 App 仓。
#
#   tools/install-dist.sh <app-root> [--from <dir>]
#
# 从 <dir>（缺省 apps/web-frontend-app）取 dist.zip / dist.zip.sha256 / dist.zip.json，
# 校验 sha 后拷到 <app-root>/assets/，同名旧文件先删。手工 cp 不再是流程的一部分：
# sidecar 跟着 zip 走，App 仓里 assets/dist.zip.json 就是「这份 dist 对应哪个
# commit」的账本。
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ROOT=""
FROM="$REPO_DIR/apps/web-frontend-app"

while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) if [ -z "$APP_ROOT" ]; then APP_ROOT="$1"; shift; else echo "多余参数：$1" >&2; exit 2; fi ;;
  esac
done
[ -n "$APP_ROOT" ] || { echo "用法：$0 <app-root> [--from <dir>]" >&2; exit 2; }
[ -d "$APP_ROOT" ] || { echo "错误：$APP_ROOT 不是目录" >&2; exit 2; }

ZIP="$FROM/dist.zip"
for f in "$ZIP" "$ZIP.sha256" "$ZIP.json"; do
  [ -f "$f" ] || { echo "错误：缺 ${f}（先 make dist-zip）" >&2; exit 1; }
done

# 拷之前校验：一份被截断/篡改的 zip 照样能拷进去、照样有一个 sha，
# 只有对着 sidecar 核过才算数。shasum -c 要在 sidecar 所在目录里跑。
( cd "$FROM" && shasum -a 256 -c "$(basename "$ZIP").sha256" >/dev/null ) ||
  { echo "错误：$ZIP 与 $ZIP.sha256 对不上，拒绝安装" >&2; exit 1; }

DEST="$APP_ROOT/assets"
mkdir -p "$DEST"
for f in "$ZIP" "$ZIP.sha256" "$ZIP.json"; do
  rm -f "$DEST/$(basename "$f")"
  cp "$f" "$DEST/"
done

echo "==> 已装到 $DEST/"
echo "    $(cat "$ZIP.sha256")"
echo "    $(cat "$ZIP.json")"
