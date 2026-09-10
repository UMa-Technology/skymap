"""install-dist.sh：三件套拷进 <app-root>/assets/，拷前校 sha，旧的先删。"""
import hashlib
import os
import subprocess

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPT = os.path.join(REPO, "tools", "install-dist.sh")


def make_source(root, payload=b"zip-bytes"):
    src = os.path.join(root, "src")
    os.makedirs(src)
    zp = os.path.join(src, "dist.zip")
    with open(zp, "wb") as f:
        f.write(payload)
    with open(zp + ".sha256", "w") as f:
        f.write(hashlib.sha256(payload).hexdigest() + "  dist.zip\n")
    with open(zp + ".json", "w") as f:
        f.write('{"commit": "x", "dirty": false, "engine_wasm_sha256": "y"}\n')
    return src


def run(app_root, src):
    return subprocess.run([SCRIPT, app_root, "--from", src],
                          capture_output=True, text=True)


def test_copies_three_files_into_assets(tmp_path):
    src = make_source(str(tmp_path))
    app = str(tmp_path / "app")
    os.makedirs(app)
    r = run(app, src)
    assert r.returncode == 0, r.stderr
    for name in ("dist.zip", "dist.zip.sha256", "dist.zip.json"):
        assert os.path.exists(os.path.join(app, "assets", name))


def test_replaces_stale_copy(tmp_path):
    src = make_source(str(tmp_path), payload=b"new")
    app = str(tmp_path / "app")
    os.makedirs(os.path.join(app, "assets"))
    with open(os.path.join(app, "assets", "dist.zip"), "wb") as f:
        f.write(b"old")
    assert run(app, src).returncode == 0
    with open(os.path.join(app, "assets", "dist.zip"), "rb") as f:
        assert f.read() == b"new"


def test_refuses_when_sha_mismatch(tmp_path):
    src = make_source(str(tmp_path))
    with open(os.path.join(src, "dist.zip"), "wb") as f:
        f.write(b"tampered")
    app = str(tmp_path / "app")
    os.makedirs(app)
    r = run(app, src)
    assert r.returncode != 0
    assert not os.path.exists(os.path.join(app, "assets", "dist.zip"))


def test_help_prints_only_the_header_comment():
    r = subprocess.run([SCRIPT, "-h"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "install-dist.sh <app-root> [--from <dir>]" in r.stdout
    assert "set -euo pipefail" not in r.stdout
