# CLAUDE.md

This file provides guidance for AI assistants working on the **not-jarvis** codebase.

## Project Overview

**not-jarvis** is a Slack bot that uses the OpenAI Responses API to answer messages. It runs via Slack Socket Mode (no public URL needed), responds to @mentions in channels and direct messages, maintains per-thread conversation context, and supports long-term per-user memory.

## Repository Structure

```
not-jarvis/
├── bot.py           # Entry point, event handlers, and chat orchestration
├── config.py        # Environment variable loading, client initialization
├── memory.py        # File-based per-user memory (read/write)
├── prompts.py       # Default system prompt string
├── tools.py         # OpenAI tool schemas and function-call dispatch
├── requirements.txt # Python dependencies
├── .env.example     # Template for required environment variables
├── .gitignore       # Excludes .env, memory/, __pycache__, .venv, .claude
└── README.md        # Setup and usage guide
```

There are no subdirectories with application code. All logic lives in five small modules (~308 lines total).

## Technology Stack

- **Language**: Python 3.x
- **Slack integration**: `slack-bolt` (Socket Mode via WebSocket)
- **AI backend**: OpenAI Responses API (not Chat Completions) — `openai>=1.0.0`
- **Markdown rendering**: `markdown_to_mrkdwn` — converts standard Markdown to Slack's mrkdwn format
- **Config**: `python-dotenv` (loaded in `config.py` via `load_dotenv()`)

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SLACK_BOT_TOKEN` | Yes | — | `xoxb-...` OAuth bot token |
| `SLACK_APP_TOKEN` | Yes | — | `xapp-...` Socket Mode app-level token |
| `OPENAI_API_KEY` | Yes | — | OpenAI API key |
| `OPENAI_MODEL` | No | `gpt-4o` | OpenAI model to use |
| `SYSTEM_PROMPT` | No | (see `prompts.py`) | Override the default system prompt entirely |
| `MEMORY_DIR` | No | `memory/` | Directory for user memory files |

Copy `.env.example` to `.env` and fill in values. The `.env` file is gitignored.

## Running the Bot

```bash
pip install -r requirements.txt
export $(cat .env | xargs)
python bot.py
```

The bot connects via WebSocket and logs `⚡️ Bolt app is running!` when ready. There is no Makefile, build step, or daemon wrapper — it runs as a foreground Python process.

## Module Responsibilities

### `config.py`
Loads `.env`, initializes all shared singletons, and exports them for other modules to import:
- `app` — Slack Bolt `App` instance
- `openai_client` — OpenAI `OpenAI` client
- `mrkdwn_converter` — `SlackMarkdownConverter` instance
- `logger` — standard Python logger named `"bot"`
- All environment variable constants (`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `SYSTEM_PROMPT_OVERRIDE`)

Always import shared clients from `config` rather than re-instantiating them.

### `prompts.py`
Exports a single string `SYSTEM_PROMPT`. This is the default personality and behavioral instruction for the bot. It instructs the model to:
- Reply with standard Markdown formatting
- Use `save_memory` to persist user facts selectively
- Incorporate the `## User Memory` section (injected at runtime) when personalizing replies

### `memory.py`
File-based per-user memory. Each user gets a Markdown file at `memory/{username}.md`. The `username` key is the user's Slack first name, lowercased (see `get_user_first_name` in `bot.py`).

- `read_memory(user_id)` — returns file contents as a string, or `""` if no file exists
- `save_memory(user_id, fact)` — creates the file with a header if needed, then appends `- {fact}`

The `memory/` directory is gitignored and must be created at runtime (done automatically by `save_memory`).

### `tools.py`
Defines OpenAI tool schemas and dispatches function calls:

- `TOOLS` — list passed as the `tools` argument to every Responses API call. Currently contains:
  - `{"type": "web_search_preview"}` — hosted OpenAI tool for real-time web search
  - `SAVE_MEMORY_TOOL` — function tool that calls `save_memory`
- `dispatch_function_call(name, arguments, username)` — routes by tool name, returns a result string
- `handle_function_calls(response, username)` — iterates over `response.output`, calls `dispatch_function_call` for each `function_call` item, returns a list of `function_call_output` dicts

**To add a new tool**: add a schema dict to `TOOLS` and add a matching branch in `dispatch_function_call`.

### `bot.py`
Main module. Contains:

- `get_user_first_name(user_id)` — Calls `users_info`, falls back through display name → real name → user_id
- `get_thread_messages(channel, thread_ts)` — Calls `conversations_replies` to fetch full thread
- `build_openai_messages(thread_messages, bot_user_id)` — Converts Slack messages to `[{role, content}]` format; strips `<@BOT_ID>` mentions; skips messages with a `subtype`
- `_build_instructions(user_id)` — Returns system prompt with user memory appended under `## User Memory` if memory exists
- `chat(messages, user_id)` — Core AI loop (see below)
- `handle_mention` — `@app.event("app_mention")` handler
- `handle_dm` — `@app.event("message")` handler; only processes `channel_type == "im"` events

## Chat Loop (key logic)

```
openai_client.responses.create(model, instructions, input, tools)
    → response

while response.output contains function_call items:
    tool_outputs = handle_function_calls(response, username)
    log non-message, non-function_call items (e.g. web_search steps)
    response = openai_client.responses.create(
        model, previous_response_id=response.id, input=tool_outputs, tools
    )

return response.output_text
```

The OpenAI Responses API is stateful via `previous_response_id` — function call continuation does not re-send the full message history. Only the initial call sends `instructions` and `input`.

## Conventions

- **No re-initialization**: All clients live in `config.py`. Never create a second `App`, `OpenAI`, or `SlackMarkdownConverter`.
- **System prompt in `instructions`**: `chat()` strips the `system` role message from the input list and passes it as the top-level `instructions` param — that's how the Responses API expects it.
- **User identity key**: Memory files and logs use the lowercased first name (or display/real name fallback). This is not the Slack user ID.
- **Markdown → mrkdwn at the edge**: All Slack replies go through `mrkdwn_converter.convert()` immediately before `say()`. Do not convert earlier in the pipeline.
- **Replies are always threaded**: Both handlers call `say(..., thread_ts=thread_ts)`.
- **No error handling**: The codebase intentionally has no try/except. Exceptions surface to Slack Bolt's default handler. Do not add defensive catches unless implementing a specific recovery behavior.
- **No tests**: There is no test suite. Manual testing against a real Slack workspace is the expected workflow.

## Adding a New Function Tool

1. Define a schema dict following the `SAVE_MEMORY_TOOL` pattern in `tools.py`.
2. Append it to the `TOOLS` list in `tools.py`.
3. Add a named branch in `dispatch_function_call` that executes the logic and returns a string result.
4. If the tool needs a new module, import it in `tools.py` (not in `bot.py`).

## Slack App Requirements

The Slack app must have these **Bot Token Scopes**:
`app_mentions:read`, `chat:write`, `channels:history`, `groups:history`, `im:history`, `im:read`, `im:write`

And must subscribe to these **bot events**:
`app_mention`, `message.im`

Socket Mode must be enabled, and an app-level token with `connections:write` scope is required for `SLACK_APP_TOKEN`.
