#!/usr/bin/env python3
"""
AetherCloud-L
Quantum-secured AI file intelligence system.
Powered by Aether Protocol-L.

Aether Systems LLC — Patent Pending
"""

import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.terminal import AetherCloudTerminal


def main():
    """Entry point for AetherCloud-L."""
    terminal = AetherCloudTerminal()
    terminal.run()


if __name__ == "__main__":
    main()
