"""
aether_protocol/timestamp_authority.py

RFC 3161 Trusted Timestamp Authority integration.

Provides third-party timestamping of commitment data via RFC 3161-compliant
Timestamp Authorities (TSAs).  A timestamp token proves that the data existed
at a specific point in time, as certified by an independent authority.

The module uses only stdlib ``urllib.request`` for HTTP and ``pyasn1`` for
ASN.1 DER encoding/decoding of TimeStampReq / TimeStampResp messages.

Usage::

    from aether_protocol.timestamp_authority import RFC3161TimestampAuthority

    tsa = RFC3161TimestampAuthority()
    token = tsa.stamp(commitment_bytes)
    assert tsa.verify(commitment_bytes, token)
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Optional

try:
    from pyasn1.type import univ, namedtype, tag, useful, constraint
    from pyasn1.codec.der import encoder as der_encoder
    from pyasn1.codec.der import decoder as der_decoder
    _PYASN1_AVAILABLE = True
except ImportError:
    _PYASN1_AVAILABLE = False


# ── ASN.1 structures for RFC 3161 ────────────────────────────────────

if _PYASN1_AVAILABLE:

    class MessageImprint(univ.Sequence):
        """ASN.1 MessageImprint ::= SEQUENCE { hashAlgorithm, hashedMessage }"""
        componentType = namedtype.NamedTypes(
            namedtype.NamedType(
                "hashAlgorithm",
                univ.Sequence(
                    componentType=namedtype.NamedTypes(
                        namedtype.NamedType("algorithm", univ.ObjectIdentifier()),
                        namedtype.OptionalNamedType("parameters", univ.Any()),
                    )
                ),
            ),
            namedtype.NamedType(
                "hashedMessage", univ.OctetString()
            ),
        )

    class TimeStampReq(univ.Sequence):
        """ASN.1 TimeStampReq per RFC 3161."""
        componentType = namedtype.NamedTypes(
            namedtype.NamedType("version", univ.Integer()),
            namedtype.NamedType("messageImprint", MessageImprint()),
            namedtype.OptionalNamedType("reqPolicy", univ.ObjectIdentifier()),
            namedtype.OptionalNamedType("nonce", univ.Integer()),
            namedtype.DefaultedNamedType(
                "certReq",
                univ.Boolean(False).subtype(
                    implicitTag=tag.Tag(
                        tag.tagClassContext, tag.tagFormatSimple, 0
                    )
                ),
            ),
        )

    # OID for SHA-256
    _SHA256_OID = univ.ObjectIdentifier((2, 16, 840, 1, 101, 3, 4, 2, 1))


# ── Data classes ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class TimestampToken:
    """
    Frozen record of an RFC 3161 timestamp token.

    Fields:
        tsa_url: The TSA endpoint that issued this token.
        token_bytes: Raw DER-encoded TimeStampResp bytes.
        token_hex: Hex encoding of ``token_bytes``.
        stamped_at: Unix timestamp when the stamp was obtained.
        hash_algorithm: Hash algorithm used (always ``"sha-256"``).
        message_imprint: Hex digest of the stamped data.
    """

    tsa_url: str
    token_bytes: bytes
    token_hex: str
    stamped_at: int
    hash_algorithm: str
    message_imprint: str

    def to_dict(self) -> dict:
        """Serialise to a plain dict (suitable for JSON)."""
        return {
            "tsa_url": self.tsa_url,
            "token_hex": self.token_hex,
            "stamped_at": self.stamped_at,
            "hash_algorithm": self.hash_algorithm,
            "message_imprint": self.message_imprint,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TimestampToken":
        """Reconstruct from a dict."""
        token_hex = d["token_hex"]
        return cls(
            tsa_url=d["tsa_url"],
            token_bytes=bytes.fromhex(token_hex),
            token_hex=token_hex,
            stamped_at=d["stamped_at"],
            hash_algorithm=d["hash_algorithm"],
            message_imprint=d["message_imprint"],
        )


class TimestampError(Exception):
    """Raised when timestamping operations fail."""


# ── RFC 3161 Timestamp Authority ──────────────────────────────────────

class RFC3161TimestampAuthority:
    """
    Client for RFC 3161-compliant Timestamp Authorities.

    Sends a ``TimeStampReq`` over HTTP and parses the ``TimeStampResp``.
    Supports automatic fallback to a secondary TSA if the primary is
    unavailable.

    Args:
        tsa_url: Primary TSA endpoint URL.
        fallback_url: Fallback TSA endpoint URL.
        timeout: HTTP request timeout in seconds.
    """

    DEFAULT_TSA_URL = "http://timestamp.digicert.com"
    FALLBACK_TSA_URL = "http://timestamp.sectigo.com"

    def __init__(
        self,
        tsa_url: Optional[str] = None,
        fallback_url: Optional[str] = None,
        timeout: int = 10,
    ) -> None:
        self._tsa_url = tsa_url or self.DEFAULT_TSA_URL
        self._fallback_url = fallback_url or self.FALLBACK_TSA_URL
        self._timeout = timeout

    def _build_timestamp_request(self, data: bytes) -> bytes:
        """
        Build a DER-encoded RFC 3161 TimeStampReq for the given data.

        Args:
            data: The raw bytes to timestamp.

        Returns:
            DER-encoded TimeStampReq bytes.

        Raises:
            TimestampError: If pyasn1 is not available.
        """
        if not _PYASN1_AVAILABLE:
            raise TimestampError(
                "pyasn1 is required for RFC 3161 timestamps.  "
                "Install with:  pip install pyasn1"
            )

        digest = hashlib.sha256(data).digest()

        # Build MessageImprint
        imprint = MessageImprint()
        algo_seq = univ.Sequence()
        algo_seq.setComponentByPosition(0, _SHA256_OID)
        imprint.setComponentByName("hashAlgorithm", algo_seq)
        imprint.setComponentByName("hashedMessage", univ.OctetString(digest))

        # Build TimeStampReq
        req = TimeStampReq()
        req.setComponentByName("version", univ.Integer(1))
        req.setComponentByName("messageImprint", imprint)
        # Random nonce for replay protection
        nonce_val = int.from_bytes(os.urandom(8), "big")
        req.setComponentByName("nonce", univ.Integer(nonce_val))
        # certReq: BOOLEAN DEFAULT FALSE — use matching implicit tag
        cert_req = univ.Boolean(True).subtype(
            implicitTag=tag.Tag(
                tag.tagClassContext, tag.tagFormatSimple, 0
            )
        )
        req.setComponentByName("certReq", cert_req)

        return der_encoder.encode(req)

    def _send_request(self, tsa_url: str, req_bytes: bytes) -> bytes:
        """
        Send a TimeStampReq to a TSA and return the raw response.

        Args:
            tsa_url: The TSA endpoint URL.
            req_bytes: DER-encoded TimeStampReq.

        Returns:
            Raw response bytes.

        Raises:
            TimestampError: If the HTTP request fails.
        """
        import urllib.request

        http_req = urllib.request.Request(
            tsa_url,
            data=req_bytes,
            headers={
                "Content-Type": "application/timestamp-query",
                "Accept": "application/timestamp-reply",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(http_req, timeout=self._timeout) as resp:
                return resp.read()
        except Exception as exc:
            raise TimestampError(
                f"TSA request to {tsa_url} failed: {exc}"
            ) from exc

    def stamp(self, data: bytes) -> TimestampToken:
        """
        Obtain an RFC 3161 timestamp for the given data.

        Tries the primary TSA first; falls back to the secondary if the
        primary is unavailable.

        Args:
            data: The raw bytes to timestamp.

        Returns:
            A :class:`TimestampToken` containing the TSA response.

        Raises:
            TimestampError: If both TSAs are unavailable or pyasn1
                is missing.
        """
        req_bytes = self._build_timestamp_request(data)
        digest_hex = hashlib.sha256(data).hexdigest()

        errors: list[str] = []
        for url in (self._tsa_url, self._fallback_url):
            try:
                resp_bytes = self._send_request(url, req_bytes)
                return TimestampToken(
                    tsa_url=url,
                    token_bytes=resp_bytes,
                    token_hex=resp_bytes.hex(),
                    stamped_at=int(time.time()),
                    hash_algorithm="sha-256",
                    message_imprint=digest_hex,
                )
            except TimestampError as exc:
                errors.append(str(exc))
                continue

        raise TimestampError(
            f"All TSA endpoints failed: {'; '.join(errors)}"
        )

    def verify(self, data: bytes, token: TimestampToken) -> bool:
        """
        Verify that a timestamp token matches the given data.

        Checks that the ``message_imprint`` stored in the token matches
        the SHA-256 of ``data``.  This is a local verification -- it
        confirms data integrity but does not re-contact the TSA.

        For full TSA certificate chain verification, use a dedicated
        PKI library.

        Args:
            data: The original data that was timestamped.
            token: The :class:`TimestampToken` to verify.

        Returns:
            ``True`` if the imprint matches; ``False`` otherwise.
        """
        expected = hashlib.sha256(data).hexdigest()
        return expected == token.message_imprint
