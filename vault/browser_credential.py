"""
AetherCloud-L — Browser Credential Token Service
Issues one-time signed JWT tokens that AetherBrowser containers redeem
from the vault to inject auth cookies into browser sessions.

Uses Protocol-C ephemeral signing — no external JWT library needed.

Aether Systems LLC — Patent Pending
"""

import hashlib
import hmac
import json
import logging
import time
from uuid import uuid4

from aether_protocol.ephemeral_signer import EphemeralSigner
from aether_protocol.quantum_crypto import get_quantum_seed

logger = logging.getLogger("aethercloud.vault.browser_credential")

# In-memory set of redeemed token IDs — cleared on restart.
# Expired tokens are already invalid, so cleared JTIs cannot be replayed.
_redeemed_jtis: set[str] = set()


def issue_browser_credential_token(
    credential_key: str,
    session_id: str,
) -> str:
    """
    Issue a one-time browser credential token (signed JWT-like payload).

    The token is:
      - Bound to a specific credential_key and session_id
      - Valid for 60 seconds
      - Redeemable exactly once (enforced by JTI tracking)
      - Signed using Protocol-C ephemeral ECDSA

    Args:
        credential_key: Which vault credential to retrieve on redemption.
        session_id: The AetherBrowser session this token is bound to.

    Returns:
        A base64url-encoded signed token string.
    """
    import base64

    jti = str(uuid4())
    now = time.time()

    payload = {
        "jti": jti,
        "credential_key": credential_key,
        "session_id": session_id,
        "iat": now,
        "exp": now + 60,
    }

    # Sign using Protocol-C ephemeral signer
    seed_int, _method = get_quantum_seed(method="OS_URANDOM")
    signer = EphemeralSigner(quantum_seed=seed_int)
    signature = signer.sign_manifest(payload)
    signer.destroy()

    token_data = {
        "payload": payload,
        "signature": signature,
    }

    token_bytes = json.dumps(token_data, separators=(",", ":")).encode("utf-8")
    token_str = base64.urlsafe_b64encode(token_bytes).decode("ascii")

    logger.info(
        "Issued browser credential token jti=%s for session=%s (credential=%s)",
        jti, session_id, credential_key,
    )
    return token_str


def redeem_browser_credential_token(token_str: str, vault_get_fn=None) -> dict:
    """
    Validate and redeem a browser credential token.

    Called by the vault endpoint when AetherBrowser containers POST to
    /vault/browser-credential.

    Args:
        token_str: The base64url-encoded signed token.
        vault_get_fn: Callable(credential_key) -> dict that retrieves
                      the actual credential from the vault store.

    Returns:
        The decrypted credential dict (cookies, etc.).

    Raises:
        ValueError: If the token is expired, already redeemed, or invalid.
    """
    import base64

    # Decode the token
    try:
        token_bytes = base64.urlsafe_b64decode(token_str)
        token_data = json.loads(token_bytes)
    except Exception as exc:
        raise ValueError(f"Malformed token: {exc}")

    payload = token_data.get("payload", {})
    signature = token_data.get("signature", {})

    # Validate signature using Protocol-C
    from aether_protocol.ephemeral_signer import EphemeralSigner

    temp_signer = EphemeralSigner(quantum_seed=1)
    valid = temp_signer.verify(payload, signature)
    temp_signer.destroy()
    if not valid:
        raise ValueError("Invalid token signature")

    # Check expiration
    now = time.time()
    if now > payload.get("exp", 0):
        raise ValueError("Token expired")

    # Check one-time use
    jti = payload.get("jti", "")
    if jti in _redeemed_jtis:
        raise ValueError("Token already redeemed")

    # Mark as redeemed BEFORE returning credential (prevent race)
    _redeemed_jtis.add(jti)

    credential_key = payload.get("credential_key", "")
    session_id = payload.get("session_id", "")

    logger.info("Redeemed browser credential token jti=%s session=%s", jti, session_id)

    # Retrieve the actual credential
    if vault_get_fn:
        credential = vault_get_fn(credential_key)
    else:
        # Fallback: return empty credential structure
        logger.warning("No vault_get_fn provided — returning empty credential")
        credential = {"cookies": []}

    # NEVER log credential values
    return credential
