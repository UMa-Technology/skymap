#!/usr/bin/env bash
#
# make-dist-zip.sh —— 从 apps/skymap-web/dist/ 生成可复现的 dist.zip。
#
# 与直接 `zip -rqX ../dist.zip .` 的两点不同：
#
# 1. Allowlist（其实是 denylist + 显式排除）。dist/ 里混着只在开发时用的东西：
#    SkyPhotos 对齐的回归夹具图（6.8MB）、瓦片调试页、以及 macOS 的 .DS_Store。
#    它们进不进包不影响星图渲染。排除清单里还留着一条 drakkar.zip，那是历史遗留：
#    当前树里已经没有这个文件了，留着纯粹是防它哪天再回来，详见 EXCLUDES 处的注释。
#
# 2. 归一 mtime 与权限位。zip 存每个文件的修改时间和 Unix 权限，所以内容完全相同的
#    两次构建产出的 zip 字节不同。消费方（Flutter 包）用 zip 的 sha256 当缓存目录名，
#    字节抖动会让每次构建都触发一次 80MB 的重新解压，且包仓库每提交一次就白涨 80MB 历史。
#    做法是把文件克隆进一个暂存目录、chmod 成统一的 755/644、全部 touch 成 zip 纪元
#    （1980-01-01），再打包。`zip -X` 只去掉 extra field，管不到权限位，详见下面的注释。
#
# 用法：
#   tools/make-dist-zip.sh                    # 默认读 apps/skymap-web/dist
#   tools/make-dist-zip.sh path/to/dist       # 指定目录
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${1:-$REPO_DIR/apps/skymap-web/dist}"
OUT_ZIP="$(cd "$(dirname "$DIST_DIR")" && pwd)/dist.zip"
# 先写到 .tmp 再 mv 就位：mv 是原子的，中途失败不会留下一个截断的 dist.zip
# 冒充好产物（它照样能算出一个稳定的 sha256），也不会被顺手 commit 进去。
TMP_ZIP="$OUT_ZIP.tmp"
STAGE_DIR="$(dirname "$DIST_DIR")/.dist-stage"

if [ ! -f "$DIST_DIR/index.html" ]; then
  echo "错误：$DIST_DIR 里没有 index.html，先跑一次 vite build" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# dist/ 陈旧检查。zip 的 sha256 会被下游当资源版本号钉住，所以打包一份落后于
# 源码的 dist/ 是可以的（有时正是想要的），悄悄打包才是问题。
# 两棵源码树分开报：前端只要 npx vite build，引擎 C 还得重编 WASM，代价不同；
# 只重建前端会得到一个"半套"产物——同时改了两棵树的提交只落地了 JS 那一半。
# 拿不到 git（没装 / 不是工作树 / 导出的 tarball）就静默跳过，绝不因此挡住出包。
# ---------------------------------------------------------------------------
newest_mtime() {
  # BSD stat（macOS）用 -f 取格式串，GNU stat（Linux）用 -c，各试一次。
  # 每次都必须验结果是不是纯数字，不能只判断"空不空"：GNU 的 -f 是 --file-system，
  # 根本不是格式串，它会把文件系统信息（File:/ID:/Type: …）打到 stdout、只把对
  # %m 的抱怨丢进 stderr。于是 $t 拿到一堆非空垃圾，"空才回退"的判断被骗过，
  # GNU 分支永远走不到，git 又收到 --since="@Inodes: Total: …" 这种没法解析的日期，
  # 算出 0 个提交落后——陈旧告警在 Linux 上就等于不存在了。
  local t=""
  t=$(find "$1" -exec stat -f '%m' {} + 2>/dev/null | sort -rn | head -1) || true
  case "$t" in ''|*[!0-9]*) t="" ;; esac
  if [ -z "$t" ]; then
    t=$(find "$1" -exec stat -c '%Y' {} + 2>/dev/null | sort -rn | head -1) || true
    case "$t" in ''|*[!0-9]*) t="" ;; esac
  fi
  printf '%s' "$t"
}

