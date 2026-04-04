"""Live TUI dashboard for not-jarvis.

Tails the JSONL event log and displays:
- Orchestrator pane: conversation flow, agent turns, tool calls
- Sessions pane: Claude Code session grid with live status/output

Run:  python dashboard.py [--log-dir logs]
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, RichLog, Static


def find_latest_log(log_dir: str) -> Path | None:
    """Find the most recently modified .jsonl file in log_dir."""
    log_path = Path(log_dir)
    if not log_path.exists():
        return None
    files = sorted(log_path.glob("events_*.jsonl"), key=os.path.getmtime, reverse=True)
    return files[0] if files else None


def fmt_time(iso_ts: str) -> str:
    """Format ISO timestamp to HH:MM:SS."""
    try:
        dt = datetime.fromisoformat(iso_ts)
        return dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return "??:??:??"


def _format_args(name: str, raw_args: str) -> list[str]:
    """Turn raw JSON tool arguments into readable lines.

    Returns a list of lines to display below the tool name.
    """
    try:
        args = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError:
        return [raw_args] if raw_args else []

    if name == "dispatch_computer_task":
        lines = [args.get("task", "")]
        flags = []
        if args.get("use_browser"):
            flags.append("browser")
        if args.get("isolate"):
            flags.append("isolated")
        if flags:
            lines.append(f"[{', '.join(flags)}]")
        return lines
    if name == "read_task_output":
        return [args.get("session_id", "?")]
    if name == "send_followup_to_task":
        sid = args.get("session_id", "?")
        return [sid, args.get("message", "")]
    if name == "save_memory":
        return [args.get("fact", "")]
    if name == "list_computer_tasks":
        return []

    # Fallback: one line per key
    return [f"{k}: {json.dumps(v)}" for k, v in args.items()]


def _summarize_tool_result(raw: str) -> str:
    """Make tool results more readable."""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            if "message" in data:
                return data["message"]
            if "status" in data:
                parts = []
                if "session_id" in data:
                    parts.append(data["session_id"])
                parts.append(data["status"])
                if "message" in data:
                    parts.append(data["message"])
                return " | ".join(parts)
        return raw
    except (json.JSONDecodeError, TypeError):
        return raw


class SessionPanel(Static):
    """Displays info about a single Claude Code session."""

    def __init__(self, session_id: str, **kwargs):
        super().__init__(**kwargs)
        self.session_id = session_id
        self.task_desc = ""
        self.status = "running"
        self.cost = 0.0
        self.duration = 0
        self.lines: list[str] = []

    def update_display(self):
        status_colors = {"running": "yellow", "done": "green", "failed": "red"}
        color = status_colors.get(self.status, "white")

        # Header line: session ID, status, cost
        header = f"[bold {color}]{self.session_id}[/] [{color}]{self.status}[/]"
        if self.cost > 0:
            header += f"  ${self.cost:.3f}"
        if self.duration > 0:
            header += f"  {self.duration}s"

        parts = [header]

        # Task description on its own line, truncated sensibly
        if self.task_desc:
            desc = self.task_desc[:120]
            parts.append(f"[dim italic]{desc}[/]")

        # Activity log — show last 5 lines
        if self.lines:
            parts.append("")  # spacer
            for line in self.lines[-5:]:
                parts.append(f"  {line}")

        self.update("\n".join(parts))


class Dashboard(App):
    """not-jarvis observability dashboard."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #top-row {
        height: 1fr;
        layout: horizontal;
    }
    #orchestrator-pane {
        width: 3fr;
        border: solid $primary;
        height: 100%;
    }
    #sessions-pane {
        width: 2fr;
        border: solid $secondary;
        height: 100%;
    }
    .pane-title {
        dock: top;
        text-style: bold;
        padding: 0 1;
        background: $surface;
    }
    #orchestrator-log {
        height: 1fr;
    }
    #sessions-container {
        height: 1fr;
        overflow-y: auto;
    }
    SessionPanel {
        height: auto;
        margin: 0 0 1 0;
        padding: 1 1;
        border: round $surface-lighten-2;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("c", "clear_log", "Clear Log"),
    ]

    def __init__(self, log_dir: str = "logs"):
        super().__init__()
        self.log_dir = log_dir
        self.log_file = None
        self.log_handle = None
        self.session_panels: dict[str, SessionPanel] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="top-row"):
            with Vertical(id="orchestrator-pane"):
                yield Static("  Orchestrator", classes="pane-title")
                yield RichLog(id="orchestrator-log", highlight=True, markup=True, wrap=True)
            with Vertical(id="sessions-pane"):
                yield Static("  Sessions", classes="pane-title")
                yield Vertical(id="sessions-container")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "not-jarvis dashboard"
        self._open_log()
        self.set_interval(0.5, self._poll_events)

    def _open_log(self):
        """Open the latest log file for tailing."""
        log_file = find_latest_log(self.log_dir)
        if log_file and log_file != self.log_file:
            if self.log_handle:
                self.log_handle.close()
            self.log_file = log_file
            self.log_handle = open(log_file, "r")
            orch_log = self.query_one("#orchestrator-log", RichLog)
            orch_log.write(f"[dim]Tailing {log_file.name}[/]")

    def _poll_events(self):
        """Read new lines from the log file and process them."""
        latest = find_latest_log(self.log_dir)
        if latest and latest != self.log_file:
            self._open_log()

        if not self.log_handle:
            self._open_log()
            if not self.log_handle:
                return

        for line in self.log_handle.readlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                self._handle_event(event)
            except json.JSONDecodeError:
                continue

    def _handle_event(self, event: dict):
        """Route an event to the right pane."""
        category = event.get("category", "")
        event_type = event.get("event_type", "")
        data = event.get("data", {})
        ts = fmt_time(event.get("timestamp", ""))

        if category == "orchestrator":
            self._handle_orchestrator_event(ts, event_type, data)
        elif category == "session":
            self._handle_session_event(ts, event_type, data)
        elif category == "system":
            self._handle_system_event(ts, event_type, data)

    def _handle_orchestrator_event(self, ts: str, event_type: str, data: dict):
        orch_log = self.query_one("#orchestrator-log", RichLog)

        if event_type == "chat_start":
            # Skip — user_message already shows this
            pass

        elif event_type == "agent_turn":
            turn = data.get("turn", "?")
            latency = data.get("latency_s", 0)
            fn_calls = data.get("function_calls", [])
            item_types = data.get("item_types", [])

            orch_log.write(f"[dim]{ts}[/] Turn {turn} [dim]({latency}s)[/]")

            for fn in fn_calls:
                name = fn.get("name", "?")
                arg_lines = _format_args(name, fn.get("arguments", ""))
                if arg_lines and len(arg_lines) == 1 and len(arg_lines[0]) < 60:
                    # Short args: show inline
                    orch_log.write(f"  [yellow]{name}[/] {arg_lines[0]}")
                elif arg_lines:
                    # Longer args: tool name on its own line, args indented below
                    orch_log.write(f"  [yellow]{name}[/]")
                    for arg_line in arg_lines:
                        orch_log.write(f"    [dim]{arg_line}[/]")
                else:
                    orch_log.write(f"  [yellow]{name}[/]")

            # Show web search on the same turn line, not as separate events
            search_count = item_types.count("web_search_call")
            if search_count:
                orch_log.write(f"  [blue]web search[/] [dim]({search_count} queries)[/]")

        elif event_type == "web_search":
            # Compact: show queries on one line
            queries = data.get("queries", [])
            if queries:
                orch_log.write(f"    [dim blue]{queries[0][:80]}[/]")

        elif event_type == "tool_result":
            preview = _summarize_tool_result(data.get("output_preview", ""))
            # Wrap long results onto multiple indented lines
            if len(preview) > 80:
                orch_log.write(f"  [green]{preview}[/]")
            else:
                orch_log.write(f"  [green]{preview}[/]")

        elif event_type == "chat_end":
            turns = data.get("turns", "?")
            latency = data.get("total_latency_s", 0)
            orch_log.write(f"[bold green]{ts}[/] Done in {turns} turns ({latency}s)")

    def _handle_session_event(self, ts: str, event_type: str, data: dict):
        sid = data.get("session_id", "?")

        if event_type == "session_dispatch":
            panel = SessionPanel(sid, id=f"panel-{sid}")
            panel.task_desc = data.get("task", "")
            panel.status = "running"
            panel.lines.append(f"[dim]{ts}[/] Dispatched")
            if data.get("use_browser"):
                panel.lines.append(f"[dim]{ts}[/] [yellow]Browser enabled[/]")
            self.session_panels[sid] = panel
            container = self.query_one("#sessions-container", Vertical)
            container.mount(panel)
            panel.update_display()

        elif sid in self.session_panels:
            panel = self.session_panels[sid]

            if event_type == "tool_call":
                tool = data.get("tool", "?")
                preview = data.get("input_preview", "")[:50]
                # Shorten file paths to just the filename
                if "/" in preview:
                    preview = "..." + preview.rsplit("/", 1)[-1]
                panel.lines.append(f"[dim]{ts}[/] [yellow]{tool}[/] {preview}")

            elif event_type == "assistant_text":
                text = data.get("text", "")[:80]
                panel.lines.append(f"[dim]{ts}[/] {text}")

            elif event_type == "session_end":
                panel.status = data.get("status", "done")
                panel.cost = data.get("cost", 0.0)
                panel.duration = data.get("duration_s", 0)
                panel.lines.append(f"[dim]{ts}[/] [bold]Finished[/]")

            elif event_type == "session_followup":
                panel.status = "running"
                msg = data.get("message", "")[:60]
                panel.lines.append(f"[dim]{ts}[/] [cyan]Follow-up:[/] {msg}")

            panel.update_display()

    def _handle_system_event(self, ts: str, event_type: str, data: dict):
        orch_log = self.query_one("#orchestrator-log", RichLog)

        if event_type == "user_message":
            user = data.get("user", "?")
            text = data.get("text", "")[:120]
            orch_log.write(f"\n[bold cyan]{ts} {user}:[/] {text}")

        elif event_type == "bot_reply":
            text = data.get("text", "")[:200]
            orch_log.write(f"[bold green]{ts} Bot:[/] {text}")

        elif event_type == "bot_start":
            model = data.get("model", "?")
            orch_log.write(f"[bold]{ts}[/] Bot started [dim](model: {model})[/]")

    def action_clear_log(self):
        orch_log = self.query_one("#orchestrator-log", RichLog)
        orch_log.clear()

    def on_unmount(self):
        if self.log_handle:
            self.log_handle.close()


def main():
    parser = argparse.ArgumentParser(description="not-jarvis dashboard")
    parser.add_argument("--log-dir", default="logs", help="Directory containing event JSONL files")
    args = parser.parse_args()

    dashboard = Dashboard(log_dir=args.log_dir)
    dashboard.run()


if __name__ == "__main__":
    main()
