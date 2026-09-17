"""release.sh：tag 必须与 main 一起推，落后于远端时先拦住。

2026-09-17 的 v1.1.2 踩过一次：脚本推了 tag 与 dist 分支、**没推 main**，于是
远端的 main 还停在上一版，而 tag 指着一个不在任何已推分支上的提交——克隆的人看不
到它的历史，`tools/sync-github.sh`（它走的是 `origin/main`）也整版漏掉，是手工同步
GitHub 时才发现的。

前置那条守卫跑在构建之前，所以能真跑一遍；推那一段跑在构建之后（npm ci + vite
build，两分钟起），整条跑一遍代价太大——**那一条退回读脚本**，钉的是「main 与 tag
在同一个 --atomic 推里」这个不变量本身。
"""
import os
import re
import shutil
import subprocess

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPT = os.path.join(REPO, "tools", "release.sh")


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )


def make_repo(tmp_path):
    """造一个能跑到「前置检查」那一步的仓：干净的 main + 一个当 origin 的裸仓。

    只满足 release.sh 在守卫之前那几条（分支是 main、工作树干净、tag 不存在），
    不装 git-lfs——那几条排在守卫后面，跑不到。
    """
    work = str(tmp_path / "work")
    bare = str(tmp_path / "origin.git")
    os.makedirs(work)
    _git(str(tmp_path), "init", "--bare", "-b", "main", bare)
    _git(str(tmp_path), "init", "-b", "main", work)
    _git(work, "config", "user.email", "t@t")
    _git(work, "config", "user.name", "t")
    os.makedirs(os.path.join(work, "tools"))
    shutil.copy(SCRIPT, os.path.join(work, "tools", "release.sh"))
    with open(os.path.join(work, "README.md"), "w") as f:
        f.write("x\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "init")
    _git(work, "remote", "add", "origin", bare)
    _git(work, "push", "-q", "origin", "main")
    return work, bare


def run(work, *args):
    # **errors="replace"**：脚本自己报错时可能吐出半个多字节字符
    # （`TAG\xef: unbound variable` 就是），严格解码会让测试倒在 UnicodeDecodeError
    # 上，看不见真正的错误信息。
    return subprocess.run(
        [os.path.join(work, "tools", "release.sh"), *args],
        cwd=work, capture_output=True, text=True, errors="replace",
    )


def test_refuses_when_origin_main_is_ahead(tmp_path):
    """远端有本地没有的提交 → 在构建之前就拦住。

    不拦的话：构建两分钟、打完 tag，推的时候才被拒，本地还留着一个推不上去的
    tag 要手工删。
    """
    work, bare = make_repo(tmp_path)
    # 另起一个克隆往 origin 推一笔，让本地 main 落后。
    other = str(tmp_path / "other")
    _git(str(tmp_path), "clone", "-q", bare, other)
    _git(other, "config", "user.email", "t@t")
    _git(other, "config", "user.name", "t")
    with open(os.path.join(other, "b.txt"), "w") as f:
        f.write("y\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-qm", "ahead")
    _git(other, "push", "-q", "origin", "main")

    r = run(work, "v9.9.9")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "先 pull 再发版" in r.stderr
    # 拦住了就不许留下 tag。
    assert "v9.9.9" not in _git(work, "tag", "-l").stdout


def test_guard_is_skipped_with_no_push(tmp_path):
    """`--no-push` 不碰远端，落后与否都不该拦——它本来就不推。"""
    work, bare = make_repo(tmp_path)
    other = str(tmp_path / "other")
    _git(str(tmp_path), "clone", "-q", bare, other)
    _git(other, "config", "user.email", "t@t")
    _git(other, "config", "user.name", "t")
    with open(os.path.join(other, "b.txt"), "w") as f:
        f.write("y\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-qm", "ahead")
    _git(other, "push", "-q", "origin", "main")

    r = run(work, "v9.9.9", "--no-push")
    # 会倒在后面某一条（没有 git-lfs / 没有 npm），但**不该是这一条**。
    assert "先 pull 再发版" not in r.stderr


def test_no_variable_is_glued_to_a_cjk_char():
    """`"$TAG）"` 这种写法在有些 locale 下会把全角括号那几个字节也当成变量名。

    **不是假想**：写这组测试时 `--no-push` 那一条当场倒在第 29 行的
    `SKYMAP_VERSION=$TAG）` 上，报 `TAG\xef: unbound variable`——0xEF 是 `）`
    （U+FF09）的头一个字节。发版时没炸只是因为终端的 locale 恰好不同。
    一律写成 `${TAG}` 就没这回事。
    """
    src = open(SCRIPT, encoding="utf-8").read()
    bad = re.findall(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]", src)
    assert not bad, f"这些变量后面直接跟了中文，要加花括号：{bad}"


def test_guard_runs_before_the_build(tmp_path):
    """守卫要排在 npm 之前：倒在这儿的人不该已经等了两分钟。"""
    src = open(SCRIPT, encoding="utf-8").read()
    assert src.index("先 pull 再发版") < src.index("npm ci")


def test_main_and_tag_go_in_one_atomic_push():
    """**这一条是 v1.1.2 那次事故本身。**

    推那一段在构建之后，整条跑一遍要 npm ci + vite build，代价太大——所以这一条
    读脚本，钉的是不变量：`main` 与 `$TAG` 必须出现在**同一个** `--atomic` 推里。
    分成两条推也不行：前一条成了、后一条挂了，远端照样是「tag 不在任何分支上」。
    """
    src = open(SCRIPT, encoding="utf-8").read()
    pushes = [
        line.strip()
        for line in src.splitlines()
        if line.strip().startswith("git push") and "$TAG" in line
    ]
    assert pushes, "脚本里一条推 tag 的命令都没有"
    with_main = [p for p in pushes if " main " in p and '"$TAG"' in p]
    assert len(with_main) == 1, f"main 没跟 tag 一起推：{pushes}"
    assert "--atomic" in with_main[0], f"要原子推，不然会一半成一半败：{with_main[0]}"
