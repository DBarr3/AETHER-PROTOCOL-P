# ═══════════════════════════════════════════════════
# AetherCloud-L — DO Spaces Vault Client
# Per-user cloud file vault backed by DigitalOcean Spaces (S3-compatible)
# Aether Systems LLC · Patent Pending
# ═══════════════════════════════════════════════════
"""
Provides upload, download, list, and delete for per-user vault files
stored in a DO Spaces bucket. Each user's files are isolated under
a prefix: ``vaults/{username}/``
"""

from __future__ import annotations

import logging
import os
import mimetypes
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional

log = logging.getLogger("aether.vault_spaces")

# ── Configuration ─────────────────────────────────
SPACES_REGION = os.environ.get("DO_SPACES_REGION", "nyc3")
SPACES_ENDPOINT = os.environ.get(
    "DO_SPACES_ENDPOINT",
    f"https://{SPACES_REGION}.digitaloceanspaces.com",
)
SPACES_BUCKET = os.environ.get("DO_SPACES_BUCKET", "aethercloud-vault")
SPACES_KEY = os.environ.get("DO_SPACES_KEY", "")
SPACES_SECRET = os.environ.get("DO_SPACES_SECRET", "")

# Max single-file upload size (50 MB)
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# ── Upload MIME hardening ─────────────────────────
# A user-uploaded file is later served back by the API, inline-linkable via
# /vault/spaces/download/<name>. Without a type allowlist, an attacker with
# a valid session can upload "x.html" as text/html and weaponize it into
# stored XSS against any other browser that fetches the URL (including
# the Electron renderer itself, if loaded in an <iframe> or new window).
#
# The policy below rejects active content at upload time. Download still
# forces Content-Disposition: attachment + X-Content-Type-Options: nosniff
# (see api_server.py) as defense-in-depth — but the primary fix is here.
DANGEROUS_UPLOAD_EXTS = frozenset({
    # Executable / script
    ".exe", ".bat", ".cmd", ".com", ".ps1", ".vbs", ".vbe", ".js", ".jse",
    ".ws", ".wsf", ".wsh", ".msh", ".hta", ".scr", ".msi", ".msp", ".lnk",
    ".url", ".reg", ".dll", ".chm", ".cpl", ".pif", ".jar", ".appx",
    ".appxbundle",
    # Browser-renderable active content (stored-XSS vectors)
    ".html", ".htm", ".xhtml", ".xml", ".xsl", ".xslt", ".svg", ".mhtml",
    ".mht",
    # Server-side script
    ".php", ".phtml", ".asp", ".aspx", ".jsp", ".py", ".rb", ".sh",
    # Office macro-enabled (users tend to trust .docx but .docm/.xlsm execute)
    ".docm", ".xlsm", ".pptm", ".dotm", ".xltm", ".potm",
})

# Set of MIME types that force `application/octet-stream` rewrite regardless
# of what the extension says — catches poly-glot and server-side-guessed
# types that could still be rendered as HTML/JS.
RISKY_MIME_TYPES = frozenset({
    "text/html", "application/xhtml+xml", "image/svg+xml",
    "text/javascript", "application/javascript", "application/ecmascript",
    "text/xml", "application/xml", "application/xslt+xml",
})


def _sanitize_filename(filename: str) -> str:
    """
    Strip path separators, CR/LF (prevents Content-Disposition header
    injection on download), NUL, and leading/trailing whitespace. Returns
    a name that's safe to use as both an S3 key suffix and an
    attachment filename.
    """
    if not isinstance(filename, str):
        raise ValueError("filename must be a string")
    # Kill path separators and traversal sequences
    name = filename.replace("/", "_").replace("\\", "_").replace("..", "_")
    # Kill characters that would corrupt HTTP headers or log lines
    for ch in ("\r", "\n", "\x00", '"'):
        name = name.replace(ch, "_")
    name = name.strip().lstrip(".")  # no leading dot → no hidden files
    if not name:
        raise ValueError("filename empty after sanitization")
    if len(name) > 255:
        raise ValueError(f"filename too long ({len(name)} chars, max 255)")
    return name


def _classify_upload(safe_name: str) -> tuple[str, str]:
    """
    Given a sanitized filename, return (ext, content_type) or raise
    ValueError for disallowed types. Content-type is always server-derived;
    the client's supplied content_type is intentionally ignored.
    """
    # Split on the LAST dot so "archive.tar.gz" → ".gz"
    ext = os.path.splitext(safe_name)[1].lower()
    if ext in DANGEROUS_UPLOAD_EXTS:
        raise ValueError(f"file type not permitted: {ext}")

    guessed = mimetypes.guess_type(safe_name)[0]
    if not guessed or guessed.lower() in RISKY_MIME_TYPES:
        # Force opaque type: no browser will try to render it inline.
        content_type = "application/octet-stream"
    else:
        content_type = guessed
    return ext, content_type


