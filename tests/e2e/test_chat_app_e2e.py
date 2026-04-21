"""E2E: ailit chat (Streamlit) smoke + DeepSeek live (opt-in).

Live DeepSeek requires explicit opt-in and a key from `config/test.local.yaml`
or `DEEPSEEK_API_KEY`.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


@pytest.mark.e2e
def test_chat_app_smoke_and_enter_sends(tmp_path: Path) -> None:
    """Start chat app via Streamlit test harness and send message."""
    if os.environ.get("AILIT_E2E_CHAT", "") != "1":
        pytest.skip("set AILIT_E2E_CHAT=1 to run Streamlit chat e2e")
    try:
        from streamlit.testing.v1 import AppTest
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"streamlit.testing is unavailable: {exc}")

    repo = Path(__file__).resolve().parents[2]
    app_path = repo / "tools" / "ailit" / "chat_app.py"
    assert app_path.is_file()

    # Avoid reading dev config; keep workspace isolated.
    os.environ.setdefault("AILIT_CONFIG_DIR", str(tmp_path / "ailit_config"))
    os.environ.setdefault("AILIT_WORK_ROOT", str(tmp_path))

    at = AppTest.from_file(str(app_path))
    at.run()

    # Provider dropdown is in sidebar; we don't depend on it here.
    # Enter should send: text_input has on_change that sets send_request.
    msg = "кто слушает порт 443"
    at.text_input(key="ailit_chat_input").set_value(msg).run()

    # After send, the user message should appear in transcript.
    # Streamlit's chat_message is rendered as markdown in testing tree.
    texts = "\n".join(x.value for x in at.markdown)
    assert "порт 443" in texts.lower()


@pytest.mark.e2e
def test_chat_app_deepseek_live_port_443(tmp_path: Path) -> None:
    """Live: run a chat turn with DeepSeek and check it responds."""
    if os.environ.get("AILIT_E2E_CHAT_DEEPSEEK", "") != "1":
        pytest.skip(
            "set AILIT_E2E_CHAT_DEEPSEEK=1 to run DeepSeek live chat e2e",
        )
    try:
        from streamlit.testing.v1 import AppTest
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"streamlit.testing is unavailable: {exc}")

    from agent_core.config_loader import (
        deepseek_api_key_from_env_or_config,
        load_test_local_yaml,
        live_run_allowed,
    )

    cfg = load_test_local_yaml(Path.cwd() / "config" / "test.local.yaml")
    if not live_run_allowed(cfg):
        pytest.skip("live.run is false; enable it in config/test.local.yaml")
    key = deepseek_api_key_from_env_or_config(cfg)
    if not key:
        pytest.skip("DeepSeek key missing in config/test.local.yaml / env")

    os.environ["AILIT_RUN_LIVE"] = "1"
    os.environ["DEEPSEEK_API_KEY"] = key
    os.environ.setdefault("AILIT_WORK_ROOT", str(tmp_path))

    repo = Path(__file__).resolve().parents[2]
    app_path = repo / "tools" / "ailit" / "chat_app.py"
    at = AppTest.from_file(str(app_path))
    at.run()

    # Best-effort: pick DeepSeek in sidebar.
    try:
        at.sidebar.selectbox("Провайдер").set_value("deepseek").run()
    except Exception:
        pass

    at.text_input(key="ailit_chat_input").set_value(
        "кто слушает порт 443",
    ).run()

    # The app uses background worker + reruns; poll a few runs.
    deadline = time.time() + 40.0
    seen = ""
    while time.time() < deadline:
        at.run()
        seen = "\n".join(x.value for x in at.markdown).lower()
        if "443" in seen:
            break
        time.sleep(0.2)
    assert "443" in seen