warn_if_stale() {
  command -v git >/dev/null 2>&1 || return 0
  git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0

  local dist_t=""
  dist_t=$(newest_mtime "$DIST_DIR")
  [ -n "$dist_t" ] || return 0

  # 每项格式："路径|人话名字|重建方式"
  # public/ 也是真构建输入（Vite 的 publicDir 整个拷进 dist/），漏掉它就是漏一类陈旧。
  # 注意 public/skydata 是指向 apps/skydata 的软链接，git 只跟踪这条软链本身——
  # 星表数据自身的改动这里看不到，那是另一棵树，暂不纳入。
  local specs="apps/skymap-web/src|前端源码|npx vite build
apps/skymap-web/public|前端静态资源 fonts/images/favicon|npx vite build
src|引擎 C 源码|./build-engine.sh（重编 WASM）"
  local lines_n=0 lines="" spec path label how n newest
  local OLD_IFS="$IFS"
  IFS='
'
  for spec in $specs; do
    IFS="$OLD_IFS"
    path=${spec%%|*}
    spec=${spec#*|}
    label=${spec%%|*}
    how=${spec#*|}
    [ -e "$REPO_DIR/$path" ] || { IFS='
'; continue; }
    n=$(git -C "$REPO_DIR" log --oneline --since="@$dist_t" -- "$path" 2>/dev/null | wc -l | tr -d ' ') || n=0
    if [ -n "$n" ] && [ "$n" -gt 0 ]; then
      newest=$(git -C "$REPO_DIR" log -1 --format='%h %cd' --date=format:'%Y-%m-%d %H:%M' -- "$path" 2>/dev/null) || newest="?"
      lines="$lines
!!   ${path}（${label}）落后 ${n} 个提交，最新 ${newest} —— 重建：${how}"
      lines_n=$((lines_n + 1))
    fi
    IFS='
'
  done
  IFS="$OLD_IFS"
  [ "$lines_n" -gt 0 ] || return 0
  # 记进 sidecar：commit 字段是**打包时**的 HEAD，dist/ 却可能是更早构建的；
  # 「在 A 构建、提交 B 再打包」会得到 commit=B 而内容来自 A，stale=true 就是这种情况的标记
  STALE=true

  local dist_h
  dist_h=$(date -r "$dist_t" '+%Y-%m-%d %H:%M' 2>/dev/null) ||
    dist_h=$(date -d "@$dist_t" '+%Y-%m-%d %H:%M' 2>/dev/null) || dist_h="$dist_t"

  {
    echo "!! ==================================================================="
    echo "!! 警告：dist/ 比源码旧，正在打包一份陈旧快照"
    echo "!!   dist/ 最新改动：$dist_h"
    printf '%s\n' "${lines#
}"
    echo "!!   有意打包旧快照就忽略本条；否则先重建再打包。"
    echo "!!   注意：只重建前端会得到半套产物——同时改了两棵树的提交只落地 JS 那一半。"
    echo "!! ==================================================================="
  } >&2
}
STALE=false
warn_if_stale

# 排除清单。每条都注明为什么。
EXCLUDES=(
  # SkyPhotos 对齐的回归夹具，只在开发时从控制台手动贴图用
  # （见 apps/skymap-web/USAGE.md）。仓库里保留，不进产物。
  "images/m42.jpeg"
  "images/rose.jpeg"
  # 历史遗留：曾经出现过一份与 skydata/landscapes/drakkar/ 目录内容重复的压缩包。
  # 当前树里已经没有它了（旧 dist.zip 里也没有），这条纯粹是防它哪天再回来。
  "skydata/landscapes/drakkar.zip"
  # 瓦片挑选/评分的开发调试页
  "tile-picker.html"
  "tile-scores.json"
  "tile-streaks.json"
  # DSS 清理工具在 8080 开发服务器上看的评审页，生成在本树 public/ 下，不进产物
  "staircase-picker"
  "plate-eq-review"
  "cast-final-review"
  "seam-feather-review"
)

echo "==> 暂存到 $STAGE_DIR"
# 无论成功、失败还是 Ctrl-C 都清掉暂存目录。残留的 .dist-stage 会让下一次
# cp -R 把源拷"进"这个已存在的目录，zip 里所有路径平白多一层 dist/ 前缀——
# 产物看着正常、解压出来结构不对，极难排查。
# INT/TERM 各自单列并显式 exit：陷阱处理函数跑完是「返回」而不是「退出」，
# 只挂 EXIT INT TERM 的话 Ctrl-C 会先清掉暂存目录、然后**继续往下跑**，
# 在下一步撞上刚被删掉的目录才死——错得晚且看不出因果。
# ${STAGE_DIR:?} 是纵深防御：STAGE_DIR 由 ${1:-…}（用的是 `:-`）推出来，不可能为空，
# 但 `rm -rf ""` 的后果太大，四处（三个 trap、暂存前的清理、回退分支的清理、
# 排除项循环）统一都带上。
trap 'rm -rf "${STAGE_DIR:?}" "${TMP_ZIP:?}"' EXIT
trap 'rm -rf "${STAGE_DIR:?}" "${TMP_ZIP:?}"; exit 130' INT
trap 'rm -rf "${STAGE_DIR:?}" "${TMP_ZIP:?}"; exit 143' TERM
rm -rf "${STAGE_DIR:?}"
# -c 用 APFS clone（秒级、不占额外空间）；不支持时退回普通拷贝。
# 回退前必须先删掉 $STAGE_DIR：cp -Rc 可能是拷到一半才失败的（目标不是 APFS、
# 网络卷、磁盘满、权限），此时目录已存在，而 `cp -R src 已存在的目录` 的语义是
# 拷"进去"，会得到 .dist-stage/dist/…，最终 zip 里每条路径都多一层 dist/ 前缀。
# 那样的包照样能过 unzip -t、照样有稳定的 sha256，只是结构整个是错的。
cp -Rc "$DIST_DIR" "$STAGE_DIR" 2>/dev/null || { rm -rf "${STAGE_DIR:?}"; cp -R "$DIST_DIR" "$STAGE_DIR"; }

echo "==> 剔除非运行时文件"
for rel in "${EXCLUDES[@]}"; do
  if [ -e "$STAGE_DIR/$rel" ]; then
    rm -rf "${STAGE_DIR:?}/$rel"
    echo "    - $rel"
  fi
done
# macOS 垃圾文件按名字全删。.DS_Store 当前就有 5 个；._* 是 AppleDouble 资源叉、
# __MACOSX 是 macOS 打的 zip 解出来带的，目前树里没有，但文件一旦经由网络卷或
# 一次解压中转就会冒出来，顺手一起扫掉。
find "$STAGE_DIR" -name '.DS_Store' -delete
find "$STAGE_DIR" -name '._*' -delete
find "$STAGE_DIR" -name '__MACOSX' -type d -prune -exec rm -rf {} +

echo "==> 归一权限位与 mtime"
# 权限位必须一起归一，`zip -X` 管不着它。-X 去掉的是 extra field（实测归档里
# "length of extra field: 0"），而 Unix 权限存在中央目录的外部属性字段里，-X 原样保留
# （实测能读到 "Unix file attributes (100644 octal)"）——内容一模一样的两次打包，
# 权限位一差字节就不同，sha256 跟着变，而下游拿它当缓存目录名。
# 两条拷贝路径的权限语义还不一样：GNU cp 没有 -c，所以每次 Linux 运行都走 `cp -R`
# 那条回退，产出的权限受调用者 umask 影响；macOS 的 `cp -Rc` 克隆能保住文件权限，
# 但它新建的目录同样吃 umask（实测 umask 077 下拷出来是 drwx------）。
# 现在 dist/ 恰好是齐整的 644/755、CI 又恰好 umask 022，才显得一直没事。
# 注意剩下的边界：deflate 的输出还取决于 zip 的实现（macOS 自带的是 Apple 改过的
# Info-ZIP 3.0），跨操作系统的字节一致性这里没有任何东西能保证；归一权限位收掉的是
# 我们控制得了的那部分方差。
find "$STAGE_DIR" -type d -exec chmod 755 {} +
find "$STAGE_DIR" -type f -exec chmod 644 {} +
find "$STAGE_DIR" -exec touch -t 198001010000 {} +

echo "==> 打包"
rm -f "$TMP_ZIP"
# 显式排序后喂给 zip，而不是让它 -r 按 readdir 走目录。
# readdir 顺序在同一个卷上稳定，但换机器、换文件系统、甚至重新 clone 之后都可能变，
# 而 zip 的中央目录记录条目顺序——顺序一变字节就变，sha256 跟着变，
# 「可复现」就退化成「只在这台机器上可复现」。
# LC_ALL=C 让排序按字节序，不受 locale 影响（同一类 bug 的下一层）。
# -X 去掉额外的文件属性（uid/gid/扩展属性），与归一 mtime 一起保证可复现。
# -@ 从 stdin 读文件名，-q 安静。在暂存目录里执行，让 zip 内的路径不带前缀。
( cd "$STAGE_DIR" && find . -mindepth 1 | LC_ALL=C sort | zip -qX "$TMP_ZIP" -@ )

# 暂存目录由上面的 trap 清理。

echo "==> 自检"
# 把原本一次性的手工验证做进脚本：make dist-zip 和 npm run postbuild 才是别人
# 实际会走的两条路径，而按裁决没人跑浏览器冒烟、消费方又只校验 sha256——一个
# 结构错了的包同样有稳定的 sha256，不自检就一道防线都没有。在 mv 就位之前查，
# 不合格的产物根本不会顶掉上一份好的 dist.zip。
selfcheck_fail() {
  echo "自检失败：$1" >&2
  echo "（未就位，$OUT_ZIP 保持原样）" >&2
  exit 1
}
# 用 here-string 而不是 `printf | grep -q`：grep -q 命中就立刻退出，写端吃到
# SIGPIPE，配上 set -o pipefail 整条管线就算失败——检查通过反被判成不通过。
NAMES=$(unzip -Z1 "$TMP_ZIP")
COUNT=$(printf '%s\n' "$NAMES" | wc -l | tr -d ' ')
grep -qx 'index.html' <<<"$NAMES" ||
  selfcheck_fail "包根目录没有 index.html（多半是暂存目录嵌套，整包路径多了一层前缀）"
grep -q '\.wasm$' <<<"$NAMES" ||
  selfcheck_fail "包里没有引擎 .wasm，星图起不来"
# 暂存目录此刻还在（trap 到脚本结束才清），所以可以拿它的真实条目数做精确比对，
# 比任何静态下限都严：少一个文件就报。静态下限在本仓库尤其无力——
# skydata/surveys/dss 一棵子树就占 4656 条里的 4040 条（86.8%），
# 其余 616 条全丢光也照样过得去 4000 这道坎。
STAGE_COUNT=$(find "$STAGE_DIR" -mindepth 1 | wc -l | tr -d ' ')
[ "$COUNT" = "$STAGE_COUNT" ] ||
  selfcheck_fail "条目数对不上：包里 ${COUNT} 条，暂存目录 ${STAGE_COUNT} 条（差 $((STAGE_COUNT - COUNT))）"
echo "    根目录 index.html、引擎 .wasm 都在，条目数 ${COUNT} = 暂存目录 ${STAGE_COUNT}"

mv "$TMP_ZIP" "$OUT_ZIP"

SIZE=$(wc -c < "$OUT_ZIP" | tr -d ' ')
SHA=$(shasum -a 256 "$OUT_ZIP" | cut -d' ' -f1)

# ---------------------------------------------------------------------------
# sidecar：来源信息写在 zip 旁边，**不进 zip**。zip 里塞任何随 commit 变的东西
# 都会让 docs-only 提交后的重打包也换 sha，进而触发手机端一次 80MB 的重解压。
#   dist.zip.sha256  shasum -a 256 格式，`shasum -c` 可直接校验
#   dist.zip.json    commit / dirty / stale / engine_wasm_sha256
# engine_wasm_sha256 用来区分「只重建了前端」和「引擎也重编了」——陈旧检查靠
# mtime 猜，这个字段是硬证据。stale 是陈旧检查的结论：true 表示 dist/ 比源码旧，
# 此时 commit 记的是打包时 HEAD 而不是产出这份 dist 的提交。暂存目录此刻还在
#（trap 到脚本结束才清）。
# ---------------------------------------------------------------------------
printf '%s  %s\n' "$SHA" "$(basename "$OUT_ZIP")" > "$OUT_ZIP.sha256"

WASM=$(find "$STAGE_DIR" -name '*.wasm' | LC_ALL=C sort | head -1)
ENGINE_SHA=$(shasum -a 256 "$WASM" | cut -d' ' -f1)
COMMIT=$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo unknown)
DIRTY=false
if git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 &&
   [ -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
  DIRTY=true
fi
printf '{"commit": "%s", "dirty": %s, "stale": %s, "engine_wasm_sha256": "%s"}\n' \
  "$COMMIT" "$DIRTY" "$STALE" "$ENGINE_SHA" > "$OUT_ZIP.json"

echo "==> 完成：$OUT_ZIP"
echo "    大小：$SIZE 字节"
echo "    sha256：${SHA}（已写 $(basename "$OUT_ZIP").sha256）"
echo "    来源：$COMMIT dirty=$DIRTY stale=$STALE 引擎 wasm sha256 ${ENGINE_SHA:0:12}…（已写 $(basename "$OUT_ZIP").json）"
