#!/usr/bin/env python3
"""
AetherCloud-L
Quantum-secured AI file intelligence system.
Powered by Aether Protocol-L.

Aether Systems LLC — Patent Pending

Usage:
    python main.py          # Launch terminal UI
    python main.py --serve  # Launch FastAPI server on :8741
"""

import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    """Entry point for AetherCloud-L."""
    if "--serve" in sys.argv:
        from api_server import run_server
        run_server()
    else:
        from ui.terminal import AetherCloudTerminal
        terminal = AetherCloudTerminal()
        terminal.run()


if __name__ == "__main__":
    main()
