"""make-dist-zip.sh：zip 可复现 + 旁边两个 sidecar。

用一个假的 dist 目录（index.html + assets/*.wasm + 一个数据文件）跑真脚本。
脚本的陈旧检查会去问本仓库的 git，在 CI / 无 git 时静默跳过，不影响这里。
"""
import hashlib
import json
import os
import subprocess

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPT = os.path.join(REPO, "tools", "make-dist-zip.sh")
WASM_BYTES = b"\x00asm\x01\x00\x00\x00fake-engine"


def make_fake_dist(root):
    dist = os.path.join(root, "dist")
    os.makedirs(os.path.join(dist, "assets"))
    os.makedirs(os.path.join(dist, "skydata"))
    with open(os.path.join(dist, "index.html"), "w") as f:
        f.write("<html>fake</html>")
    with open(os.path.join(dist, "assets", "stellarium-web-engine-abc.wasm"), "wb") as f:
        f.write(WASM_BYTES)
    with open(os.path.join(dist, "skydata", "stars.json"), "w") as f:
        f.write("[]")
    return dist


def run(dist):
    subprocess.run([SCRIPT, dist], check=True, capture_output=True, text=True)


def sha256_of(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_writes_zip_and_two_sidecars(tmp_path):
    dist = make_fake_dist(str(tmp_path))
    run(dist)
    out = str(tmp_path / "dist.zip")
    assert os.path.exists(out)
    assert os.path.exists(out + ".sha256")
    assert os.path.exists(out + ".json")


def test_sha256_sidecar_matches_zip(tmp_path):
    dist = make_fake_dist(str(tmp_path))
    run(dist)
    out = str(tmp_path / "dist.zip")
    with open(out + ".sha256") as f:
        line = f.read().strip()
    digest, name = line.split()
    assert name == "dist.zip"
    assert digest == sha256_of(out)


def test_json_sidecar_fields(tmp_path):
    dist = make_fake_dist(str(tmp_path))
    run(dist)
    with open(str(tmp_path / "dist.zip.json")) as f:
        meta = json.load(f)
    assert set(meta) == {"commit", "dirty", "stale", "engine_wasm_sha256", "version"}
    assert meta["engine_wasm_sha256"] == hashlib.sha256(WASM_BYTES).hexdigest()
    assert isinstance(meta["dirty"], bool)
    assert meta["commit"] == "unknown" or len(meta["commit"]) == 40
    # 刚生成的假 dist 比任何提交都新，不可能陈旧
    assert meta["stale"] is False


def test_stale_flag_when_dist_predates_source_commits(tmp_path):
    """把假 dist 的 mtime 拨回 2020 年：本仓的前端/引擎源码此后有大量提交 → stale=true。"""
    dist = make_fake_dist(str(tmp_path))
    old = 1577836800  # 2020-01-01
    # 目录也要拨：newest_mtime 是整棵树里最新的 mtime，漏一个子目录就等于没拨
    for root, dirs, files in os.walk(dist, topdown=False):
        for name in files + dirs:
            os.utime(os.path.join(root, name), (old, old))
    os.utime(dist, (old, old))
    run(dist)
    with open(str(tmp_path / "dist.zip.json")) as f:
        meta = json.load(f)
    assert meta["stale"] is True


def test_reproducible_across_two_runs(tmp_path):
    dist = make_fake_dist(str(tmp_path))
    run(dist)
    first = sha256_of(str(tmp_path / "dist.zip"))
    run(dist)
    second = sha256_of(str(tmp_path / "dist.zip"))
    assert first == second


def test_json_sidecar_version_from_skymap_base_json(tmp_path):
    dist = make_fake_dist(str(tmp_path))
    with open(os.path.join(dist, "skymap-base.json"), "w") as f:
        json.dump({"version": "v9.9.9", "protocol": 1}, f)
    run(dist)
    with open(str(tmp_path / "dist.zip.json")) as f:
        meta = json.load(f)
    assert meta["version"] == "v9.9.9"


def test_json_sidecar_version_unknown_without_skymap_base_json(tmp_path):
    dist = make_fake_dist(str(tmp_path))
    run(dist)
    with open(str(tmp_path / "dist.zip.json")) as f:
        meta = json.load(f)
    assert meta["version"] == "unknown"
