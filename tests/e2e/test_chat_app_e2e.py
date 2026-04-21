"""E2E: ailit chat (Streamlit) smoke + send-on-enter.

DeepSeek is networked; this test is a UI smoke and is skipped unless
explicitly enabled via env.
"""

from __future__ import annotations

import os
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
