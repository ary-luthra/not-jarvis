import atexit
import functools
import signal
import sys
import time

from slack_bolt.adapter.socket_mode import SocketModeHandler

from config import (
    SLACK_APP_TOKEN,
    OPENAI_MODEL,
    app,
    openai_client,
    mrkdwn_converter,
    logger,
)
import datetime

from event_log import event_log
from memory import read_memory
from prompts import SYSTEM_PROMPT_TEMPLATE
from session_manager import session_manager
from tools import TOOLS, handle_function_calls

# Cache bot user ID once at startup instead of calling auth_test() per message.
BOT_USER_ID: str = ""


def _init_bot_user_id():
    global BOT_USER_ID
    BOT_USER_ID = app.client.auth_test()["user_id"]
    logger.info("Bot user ID: %s", BOT_USER_ID)


@functools.lru_cache(maxsize=128)
def get_user_first_name(user_id: str) -> str:
    """Look up a Slack user's first name and return it lowercased."""
    result = app.client.users_info(user=user_id)
    first_name = result["user"]["profile"].get("first_name", "").strip()
    if not first_name:
        # Fall back to display name or real name if first_name is empty
        first_name = (
            result["user"]["profile"].get("display_name")
            or result["user"]["profile"].get("real_name")
            or user_id
        )
    return first_name.lower()


def get_thread_messages(channel: str, thread_ts: str) -> list[dict]:
    """Fetch all messages in a Slack thread to use as conversation history."""
    result = app.client.conversations_replies(channel=channel, ts=thread_ts)
    return result["messages"]


def get_channel_history(channel: str) -> list[dict]:
    """Fetch recent messages from a channel (for unthreaded DM conversations).

    Pulls up to 200 messages (Slack default). The OpenAI Responses API
    handles context truncation if needed — we don't limit artificially.
    """
    result = app.client.conversations_history(channel=channel)
    # conversations_history returns newest first, reverse for chronological order
    messages = result.get("messages", [])
    messages.reverse()
    return messages


def build_openai_messages(thread_messages: list[dict], bot_user_id: str) -> list[dict]:
    """Convert Slack thread messages into OpenAI chat messages."""
    openai_messages = []

    for msg in thread_messages:
        # Skip bot join messages, etc.
        if msg.get("subtype"):
            continue

        text = msg.get("text", "")
        # Strip the bot mention from the text
        text = text.replace(f"<@{bot_user_id}>", "").strip()

        if not text:
            continue

        if msg.get("user") == bot_user_id or msg.get("bot_id"):
            openai_messages.append({"role": "assistant", "content": text})
        else:
            name = get_user_first_name(msg["user"])
            openai_messages.append({"role": "user", "content": f"[{name}]: {text}"})

    return openai_messages


def _get_session_summary() -> str:
    """One-liner summary of tracked sessions so the model knows they exist."""
    sessions = session_manager.list_sessions()
    if not sessions:
        return ""
    parts = [f"{s['id']}({s['status']})" for s in sessions]
    return "Active sessions: " + ", ".join(parts)


def _build_instructions(user_id: str) -> str:
    """Build the system instructions, injecting user memory if available."""
    return SYSTEM_PROMPT_TEMPLATE.render(
        today=datetime.date.today().isoformat(),
        user_memory=read_memory(user_id),
        session_summary=_get_session_summary(),
    )


