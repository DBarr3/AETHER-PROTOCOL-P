"""
aether_protocol/terminal_ui.py

Rich retro terminal UI for AETHER-PROTOCOL-L.

Provides three display surfaces:
    1. Boot banner — shown when the server starts or the library loads
    2. Seed display — live-updating panels for IBM Fez / Aer / OS_URANDOM
       seed generation with spinners and provenance metadata
    3. Protocol cycle display — commit → execute → settle phase rendering
       with signature fragments, quantum binding, and temporal windows

All output is strictly cosmetic — no protocol logic lives here.
The module is safe to import even if ``rich`` is missing (functions
become silent no-ops), so existing tests never break.

Usage::

    from aether_protocol.terminal_ui import AetherConsole

    ui = AetherConsole()
    ui.boot_banner()
    ui.show_seed_result(seed_result)
    ui.show_phase("COMMIT", commitment_dict, signature_dict)
"""

from __future__ import annotations

import time
from typing import Any, Optional

# ── Graceful degradation — rich is optional for tests ──────────────
_RICH_AVAILABLE = False
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.align import Align
    from rich.columns import Columns
    from rich.layout import Layout
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.style import Style
    from rich.rule import Rule
    from rich import box

    _RICH_AVAILABLE = True
except ImportError:
    pass

# ── Version ────────────────────────────────────────────────────────
__version__ = "0.5.1"

# ── Color palette — retro CRT / amber-green-cyan ──────────────────
_AMBER = "#FFB000"
_GREEN = "#39FF14"
_CYAN = "#00FFFF"
_DIM_GREEN = "#0A6E0A"
_RED = "#FF3131"
_WHITE = "#E0E0E0"
_DIM = "#555555"
_MAGENTA = "#FF00FF"
_BLUE = "#00BFFF"

# ── ASCII art banner ──────────────────────────────────────────────
_BANNER_ART = r"""
    ╔═══════════════════════════════════════════════════════════════╗
    ║                                                               ║
    ║     █████╗ ███████╗████████╗██╗  ██╗███████╗██████╗          ║
    ║    ██╔══██╗██╔════╝╚══██╔══╝██║  ██║██╔════╝██╔══██╗         ║
    ║    ███████║█████╗     ██║   ███████║█████╗  ██████╔╝         ║
    ║    ██╔══██║██╔══╝     ██║   ██╔══██║██╔══╝  ██╔══██╗         ║
    ║    ██║  ██║███████╗   ██║   ██║  ██║███████╗██║  ██║         ║
    ║    ╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝         ║
    ║                                                               ║
    ║        ██████╗ ██████╗  ██████╗ ████████╗ ██████╗  ██████╗██╗  ██║
    ║        ██╔══██╗██╔══██╗██╔═══██╗╚══██╔══╝██╔═══██╗██╔════╝██║  ██║
    ║        ██████╔╝██████╔╝██║   ██║   ██║   ██║   ██║██║     ██║  ██║
    ║        ██╔═══╝ ██╔══██╗██║   ██║   ██║   ██║   ██║██║     ██║  ██║
    ║        ██║     ██║  ██║╚██████╔╝   ██║   ╚██████╔╝╚██████╗███████║
    ║        ╚═╝     ╚═╝  ╚═╝ ╚═════╝    ╚═╝    ╚═════╝  ╚═════╝╚══════╝
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
"""

_TAGLINE = "Quantum-First Trade Auditability Protocol"
_CIRCUIT_DIAGRAM = (
    "  |0⟩─[H]─●──────[S]─[H]─┤M├\n"
    "  |0⟩─[H]─⊕──●───[S]─[H]─┤M├\n"
    "  |0⟩─[H]────⊕──●─[S]─[H]─┤M├\n"
    "   ...         ⊕  ...       \n"
    "  |0⟩─[H]──────⊕─[S]─[H]─┤M├"
)


def _short_hash(h: str, length: int = 12) -> str:
    """Truncate a hex hash for display."""
    if not h or len(h) < length:
        return h or "—"
    return h[:length] + "…"


def _format_timestamp(ts: int | float) -> str:
    """Format a Unix timestamp to human-readable."""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts))
    except (TypeError, ValueError, OSError):
        return str(ts)


