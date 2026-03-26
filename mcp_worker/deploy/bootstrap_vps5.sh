#!/bin/bash
# ═══════════════════════════════════════════════════
# Generate VPS5 Ed25519 Node Identity
# Creates /opt/aether-mcp/certs/VPS5.key and VPS5.pub
# ═══════════════════════════════════════════════════
set -e

INSTALL_DIR="/opt/aether-mcp"
CERT_DIR="$INSTALL_DIR/certs"

echo "Generating VPS5 Ed25519 identity..."

"$INSTALL_DIR/venv/bin/python3" -c "
import sys
sys.path.insert(0, '$INSTALL_DIR')
from mcp_worker.node_auth import NodeAuth
NodeAuth.generate_keypair('$CERT_DIR/VPS5')

print()
print('═══════════════════════════════════════════════════')
print('  VPS5 Identity Generated')
print('═══════════════════════════════════════════════════')
print()
print('Private key: $CERT_DIR/VPS5.key (keep secret)')
print('Public key:  $CERT_DIR/VPS5.pub (share with VPS2)')
print()
print('VPS5 Public Key:')
with open('$CERT_DIR/VPS5.pub') as f:
    print(f.read())
print('Copy the public key above and save it on VPS2 at:')
print('  /opt/aether-cloud/certs/VPS5.pub')
print()
print('Also copy VPS2 public key to this server at:')
print('  $CERT_DIR/VPS2.pub')
print('═══════════════════════════════════════════════════')
"
