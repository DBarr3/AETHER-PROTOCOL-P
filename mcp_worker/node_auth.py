"""
Aether MCP Worker — Ed25519 Node Authentication
Mutual authentication between VPS2 and VPS5 using Ed25519 signatures.

Aether Systems LLC — Patent Pending
"""

import hashlib
import logging
import os
import time
from collections import deque
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

logger = logging.getLogger("aether.mcp.nodeauth")

TIMESTAMP_WINDOW = 30
NONCE_HISTORY = 10000


class NodeAuth:
    """Ed25519-based node authentication for inter-VPS communication."""

    def __init__(self, node_id="", private_key_path="", trusted_peers=None):
        self.node_id = node_id
        self._private_key = None
        self._trusted_peers: dict[str, Ed25519PublicKey] = {}
        self._seen_nonces: deque = deque(maxlen=NONCE_HISTORY)

        if private_key_path and Path(private_key_path).exists():
            self._private_key = self._load_private_key(private_key_path)
            logger.info("Node %s: private key loaded from %s", node_id, private_key_path)

        if trusted_peers:
            for peer_id, pub_path in trusted_peers.items():
                if Path(pub_path).exists():
                    self._trusted_peers[peer_id] = self._load_public_key(pub_path)
                    logger.info("Node %s: trusted peer %s loaded", node_id, peer_id)
                else:
                    logger.warning("Node %s: peer %s key not found at %s", node_id, peer_id, pub_path)

    @staticmethod
    def _load_private_key(path):
        with open(path, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

    @staticmethod
    def _load_public_key(path):
        with open(path, "rb") as f:
            return serialization.load_pem_public_key(f.read())

    def sign_request(self, body: bytes) -> dict:
        if not self._private_key:
            raise RuntimeError(f"Node {self.node_id}: no private key loaded")
        timestamp = str(int(time.time()))
        nonce = os.urandom(16).hex()
        body_hash = hashlib.sha256(body).hexdigest()
        message = f"{self.node_id}|{timestamp}|{nonce}|{body_hash}".encode()
        signature = self._private_key.sign(message).hex()
        return {
            "X-Aether-Node-ID": self.node_id,
            "X-Aether-Timestamp": timestamp,
            "X-Aether-Nonce": nonce,
            "X-Aether-Signature": signature,
        }

    def verify_request(self, headers: dict, body: bytes) -> bool:
        node_id = headers.get("X-Aether-Node-ID", "")
        timestamp_str = headers.get("X-Aether-Timestamp", "")
        nonce = headers.get("X-Aether-Nonce", "")
        signature_hex = headers.get("X-Aether-Signature", "")

        if not all([node_id, timestamp_str, nonce, signature_hex]):
            raise ValueError("Missing authentication headers")
        if node_id not in self._trusted_peers:
            raise ValueError(f"Unknown node: {node_id}")

        try:
            timestamp = int(timestamp_str)
        except ValueError:
            raise ValueError("Invalid timestamp format")

        if abs(time.time() - timestamp) > TIMESTAMP_WINDOW:
            raise ValueError(f"Request too old (max {TIMESTAMP_WINDOW}s)")
        if nonce in self._seen_nonces:
            raise ValueError("Nonce replay detected")
        self._seen_nonces.append(nonce)

        body_hash = hashlib.sha256(body).hexdigest()
        message = f"{node_id}|{timestamp_str}|{nonce}|{body_hash}".encode()
        try:
            signature = bytes.fromhex(signature_hex)
            self._trusted_peers[node_id].verify(signature, message)
        except Exception:
            raise ValueError("Invalid Ed25519 signature")
        return True

    def sign_response(self, response_body: bytes) -> str:
        if not self._private_key:
            raise RuntimeError(f"Node {self.node_id}: no private key loaded")
        return self._private_key.sign(response_body).hex()

    def verify_response_signature(self, peer_id, response_body, signature_hex):
        if peer_id not in self._trusted_peers:
            raise ValueError(f"Unknown peer: {peer_id}")
        try:
            self._trusted_peers[peer_id].verify(bytes.fromhex(signature_hex), response_body)
            return True
        except Exception:
            return False

    @staticmethod
    def generate_keypair(base_path: str):
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        key_path = f"{base_path}.key"
        pub_path = f"{base_path}.pub"
        Path(key_path).parent.mkdir(parents=True, exist_ok=True)
        with open(key_path, "wb") as f:
            f.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ))
        os.chmod(key_path, 0o600)
        with open(pub_path, "wb") as f:
            f.write(public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ))
        logger.info("Generated Ed25519 keypair: %s.key / %s.pub", base_path, base_path)
        return key_path, pub_path
