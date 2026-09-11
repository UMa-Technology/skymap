#!/usr/bin/env bash
# 发版：tools/release.sh vX.Y.Z [--no-push]
# 在干净的 main 上构建 web 层（版本烙进 window.SkymapBase / skymap-base.json / dist.zip.json），
# 自检，打 tag vX.Y.Z；再把 dist.zip 三件提交到孤儿分支 dist（LFS），打 dist/vX.Y.Z；推 origin。
# App 仓：bin/skymap_dist.py update vX.Y.Z（git clone --depth 1 --branch dist/vX.Y.Z）。
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
TAG="${1:-}"; PUSH=true
[ "${2:-}" = "--no-push" ] && PUSH=false
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "用法：tools/release.sh vX.Y.Z [--no-push]" >&2; exit 2; }
[ "$(git branch --show-current)" = main ] || { echo "错误：请在 main 上发版（当前 $(git branch --show-current)）" >&2; exit 2; }
[ -z "$(git status --porcelain)" ] || { echo "错误：工作树不干净" >&2; exit 2; }
for t in "$TAG" "dist/$TAG"; do
  git rev-parse -q --verify "refs/tags/$t" >/dev/null && { echo "错误：tag $t 已存在" >&2; exit 2; }
done
command -v git-lfs >/dev/null || { echo "错误：需要 git-lfs（brew install git-lfs && git lfs install）" >&2; exit 2; }
WEB="$REPO_DIR/apps/skymap-web"

echo "==> 构建 web 层（SKYMAP_VERSION=$TAG）"
( cd "$WEB" && npm ci >/dev/null 2>&1 && SKYMAP_VERSION="$TAG" npm run build >/dev/null 2>&1 )

echo "==> 自检"
( cd "$WEB" && shasum -a 256 -c dist.zip.sha256 >/dev/null )
v=$(unzip -p "$WEB/dist.zip" skymap-base.json | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])')
[ "$v" = "$TAG" ] || { echo "错误：skymap-base.json version=$v，不是 $TAG" >&2; exit 1; }
j=$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(m["version"], m["dirty"], m["stale"])' "$WEB/dist.zip.json")
[ "$j" = "$TAG False False" ] || { echo "错误：dist.zip.json 不干净：$j" >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "错误：构建改动了跟踪文件（字体 / 图标子集漂移？）：" >&2; git status --porcelain >&2; exit 1; }
SHA=$(git rev-parse HEAD)

echo "==> tag $TAG @ ${SHA:0:7}"
git tag -a "$TAG" -m "SkyMap base $TAG"

echo "==> dist 分支"
WT="$(mktemp -d "${TMPDIR:-/tmp}/skymap-dist.XXXXXX")"
rmdir "$WT"
if git rev-parse -q --verify refs/heads/dist >/dev/null; then
  git worktree add -q "$WT" dist
elif git ls-remote --exit-code --heads origin dist >/dev/null 2>&1; then
  git fetch -q origin dist && git worktree add -q -b dist "$WT" origin/dist
else
  git worktree add -q --orphan -b dist "$WT"
fi
(
  cd "$WT"
  printf 'dist.zip filter=lfs diff=lfs merge=lfs -text\n' > .gitattributes
  cat > README.md <<'X'
# dist 分支

只放 web 层产物：dist.zip、dist.zip.sha256、dist.zip.json（dist.zip 走 LFS）。
每次发版一次提交，tag dist/vX.Y.Z 对应基座 tag vX.Y.Z。由 tools/release.sh 生成，不要手工提交。
App 仓用 bin/skymap_dist.py update vX.Y.Z 拉取。
X
  cp "$WEB/dist.zip" "$WEB/dist.zip.sha256" "$WEB/dist.zip.json" .
  git add -A
  git commit -q -m "dist $TAG (base ${SHA:0:7})"
  git tag -a "dist/$TAG" -m "dist for $TAG"
)
git worktree remove --force "$WT"

if $PUSH; then
  git push -q origin "$TAG"
  git push -q origin dist "dist/$TAG"
  echo "==> 已推 origin：$TAG、dist、dist/$TAG"
else
  echo "==> --no-push：本地已有 tag $TAG、分支 dist、tag dist/$TAG（未推送）"
fi
echo "==> App 仓：bin/skymap_dist.py update $TAG"
