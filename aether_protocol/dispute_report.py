"""
aether_protocol/dispute_report.py

PDF Dispute Report Export.

Generates a professional 4-page PDF report for compliance and dispute
resolution.  The report contains:

    Page 1 — Cover: protocol branding, order ID, generation timestamp
    Page 2 — Decision Record: trade details, reasoning, account state
    Page 3 — Cryptographic Proof: signatures, quantum seeds, temporal windows
    Page 4 — Legal Notice: tamper-evidence statement, verification instructions

Requires ``reportlab`` (optional dependency under ``[compliance]``).

Usage::

    from aether_protocol.dispute_report import DisputeReportGenerator

    gen = DisputeReportGenerator()
    pdf_bytes = gen.generate(order_id, flow, verification)
"""

from __future__ import annotations

import io
import time
from typing import Any, Optional

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        PageBreak,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False


def _fmt_ts(ts: Any) -> str:
    """Format a unix timestamp to a human-readable string."""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(float(ts)))
    except (TypeError, ValueError):
        return str(ts)


def _short(h: Any, n: int = 16) -> str:
    """Truncate a hex hash for display."""
    s = str(h) if h else "—"
    return s[:n] + "…" if len(s) > n else s


class DisputeReportError(Exception):
    """Raised when report generation fails."""


