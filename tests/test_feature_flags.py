"""
Tests for lib/feature_flags.py — the UVT kill switch.

Covers precedence (override > pct > global), determinism of bucketing,
clamping of out-of-range pct values, override parsing edge cases, and
the `flag_snapshot()` sanitized export.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import pytest

from lib import feature_flags as ff


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Start each test with no UVT env vars set."""
    for var in (ff.ENV_ENABLED, ff.ENV_ROLLOUT_PCT, ff.ENV_USER_OVERRIDES):
        monkeypatch.delenv(var, raising=False)
    ff._reset_first_time_cache_for_tests()


# ═══════════════════════════════════════════════════════════════════════════
# Global flag
# ═══════════════════════════════════════════════════════════════════════════


def test_default_is_off():
    assert ff.is_uvt_enabled("some-user") is False


def test_global_on_returns_true(monkeypatch):
    monkeypatch.setenv(ff.ENV_ENABLED, "true")
    assert ff.is_uvt_enabled("any-user") is True


def test_global_variants(monkeypatch):
    for truthy in ("true", "TRUE", "True", "1", "yes", "on"):
        monkeypatch.setenv(ff.ENV_ENABLED, truthy)
        assert ff.is_uvt_enabled("u") is True, f"{truthy!r} should be true"
    for falsy in ("false", "0", "", "no", "off", "nonsense"):
        monkeypatch.setenv(ff.ENV_ENABLED, falsy)
        assert ff.is_uvt_enabled("u") is False, f"{falsy!r} should be false"


def test_no_user_id_still_evaluates_global(monkeypatch):
    monkeypatch.setenv(ff.ENV_ENABLED, "true")
    assert ff.is_uvt_enabled(None) is True
    monkeypatch.setenv(ff.ENV_ENABLED, "false")
    assert ff.is_uvt_enabled(None) is False


# ═══════════════════════════════════════════════════════════════════════════
# Percentage rollout
# ═══════════════════════════════════════════════════════════════════════════


def test_rollout_zero_is_off_even_with_user(monkeypatch):
    monkeypatch.setenv(ff.ENV_ROLLOUT_PCT, "0")
    assert ff.is_uvt_enabled("user-1") is False


def test_rollout_hundred_is_on_for_everyone(monkeypatch):
    monkeypatch.setenv(ff.ENV_ROLLOUT_PCT, "100")
    for uid in ("a", "b", "c", "11111", "22222"):
        assert ff.is_uvt_enabled(uid) is True


def test_rollout_deterministic_per_user(monkeypatch):
    """Same user_id must land in the same bucket every call."""
    monkeypatch.setenv(ff.ENV_ROLLOUT_PCT, "50")
    uid = "deterministic-user-uuid"
    first = ff.is_uvt_enabled(uid)
    for _ in range(20):
        assert ff.is_uvt_enabled(uid) is first


def test_rollout_distributes_across_users(monkeypatch):
    """With pct=50, roughly half of 1000 random-ish user_ids should be True."""
    monkeypatch.setenv(ff.ENV_ROLLOUT_PCT, "50")
    uids = [f"user-{i}" for i in range(1000)]
    enabled = sum(1 for u in uids if ff.is_uvt_enabled(u))
    # SHA-256 distribution should be close to uniform; allow ±10% slop.
    assert 400 <= enabled <= 600, f"got {enabled}/1000 enabled"


def test_rollout_without_user_id_falls_through_to_global(monkeypatch):
    monkeypatch.setenv(ff.ENV_ROLLOUT_PCT, "100")
    # No user_id → no bucketing possible → global flag (default off)
    assert ff.is_uvt_enabled(None) is False


def test_rollout_value_clamped_high(monkeypatch):
    """pct=150 must clamp to 100, not enable some weird negative math."""
    monkeypatch.setenv(ff.ENV_ROLLOUT_PCT, "150")
    assert ff.is_uvt_enabled("u") is True


def test_rollout_value_clamped_low(monkeypatch):
    monkeypatch.setenv(ff.ENV_ROLLOUT_PCT, "-30")
    assert ff.is_uvt_enabled("u") is False


def test_rollout_value_invalid_defaults_to_zero(monkeypatch):
    monkeypatch.setenv(ff.ENV_ROLLOUT_PCT, "banana")
    assert ff.is_uvt_enabled("u") is False


def test_rollout_user_not_in_bucket_falls_through_to_global(monkeypatch):
    """If a user is NOT in the rollout bucket, they fall through to the
    global flag — so if global is ON, they still get UVT. Documented combo:
    pct>0 + AETHER_UVT_ENABLED=false = staged rollout."""
    monkeypatch.setenv(ff.ENV_ROLLOUT_PCT, "1")  # 1% — most users out
    monkeypatch.setenv(ff.ENV_ENABLED, "true")
    # With global on, users-not-in-bucket still get UVT via the global path.
    enabled_count = sum(
        1 for i in range(100) if ff.is_uvt_enabled(f"user-{i}")
    )
    assert enabled_count == 100


