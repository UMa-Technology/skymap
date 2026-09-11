#!/usr/bin/env bash
# 把 github 分支快进到 origin/main（或指定提交）并推到 GitHub 的 main，连同 v* 标签。
# 约定：日常在 develop，稳定后合 main；github 是 main 的延后快照，GitHub 只由本脚本推。
#   tools/sync-github.sh              # github := origin/main
#   tools/sync-github.sh <commit>     # github := <commit>（须在 main 历史上）
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
git remote get-url github >/dev/null 2>&1 || { echo "错误：没有 github remote" >&2; exit 2; }
[ "$(git branch --show-current)" != github ] || { echo "错误：请先切到别的分支" >&2; exit 2; }
git fetch -q origin
TARGET="${1:-origin/main}"
git merge-base --is-ancestor "$TARGET" origin/main || { echo "错误：$TARGET 不在 origin/main 历史上" >&2; exit 2; }
OLD=$(git rev-parse --short github 2>/dev/null || echo '(无)')
echo "==> github: $OLD → $(git rev-parse --short "$TARGET")"
[ "$OLD" = '(无)' ] || git log --oneline "github..$TARGET" | head -50
git branch -f github "$TARGET"
git push -q origin github
git push github github:main
git push github 'refs/tags/v*:refs/tags/v*'
echo "==> 已同步到 GitHub main"
