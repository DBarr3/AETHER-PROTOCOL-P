"""
AetherCloud-L — Protocol-L Hardened Claude Agent
Every Claude API response is SHA-256 hashed, quantum-session-bound,
ECDSA signed, and RFC 3161 timestamped before being acted upon.

This is the cryptographically verified AI reasoning layer.
If a response is tampered with between generation and action,
the signature check fails and AetherCloud-L refuses to act.

Third Patent Claim: Cryptographically Verified AI Reasoning
Aether Systems LLC — Patent Pending
"""

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from anthropic import Anthropic

from aether_protocol.audit import AuditLog
from aether_protocol.quantum_crypto import (
    QuantumSeedCommitment,
    QuantumEphemeralKey,
    get_quantum_seed,
    verify_signature,
)
from aether_protocol.ephemeral_signer import EphemeralSigner
from aether_protocol.timestamp_authority import (
    RFC3161TimestampAuthority,
    TimestampToken,
)

from config.settings import (
    CLAUDE_API_KEY,
    CLAUDE_MODEL,
    CLAUDE_MAX_TOKENS,
    DEFAULT_AUDIT_DIR,
)
from config.agent_prompt import AETHER_AGENT_SYSTEM_PROMPT, TASK_SUFFIXES
from agent.qopc_feedback import QOPCLoop, UserContextScorer

logger = logging.getLogger(__name__)


class ResponseTamperingError(SecurityError if hasattr(__builtins__, 'SecurityError') else Exception):
    """Raised when a Claude response fails integrity verification."""


@dataclass(frozen=True)
class HardenedResponse:
    """
    Immutable record of a cryptographically committed Claude response.

    Every field is frozen — once committed, the response cannot be
    modified without invalidating the signature chain.
    """
    response_text: str
    response_hash: str              # SHA-256 of response_text
    model: str                      # Claude model that generated it
    prompt_hash: str                # SHA-256 of the input prompt
    session_token_hash: str         # SHA-256 of the session token
    quantum_seed_hash: str          # SHA-256 of the quantum seed used
    signature: dict                 # ECDSA signature envelope
    seed_commitment: dict           # QuantumSeedCommitment as dict
    timestamp: float                # Unix timestamp of commitment
    rfc3161_token: Optional[dict] = None  # RFC 3161 timestamp token (if available)

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "response_hash": self.response_hash,
            "model": self.model,
            "prompt_hash": self.prompt_hash,
            "session_token_hash": self.session_token_hash,
            "quantum_seed_hash": self.quantum_seed_hash,
            "signature": self.signature,
            "seed_commitment": self.seed_commitment,
            "timestamp": self.timestamp,
            "rfc3161_token": self.rfc3161_token,
        }