# ═══════════════════════════════════════════════════════════════════════════
# Per-user overrides
# ═══════════════════════════════════════════════════════════════════════════


def test_override_true_beats_global_off(monkeypatch):
    monkeypatch.setenv(ff.ENV_ENABLED, "false")
    monkeypatch.setenv(ff.ENV_USER_OVERRIDES, "me-uuid:true")
    assert ff.is_uvt_enabled("me-uuid") is True
    assert ff.is_uvt_enabled("someone-else") is False


def test_override_false_beats_global_on(monkeypatch):
    """Opt-out is respected even when UVT is globally on."""
    monkeypatch.setenv(ff.ENV_ENABLED, "true")
    monkeypatch.setenv(ff.ENV_USER_OVERRIDES, "opted-out:false")
    assert ff.is_uvt_enabled("opted-out") is False
    assert ff.is_uvt_enabled("someone-else") is True


def test_override_false_beats_rollout_pct(monkeypatch):
    monkeypatch.setenv(ff.ENV_ROLLOUT_PCT, "100")
    monkeypatch.setenv(ff.ENV_USER_OVERRIDES, "opt-out:false")
    assert ff.is_uvt_enabled("opt-out") is False


def test_override_multiple_users(monkeypatch):
    monkeypatch.setenv(
        ff.ENV_USER_OVERRIDES,
        "a:true, b:false , c:true,d:false",
    )
    assert ff.is_uvt_enabled("a") is True
    assert ff.is_uvt_enabled("b") is False
    assert ff.is_uvt_enabled("c") is True
    assert ff.is_uvt_enabled("d") is False


def test_override_empty_string_tolerated(monkeypatch):
    monkeypatch.setenv(ff.ENV_USER_OVERRIDES, "")
    assert ff.is_uvt_enabled("a") is False


def test_override_malformed_entries_skipped(monkeypatch):
    """Trailing commas, missing colons, empty uids — none should crash."""
    monkeypatch.setenv(
        ff.ENV_USER_OVERRIDES,
        ",  ,:true,valid:true,nosep,",
    )
    assert ff.is_uvt_enabled("valid") is True
    assert ff.is_uvt_enabled("nosep") is False  # no colon → value empty → false


# ═══════════════════════════════════════════════════════════════════════════
# require_uvt_or_legacy helper
# ═══════════════════════════════════════════════════════════════════════════


def test_require_legacy_default():
    assert ff.require_uvt_or_legacy("u") == "legacy"


def test_require_uvt_when_enabled(monkeypatch):
    monkeypatch.setenv(ff.ENV_ENABLED, "true")
    assert ff.require_uvt_or_legacy("u") == "uvt"


# ═══════════════════════════════════════════════════════════════════════════
# flag_snapshot sanitization
# ═══════════════════════════════════════════════════════════════════════════


def test_snapshot_never_leaks_user_ids(monkeypatch):
    monkeypatch.setenv(ff.ENV_USER_OVERRIDES, "secret-uuid:true,another:false")
    snap = ff.flag_snapshot()
    assert "secret-uuid" not in str(snap)
    assert "another" not in str(snap)
    assert snap["override_count"] == 2


def test_snapshot_shape(monkeypatch):
    monkeypatch.setenv(ff.ENV_ENABLED, "true")
    monkeypatch.setenv(ff.ENV_ROLLOUT_PCT, "25")
    snap = ff.flag_snapshot()
    assert snap["AETHER_UVT_ENABLED"] == "true"
    assert snap["AETHER_UVT_ROLLOUT_PCT"] == 25
    assert snap["override_count"] == 0


def test_snapshot_default_off():
    snap = ff.flag_snapshot()
    assert snap["AETHER_UVT_ENABLED"] == "false"
    assert snap["AETHER_UVT_ROLLOUT_PCT"] == 0
    assert snap["override_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# First-time logging (observability — rollout progress visible in journal)
# ═══════════════════════════════════════════════════════════════════════════


def test_first_time_logs_then_dedupes(monkeypatch, caplog):
    monkeypatch.setenv(ff.ENV_ENABLED, "true")
    caplog.set_level("INFO", logger="aethercloud.feature_flags")

    ff.is_uvt_enabled("u-1")
    ff.is_uvt_enabled("u-1")  # second call should NOT log
    ff.is_uvt_enabled("u-2")

    first_time_logs = [r for r in caplog.records if "first UVT hit" in r.message]
    assert len(first_time_logs) == 2  # one per unique user


def test_first_time_not_logged_when_false(monkeypatch, caplog):
    """Users who get the legacy path should not produce first-UVT logs."""
    caplog.set_level("INFO", logger="aethercloud.feature_flags")
    ff.is_uvt_enabled("u-1")
    first_time_logs = [r for r in caplog.records if "first UVT hit" in r.message]
    assert len(first_time_logs) == 0
