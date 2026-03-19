"""
AetherCloud-L — Textual TUI Dashboard (Phase 2)
Real-time vault visualization with file tree, audit trail, and AI chat.
Aether Systems LLC — Patent Pending
"""

import json
import time
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Static, Input, Tree, RichLog
from textual.binding import Binding
from textual import on


DASHBOARD_CSS = """
Screen {
    background: #0a0a1a;
}

#header-bar {
    background: #1a1a2e;
    color: #00ccff;
    height: 3;
    content-align: center middle;
    text-style: bold;
}

#main-area {
    height: 1fr;
}

#file-panel {
    width: 1fr;
    border: solid #00ccff;
    background: #0a0a1a;
}

#file-panel-title {
    color: #ffaa00;
    text-style: bold;
    height: 1;
    padding: 0 1;
}

#file-tree {
    color: #00ccff;
    background: #0a0a1a;
}

#audit-panel {
    width: 2fr;
    border: solid #00ccff;
    background: #0a0a1a;
}

#audit-panel-title {
    color: #ffaa00;
    text-style: bold;
    height: 1;
    padding: 0 1;
}

#audit-log {
    color: #cccccc;
    background: #0a0a1a;
}

#agent-panel {
    width: 1fr;
    border: solid #00ccff;
    background: #0a0a1a;
}

#agent-panel-title {
    color: #ffaa00;
    text-style: bold;
    height: 1;
    padding: 0 1;
}

#agent-output {
    color: #cccccc;
    background: #0a0a1a;
    height: 1fr;
}

#agent-input {
    color: #ffaa00;
    background: #111122;
    border: solid #00ccff;
    height: 3;
}

#status-bar {
    background: #1a1a2e;
    color: #888888;
    height: 1;
    padding: 0 1;
}

.threat-none    { color: #00ff88; }
.threat-low     { color: #ffff00; }
.threat-medium  { color: #ffaa00; }
.threat-high    { color: #ff3333; text-style: bold; }
"""


