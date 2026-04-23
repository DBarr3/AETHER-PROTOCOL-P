"""Red Team #2 L1 — log injection via unsanitized `chosen_model`.

lib/uvt_routes.py (shadow-dispatch path, marked # router-shadow-log):

    shadow = await router_client.pick({...})
    log.info("router_would_pick: %s", shadow.chosen_model)

Python's logging doesn't escape control chars in %s substitution. If
AETHER_ROUTER_URL points at an attacker-controlled origin (M2 — future
risk at PR 2 cutover), the attacker returns `chosen_model` with an
embedded \\n plus a forged log line; that line lands in the aggregator
and can mimic a legit router event (e.g. "gate_passed").

Severity: LOW today (precondition is high-privilege env-var write).
Fix: strip control chars (ASCII 0x00-0x1F + DEL 0x7F) from
`shadow.chosen_model` before the log.info call.

This file is the post-fix regression guard.

Aether Systems LLC — Patent Pending
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from lib.uvt_routes import _sanitize_log_value  # noqa: E402


def test_sanitize_strips_newline() -> None:
    """Newline is the primary log-injection vector."""
    out = _sanitize_log_value("claude-sonnet-4\nROUTER: forged-line")
    assert "\n" not in out
    # Keeps visible content so operators can still read it
    assert "claude-sonnet-4" in out


def test_sanitize_strips_carriage_return() -> None:
    out = _sanitize_log_value("claude-sonnet-4\rrogue")
    assert "\r" not in out


def test_sanitize_strips_ansi_escape() -> None:
    out = _sanitize_log_value("\x1b[31mred\x1b[0m")
    # ANSI escape sequences use ESC (0x1B) which is a control char
    assert "\x1b" not in out


def test_sanitize_strips_all_ascii_control_chars() -> None:
    """Sweep every byte 0x00..0x1F + DEL (0x7F)."""
    controls = "".join(chr(c) for c in list(range(0x00, 0x20)) + [0x7F])
    out = _sanitize_log_value(f"claude-{controls}opus")
    for c in controls:
        assert c not in out, (
            f"Unstripped control char 0x{ord(c):02x} in sanitized output"
        )
    assert "claude-" in out and "opus" in out


def test_sanitize_preserves_printable_ascii() -> None:
    """The allowed alphabet must pass through unchanged."""
    s = "claude-haiku-4-5-20251001"
    assert _sanitize_log_value(s) == s


def test_sanitize_preserves_non_ascii_unicode() -> None:
    """Non-control unicode (letters with diacritics, emoji, CJK) is
    printable and should pass through. The filter is about control
    chars, not unicode."""
    s = "claude-\u00e9\u00e0\u4e2d"
    assert _sanitize_log_value(s) == s


def test_sanitize_handles_empty_and_none_style_inputs() -> None:
    assert _sanitize_log_value("") == ""
    # A weird model_id of just control chars should yield ""
    assert _sanitize_log_value("\n\t\r") == ""


def test_uvt_routes_shadow_log_uses_sanitizer() -> None:
    """Grep assertion — the shadow-dispatch log.info must wrap
    chosen_model in `_sanitize_log_value(...)`. If someone drops the
    call while refactoring, this test fails."""
    text = (REPO / "lib" / "uvt_routes.py").read_text(encoding="utf-8")
    # Find the log.info call that mentions router_would_pick
    match = re.search(
        r'log\.info\("router_would_pick:[^"]*"\s*,\s*([^)]+)\)',
        text,
    )
    assert match, (
        "Could not find `log.info(\"router_would_pick: ...\", ...)` in "
        "lib/uvt_routes.py — did the shadow-dispatch path move?"
    )
    arg = match.group(1).strip()
    assert "_sanitize_log_value" in arg, (
        f"The log argument `{arg}` is not wrapped in _sanitize_log_value(). "
        f"Direct interpolation of `shadow.chosen_model` allows log-line "
        f"injection via \\n when AETHER_ROUTER_URL is attacker-controlled."
    )


if __name__ == "__main__":
    test_sanitize_strips_newline()
    test_sanitize_strips_carriage_return()
    test_sanitize_strips_ansi_escape()
    test_sanitize_strips_all_ascii_control_chars()
    test_sanitize_preserves_printable_ascii()
    test_sanitize_preserves_non_ascii_unicode()
    test_sanitize_handles_empty_and_none_style_inputs()
    test_uvt_routes_shadow_log_uses_sanitizer()
    print("Group C L1 regression guards: 8 checks pass.")
