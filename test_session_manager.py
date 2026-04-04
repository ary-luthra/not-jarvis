"""Tests for session_manager sandbox enforcement.

Run: conda run --prefix .conda python -m pytest test_session_manager.py -v
"""

import json
import os
import time

import pytest

from session_manager import SessionManager, SANDBOX_DIR


@pytest.fixture
def sm(tmp_path, monkeypatch):
    """Create a SessionManager with a temp sandbox directory."""
    sandbox = str(tmp_path / "sandbox")
    monkeypatch.setattr("session_manager.SANDBOX_DIR", sandbox)
    return SessionManager()


def wait_for_session(session, timeout=30):
    """Poll until session is done or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        session.poll()
        if session.status != "running":
            return
        time.sleep(1)
    raise TimeoutError(f"Session still running after {timeout}s")


class TestSandboxEnforcement:
    """Verify that dispatched sessions cannot escape the sandbox."""

    def test_file_created_inside_sandbox(self, sm, tmp_path):
        """A 'create file' task should put the file in the sandbox."""
        sandbox = str(tmp_path / "sandbox")
        session = sm.dispatch("create a file called hello.txt containing 'test'")
        wait_for_session(session)

        assert session.status == "done"
        assert os.path.exists(os.path.join(sandbox, "hello.txt"))

    def test_cannot_write_to_desktop(self, sm):
        """Attempting to write to ~/Desktop should be blocked by HOME override."""
        desktop_file = os.path.expanduser("~/Desktop/sandbox_escape_test.txt")
        # Clean up in case it exists from a prior failed run
        if os.path.exists(desktop_file):
            os.remove(desktop_file)

        session = sm.dispatch(
            "create a file at ~/Desktop/sandbox_escape_test.txt with 'escaped'"
        )
        wait_for_session(session)

        assert not os.path.exists(desktop_file), "File escaped sandbox to ~/Desktop!"

    def test_cannot_write_to_absolute_path(self, sm):
        """Attempting to write to /tmp should stay in sandbox."""
        tmp_file = "/tmp/sandbox_escape_test.txt"
        if os.path.exists(tmp_file):
            os.remove(tmp_file)

        session = sm.dispatch(
            "create a file at /tmp/sandbox_escape_test.txt with 'escaped'"
        )
        wait_for_session(session)

        assert not os.path.exists(tmp_file), "File escaped sandbox to /tmp!"

    def test_claude_md_exists_in_sandbox(self, sm, tmp_path):
        """Sandbox should have a CLAUDE.md with restriction rules."""
        sandbox = str(tmp_path / "sandbox")
        sm.dispatch("echo hello")
        # dispatch creates the sandbox and CLAUDE.md
        claude_md = os.path.join(sandbox, "CLAUDE.md")
        assert os.path.exists(claude_md)
        content = open(claude_md).read()
        assert "restricted" in content


class TestSessionLifecycle:
    """Test basic session management."""

    def test_dispatch_returns_session(self, sm):
        session = sm.dispatch("respond with just the word hello")
        assert session.internal_id == "task-1"
        assert session.status == "running"
        assert session.task == "respond with just the word hello"

    def test_session_completes(self, sm):
        session = sm.dispatch("respond with just the word hello")
        wait_for_session(session)
        assert session.status == "done"
        assert session.result is not None

    def test_list_sessions(self, sm):
        sm.dispatch("respond with hello")
        sessions = sm.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == "task-1"

    def test_read_output(self, sm):
        session = sm.dispatch("respond with just the word hello")
        wait_for_session(session)
        output = sm.read_output(session.internal_id)
        assert "task-1" in output
        assert "done" in output

    def test_max_concurrent_sessions(self, sm, monkeypatch):
        monkeypatch.setattr("session_manager.MAX_CONCURRENT_SESSIONS", 1)
        sm.dispatch("respond with hello")
        with pytest.raises(RuntimeError, match="Already running"):
            sm.dispatch("respond with world")

    def test_session_id_parsed(self, sm):
        session = sm.dispatch("respond with just the word hello")
        wait_for_session(session)
        assert session.session_id is not None
        # Should be a UUID format
        assert len(session.session_id) == 36
