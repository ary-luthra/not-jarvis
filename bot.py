import argparse
import functools
import os
import sys

# --- CLI flags must be parsed before any local imports so that env vars are
#     set before config.py (and its module-level side-effects) are executed. ---
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="not-jarvis Slack bot")
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Enable Opik LLM call tracing (requires OPIK_API_KEY to be set)",
    )
    # parse_known_args so that Slack Bolt / pytest flags don't cause errors
    args, _ = parser.parse_known_args()
    return args

_args = _parse_args()
if _args.trace:
    os.environ["OPIK_TRACING_ENABLED"] = "1"

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

from memory import read_memory
from prompts import SYSTEM_PROMPT_TEMPLATE
from tools import TOOLS, handle_function_calls


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


def _build_instructions(user_id: str) -> str:
    """Build the system instructions, injecting user memory if available."""
    return SYSTEM_PROMPT_TEMPLATE.render(
        today=datetime.date.today().isoformat(),
        user_memory=read_memory(user_id),
    )


def chat(messages: list[dict], user_id: str) -> str:
    """Send messages to OpenAI and return the response.

    Uses the Responses API with web search so the model can look up
    current information from the internet when the question needs it.
    The model can also save facts about the user to long-term memory.
    """
    # The system prompt moves to the top-level `instructions` param.
    # Everything else in the messages list stays in `input`.
    input_messages = []
    for msg in messages:
        if msg["role"] != "system":
            input_messages.append(msg)

    instructions = _build_instructions(user_id)

    response = openai_client.responses.create(
        model=OPENAI_MODEL,
        instructions=instructions,
        input=input_messages,
        tools=TOOLS,
    )

    # Handle function calls in a loop until the model produces a final text reply.
    while any(item.type == "function_call" for item in response.output):
        tool_outputs = handle_function_calls(response, user_id)

        # Log non-function-call items (e.g. web searches) as they happen.
        for item in response.output:
            if item.type in ("message", "function_call"):
                continue
            logger.info("Tool call: %s | Params: %s", item.type, item.model_dump_json())

        response = openai_client.responses.create(
            model=OPENAI_MODEL,
            previous_response_id=response.id,
            input=tool_outputs,
            tools=TOOLS,
        )

    # Log any remaining tool calls from the final response.
    for item in response.output:
        if item.type == "message":
            continue
        logger.info("Tool call: %s | Params: %s", item.type, item.model_dump_json())

    return response.output_text


# --- Event Handlers ---

@app.event("app_mention")
def handle_mention(event, say):
    """Respond when the bot is @mentioned in a channel."""
    channel = event["channel"]
    thread_ts = event.get("thread_ts", event["ts"])
    username = get_user_first_name(event["user"])
    bot_user_id = app.client.auth_test()["user_id"]

    # Fetch thread history for context
    thread_messages = get_thread_messages(channel, thread_ts)
    openai_messages = build_openai_messages(thread_messages, bot_user_id)

    reply = chat(openai_messages, username)
    say(text=mrkdwn_converter.convert(reply), thread_ts=thread_ts)


@app.event("message")
def handle_dm(event, say):
    """Respond to direct messages."""
    # Only handle DMs (channel type 'im'), ignore other message subtypes
    if event.get("channel_type") != "im" or event.get("subtype"):
        return

    bot_user_id = app.client.auth_test()["user_id"]
    # Don't respond to our own messages
    if event.get("user") == bot_user_id:
        return

    channel = event["channel"]
    thread_ts = event.get("thread_ts", event["ts"])
    username = get_user_first_name(event["user"])

    thread_messages = get_thread_messages(channel, thread_ts)
    openai_messages = build_openai_messages(thread_messages, bot_user_id)

    reply = chat(openai_messages, username)
    say(text=mrkdwn_converter.convert(reply), thread_ts=thread_ts)


if __name__ == "__main__":
    logger.info("Starting bot... (tracing=%s)", _args.trace)
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