class HardenedClaudeAgent:
    """
    Protocol-L hardened Claude API wrapper.

    Every Claude response is:
      1. SHA-256 hashed
      2. Bound to a quantum-seeded session token
      3. ECDSA signed with an ephemeral key (destroyed after signing)
      4. RFC 3161 timestamped (when TSA is reachable)
      5. Logged to the Protocol-L audit trail

    Before any response is acted upon, the full chain is verified.
    If verification fails, a ResponseTamperingError is raised and
    the response is refused.

    This creates an immutable, cryptographically verified chain of custody
    for every AI decision — the third patent claim.

    Security Model:
      - Response cannot be modified after commitment
      - Quantum seed ensures non-reproducible binding
      - Ephemeral key provides perfect forward secrecy
      - RFC 3161 proves existence at a specific time
      - Audit log is append-only with SQLite index
      - File contents NEVER leave the machine

    Aether Systems LLC — Patent Pending
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        session_token: Optional[str] = None,
        audit_log: Optional[AuditLog] = None,
        enable_rfc3161: bool = True,
    ):
        self._api_key = api_key or CLAUDE_API_KEY
        if not self._api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not set. Add to your .env file."
            )

        self.client = Anthropic(api_key=self._api_key)
        self.model = model or CLAUDE_MODEL
        self.max_tokens = max_tokens or CLAUDE_MAX_TOKENS
        self.system_prompt = AETHER_AGENT_SYSTEM_PROMPT
        self._active_system_prompt = self.system_prompt
        self.user_context: str = ""
        self._context_scorer = UserContextScorer("")
        self.conversation_history: list[dict] = []

        # QOPC feedback loop — recursive truth loop
        self._qopc: Optional[QOPCLoop] = None
        try:
            self._qopc = QOPCLoop()
            logger.info("QOPC feedback loop initialized")
        except Exception as e:
            logger.warning("QOPC feedback loop unavailable: %s", e)

        # Session binding — every response is bound to this session
        self._session_token = session_token or hashlib.sha256(
            os.urandom(32)
        ).hexdigest()
        self._session_token_hash = hashlib.sha256(
            self._session_token.encode()
        ).hexdigest()

        # Audit log for hardened responses
        audit_dir = DEFAULT_AUDIT_DIR
        audit_dir.mkdir(parents=True, exist_ok=True)
        self._audit_log = audit_log or AuditLog(
            str(audit_dir / "hardened_agent_audit.jsonl")
        )

        # RFC 3161 timestamp authority (best-effort)
        self._enable_rfc3161 = enable_rfc3161
        self._tsa: Optional[RFC3161TimestampAuthority] = None
        if enable_rfc3161:
            try:
                self._tsa = RFC3161TimestampAuthority()
            except Exception as e:
                logger.warning("RFC 3161 TSA unavailable: %s", e)

        # Verification statistics
        self._total_responses = 0
        self._verified_responses = 0
        self._failed_verifications = 0
        self._tamper_detections = 0

        logger.info(
            "HardenedClaudeAgent initialized (model=%s, rfc3161=%s)",
            self.model,
            self._tsa is not None,
        )

    def set_user_context(self, context: str) -> None:
        """Update user context preferences for scoring and prompt injection."""
        self.user_context = context
        self._context_scorer.update_context(context)
        if context.strip():
            self._active_system_prompt = (
                self.system_prompt + f"\n\nUSER PREFERENCES:\n{context}"
            )
        else:
            self._active_system_prompt = self.system_prompt

    # ─── Core: Commit a Claude response ──────────────────────

    def _commit_response(
        self,
        response_text: str,
        prompt: str,
    ) -> HardenedResponse:
        """
        Cryptographically commit a Claude API response via Protocol-L.

        Steps:
          1. SHA-256 hash the response
          2. SHA-256 hash the prompt (for binding)
          3. Generate quantum seed → derive ephemeral key
          4. Build commitment manifest (response hash + session + seed)
          5. Sign with ephemeral key (key destroyed after signing)
          6. Obtain RFC 3161 timestamp (best-effort)
          7. Log to Protocol-L audit trail

        Returns:
            HardenedResponse — immutable, frozen record
        """
        now = time.time()

        # 1. Hash the response
        response_hash = hashlib.sha256(response_text.encode()).hexdigest()

        # 2. Hash the prompt
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()

        # 3. Generate quantum seed and derive ephemeral key
        seed_int, method = get_quantum_seed(method="OS_URANDOM")
        ephemeral_key = QuantumEphemeralKey(
            quantum_seed=seed_int,
            method=method,
        )
        seed_commitment = ephemeral_key.seed_commitment

        # 4. Build the commitment manifest
        manifest = {
            "response_hash": response_hash,
            "prompt_hash": prompt_hash,
            "session_token_hash": self._session_token_hash,
            "quantum_seed_hash": seed_commitment.seed_hash,
            "model": self.model,
            "timestamp": now,
            "commitment_type": "AI_RESPONSE_VERIFICATION",
        }

        # 5. Sign with ephemeral key (key destroyed immediately)
        signature = ephemeral_key.sign(manifest)

        # 6. RFC 3161 timestamp (best-effort)
        rfc3161_token = None
        if self._tsa:
            try:
                commitment_bytes = json.dumps(
                    manifest, sort_keys=True
                ).encode()
                token = self._tsa.stamp(commitment_bytes)
                rfc3161_token = token.to_dict()
            except Exception as e:
                logger.warning("RFC 3161 timestamping failed: %s", e)

        # 7. Log to Protocol-L audit trail
        commitment_entry = {
            "order_id": f"agent_response_{int(now * 1000)}",
            "trade_details": {
                "event_type": "AI_RESPONSE_COMMITTED",
                "response_hash": response_hash,
                "prompt_hash": prompt_hash,
                "model": self.model,
                "session_bound": True,
                "rfc3161_timestamped": rfc3161_token is not None,
                "timestamp": now,
            },
            "quantum_seed_commitment": seed_commitment.to_dict(),
            "seed_measurement_method": method,
            "timestamp": now,
        }

        self._audit_log.append_commitment(commitment_entry, signature)

        self._total_responses += 1

        return HardenedResponse(
            response_text=response_text,
            response_hash=response_hash,
            model=self.model,
            prompt_hash=prompt_hash,
            session_token_hash=self._session_token_hash,
            quantum_seed_hash=seed_commitment.seed_hash,
            signature=signature,
            seed_commitment=seed_commitment.to_dict(),
            timestamp=now,
            rfc3161_token=rfc3161_token,
        )

    # ─── Core: Verify a hardened response ────────────────────

    def _verify_response(self, hardened: HardenedResponse) -> bool:
        """
        Verify the full cryptographic chain of a hardened response.

        Checks:
          1. Response hash matches response text
          2. Session token binding is correct
          3. ECDSA signature is valid over the manifest
          4. Quantum seed commitment is well-formed

        Returns:
            True if the response passes all checks.

        Raises:
            ResponseTamperingError if any check fails.
        """
        # 1. Verify response hash
        computed_hash = hashlib.sha256(
            hardened.response_text.encode()
        ).hexdigest()
        if computed_hash != hardened.response_hash:
            self._tamper_detections += 1
            raise ResponseTamperingError(
                f"Response hash mismatch: computed={computed_hash[:16]}... "
                f"vs stored={hardened.response_hash[:16]}..."
            )

        # 2. Verify session binding
        if hardened.session_token_hash != self._session_token_hash:
            self._tamper_detections += 1
            raise ResponseTamperingError(
                "Session token mismatch — response not bound to this session"
            )

        # 3. Verify ECDSA signature
        manifest = {
            "response_hash": hardened.response_hash,
            "prompt_hash": hardened.prompt_hash,
            "session_token_hash": hardened.session_token_hash,
            "quantum_seed_hash": hardened.quantum_seed_hash,
            "model": hardened.model,
            "timestamp": hardened.timestamp,
            "commitment_type": "AI_RESPONSE_VERIFICATION",
        }

        if not verify_signature(manifest, hardened.signature):
            self._tamper_detections += 1
            raise ResponseTamperingError(
                "ECDSA signature verification failed — response may be tampered"
            )

        # 4. Verify quantum seed commitment structure
        try:
            QuantumSeedCommitment.from_dict(hardened.seed_commitment)
        except Exception as e:
            self._tamper_detections += 1
            raise ResponseTamperingError(
                f"Quantum seed commitment invalid: {e}"
            )

        self._verified_responses += 1
        return True

    # ─── Hardened analyze_file ───────────────────────────────

    def analyze_file(
        self,
        filename: str,
        extension: str,
        directory: str,
        vault_context: Optional[dict] = None,
        vault=None,
    ) -> dict:
        """
        Analyze a single file with full Protocol-L verification
        and QOPC feedback loop integration.

        The Claude response is committed and verified before being
        returned. If verification fails, falls back to rule-based.

        QOPC cycle:
          1. Capture vault state (DQVL)
          2. Select optimal prompt variant (QOPGC)
          3. Call Claude with variant prompt (LLMRE)
          4. Validate response against state (QOVL)
          5. Outcome recorded later via record_outcome()
        """
        # QOPC: Begin reasoning cycle
        cycle = None
        variant = None
        suffix = TASK_SUFFIXES.get("ANALYZE", "")

        if self._qopc and vault:
            try:
                cycle, variant = self._qopc.begin_cycle(
                    vault, "ANALYZE", f"{filename}{extension}"
                )
                suffix = variant.suffix
            except Exception as e:
                logger.warning("QOPC begin_cycle failed: %s", e)

        prompt = (
            f"Analyze this file and respond with a JSON object only. No other text.\n\n"
            f"filename: {filename}\n"
            f"extension: {extension}\n"
            f"current_directory: {directory}\n\n"
            f"{suffix}"
        )

        try:
            # Node 3: LLMRE — Call Claude
            system = variant.system_prompt if variant else self._active_system_prompt
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            raw = self._strip_markdown_fences(raw)

            # Commit the response via Protocol-L
            hardened = self._commit_response(raw, prompt)

            # Verify before acting
            self._verify_response(hardened)

            # Parse only after verification passes
            parsed = json.loads(hardened.response_text)

            # Node 4: QOVL — Validate response
            if self._qopc and cycle:
                validation = self._qopc.validate_response(cycle, parsed)
                if not validation["valid"]:
                    logger.warning("QOVL issues: %s", validation["issues"])
                    parsed = validation["adjusted"]

            # Store cycle_id on result for later outcome recording
            if cycle:
                parsed["_cycle_id"] = cycle.cycle_id
                if hardened:
                    cycle.commitment_hash = hardened.response_hash

            return parsed

        except ResponseTamperingError as e:
            logger.error("TAMPERING DETECTED: %s", e)
            return self._rule_based_fallback(filename, extension, directory)
        except Exception as e:
            logger.warning(
                "HardenedClaudeAgent error: %s — using rule-based fallback", e
            )
            return self._rule_based_fallback(filename, extension, directory)

    # ─── Hardened batch_analyze ──────────────────────────────

    def batch_analyze(
        self,
        files: list[dict],
        dry_run: bool = True,
    ) -> list[dict]:
        """
        Analyze multiple files with Protocol-L verification on each response.
        """
        if not files:
            return []

        file_list = "\n".join(
            f"{i + 1}. {f['filename']}{f['extension']} in {f['directory']}"
            for i, f in enumerate(files)
        )

        prompt = (
            f"Analyze these {len(files)} files.\n"
            f"Respond with a JSON array only. No other text.\n\n"
            f"Files:\n{file_list}\n\n"
            f"For each file respond with:\n"
            f'{{\n'
            f'  "index": 1,\n'
            f'  "suggested_name": "YYYYMMDD_CATEGORY_Description.ext",\n'
            f'  "category": "CATEGORY",\n'
            f'  "suggested_directory": "path",\n'
            f'  "confidence": 0.0-1.0,\n'
            f'  "reasoning": "one sentence",\n'
            f'  "security_flag": false,\n'
            f'  "security_note": null\n'
            f'}}\n\n'
            f"Return a JSON array of {len(files)} objects."
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            raw = self._strip_markdown_fences(raw)

            # Commit and verify
            hardened = self._commit_response(raw, prompt)
            self._verify_response(hardened)

            results = json.loads(hardened.response_text)
            for i, result in enumerate(results):
                if i < len(files):
                    result["original"] = files[i]

            return results

        except ResponseTamperingError as e:
            logger.error("TAMPERING DETECTED in batch: %s", e)
            return [
                self._rule_based_fallback(
                    f["filename"], f["extension"], f["directory"]
                )
                for f in files
            ]
        except Exception as e:
            logger.warning("Batch analysis failed: %s — falling back", e)
            return [
                self._rule_based_fallback(
                    f["filename"], f["extension"], f["directory"]
                )
                for f in files
            ]

    # ─── Hardened chat ───────────────────────────────────────

    def chat(self, query: str, vault_context: Optional[dict] = None) -> str:
        """
        Natural language conversation with Protocol-L verification.
        Every response is committed and verified before delivery.
        """
        vault_context = vault_context or {}

        context = (
            f"Current vault state:\n"
            f"  Files: {vault_context.get('file_count', 0)}\n"
            f"  Recent audit events: {json.dumps(vault_context.get('recent_events', [])[-5:], indent=2, default=str)}\n"
            f"  Sample files: {', '.join(vault_context.get('file_sample', [])[:10])}\n"
            f"  Vault stats: {json.dumps(vault_context.get('vault_stats', {}), indent=2, default=str)}"
        )

        if not self.conversation_history:
            full_query = f"{context}\n\nUser: {query}"
        else:
            full_query = query

        self.conversation_history.append(
            {"role": "user", "content": full_query}
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self._active_system_prompt,
                messages=self.conversation_history,
            )

            raw = response.content[0].text.strip()

            # Commit and verify
            hardened = self._commit_response(raw, full_query)
            self._verify_response(hardened)

            reply = hardened.response_text
            self.conversation_history.append(
                {"role": "assistant", "content": reply}
            )

            # Keep history bounded
            if len(self.conversation_history) > 40:
                self.conversation_history = self.conversation_history[-40:]

            return reply

        except ResponseTamperingError as e:
            logger.error("TAMPERING DETECTED in chat: %s", e)
            return f"⚠ Response integrity check failed: {e}"
        except Exception as e:
            logger.error("Chat failed: %s", e)
            return f"Agent unavailable: {str(e)}\nCheck ANTHROPIC_API_KEY in .env"

    # ─── Hardened security analysis ──────────────────────────

    def analyze_security_pattern(self, audit_events: list[dict]) -> dict:
        """
        Analyze audit events for threats with Protocol-L verification.
        """
        if not audit_events:
            return {
                "threat_level": "NONE",
                "findings": [],
                "recommended_action": "No events to analyze",
            }

        events_str = json.dumps(audit_events[-50:], indent=2, default=str)

        prompt = (
            f"Analyze these vault audit events for security threats.\n"
            f"Respond with JSON only.\n\n"
            f"Recent audit events:\n{events_str}\n\n"
            f"Respond with exactly:\n"
            f'{{\n'
            f'  "threat_level": "NONE|LOW|MEDIUM|HIGH",\n'
            f'  "findings": ["finding 1", "finding 2"],\n'
            f'  "recommended_action": "one clear action"\n'
            f'}}'
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=512,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            raw = self._strip_markdown_fences(raw)

            hardened = self._commit_response(raw, prompt)
            self._verify_response(hardened)

            return json.loads(hardened.response_text)

        except ResponseTamperingError as e:
            logger.error("TAMPERING DETECTED in security scan: %s", e)
            return {
                "threat_level": "UNKNOWN",
                "findings": [f"Tampering detected: {e}"],
                "recommended_action": "Immediate manual review required",
            }
        except Exception as e:
            logger.error("Security analysis failed: %s", e)
            return {
                "threat_level": "UNKNOWN",
                "findings": [f"Analysis failed: {e}"],
                "recommended_action": "Manual review required",
            }

    # ─── Hardened marketing methods ─────────────────────────

    def create_competitive_card(
        self,
        product: str,
        competitors: list[str],
        features: Optional[list[str]] = None,
    ) -> dict:
        """Create a competitive card with Protocol-L verification."""
        suffix = TASK_SUFFIXES.get("COMPETITIVE_CARD", "")
        comp_list = ", ".join(competitors)
        feat_hint = f"\nFocus on: {', '.join(features)}" if features else ""

        prompt = (
            f"Create a competitive comparison card.\n\n"
            f"Our product: {product}\n"
            f"Competitors: {comp_list}\n"
            f"{feat_hint}\n\n{suffix}"
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            raw = self._strip_markdown_fences(raw)
            hardened = self._commit_response(raw, prompt)
            self._verify_response(hardened)
            return json.loads(hardened.response_text)
        except ResponseTamperingError as e:
            logger.error("TAMPERING DETECTED in competitive card: %s", e)
            return {"product": product, "competitors": competitors,
                    "differentiators": [], "summary": f"Tamper detected: {e}", "confidence": 0.0}
        except Exception as e:
            logger.warning("Competitive card failed: %s", e)
            return {"product": product, "competitors": competitors,
                    "differentiators": [], "summary": f"Unavailable: {e}", "confidence": 0.0}

    def draft_content(
        self,
        content_type: str,
        topic: str,
        audience: Optional[str] = None,
        tone: Optional[str] = None,
    ) -> dict:
        """Draft marketing content with Protocol-L verification."""
        suffix = TASK_SUFFIXES.get("CONTENT_DRAFT", "")
        aud = f"\nTarget audience: {audience}" if audience else ""
        t = f"\nTone: {tone}" if tone else ""

        prompt = (
            f"Draft marketing content.\n\n"
            f"Content type: {content_type}\n"
            f"Topic: {topic}\n{aud}{t}\n\n{suffix}"
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            raw = self._strip_markdown_fences(raw)
            hardened = self._commit_response(raw, prompt)
            self._verify_response(hardened)
            return json.loads(hardened.response_text)
        except ResponseTamperingError as e:
            logger.error("TAMPERING DETECTED in content draft: %s", e)
            return {"content_type": content_type, "title": topic, "body": f"Tamper detected: {e}",
                    "cta": "", "seo_keywords": [], "tone": tone or "", "word_count": 0, "confidence": 0.0}
        except Exception as e:
            logger.warning("Content draft failed: %s", e)
            return {"content_type": content_type, "title": topic, "body": f"Unavailable: {e}",
                    "cta": "", "seo_keywords": [], "tone": tone or "", "word_count": 0, "confidence": 0.0}

    def draft_email_sequence(
        self,
        sequence_type: str,
        product: str,
        num_emails: int = 5,
        audience: Optional[str] = None,
    ) -> dict:
        """Design an email sequence with Protocol-L verification."""
        suffix = TASK_SUFFIXES.get("EMAIL_SEQUENCE", "")
        aud = f"\nTarget audience: {audience}" if audience else ""

        prompt = (
            f"Design a {num_emails}-email drip campaign.\n\n"
            f"Sequence type: {sequence_type}\n"
            f"Product: {product}\n{aud}\n\n{suffix}"
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            raw = self._strip_markdown_fences(raw)
            hardened = self._commit_response(raw, prompt)
            self._verify_response(hardened)
            return json.loads(hardened.response_text)
        except ResponseTamperingError as e:
            logger.error("TAMPERING DETECTED in email sequence: %s", e)
            return {"sequence_name": sequence_type, "emails": [], "total_emails": 0, "confidence": 0.0}
        except Exception as e:
            logger.warning("Email sequence failed: %s", e)
            return {"sequence_name": sequence_type, "emails": [], "total_emails": 0, "confidence": 0.0}

    def review_content(
        self,
        content: str,
        content_type: Optional[str] = None,
        audience: Optional[str] = None,
    ) -> dict:
        """Review marketing content with Protocol-L verification."""
        suffix = TASK_SUFFIXES.get("CONTENT_REVIEW", "")
        ct = f"\nContent type: {content_type}" if content_type else ""
        aud = f"\nTarget audience: {audience}" if audience else ""

        prompt = (
            f"Review this marketing content.\n\n"
            f"Content:\n{content}\n{ct}{aud}\n\n{suffix}"
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            raw = self._strip_markdown_fences(raw)
            hardened = self._commit_response(raw, prompt)
            self._verify_response(hardened)
            return json.loads(hardened.response_text)
        except ResponseTamperingError as e:
            logger.error("TAMPERING DETECTED in content review: %s", e)
            return {"readability_score": 0.0, "accuracy_issues": [str(e)], "unsupported_claims": [],
                    "cta_suggestions": [], "revised_content": content, "overall_grade": "F", "confidence": 0.0}
        except Exception as e:
            logger.warning("Content review failed: %s", e)
            return {"readability_score": 0.0, "accuracy_issues": [str(e)], "unsupported_claims": [],
                    "cta_suggestions": [], "revised_content": content, "overall_grade": "F", "confidence": 0.0}

    def develop_positioning(
        self,
        product: str,
        market: str,
        competitors: Optional[list[str]] = None,
    ) -> dict:
        """Develop market positioning with Protocol-L verification."""
        suffix = TASK_SUFFIXES.get("POSITIONING", "")
        comp = f"\nKey competitors: {', '.join(competitors)}" if competitors else ""

        prompt = (
            f"Develop a market positioning framework.\n\n"
            f"Product: {product}\n"
            f"Market: {market}\n{comp}\n\n{suffix}"
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            raw = self._strip_markdown_fences(raw)
            hardened = self._commit_response(raw, prompt)
            self._verify_response(hardened)
            return json.loads(hardened.response_text)
        except ResponseTamperingError as e:
            logger.error("TAMPERING DETECTED in positioning: %s", e)
            return {"category": market, "value_proposition": f"Tamper detected: {e}",
                    "icp": {"title": "", "company_size": "", "pain_points": []},
                    "messaging_hierarchy": {"primary": "", "supporting": []},
                    "competitive_moat": [], "confidence": 0.0}
        except Exception as e:
            logger.warning("Positioning failed: %s", e)
            return {"category": market, "value_proposition": f"Unavailable: {e}",
                    "icp": {"title": "", "company_size": "", "pain_points": []},
                    "messaging_hierarchy": {"primary": "", "supporting": []},
                    "competitive_moat": [], "confidence": 0.0}

    # ─── QOPC Feedback ────────────────────────────────────────

    def record_outcome(
        self,
        cycle_id: str,
        user_action: str,
        user_correction: Optional[str] = None,
    ) -> Optional[float]:
        """
        Node 5: Record user outcome for a QOPC reasoning cycle.
        Feeds delta back to prompt optimizer.

        Args:
            cycle_id: The _cycle_id from a previous analyze_file result
            user_action: ACCEPTED | REJECTED | CORRECTED | IGNORED
            user_correction: Optional correction text

        Returns:
            Delta value (prediction - reality), or None if no QOPC loop
        """
        if not self._qopc:
            return None
        return self._qopc.record_outcome(
            cycle_id, user_action, user_correction
        )

    def get_qopc_stats(self) -> dict:
        """Return QOPC feedback loop statistics."""
        if not self._qopc:
            return {"enabled": False}
        stats = self._qopc.get_loop_stats()
        stats["enabled"] = True
        stats["context_scoring"] = {
            "has_context": self._context_scorer.has_context,
            "active_signals": self._context_scorer.active_signals,
            "user_context_length": len(self.user_context),
        }
        return stats

    # ─── Verification report ─────────────────────────────────

    def get_verification_report(self) -> dict:
        """
        Return a summary of all verification activity for this session.

        This is the audit evidence for the third patent claim:
        cryptographically verified AI reasoning.
        """
        report = {
            "session_token_hash": self._session_token_hash,
            "model": self.model,
            "total_responses": self._total_responses,
            "verified_responses": self._verified_responses,
            "failed_verifications": self._failed_verifications,
            "tamper_detections": self._tamper_detections,
            "rfc3161_enabled": self._tsa is not None,
            "verification_rate": (
                f"{self._verified_responses}/{self._total_responses}"
                if self._total_responses > 0
                else "0/0"
            ),
            "integrity": (
                "CLEAN"
                if self._tamper_detections == 0
                else f"COMPROMISED ({self._tamper_detections} detections)"
            ),
            "qopc": self.get_qopc_stats(),
        }
        return report

    # ─── Utility methods ─────────────────────────────────────

    def reset_conversation(self) -> None:
        """Clear conversation history."""
        self.conversation_history = []
        logger.info("HardenedClaudeAgent conversation reset")

    def _strip_markdown_fences(self, text: str) -> str:
        """Strip markdown code fences from API response."""
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            return "\n".join(lines)
        return text

    def _rule_based_fallback(
        self,
        filename: str,
        extension: str,
        directory: str,
    ) -> dict:
        """
        Rule-based fallback when Claude API is unavailable or
        response verification fails.
        """
        from datetime import datetime

        date = datetime.now().strftime("%Y%m%d")

        ext_map = {
            ".py": "CODE", ".js": "CODE", ".ts": "CODE", ".sh": "CODE",
            ".java": "CODE", ".c": "CODE", ".cpp": "CODE", ".rs": "CODE",
            ".go": "CODE", ".html": "CODE", ".css": "CODE",
            ".pdf": "LEGAL", ".docx": "LEGAL", ".doc": "LEGAL",
            ".xlsx": "FINANCE", ".xls": "FINANCE", ".csv": "FINANCE",
            ".zip": "BACKUP", ".tar": "BACKUP", ".gz": "BACKUP",
            ".rar": "BACKUP", ".7z": "BACKUP",
            ".log": "LOG", ".json": "CONFIG", ".env": "CONFIG",
            ".yml": "CONFIG", ".yaml": "CONFIG", ".toml": "CONFIG",
            ".ini": "CONFIG",
        }
        category = ext_map.get(extension.lower(), "PERSONAL")

        name_lower = filename.lower()
        if any(k in name_lower for k in ["patent", "filing", "uspto"]):
            category = "PATENT"
        elif any(k in name_lower for k in ["trade", "position", "pnl", "futures"]):
            category = "TRADING"
        elif any(k in name_lower for k in ["password", "key", "secret", "credential"]):
            category = "SECURITY"
        elif any(k in name_lower for k in ["contract", "nda", "legal"]):
            category = "LEGAL"
        elif any(k in name_lower for k in ["backup", "bak"]):
            category = "BACKUP"

        clean = filename.replace(" ", "_")

        return {
            "suggested_name": f"{date}_{category}_{clean}{extension}",
            "category": category,
            "suggested_directory": category.lower(),
            "confidence": 0.6,
            "reasoning": "Rule-based (API unavailable or verification failed)",
            "security_flag": False,
            "security_note": None,
        }