class AetherDashboard(App):
    """
    Phase 2 TUI dashboard for AetherCloud-L.
    Real-time vault visualization with:
      - Live file tree (left panel)
      - Live audit trail (center panel)
      - AI agent chat (right panel)
    """

    CSS = DASHBOARD_CSS

    TITLE = "AetherCloud-L Dashboard"
    SUB_TITLE = "Quantum-Secured File Intelligence"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("s", "scan", "Security Scan"),
        Binding("o", "organize", "Organize"),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(
        self,
        vault=None,
        agent=None,
        watcher=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._vault = vault
        self._agent = agent
        self._watcher = watcher

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-area"):
            # Left: File Tree
            with Vertical(id="file-panel"):
                yield Static("📁 FILE TREE", id="file-panel-title")
                yield Tree("Vault", id="file-tree")

            # Center: Audit Trail
            with Vertical(id="audit-panel"):
                yield Static("🔒 AUDIT TRAIL", id="audit-panel-title")
                yield RichLog(id="audit-log", highlight=True, markup=True)

            # Right: Agent Chat
            with Vertical(id="agent-panel"):
                yield Static("🤖 AI AGENT", id="agent-panel-title")
                yield RichLog(id="agent-output", highlight=True, markup=True)
                yield Input(
                    placeholder="> Ask the agent...",
                    id="agent-input",
                )
        yield Footer()

    def on_mount(self) -> None:
        """Start live update timers."""
        self.refresh_tree()
        self.refresh_audit()

        self.set_interval(10, self.refresh_tree)
        self.set_interval(3, self.refresh_audit)

        # Welcome message in agent panel
        agent_log = self.query_one("#agent-output", RichLog)
        agent_log.write("[bold cyan]AetherCloud-L AI Agent[/bold cyan]")
        agent_log.write("Type a question below and press Enter.")
        agent_log.write("")

    def refresh_tree(self) -> None:
        """Refresh file tree from vault."""
        if not self._vault:
            return

        try:
            tree = self.query_one("#file-tree", Tree)
            tree.clear()
            tree.root.expand()

            files = self._vault.list_files(recursive=True)
            for f in files:
                label = f"📁 {f['name']}" if f.get("is_dir") else f"📄 {f['name']}"
                tree.root.add_leaf(label)
        except Exception:
            pass

    def refresh_audit(self) -> None:
        """Pull latest audit events and display."""
        if not self._vault:
            return

        try:
            audit_log = self.query_one("#audit-log", RichLog)
            trail = self._vault.get_audit_trail(limit=5)

            for entry in trail:
                data = entry.get("data", {}).get("trade_details", {})
                event_type = data.get("event_type", "UNKNOWN")
                path = data.get("path", data.get("username", "—"))
                ts = data.get("timestamp", "")
                if isinstance(ts, (int, float)):
                    ts = time.strftime("%H:%M:%S", time.localtime(ts))

                if "UNAUTHORIZED" in event_type:
                    audit_log.write(
                        f"[bold red]⚠ {event_type}[/bold red] {path} @ {ts}"
                    )
                else:
                    audit_log.write(
                        f"[green]{event_type}[/green] {path} @ {ts}"
                    )
        except Exception:
            pass

    @on(Input.Submitted, "#agent-input")
    def on_agent_input(self, event: Input.Submitted) -> None:
        """Handle agent chat input."""
        query = event.value.strip()
        if not query:
            return

        agent_input = self.query_one("#agent-input", Input)
        agent_input.value = ""

        agent_output = self.query_one("#agent-output", RichLog)
        agent_output.write(f"[bold yellow]> {query}[/bold yellow]")

        if self._agent:
            try:
                response = self._agent.chat(query)
                agent_output.write(f"[white]{response}[/white]")
            except Exception as e:
                agent_output.write(f"[red]Error: {e}[/red]")
        else:
            agent_output.write("[red]Agent not available. Login required.[/red]")

        agent_output.write("")

    def action_refresh(self) -> None:
        """Refresh all panels."""
        self.refresh_tree()
        self.refresh_audit()

    def action_scan(self) -> None:
        """Run security scan and display result."""
        if not self._agent:
            return

        agent_output = self.query_one("#agent-output", RichLog)
        agent_output.write("[bold cyan]Running security scan...[/bold cyan]")

        try:
            result = self._agent.security_scan()
            threat = result.get("threat_level", "UNKNOWN")

            color_map = {
                "NONE": "green",
                "LOW": "yellow",
                "MEDIUM": "dark_orange",
                "HIGH": "red",
            }
            color = color_map.get(threat, "white")

            agent_output.write(f"[bold {color}]Threat Level: {threat}[/bold {color}]")
            for finding in result.get("findings", []):
                agent_output.write(f"  • {finding}")
            agent_output.write(
                f"[yellow]Action: {result.get('recommended_action', 'None')}[/yellow]"
            )
        except Exception as e:
            agent_output.write(f"[red]Scan failed: {e}[/red]")

        agent_output.write("")

    def action_organize(self) -> None:
        """Run vault organization (dry run)."""
        if not self._agent:
            return

        agent_output = self.query_one("#agent-output", RichLog)
        agent_output.write("[bold cyan]Running vault organization (dry run)...[/bold cyan]")

        try:
            suggestions = self._agent.organize_vault(dry_run=True)
            if not suggestions:
                agent_output.write("[green]Vault is well-organized.[/green]")
            else:
                for s in suggestions[:10]:
                    agent_output.write(
                        f"  {s['current_name']} → {s['suggested_name']} "
                        f"[{s.get('category', '?')}]"
                    )
        except Exception as e:
            agent_output.write(f"[red]Organization failed: {e}[/red]")

        agent_output.write("")


def launch_dashboard(vault=None, agent=None, watcher=None) -> None:
    """Launch the Textual dashboard."""
    app = AetherDashboard(vault=vault, agent=agent, watcher=watcher)
    app.run()
