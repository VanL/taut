"""Summon presentation failures preserve owner retirement [TUI-12.1]."""

from concurrent.futures import Future
from typing import Any

import pytest

from taut_tui.app import TautApp
from taut_tui.summon import OwnedSummonRun


@pytest.mark.parametrize("boundary", ["log", "ready", "return", "failure", "status"])
@pytest.mark.parametrize("interrupt", [False, True])
def test_summon_presentation_reports_errors_and_preserves_interrupts(
    monkeypatch: pytest.MonkeyPatch, boundary: str, interrupt: bool
) -> None:
    app = TautApp(db_path=None, as_name=None, continuity_token=None)
    app._owned_summon_tokens.add("token")
    app._summon_names["token"] = "member"
    app._operation_state = "summon live"
    notices: list[str] = []
    failure = (
        KeyboardInterrupt("render interrupt")
        if interrupt
        else ValueError("render failed")
    )

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise failure

    def notify(message: str, **_kwargs: Any) -> None:
        notices.append(message)

    monkeypatch.setattr(app, "notify", notify)
    monkeypatch.setattr(app, "_update_status", lambda: None)
    monkeypatch.setattr(app, "_render_inspector", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        app,
        {"failure": "_show_error", "status": "_update_status"}.get(
            boundary, "_render_inspector"
        ),
        fail,
    )

    def apply() -> None:
        if boundary == "log":
            app._apply_summon_log("provider progress")
        elif boundary == "ready":
            app._apply_summon_ready(
                OwnedSummonRun(
                    token="token", pending=False, member_id="m", member_name="member"
                )
            )
        else:
            done: Future[None] = Future()
            if boundary == "failure":
                done.set_exception(RuntimeError("provider failed"))
            else:
                done.set_result(None)
            app._apply_summon_return("token", done)

    if interrupt:
        with pytest.raises(KeyboardInterrupt) as caught:
            apply()
        assert caught.value is failure
    else:
        apply()
        assert len(notices) == 1
        assert "render failed" in notices[0]
        if boundary == "failure":
            assert "provider failed" in notices[0]
    if boundary in {"return", "failure", "status"}:
        assert "token" not in app._owned_summon_tokens
        assert "token" not in app._summon_names
        assert app._operation_state == "idle"


def test_summon_return_displays_worker_control_flow_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = TautApp(db_path=None, as_name=None, continuity_token=None)
    app._owned_summon_tokens.add("token")
    app._operation_state = "summon live"
    shown: list[str] = []
    monkeypatch.setattr(app, "_show_error", shown.append)
    monkeypatch.setattr(app, "_update_status", lambda: None)
    done: Future[None] = Future()
    done.set_exception(KeyboardInterrupt("worker interrupted"))
    app._apply_summon_return("token", done)
    assert shown == ["worker interrupted"]
    assert not app._owned_summon_tokens
    assert app._operation_state == "idle"
