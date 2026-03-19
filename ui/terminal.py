"""
AetherCloud-L — Retro Terminal Interface
Dark background, cyan/amber/green semantic colors.
Aether Systems LLC — Patent Pending
"""

import shlex
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt
from rich import box

from config.settings import APP_NAME, APP_VERSION, APP_BANNER
from auth.login import AetherCloudAuth
from auth.session import SessionManager
from vault.filebase import AetherVault
from agent.file_agent import AetherFileAgent


class AetherCloudTerminal:
    """
    Retro terminal interface for AetherCloud-L.
    Rich-based CLI with Aether aesthetic styling.
    """

    STYLE_HEADER = "bold cyan"
    STYLE_SUCCESS = "bold green"
    STYLE_ERROR = "bold red"
    STYLE_WARNING = "bold yellow"
    STYLE_INFO = "cyan"
    STYLE_MUTED = "dim white"
    STYLE_ACCENT = "bold magenta"

    COMMANDS = {
        "login": "Authenticate with AetherCloud-L",
        "logout": "End current session",
        "ls": "List files in vault [path]",
        "audit": "Show audit trail [path]",
        "organize": "Run AI organization [--dry-run]",
        "chat": "Ask the AI agent a question",
        "rename": "Get AI name suggestion for a file",
        "move": "Move a file with audit log",
        "status": "Show vault stats + Protocol-L status",
        "help": "Show available commands",
        "exit": "Exit AetherCloud-L",
    }

    def __init__(
        self,
        vault_root: Optional[str] = None,
        config_path: Optional[str] = None,
    ):
        self.console = Console()
        self._auth = AetherCloudAuth(config_path=config_path)
        self._session_token: Optional[str] = None
        self._vault: Optional[AetherVault] = None
        self._agent: Optional[AetherFileAgent] = None
        self._vault_root = vault_root
        self._running = False

    def _ensure_authenticated(self) -> bool:
        """Check if user is authenticated."""
        if self._session_token and self._auth.verify_session(self._session_token):
            return True
        self.console.print("[red]Not authenticated. Please login first.[/red]")
        return False

    def _boot_sequence(self) -> None:
        """Display boot sequence on launch."""
        self.console.print(
            Panel(
                APP_BANNER.strip(),
                border_style="cyan",
                box=box.DOUBLE,
            )
        )
        self.console.print(
            f"  [cyan]Protocol-L[/cyan]  [green]LOADED[/green]  │  "
            f"SHA-256 commitment layer active",
            style=self.STYLE_MUTED,
        )
        self.console.print(
            f"  [cyan]Timestamp[/cyan]   {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
            style=self.STYLE_MUTED,
        )
        self.console.print()

    def run(self) -> None:
        """Main run loop."""
        self._running = True
        self._boot_sequence()

        self.console.print(
            "[yellow]Please login to continue.[/yellow]\n"
        )

        while self._running:
            try:
                prompt_text = (
                    "[cyan]aether[/cyan]:[green]cloud[/green]> "
                    if self._session_token
                    else "[dim]aether:cloud>[/dim] "
                )
                raw = Prompt.ask(prompt_text, console=self.console, default="")
                if not raw.strip():
                    continue
                self._dispatch(raw.strip())
            except KeyboardInterrupt:
                self.console.print("\n[yellow]Use 'exit' to quit.[/yellow]")
            except EOFError:
                self._running = False

        self.console.print(
            "\n[cyan]AetherCloud-L terminated. Audit trail preserved.[/cyan]"
        )

    def _dispatch(self, raw_input: str) -> None:
        """Parse and dispatch a command."""
        try:
            parts = shlex.split(raw_input)
        except ValueError:
            parts = raw_input.split()

        if not parts:
            return

        cmd = parts[0].lower()
        args = parts[1:]

        handler = {
            "login": self._cmd_login,
            "logout": self._cmd_logout,
            "ls": self._cmd_ls,
            "audit": self._cmd_audit,
            "organize": self._cmd_organize,
            "chat": self._cmd_chat,
            "rename": self._cmd_rename,
            "move": self._cmd_move,
            "status": self._cmd_status,
            "help": self._cmd_help,
            "exit": self._cmd_exit,
            "quit": self._cmd_exit,
        }.get(cmd)

        if handler:
            handler(args)
        else:
            self.console.print(
                f"[red]Unknown command: {cmd}[/red] — type 'help' for commands"
            )

    def _cmd_login(self, args: list[str]) -> None:
        """Handle login command."""
        username = Prompt.ask("[cyan]Username[/cyan]", console=self.console)
        from rich.prompt import Prompt as RichPrompt
        password = Prompt.ask(
            "[cyan]Password[/cyan]", console=self.console, password=True
        )

        result = self._auth.login(username, password)

        if result["authenticated"]:
            self._session_token = result["session_token"]
            # Initialize vault
            vault_root = self._vault_root or str(
                Path.home() / "AetherVault"
            )
            self._vault = AetherVault(vault_root, self._session_token)
            self._agent = AetherFileAgent(self._vault)

            self.console.print(
                f"\n[green]✓ Authenticated as {username}[/green]"
            )
            self.console.print(
                f"  [dim]Audit ID: {result['audit_id']}[/dim]"
            )
            self.console.print(
                f"  [dim]Commitment: {result['commitment_hash'][:24]}...[/dim]"
            )
            self.console.print(
                f"  [dim]Vault: {vault_root}[/dim]\n"
            )
        else:
            self.console.print(
                f"\n[red]✗ Authentication failed[/red]"
            )
            self.console.print(
                f"  [dim]Audit ID: {result['audit_id']} (logged)[/dim]\n"
            )

    def _cmd_logout(self, args: list[str]) -> None:
        """Handle logout command."""
        if not self._ensure_authenticated():
            return
        result = self._auth.logout(self._session_token)
        self._session_token = None
        self._vault = None
        self._agent = None
        self.console.print(
            f"[green]✓ Logged out[/green]  "
            f"[dim]Commitment: {result['commitment_hash'][:24]}...[/dim]"
        )

    def _cmd_ls(self, args: list[str]) -> None:
        """Handle ls command."""
        if not self._ensure_authenticated():
            return

        path = args[0] if args else None
        recursive = "--recursive" in args or "-r" in args

        files = self._vault.list_files(path=path, recursive=recursive)

        if not files:
            self.console.print("[dim]No files found.[/dim]")
            return

        table = Table(
            title="Vault Contents",
            box=box.SIMPLE_HEAVY,
            border_style="cyan",
        )
        table.add_column("Name", style="green")
        table.add_column("Size", justify="right", style="yellow")
        table.add_column("Modified", style="dim")
        table.add_column("Type", style="cyan")

        for f in files:
            size = f"{f['size'] / 1024:.1f} KB" if not f.get("is_dir") else "DIR"
            mtime = time.strftime(
                "%Y-%m-%d %H:%M",
                time.localtime(f.get("modified", 0))
            )
            ftype = "DIR" if f.get("is_dir") else Path(f["name"]).suffix
            table.add_row(f["name"], size, mtime, ftype)

        self.console.print(table)

    def _cmd_audit(self, args: list[str]) -> None:
        """Handle audit command."""
        if not self._ensure_authenticated():
            return

        path = args[0] if args else None
        trail = self._vault.get_audit_trail(path=path, limit=20)

        if not trail:
            self.console.print("[dim]No audit entries found.[/dim]")
            return

        table = Table(
            title="Audit Trail",
            box=box.SIMPLE_HEAVY,
            border_style="yellow",
        )
        table.add_column("Event", style="cyan")
        table.add_column("Details", style="white")
        table.add_column("Time", style="dim")

        for entry in trail:
            data = entry.get("data", {}).get("trade_details", {})
            event = data.get("event_type", "UNKNOWN")
            details = data.get("path", data.get("username", "—"))
            ts = data.get("timestamp", "")
            if isinstance(ts, (int, float)):
                ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
            table.add_row(event, str(details), str(ts))

        self.console.print(table)

    def _cmd_organize(self, args: list[str]) -> None:
        """Handle organize command."""
        if not self._ensure_authenticated():
            return

        dry_run = "--dry-run" in args or not args
        self.console.print(
            f"[cyan]Running AI organization "
            f"{'(dry run)' if dry_run else '(LIVE)'}...[/cyan]"
        )

        suggestions = self._agent.organize_vault(dry_run=dry_run)

        if not suggestions:
            self.console.print("[green]Vault is well-organized.[/green]")
            return

        table = Table(
            title="Organization Suggestions",
            box=box.SIMPLE_HEAVY,
            border_style="magenta",
        )
        table.add_column("Current", style="white")
        table.add_column("Suggested", style="green")
        table.add_column("Category", style="cyan")
        table.add_column("Confidence", justify="right", style="yellow")

        for s in suggestions[:20]:
            table.add_row(
                s["current_name"],
                s["suggested_name"],
                s.get("category", "—"),
                f"{s.get('confidence', 0):.0%}",
            )

        self.console.print(table)

    def _cmd_chat(self, args: list[str]) -> None:
        """Handle chat command."""
        if not self._ensure_authenticated():
            return

        query = " ".join(args) if args else Prompt.ask(
            "[cyan]Ask[/cyan]", console=self.console
        )
        response = self._agent.chat(query)
        self.console.print(f"\n[green]{response}[/green]\n")

    def _cmd_rename(self, args: list[str]) -> None:
        """Handle rename command."""
        if not self._ensure_authenticated():
            return

        if not args:
            self.console.print("[red]Usage: rename <filepath>[/red]")
            return

        path = args[0]
        suggested = self._agent.suggest_name(
            str(self._vault.root / path)
        )
        self.console.print(
            f"  Current:   [white]{Path(path).name}[/white]"
        )
        self.console.print(
            f"  Suggested: [green]{suggested}[/green]"
        )

        confirm = Prompt.ask(
            "[yellow]Apply rename?[/yellow]",
            choices=["y", "n"],
            default="n",
            console=self.console,
        )
        if confirm == "y":
            result = self._vault.rename_file(path, suggested)
            self.console.print(
                f"[green]✓ Renamed[/green]  "
                f"[dim]Commitment: {result['commitment_hash'][:24]}...[/dim]"
            )

    def _cmd_move(self, args: list[str]) -> None:
        """Handle move command."""
        if not self._ensure_authenticated():
            return

        if len(args) < 2:
            self.console.print("[red]Usage: move <source> <destination>[/red]")
            return

        source, dest = args[0], args[1]
        result = self._vault.move_file(source, dest)
        self.console.print(
            f"[green]✓ Moved {source} → {dest}[/green]  "
            f"[dim]Commitment: {result['commitment_hash'][:24]}...[/dim]"
        )

    def _cmd_status(self, args: list[str]) -> None:
        """Handle status command."""
        if not self._ensure_authenticated():
            return

        stats = self._vault.get_stats()

        panel_content = (
            f"[cyan]Vault Root:[/cyan]    {stats['vault_root']}\n"
            f"[cyan]Files:[/cyan]         {stats['file_count']}\n"
            f"[cyan]Total Size:[/cyan]    {stats['total_size_mb']} MB\n"
            f"[cyan]Protocol-L:[/cyan]    [green]ACTIVE[/green] — SHA-256 commitment layer\n"
            f"[cyan]Session:[/cyan]       [green]VALID[/green]\n"
            f"[cyan]Watcher:[/cyan]       [green]MONITORING[/green]\n"
            f"[cyan]AI Agent:[/cyan]      [green]READY[/green] (Qwen 2.5)\n"
            f"[cyan]Timestamp:[/cyan]     {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
        )

        self.console.print(
            Panel(
                panel_content,
                title="[bold cyan]AetherCloud-L Status[/bold cyan]",
                border_style="cyan",
                box=box.DOUBLE,
            )
        )

    def _cmd_help(self, args: list[str]) -> None:
        """Handle help command."""
        table = Table(
            title="AetherCloud-L Commands",
            box=box.SIMPLE_HEAVY,
            border_style="cyan",
        )
        table.add_column("Command", style="green")
        table.add_column("Description", style="white")

        for cmd, desc in self.COMMANDS.items():
            table.add_row(cmd, desc)

        self.console.print(table)

    def _cmd_exit(self, args: list[str]) -> None:
        """Handle exit command."""
        if self._session_token:
            self._cmd_logout([])
        self._running = False

    @staticmethod
    def parse_command(raw: str) -> tuple[str, list[str]]:
        """Parse a raw command string into command and arguments."""
        try:
            parts = shlex.split(raw)
        except ValueError:
            parts = raw.split()
        if not parts:
            return "", []
        return parts[0].lower(), parts[1:]