class DisputeReportGenerator:
    """
    Generates a 4-page PDF dispute report from a trade flow and
    verification result.

    Typography:
        - Headings: Helvetica-Bold 14pt
        - Body: Helvetica 10pt
        - Monospace (hashes, sigs): Courier 8pt

    Args:
        title_prefix: Optional prefix for the report title.
    """

    # ── Colour palette (matches terminal_ui CRT aesthetic) ────────────
    _AMBER = HexColor("#FFB000") if _REPORTLAB_AVAILABLE else None
    _DARK_BG = HexColor("#1A1A2E") if _REPORTLAB_AVAILABLE else None
    _LIGHT_TEXT = HexColor("#E0E0E0") if _REPORTLAB_AVAILABLE else None
    _GREEN = HexColor("#00FF41") if _REPORTLAB_AVAILABLE else None
    _RED = HexColor("#FF4444") if _REPORTLAB_AVAILABLE else None

    def __init__(self, title_prefix: str = "AETHER-PROTOCOL-L") -> None:
        if not _REPORTLAB_AVAILABLE:
            raise DisputeReportError(
                "reportlab is required for PDF reports.  "
                "Install with:  pip install aether-protocol-l[compliance]"
            )
        self._title_prefix = title_prefix
        self._styles = self._build_styles()

    def _build_styles(self) -> dict:
        """Build the paragraph styles used throughout the report."""
        ss = getSampleStyleSheet()
        return {
            "title": ParagraphStyle(
                "AetherTitle",
                parent=ss["Title"],
                fontName="Helvetica-Bold",
                fontSize=20,
                textColor=HexColor("#FFB000"),
                alignment=TA_CENTER,
                spaceAfter=12,
            ),
            "heading": ParagraphStyle(
                "AetherHeading",
                parent=ss["Heading1"],
                fontName="Helvetica-Bold",
                fontSize=14,
                textColor=HexColor("#FFB000"),
                spaceAfter=8,
                spaceBefore=16,
            ),
            "subheading": ParagraphStyle(
                "AetherSubheading",
                parent=ss["Heading2"],
                fontName="Helvetica-Bold",
                fontSize=12,
                textColor=HexColor("#CCCCCC"),
                spaceAfter=6,
                spaceBefore=10,
            ),
            "body": ParagraphStyle(
                "AetherBody",
                parent=ss["Normal"],
                fontName="Helvetica",
                fontSize=10,
                textColor=HexColor("#333333"),
                spaceAfter=6,
            ),
            "mono": ParagraphStyle(
                "AetherMono",
                parent=ss["Code"],
                fontName="Courier",
                fontSize=8,
                textColor=HexColor("#333333"),
                spaceAfter=4,
            ),
            "center": ParagraphStyle(
                "AetherCenter",
                parent=ss["Normal"],
                fontName="Helvetica",
                fontSize=10,
                textColor=HexColor("#666666"),
                alignment=TA_CENTER,
                spaceAfter=6,
            ),
            "legal": ParagraphStyle(
                "AetherLegal",
                parent=ss["Normal"],
                fontName="Helvetica",
                fontSize=9,
                textColor=HexColor("#555555"),
                spaceAfter=6,
                spaceBefore=4,
            ),
        }

    def generate(
        self,
        order_id: str,
        flow: dict,
        verification: dict,
        reasoning: Optional[dict] = None,
        timestamp_token: Optional[dict] = None,
    ) -> bytes:
        """
        Generate a PDF dispute report.

        Args:
            order_id: The trade order ID.
            flow: Trade flow dict (from ``AuditLog.get_trade_flow``).
            verification: Verification result dict (from
                ``AuditVerifier.verify_trade_flow``).
            reasoning: Optional reasoning capture dict.
            timestamp_token: Optional timestamp token dict.

        Returns:
            Raw PDF bytes.

        Raises:
            DisputeReportError: If reportlab is not available.
        """
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=letter,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
        )

        story: list = []

        # Page 1: Cover
        self._build_cover(story, order_id, verification)
        story.append(PageBreak())

        # Page 2: Decision Record
        self._build_decision_record(story, order_id, flow, reasoning)
        story.append(PageBreak())

        # Page 3: Cryptographic Proof
        self._build_crypto_proof(story, flow, verification, timestamp_token)
        story.append(PageBreak())

        # Page 4: Legal Notice
        self._build_legal_notice(story, order_id, verification)

        doc.build(story)
        return buf.getvalue()

    def _build_cover(
        self, story: list, order_id: str, verification: dict
    ) -> None:
        """Build the cover page."""
        s = self._styles
        story.append(Spacer(1, 2 * inch))
        story.append(Paragraph(self._title_prefix, s["title"]))
        story.append(Paragraph("Dispute Report", s["title"]))
        story.append(Spacer(1, 0.5 * inch))
        story.append(Paragraph(f"Order: {order_id}", s["center"]))
        story.append(
            Paragraph(
                f"Generated: {_fmt_ts(time.time())}", s["center"]
            )
        )
        story.append(Spacer(1, 0.3 * inch))

        chain_valid = verification.get("chain_valid", False)
        quantum_safe = verification.get("quantum_safe", False)
        status_text = (
            "CHAIN VALID • QUANTUM SAFE"
            if (chain_valid and quantum_safe)
            else "⚠ VERIFICATION ISSUES DETECTED"
        )
        story.append(Paragraph(status_text, s["center"]))
        story.append(Spacer(1, 0.5 * inch))
        story.append(
            Paragraph(
                "This document provides a cryptographic proof of the trade "
                "lifecycle for the referenced order. All signatures, quantum "
                "seed commitments, and temporal windows are included for "
                "independent verification.",
                s["body"],
            )
        )

    def _build_decision_record(
        self,
        story: list,
        order_id: str,
        flow: dict,
        reasoning: Optional[dict],
    ) -> None:
        """Build the decision record page."""
        s = self._styles
        story.append(Paragraph("Decision Record", s["heading"]))

        commitment = flow.get("commitment") or {}
        trade = commitment.get("trade_details", {})

        # Trade details table
        story.append(Paragraph("Trade Details", s["subheading"]))
        trade_data = [
            ["Field", "Value"],
            ["Order ID", order_id],
            ["Symbol", str(trade.get("symbol", "—"))],
            ["Side", str(trade.get("side", "—"))],
            ["Quantity", str(trade.get("qty", "—"))],
            ["Price", str(trade.get("price", "—"))],
            ["Timestamp", _fmt_ts(commitment.get("timestamp", "—"))],
            [
                "Seed Method",
                str(commitment.get("seed_measurement_method", "—")),
            ],
        ]
        t = Table(trade_data, colWidths=[2 * inch, 4.5 * inch])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), HexColor("#E8E8E8")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#CCCCCC")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(t)

        # Account state
        story.append(Paragraph("Account State Binding", s["subheading"]))
        state_hash = commitment.get("account_state_hash", "—")
        nonce = commitment.get("nonce", "—")
        story.append(Paragraph(f"State Hash: {state_hash}", s["mono"]))
        story.append(Paragraph(f"Nonce: {nonce}", s["body"]))

        # Reasoning (if present)
        if reasoning:
            story.append(Paragraph("AI Reasoning Capture", s["subheading"]))
            story.append(
                Paragraph(
                    f"Model: {reasoning.get('reasoning_model', '—')}",
                    s["body"],
                )
            )
            story.append(
                Paragraph(
                    f"Hash: {reasoning.get('reasoning_hash', '—')}",
                    s["mono"],
                )
            )
            story.append(
                Paragraph(
                    f"Tokens: {reasoning.get('token_count', '—')}  |  "
                    f"Captured: {_fmt_ts(reasoning.get('captured_at', '—'))}",
                    s["body"],
                )
            )
            # Truncate reasoning text for the PDF
            text = reasoning.get("reasoning_text", "")
            if len(text) > 500:
                text = text[:500] + "… [truncated]"
            story.append(Paragraph(f"Reasoning: {text}", s["body"]))

    def _build_crypto_proof(
        self,
        story: list,
        flow: dict,
        verification: dict,
        timestamp_token: Optional[dict],
    ) -> None:
        """Build the cryptographic proof page."""
        s = self._styles
        story.append(Paragraph("Cryptographic Proof", s["heading"]))

        # Commitment signature
        c_sig = flow.get("commitment_sig") or {}
        story.append(Paragraph("Commitment Signature", s["subheading"]))
        story.append(Paragraph(f"r: {c_sig.get('r', '—')}", s["mono"]))
        story.append(Paragraph(f"s: {c_sig.get('s', '—')}", s["mono"]))
        story.append(
            Paragraph(
                f"pubkey: {c_sig.get('pubkey', '—')}", s["mono"]
            )
        )
        story.append(
            Paragraph(
                f"algorithm: {c_sig.get('algorithm', '—')}", s["mono"]
            )
        )

        # Quantum seeds
        story.append(
            Paragraph("Quantum Seed Commitments", s["subheading"])
        )
        commitment = flow.get("commitment") or {}
        execution = flow.get("execution") or {}
        settlement = flow.get("settlement") or {}

        seeds_data = [
            ["Phase", "Seed Commitment Hash"],
            [
                "Commitment",
                _short(commitment.get("quantum_seed_commitment"), 32),
            ],
            [
                "Execution",
                _short(
                    execution.get("execution_quantum_seed_commitment"), 32
                ),
            ],
            [
                "Settlement",
                _short(
                    settlement.get("settlement_quantum_seed_commitment"), 32
                ),
            ],
        ]
        t = Table(seeds_data, colWidths=[1.5 * inch, 5 * inch])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), HexColor("#E8E8E8")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Courier"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#CCCCCC")),
                ]
            )
        )
        story.append(t)

        # Temporal windows
        story.append(Paragraph("Temporal Safety Windows", s["subheading"]))
        c_window = commitment.get("key_temporal_window", {})
        story.append(
            Paragraph(
                f"Commitment key window: "
                f"{_fmt_ts(c_window.get('created_at'))} → "
                f"{_fmt_ts(c_window.get('expires_at'))}",
                s["body"],
            )
        )
        story.append(
            Paragraph(
                f"Shor's earliest attack: "
                f"{_fmt_ts(c_window.get('shor_earliest_attack'))}",
                s["body"],
            )
        )

        # Verification summary
        story.append(
            Paragraph("Verification Summary", s["subheading"])
        )
        for detail in verification.get("details", []):
            story.append(Paragraph(f"• {detail}", s["body"]))

        # Timestamp token (if present)
        if timestamp_token:
            story.append(
                Paragraph("RFC 3161 Timestamp", s["subheading"])
            )
            story.append(
                Paragraph(
                    f"TSA: {timestamp_token.get('tsa_url', '—')}",
                    s["body"],
                )
            )
            story.append(
                Paragraph(
                    f"Imprint: {timestamp_token.get('message_imprint', '—')}",
                    s["mono"],
                )
            )
            story.append(
                Paragraph(
                    f"Stamped: {_fmt_ts(timestamp_token.get('stamped_at'))}",
                    s["body"],
                )
            )

    def _build_legal_notice(
        self, story: list, order_id: str, verification: dict
    ) -> None:
        """Build the legal notice page."""
        s = self._styles
        story.append(Paragraph("Legal Notice", s["heading"]))
        story.append(Spacer(1, 0.25 * inch))

        story.append(
            Paragraph("Tamper-Evidence Statement", s["subheading"])
        )
        story.append(
            Paragraph(
                "This report was generated from cryptographically signed "
                "audit records stored by the AETHER-PROTOCOL-L system.  "
                "Each phase of the trade lifecycle (commitment, execution, "
                "settlement) is signed with an independent ephemeral key "
                "derived from a quantum measurement.  The ephemeral key is "
                "destroyed immediately after signing, providing perfect "
                "forward secrecy.",
                s["legal"],
            )
        )

        story.append(
            Paragraph("Verification Instructions", s["subheading"])
        )
        instructions = [
            "1. Verify each ECDSA-secp256k1 signature against the embedded "
            "public key using any standards-compliant cryptographic library.",
            "2. Confirm that the quantum_seed_commitment is a valid 64-character "
            "hex SHA-256 hash for each phase.",
            "3. Check that key_temporal_window.expires_at is strictly less than "
            "key_temporal_window.shor_earliest_attack for each phase.",
            "4. Verify that all three quantum seed commitments are distinct "
            "(proving independent key derivation).",
            "5. Recompute the flow_merkle_hash from the commitment and execution "
            "signatures and compare with the settlement record.",
            "6. If an RFC 3161 timestamp token is present, verify it against "
            "the commitment data using the TSA's public certificate.",
        ]
        for inst in instructions:
            story.append(Paragraph(inst, s["legal"]))

        story.append(Spacer(1, 0.5 * inch))
        story.append(
            Paragraph("Quantum Safety Guarantee", s["subheading"])
        )
        story.append(
            Paragraph(
                "The ephemeral signing keys used in this protocol are derived "
                "from quantum measurements and destroyed within seconds of "
                "creation.  To forge any signature in this report, an "
                "adversary would need to solve the Elliptic Curve Discrete "
                "Logarithm Problem (ECDLP) on secp256k1, which requires "
                "approximately 2,330 logical qubits — far beyond current "
                "quantum computing capabilities (5-10 logical qubits as of "
                "2025).  The temporal safety windows prove that all keys "
                "expired before any known quantum attack could execute.",
                s["legal"],
            )
        )

        story.append(Spacer(1, 0.5 * inch))
        story.append(
            Paragraph(
                f"Report generated for order {order_id} at "
                f"{_fmt_ts(time.time())}",
                s["center"],
            )
        )
        story.append(
            Paragraph(
                "AETHER-PROTOCOL-L v0.5.1 • Quantum-First Trade Auditability",
                s["center"],
            )
        )
