"""Put the repo root on sys.path so tests can `import tools.clean_dss.*`.
(`tools` has no __init__.py — it's a namespace package — and `tools.clean_dss`
is a regular subpackage.)"""
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