class AetherConsole:
    """
    Rich retro terminal UI controller.

    All methods are no-ops when ``rich`` is not installed, so importing
    this module never breaks headless / test environments.

    Args:
        quiet: If True, suppress all output (useful for testing).
    """

    def __init__(self, quiet: bool = False) -> None:
        self._quiet = quiet
        self._console: Any = None
        if _RICH_AVAILABLE and not quiet:
            import sys
            import io as _io

            # On Windows the legacy console uses cp1252 which can't render
            # our Unicode box-drawing / emoji characters.  Wrap stdout in a
            # UTF-8 text wrapper so Rich never hits a charmap encode error.
            _stdout = sys.stdout
            if (
                hasattr(_stdout, "buffer")
                and hasattr(_stdout, "encoding")
                and (_stdout.encoding or "").lower().replace("-", "") != "utf8"
            ):
                _stdout = _io.TextIOWrapper(
                    _stdout.buffer, encoding="utf-8", errors="replace"
                )

            self._console = Console(
                file=_stdout,
                highlight=False,
                force_terminal=True,
            )

    @property
    def is_active(self) -> bool:
        """True if the console is ready to render."""
        return self._console is not None

    # ── 1. BOOT BANNER ────────────────────────────────────────────

    def boot_banner(
        self,
        version: str = __version__,
        seed_method: str = "OS_URANDOM",
        log_path: str = "audit.jsonl",
        host: str = "0.0.0.0",
        port: int = 8765,
    ) -> None:
        """
        Render the full boot banner with system info.

        Called at server startup or when running ``aether-server``.
        """
        if not self.is_active:
            return
        c = self._console

        # Main ASCII art
        c.print()
        banner_text = Text(_BANNER_ART, style=f"bold {_AMBER}")
        c.print(Align.center(banner_text))

        # Tagline
        tagline = Text(f"  {_TAGLINE}  ", style=f"bold {_CYAN}")
        c.print(Align.center(tagline))
        c.print()

        # System info table
        info_table = Table(
            show_header=False,
            box=box.SIMPLE_HEAVY,
            border_style=_DIM_GREEN,
            padding=(0, 2),
            expand=False,
        )
        info_table.add_column("key", style=f"bold {_GREEN}", min_width=20)
        info_table.add_column("value", style=_WHITE)

        info_table.add_row("VERSION", f"v{version}")
        info_table.add_row("ENTROPY SOURCE", seed_method)
        info_table.add_row("AUDIT LOG", log_path)
        info_table.add_row("LISTEN", f"{host}:{port}")
        info_table.add_row("CIPHER", "secp256k1 ECDSA / RFC 6979")
        info_table.add_row("CIRCUIT", "30-qubit H→CNOT→S→H scrambler")
        info_table.add_row("SHOR WINDOW", "> 7 days (key lifetime: 1 hr)")

        boot_panel = Panel(
            Align.center(info_table),
            title=f"[bold {_AMBER}]◈ SYSTEM STATUS ◈[/]",
            border_style=_AMBER,
            box=box.DOUBLE,
            padding=(1, 2),
        )
        c.print(Align.center(boot_panel, width=72))
        c.print()

        # Circuit diagram
        circuit_panel = Panel(
            Text(_CIRCUIT_DIAGRAM, style=f"{_CYAN}"),
            title=f"[bold {_CYAN}]⟨ ENTROPY CIRCUIT ⟩[/]",
            subtitle=f"[{_DIM}]30-qubit entangled scrambler → SHA-256 extraction[/]",
            border_style=_CYAN,
            box=box.ROUNDED,
            padding=(0, 2),
        )
        c.print(Align.center(circuit_panel, width=72))
        c.print()

        # Ready line
        ready = Text("▶ PROTOCOL READY", style=f"bold {_GREEN}")
        c.print(Align.center(ready))
        c.print(Rule(style=_DIM_GREEN))
        c.print()

    # ── 2. SEED DISPLAY ───────────────────────────────────────────

    def show_seed_generating(self, method: str = "OS_URANDOM") -> None:
        """Print a one-line seed generation start notice."""
        if not self.is_active:
            return
        c = self._console

        method_colors = {
            "IBM_QUANTUM": _MAGENTA,
            "AER_SIMULATOR": _CYAN,
            "OS_URANDOM": _GREEN,
        }
        color = method_colors.get(method, _WHITE)

        c.print(
            f"  [{_DIM}]⏳[/] [{color}]Generating quantum seed[/] "
            f"[{_DIM}]([/][bold {color}]{method}[/][{_DIM}])[/]"
        )

    def show_seed_result(self, seed_result: Any) -> None:
        """
        Render a completed seed result in a retro panel.

        Args:
            seed_result: A ``QuantumSeedResult`` (or any object with
                ``.seed_hash``, ``.method``, ``.backend_name``,
                ``.n_qubits``, ``.raw_bitstring``, ``.job_id``,
                ``.timestamp``, ``.circuit_depth`` attributes).
        """
        if not self.is_active:
            return
        c = self._console

        method = getattr(seed_result, "method", "UNKNOWN")
        method_colors = {
            "IBM_QUANTUM": _MAGENTA,
            "AER_SIMULATOR": _CYAN,
            "OS_URANDOM": _GREEN,
        }
        color = method_colors.get(method, _WHITE)

        # Seed info table
        t = Table(
            show_header=False,
            box=box.SIMPLE,
            border_style=_DIM,
            padding=(0, 2),
            expand=True,
        )
        t.add_column("key", style=f"bold {color}", ratio=1)
        t.add_column("value", style=_WHITE, ratio=3)

        seed_hash = getattr(seed_result, "seed_hash", "—")
        t.add_row("SEED HASH", seed_hash)
        t.add_row("METHOD", method)
        t.add_row("BACKEND", getattr(seed_result, "backend_name", "—"))

        n_qubits = getattr(seed_result, "n_qubits", 0)
        if n_qubits > 0:
            t.add_row("QUBITS", str(n_qubits))

        bitstring = getattr(seed_result, "raw_bitstring", None)
        if bitstring:
            display_bits = bitstring[:32] + "…" if len(bitstring) > 32 else bitstring
            t.add_row("BITSTRING", display_bits)

        depth = getattr(seed_result, "circuit_depth", 0)
        if depth > 0:
            t.add_row("CIRCUIT DEPTH", str(depth))

        job_id = getattr(seed_result, "job_id", None)
        if job_id:
            t.add_row("JOB ID", str(job_id))

        ts = getattr(seed_result, "timestamp", None)
        if ts:
            t.add_row("TIMESTAMP", _format_timestamp(ts))

        # IBM quantum gets a special glow
        if method == "IBM_QUANTUM":
            title = f"[bold {_MAGENTA}]⚛ IBM FEZ QUANTUM SEED ⚛[/]"
            border = _MAGENTA
        elif method == "AER_SIMULATOR":
            title = f"[bold {_CYAN}]◈ AER SIMULATOR SEED ◈[/]"
            border = _CYAN
        else:
            title = f"[bold {_GREEN}]● OS_URANDOM SEED ●[/]"
            border = _GREEN

        panel = Panel(
            t,
            title=title,
            border_style=border,
            box=box.HEAVY,
            padding=(0, 1),
        )
        c.print(panel)

    def show_seed_pool_status(self, pool_status: dict) -> None:
        """
        Render a compact seed pool status line.

        Args:
            pool_status: Dict from ``QuantumSeedPool.status()``.
        """
        if not self.is_active or not pool_status:
            return
        c = self._console

        pool_size = pool_status.get("pool_size", 0)
        max_size = pool_status.get("max_pool_size", 10)
        running = pool_status.get("running", False)
        completed = pool_status.get("jobs_completed", 0)
        failed = pool_status.get("jobs_failed", 0)

        # Progress bar
        filled = int((pool_size / max(max_size, 1)) * 20)
        bar = f"[{_GREEN}]{'█' * filled}[/][{_DIM}]{'░' * (20 - filled)}[/]"

        status_color = _GREEN if running else _RED
        status_text = "ACTIVE" if running else "STOPPED"

        c.print(
            f"  [{_AMBER}]SEED POOL[/]  {bar}  "
            f"[{_WHITE}]{pool_size}/{max_size}[/]  "
            f"[{status_color}]{status_text}[/]  "
            f"[{_DIM}]completed={completed} failed={failed}[/]"
        )

    # ── 3. PROTOCOL CYCLE DISPLAY ─────────────────────────────────

    def show_phase(
        self,
        phase: str,
        data: dict,
        signature: dict,
        order_id: Optional[str] = None,
    ) -> None:
        """
        Render a protocol phase result (COMMIT / EXECUTE / SETTLE).

        Args:
            phase: One of ``"COMMIT"``, ``"EXECUTE"``, ``"SETTLE"``.
            data: The phase data dict (commitment / attestation / settlement).
            signature: The ECDSA signature envelope.
            order_id: Override order_id for display (auto-detected if None).
        """
        if not self.is_active:
            return
        c = self._console

        phase_upper = phase.upper()
        phase_config = {
            "COMMIT": {
                "icon": "📋",
                "color": _GREEN,
                "label": "DECISION COMMITMENT",
                "border": _GREEN,
            },
            "EXECUTE": {
                "icon": "⚡",
                "color": _CYAN,
                "label": "EXECUTION ATTESTATION",
                "border": _CYAN,
            },
            "SETTLE": {
                "icon": "🔒",
                "color": _AMBER,
                "label": "SETTLEMENT FINALITY",
                "border": _AMBER,
            },
        }
        cfg = phase_config.get(phase_upper, {
            "icon": "●",
            "color": _WHITE,
            "label": phase_upper,
            "border": _WHITE,
        })

        color = cfg["color"]

        # Build the content table
        t = Table(
            show_header=False,
            box=box.SIMPLE,
            border_style=_DIM,
            padding=(0, 2),
            expand=True,
        )
        t.add_column("key", style=f"bold {color}", ratio=1)
        t.add_column("value", style=_WHITE, ratio=3)

        # Order ID
        oid = order_id or data.get("order_id", "—")
        t.add_row("ORDER", str(oid))

        # Signature fragment
        sig_r = signature.get("r", "")
        sig_s = signature.get("s", "")
        if sig_r:
            t.add_row("SIG.r", _short_hash(sig_r, 16))
        if sig_s:
            t.add_row("SIG.s", _short_hash(sig_s, 16))

        # Public key
        pubkey = signature.get("pubkey", "")
        if pubkey:
            t.add_row("PUBKEY", _short_hash(pubkey, 20))

        # Quantum binding
        seed_commitment = (
            data.get("quantum_seed_commitment")
            or data.get("execution_quantum_seed_commitment")
            or data.get("settlement_quantum_seed_commitment")
            or "—"
        )
        t.add_row("Q-SEED", _short_hash(seed_commitment))

        # Temporal window
        window = data.get("key_temporal_window", {})
        if window:
            created = window.get("created_at", 0)
            expires = window.get("expires_at", 0)
            if created and expires:
                lifetime_min = (expires - created) / 60
                t.add_row(
                    "TEMPORAL",
                    f"{lifetime_min:.0f} min "
                    f"(expires {_format_timestamp(expires)})"
                )

        # Seed method (commitment only)
        method = data.get("seed_measurement_method")
        if method:
            t.add_row("ENTROPY", method)

        # Nonce
        nonce = data.get("nonce") or data.get("nonce_after")
        if nonce is not None:
            t.add_row("NONCE", str(nonce))

        # Trade details (commitment)
        trade = data.get("trade_details")
        if trade:
            parts = []
            if "side" in trade:
                parts.append(trade["side"].upper())
            if "qty" in trade:
                parts.append(str(trade["qty"]))
            if "symbol" in trade:
                parts.append(trade["symbol"])
            if "price" in trade:
                parts.append(f"@ {trade['price']}")
            if parts:
                t.add_row("TRADE", " ".join(parts))

        # Execution result (execute)
        exec_result = data.get("execution_result")
        if exec_result and isinstance(exec_result, dict):
            filled = exec_result.get("filled_qty", "")
            price = exec_result.get("fill_price", "")
            if filled and price:
                t.add_row("FILL", f"{filled} @ {price}")

        # Merkle hash (settlement)
        merkle = data.get("flow_merkle_hash")
        if merkle:
            t.add_row("MERKLE", _short_hash(merkle))

        # Broker sig (settlement)
        broker = data.get("broker_settlement_sig")
        if broker:
            t.add_row("BROKER", str(broker))

        # Account state hash
        state_hash = data.get("account_state_hash") or data.get("new_account_state_hash")
        if state_hash:
            t.add_row("STATE", _short_hash(state_hash))

        panel = Panel(
            t,
            title=f"[bold {color}]{cfg['icon']} {cfg['label']} {cfg['icon']}[/]",
            border_style=cfg["border"],
            box=box.HEAVY,
            padding=(0, 1),
        )
        c.print(panel)

    def show_phase_start(self, phase: str) -> None:
        """Print a one-line phase start notice."""
        if not self.is_active:
            return

        phase_upper = phase.upper()
        icons = {"COMMIT": "📋", "EXECUTE": "⚡", "SETTLE": "🔒"}
        colors = {"COMMIT": _GREEN, "EXECUTE": _CYAN, "SETTLE": _AMBER}
        icon = icons.get(phase_upper, "●")
        color = colors.get(phase_upper, _WHITE)

        self._console.print(
            f"  [{_DIM}]⏳[/] [{color}]{icon} {phase_upper}[/] "
            f"[{_DIM}]signing with ephemeral key…[/]"
        )

    # ── 4. VERIFICATION DISPLAY ───────────────────────────────────

    def show_verification(self, result: dict, order_id: str = "—") -> None:
        """
        Render a verification result from ``AuditVerifier.verify_trade_flow``.

        Args:
            result: Verification result dict with ``chain_valid``, ``quantum_safe``,
                ``details`` list, etc.
            order_id: The order being verified.
        """
        if not self.is_active:
            return
        c = self._console

        chain_valid = result.get("chain_valid", False)
        quantum_safe = result.get("quantum_safe", False)
        valid_color = _GREEN if chain_valid else _RED
        safe_color = _GREEN if quantum_safe else _RED

        t = Table(
            show_header=False,
            box=box.SIMPLE,
            border_style=_DIM,
            padding=(0, 2),
            expand=True,
        )
        t.add_column("key", style=f"bold {_AMBER}", ratio=1)
        t.add_column("value", ratio=3)

        t.add_row("ORDER", order_id)
        t.add_row(
            "CHAIN",
            Text(
                "✓ VALID" if chain_valid else "✗ INVALID",
                style=f"bold {valid_color}",
            ),
        )
        t.add_row(
            "QUANTUM SAFE",
            Text(
                "✓ SAFE" if quantum_safe else "✗ UNSAFE",
                style=f"bold {safe_color}",
            ),
        )

        # Individual checks
        details = result.get("details", [])
        if isinstance(details, list):
            for detail in details:
                is_valid = "True" in str(detail) or "valid" in str(detail).lower()
                detail_color = _GREEN if is_valid else _RED
                icon = "✓" if is_valid else "✗"
                t.add_row("", Text(f"  {icon} {detail}", style=detail_color))

        border_color = _GREEN if (chain_valid and quantum_safe) else _RED
        title_icon = "✓" if (chain_valid and quantum_safe) else "✗"

        panel = Panel(
            t,
            title=f"[bold {border_color}]{title_icon} VERIFICATION RESULT {title_icon}[/]",
            border_style=border_color,
            box=box.DOUBLE,
            padding=(0, 1),
        )
        c.print(panel)

    # ── 5. LIFECYCLE FLOW DISPLAY ─────────────────────────────────

    def show_flow_complete(self, order_id: str) -> None:
        """Print a completion message after all three phases."""
        if not self.is_active:
            return
        c = self._console

        c.print()
        c.print(Rule(
            f"[bold {_AMBER}]◈ TRADE FLOW SEALED ◈ {order_id}[/]",
            style=_AMBER,
        ))
        c.print(
            f"  [{_GREEN}]3 quantum seeds[/] [{_DIM}]|[/] "
            f"[{_GREEN}]3 ephemeral keys destroyed[/] [{_DIM}]|[/] "
            f"[{_GREEN}]3 temporal windows closed[/]"
        )
        c.print()

    # ── 6. GENERIC HELPERS ────────────────────────────────────────

    def status_line(self, message: str, style: str = "info") -> None:
        """Print a styled status line."""
        if not self.is_active:
            return

        style_map = {
            "info": f"{_DIM}",
            "success": f"bold {_GREEN}",
            "warning": f"bold {_AMBER}",
            "error": f"bold {_RED}",
        }
        s = style_map.get(style, _WHITE)
        icons = {
            "info": "ℹ",
            "success": "✓",
            "warning": "⚠",
            "error": "✗",
        }
        icon = icons.get(style, "●")
        self._console.print(f"  [{s}]{icon} {message}[/]")

    def rule(self, title: str = "", style: str = _DIM_GREEN) -> None:
        """Print a horizontal rule."""
        if not self.is_active:
            return
        if title:
            self._console.print(Rule(title, style=style))
        else:
            self._console.print(Rule(style=style))


# ── Module-level singleton ─────────────────────────────────────────
_console_singleton: Optional[AetherConsole] = None


def get_console(quiet: bool = False) -> AetherConsole:
    """
    Return the module-level AetherConsole singleton.

    Args:
        quiet: If True, the console suppresses all output.

    Returns:
        The shared AetherConsole instance.
    """
    global _console_singleton
    if _console_singleton is None:
        _console_singleton = AetherConsole(quiet=quiet)
    return _console_singleton
