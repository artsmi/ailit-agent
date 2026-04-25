from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_scripts_install_writes_user_systemd_unit_in_dry_run(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts" / "install").resolve()
    assert script.is_file()

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["AILIT_INSTALL_DRY_RUN"] = "1"
    env["AILIT_INSTALL_NO_SHIM"] = "1"

    subprocess.check_call([str(script), "dev"], cwd=str(repo_root), env=env)
    unit = home / ".config" / "systemd" / "user" / "ailit.service"
    assert unit.is_file()
    body = unit.read_text(encoding="utf-8", errors="replace")
    assert "ExecStart=%h/.local/bin/ailit runtime supervisor" in body
    assert "Environment=AILIT_RUNTIME_DIR=%t/ailit" in body