def chat(messages: list[dict], user_id: str, thread_id: str = None) -> str:
    """Send messages to OpenAI and return the response.

    Uses the Responses API with web search so the model can look up
    current information from the internet when the question needs it.
    The model can also save facts about the user to long-term memory.
    """
    event_log.emit("orchestrator", "chat_start",
                   user_id=user_id, thread_id=thread_id,
                   message_count=len(messages),
                   last_user_message=messages[-1]["content"][:200] if messages else "")

    # The system prompt moves to the top-level `instructions` param.
    # Everything else in the messages list stays in `input`.
    input_messages = []
    for msg in messages:
        if msg["role"] != "system":
            input_messages.append(msg)

    instructions = _build_instructions(user_id)

    kwargs = dict(instructions=instructions, input=input_messages)

    # Handle function calls in a loop until the model produces a final text reply.
    MAX_TURNS = 20
    turn_count = 0
    chat_start = time.time()
    for turn_count in range(1, MAX_TURNS + 1):
        turn_start = time.time()
        response = openai_client.responses.create(
            model=OPENAI_MODEL,
            tools=TOOLS,
            reasoning={"effort": "medium"},
            **kwargs,
        )
        turn_latency = time.time() - turn_start

        # Classify what's in this turn
        item_types = [item.type for item in response.output]
        fn_calls = [
            {"name": item.name, "arguments": item.arguments[:200]}
            for item in response.output if item.type == "function_call"
        ]

        event_log.emit("orchestrator", "agent_turn",
                       turn=turn_count, latency_s=round(turn_latency, 2),
                       item_types=item_types, function_calls=fn_calls,
                       user_id=user_id, thread_id=thread_id)

        # Log non-function-call items (e.g. web searches)
        for item in response.output:
            if item.type == "web_search_call":
                queries = []
                if hasattr(item, "action") and item.action:
                    queries = getattr(item.action, "queries", []) or []
                event_log.emit("orchestrator", "web_search",
                               queries=queries, user_id=user_id)

        # Exit if no more function calls to process
        if not any(item.type == "function_call" for item in response.output):
            break

        tool_outputs = handle_function_calls(response, user_id)

        # Log each tool result
        for output in tool_outputs:
            event_log.emit("orchestrator", "tool_result",
                           call_id=output["call_id"],
                           output_preview=output["output"][:500],
                           user_id=user_id)

        kwargs = dict(previous_response_id=response.id, input=tool_outputs)

    total_latency = time.time() - chat_start

    text = response.output_text
    if not text:
        logger.warning("Agent loop ended with no text output (likely hit MAX_TURNS while still calling tools)")
        text = "Sorry, I wasn't able to finish processing that in time. Could you try again?"

    event_log.emit("orchestrator", "chat_end",
                   user_id=user_id, thread_id=thread_id,
                   turns=turn_count, total_latency_s=round(total_latency, 2),
                   response_preview=text[:300])

    return text


# --- Shutdown ---

def _shutdown(signum=None, frame=None):
    """Clean up running sessions and close event log on exit."""
    logger.info("Shutting down...")
    for sid in list(session_manager.sessions):
        session = session_manager.sessions[sid]
        if session.status == "running":
            logger.info("Terminating session %s", sid)
            session.process.terminate()
    event_log.emit("system", "bot_stop")
    event_log.close()
    sys.exit(0)


# --- Event Handlers ---

@app.event("app_mention")
def handle_mention(event, say):
    """Respond when the bot is @mentioned in a channel."""
    channel = event["channel"]
    thread_ts = event.get("thread_ts", event["ts"])
    username = get_user_first_name(event["user"])

    event_log.emit("system", "user_message",
                   user=username, channel=channel, thread_ts=thread_ts,
                   source="mention",
                   text=event.get("text", "")[:200])

    # Fetch thread history for context
    thread_messages = get_thread_messages(channel, thread_ts)
    openai_messages = build_openai_messages(thread_messages, BOT_USER_ID)

    reply = chat(openai_messages, username, thread_id=thread_ts)
    say(text=mrkdwn_converter.convert(reply), thread_ts=thread_ts)

    event_log.emit("system", "bot_reply",
                   user=username, thread_ts=thread_ts, source="mention",
                   text=reply[:200])


@app.event("message")
def handle_dm(event, say):
    """Respond to direct messages.

    DMs use a linear conversation model (no threads). The bot pulls
    recent channel history as context, like a Telegram-style chat.
    """
    # Only handle DMs (channel type 'im'), ignore other message subtypes
    if event.get("channel_type") != "im" or event.get("subtype"):
        return

    # Don't respond to our own messages
    if event.get("user") == BOT_USER_ID:
        return

    channel = event["channel"]
    username = get_user_first_name(event["user"])

    event_log.emit("system", "user_message",
                   user=username, channel=channel,
                   source="dm",
                   text=event.get("text", "")[:200])

    # Pull recent channel history (linear, no threading)
    dm_messages = get_channel_history(channel)
    openai_messages = build_openai_messages(dm_messages, BOT_USER_ID)

    reply = chat(openai_messages, username, thread_id=channel)
    # Reply at top level — no thread_ts, keeps the DM linear
    say(text=mrkdwn_converter.convert(reply))

    event_log.emit("system", "bot_reply",
                   user=username, source="dm",
                   text=reply[:200])


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    atexit.register(event_log.close)

    _init_bot_user_id()
    event_log.emit("system", "bot_start", model=OPENAI_MODEL)
    logger.info("Starting bot...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
