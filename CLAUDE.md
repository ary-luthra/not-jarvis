# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**not-jarvis** is a personal AI assistant powered by the OpenAI Responses API. It runs as a Slack bot via Socket Mode (no public URL needed), responds to @mentions and DMs, maintains per-thread conversation context, supports per-user long-term memory, and can delegate computer tasks to background Claude Code sessions.

All logic lives in a handful of small modules at the repo root. No subdirectories contain application code.

### Deployment & hardware

The bot runs on a **Mac Mini** connected to a **Reachy Mini** robot. The Reachy provides a voice interface — speech-to-text commands are routed through Slack so that all conversations (voice and text) live in Slack threads and can be continued from either interface. The user can text the bot from away or talk to the Reachy at home.

### Design philosophy: fast orchestrator + background workers

The main agent must respond near-real-time (1-2 seconds) to feel conversational, especially for the Reachy voice interface. To achieve this:

- **Main agent = mouth and brain.** It only has tools that return instantly: memory read/write, web search (hosted by OpenAI), and session management (dispatch/list/read/followup). It never blocks on heavy work.
- **Claude Code sessions = hands.** Anything that takes time (file CRUD, shell commands, browser automation, complex multi-step tasks) is dispatched to background Claude Code subprocesses via `session_manager.py`. These run in a sandboxed directory and their output can be checked later.
- The main agent should **acknowledge a dispatch and move on**, not poll for results. It only checks on a task when the user asks.

## Running

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in SLACK_BOT_TOKEN, SLACK_APP_TOKEN, OPENAI_API_KEY
export $(cat .env | xargs)
python bot.py           # optionally: python bot.py --trace  (enables Opik LLM tracing)
```

Logs `⚡️ Bolt app is running!` when ready. No build step, no test suite — manual testing against a real Slack workspace.

## Architecture

### Data flow

```
Slack event (mention/DM)
  → handle_mention / handle_dm  (bot.py)
    → get_thread_messages()     — fetch full Slack thread
    → build_openai_messages()   — convert to [{role, content}] format
    → chat()                    — core agent loop (see below)
    → mrkdwn_converter.convert() — Markdown → Slack mrkdwn at the edge
  → say(..., thread_ts=...)     — always threaded
```

### Chat loop (`bot.py:chat`)

Uses the **Responses API** (not Chat Completions). The first call sends `instructions` + `input`; subsequent turns use `previous_response_id` (stateful on OpenAI's side) and only send tool outputs. Loops up to `MAX_TURNS=20` processing function calls, then returns `response.output_text`.

### Singletons in `config.py`

All shared clients are initialized once at module level: `app` (Slack Bolt), `openai_client`, `mrkdwn_converter`, `logger`. **Never re-instantiate these** — always import from `config`.

### System prompt (`prompts.py`)

`SYSTEM_PROMPT_TEMPLATE` is a **Jinja2 `Template`**, rendered at runtime with `today` (ISO date) and `user_memory` (string from memory file). It is passed as the `instructions` param to the Responses API.

### Memory (`memory.py`)

File-based per-user memory at `{MEMORY_DIR}/{username}.md`. The username key is the Slack user's **lowercased first name** (not their Slack user ID). `read_memory` returns file contents; `save_memory` appends a bullet. The `memory/` directory is gitignored and auto-created.

### Tool system (`tool_schemas.py` + `tools.py` + `session_manager.py`)

**Schemas and dispatch are split across two files:**
- `tool_schemas.py` — defines all tool schema dicts and the `TOOLS` master list passed to the API.
- `tools.py` — contains `dispatch_function_call` (routing + error handling) and `handle_function_calls` (iterates response items). Re-exports `TOOLS` from `tool_schemas.py` so `bot.py` imports from `tools`.

**Current tools (all return instantly to keep the main agent fast):**
- `web_search_preview` — hosted OpenAI tool for real-time web search
- `save_memory` — persists user facts (backed by `memory.py`)
- `dispatch_computer_task` — spawns a background Claude Code session (backed by `session_manager.py`)
- `list_computer_tasks` — lists all sessions with status
- `read_task_output` — passively reads captured stdout from a session
- `send_followup_to_task` — resumes a completed session with new instructions

**To add a new tool:**
1. Define a schema dict in `tool_schemas.py` following existing patterns.
2. Append it to `TOOLS` in `tool_schemas.py`.
3. Implement the backing logic (new module if needed, imported in `tools.py`).
4. Add a dispatch branch in `dispatch_function_call` in `tools.py`.

### Opik tracing (`config.py` + `bot.py`)

Optional LLM observability via Opik. Enabled only when **both** `--trace` CLI flag is passed **and** `OPIK_API_KEY` is set. When active, the OpenAI client is wrapped with `track_openai` and `chat()` is decorated with `@opik.track`.

## Conventions

- **Responses API, not Chat Completions** — `chat()` uses `openai_client.responses.create()` with `instructions` param for the system prompt.
- **Markdown → mrkdwn only at the edge** — convert immediately before `say()`, never earlier.
- **User identity = lowercased first name** — used as memory file key and in logs.
- **No tests** — manual testing against Slack is the workflow.
