#!/bin/bash
# AetherCloud-L — Secure Key Setup
# Run once on VPS2 to create the protected key store
# Usage: sudo bash scripts/setup_keys.sh
#
# Aether Systems LLC — Patent Pending

set -e

echo "AetherCloud-L — Secure Key Setup"
echo "================================="

# Create protected directory
mkdir -p /etc/aethercloud
chmod 700 /etc/aethercloud

# Create .env file if it doesn't exist
if [ ! -f /etc/aethercloud/.env ]; then
    touch /etc/aethercloud/.env
    chmod 600 /etc/aethercloud/.env
    chown root:root /etc/aethercloud/.env
    echo "Created /etc/aethercloud/.env"
else
    echo "/etc/aethercloud/.env already exists — skipping creation"
fi

echo ""
echo "Next steps:"
echo "  sudo nano /etc/aethercloud/.env"
echo ""
echo "Add these lines:"
echo "  ANTHROPIC_API_KEY=your_key_here"
echo "  IBM_QUANTUM_API_KEY=your_token_here"
echo "  AETHER_DEV_KEY=your_dev_key_here"
echo "  AETHER_BIND_HOST=0.0.0.0"
echo "  AETHER_BIND_PORT=8080"
echo ""
echo "Then restart the server:"
echo "  sudo systemctl restart aethercloud"
echo "================================="
