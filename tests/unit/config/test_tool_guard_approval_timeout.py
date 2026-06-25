"""校验工具审批超时默认值。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_default_tool_guard_approval_timeout_is_two_hours(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    env["SWE_WORKING_DIR"] = str(tmp_path / ".swe")
    env["SWE_SECRET_DIR"] = str(tmp_path / ".swe.secret")
    env.pop("SWE_TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS", None)

    script = """
import json
import swe.constant as constant

print(json.dumps({
    "timeout": constant.TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
}))
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=repo_root,
    )

    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {"timeout": 7200.0}