class VaultSpacesClient:
    """S3-compatible client for DigitalOcean Spaces vault storage."""

    def __init__(self) -> None:
        self._client = None
        self._ready = False

    # ── Lazy init ──────────────────────────────────
    def _ensure_client(self):
        if self._client is not None:
            return
        if not SPACES_KEY or not SPACES_SECRET:
            log.warning("DO Spaces credentials not configured — vault uploads disabled")
            return
        try:
            import boto3
            from botocore.config import Config as BotoConfig

            self._client = boto3.client(
                "s3",
                region_name=SPACES_REGION,
                endpoint_url=SPACES_ENDPOINT,
                aws_access_key_id=SPACES_KEY,
                aws_secret_access_key=SPACES_SECRET,
                config=BotoConfig(
                    signature_version="s3v4",
                    retries={"max_attempts": 3, "mode": "adaptive"},
                ),
            )
            self._ready = True
            log.info("DO Spaces client initialized — bucket=%s region=%s", SPACES_BUCKET, SPACES_REGION)
        except ImportError:
            log.error("boto3 not installed — vault uploads disabled (pip install boto3)")
        except Exception as exc:
            log.error("Failed to init DO Spaces client: %s", exc)

    @property
    def available(self) -> bool:
        self._ensure_client()
        return self._ready

    # ── Helpers ────────────────────────────────────
    @staticmethod
    def _user_prefix(username: str) -> str:
        safe = username.replace("/", "_").replace("\\", "_").replace("..", "_")
        return f"vaults/{safe}/"

    # ── Upload ─────────────────────────────────────
    def upload(
        self,
        username: str,
        filename: str,
        data: bytes,
        content_type: Optional[str] = None,
    ) -> dict:
        """
        Upload a file to the user's vault. Returns metadata dict on success.

        Security:
          * filename is sanitized (no path traversal, no CRLF, no NUL)
          * extension is checked against DANGEROUS_UPLOAD_EXTS — dangerous
            types raise ValueError before the object hits storage
          * content_type is ALWAYS derived server-side; any client-supplied
            value is ignored to prevent polyglot/stored-XSS attacks
        """
        self._ensure_client()
        if not self._ready:
            raise RuntimeError("DO Spaces not configured")

        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError(f"File too large ({len(data)} bytes, max {MAX_UPLOAD_BYTES})")

        safe_name = _sanitize_filename(filename)
        _ext, server_content_type = _classify_upload(safe_name)
        key = self._user_prefix(username) + safe_name

        # Discard client-supplied content_type: trusting it enables stored-XSS
        # via attacker-chosen text/html. Keeping the arg in the signature for
        # API compatibility but only for logging.
        if content_type and content_type != server_content_type:
            log.info(
                "Upload content_type override: client=%r server=%r for %s",
                content_type, server_content_type, safe_name,
            )

        self._client.put_object(
            Bucket=SPACES_BUCKET,
            Key=key,
            Body=data,
            ContentType=server_content_type,
            ContentDisposition=f'attachment; filename="{safe_name}"',
            ACL="private",
            Metadata={
                "uploaded-by": username,
                "uploaded-at": datetime.now(timezone.utc).isoformat(),
            },
        )

        log.info("Uploaded %s (%d bytes, %s) → %s",
                 safe_name, len(data), server_content_type, key)

        return {
            "key": key,
            "filename": safe_name,
            "size": len(data),
            "content_type": server_content_type,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── List ───────────────────────────────────────
    def list_files(self, username: str) -> list[dict]:
        """List all files in the user's vault prefix."""
        self._ensure_client()
        if not self._ready:
            return []

        prefix = self._user_prefix(username)
        result = []

        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=SPACES_BUCKET, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    name = key[len(prefix):]  # strip prefix
                    if not name:
                        continue
                    result.append({
                        "key": key,
                        "filename": name,
                        "size": obj["Size"],
                        "last_modified": obj["LastModified"].isoformat(),
                    })
        except Exception as exc:
            log.error("Failed to list vault for %s: %s", username, exc)

        return result

    # ── Download ───────────────────────────────────
    def download(self, username: str, filename: str) -> tuple[BytesIO, str, int]:
        """Download a file from the user's vault. Returns (stream, content_type, size)."""
        self._ensure_client()
        if not self._ready:
            raise RuntimeError("DO Spaces not configured")

        safe_name = filename.replace("/", "_").replace("\\", "_")
        key = self._user_prefix(username) + safe_name

        resp = self._client.get_object(Bucket=SPACES_BUCKET, Key=key)
        body = resp["Body"].read()
        ct = resp.get("ContentType", "application/octet-stream")
        return BytesIO(body), ct, len(body)

    # ── Download raw text (for agent context) ──────
    def download_text(self, username: str, filename: str, max_bytes: int = 50 * 1024) -> Optional[str]:
        """Download file as text for agent context injection. Returns None for binary."""
        try:
            stream, ct, size = self.download(username, filename)
            if size > max_bytes:
                return f"[Truncated — file is {size} bytes, max {max_bytes}]"
            raw = stream.read()
            # Quick binary check
            sample = raw[:512]
            if sum(1 for b in sample if b == 0) > len(sample) * 0.1:
                return None
            return raw.decode("utf-8", errors="replace")
        except Exception as exc:
            log.warning("download_text failed for %s/%s: %s", username, filename, exc)
            return None

    # ── Delete ─────────────────────────────────────
    def delete(self, username: str, filename: str) -> bool:
        """Delete a file from the user's vault."""
        self._ensure_client()
        if not self._ready:
            return False

        safe_name = filename.replace("/", "_").replace("\\", "_")
        key = self._user_prefix(username) + safe_name

        try:
            self._client.delete_object(Bucket=SPACES_BUCKET, Key=key)
            log.info("Deleted vault file: %s", key)
            return True
        except Exception as exc:
            log.error("Failed to delete %s: %s", key, exc)
            return False
