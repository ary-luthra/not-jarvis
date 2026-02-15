import os
from dotenv import load_dotenv
import logging
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from openai import OpenAI
from markdown_to_mrkdwn import SlackMarkdownConverter

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
# Slack tokens
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]  # xapp-... token for Socket Mode

# OpenAI
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    "You are a helpful assistant in a Slack workspace. Be concise and helpful.",
)

# --- Clients ---
app = App(token=SLACK_BOT_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
mrkdwn_converter = SlackMarkdownConverter()


def get_thread_messages(channel: str, thread_ts: str) -> list[dict]:
    """Fetch all messages in a Slack thread to use as conversation history."""
    result = app.client.conversations_replies(channel=channel, ts=thread_ts)
    return result["messages"]


def build_openai_messages(thread_messages: list[dict], bot_user_id: str) -> list[dict]:
    """Convert Slack thread messages into OpenAI chat messages."""
    openai_messages = [{"role": "system", "content": SYSTEM_PROMPT}]

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
            openai_messages.append({"role": "user", "content": text})

    return openai_messages


def chat(messages: list[dict]) -> str:
    """Send messages to OpenAI and return the response.

    Uses the Responses API with web search so the model can look up
    current information from the internet when the question needs it.
    """
    # The system prompt moves to the top-level `instructions` param.
    # Everything else in the messages list stays in `input`.
    system = None
    input_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system = msg["content"]
        else:
            input_messages.append(msg)

    response = openai_client.responses.create(
        model=OPENAI_MODEL,
        instructions=system,
        input=input_messages,
        tools=[{"type": "web_search_preview"}],
    )
    return response.output_text


# --- Event Handlers ---

@app.event("app_mention")
def handle_mention(event, say):
    """Respond when the bot is @mentioned in a channel."""
    channel = event["channel"]
    thread_ts = event.get("thread_ts", event["ts"])
    bot_user_id = app.client.auth_test()["user_id"]

    # Fetch thread history for context
    thread_messages = get_thread_messages(channel, thread_ts)
    openai_messages = build_openai_messages(thread_messages, bot_user_id)

    reply = chat(openai_messages)
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

    thread_messages = get_thread_messages(channel, thread_ts)
    openai_messages = build_openai_messages(thread_messages, bot_user_id)

    reply = chat(openai_messages)
    say(text=mrkdwn_converter.convert(reply), thread_ts=thread_ts)


if __name__ == "__main__":
    logger.info("Starting bot...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
