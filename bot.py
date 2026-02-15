import os
import logging
from dotenv import load_dotenv
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
    "You are a helpful assistant in a Slack workspace. Be concise and helpful. "
    "Always format your responses using standard Markdown syntax "
    "(e.g. **bold**, *italic*, [links](url), - bullet lists, ```code blocks```).",
)

# --- Clients ---
app = App(token=SLACK_BOT_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
mrkdwn_converter = SlackMarkdownConverter()
BOT_USER_ID = app.client.auth_test()["user_id"]


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
    response = openai_client.responses.create(
        model=OPENAI_MODEL,
        instructions=messages[0]["content"],
        input=messages[1:],
        tools=[{"type": "web_search_preview"}],
    )

    for item in response.output:
        if item.type == "message":
            continue
        logger.info("Tool call: %s | Params: %s", item.type, item.model_dump_json())

    return response.output_text


# --- Event Handlers ---


def reply_in_thread(event, say):
    """Shared logic: fetch thread context, call OpenAI, and reply."""
    channel = event["channel"]
    thread_ts = event.get("thread_ts", event["ts"])

    thread_messages = get_thread_messages(channel, thread_ts)
    openai_messages = build_openai_messages(thread_messages, BOT_USER_ID)

    reply = chat(openai_messages)
    say(text=mrkdwn_converter.convert(reply), thread_ts=thread_ts)


@app.event("app_mention")
def handle_mention(event, say):
    """Respond when the bot is @mentioned in a channel."""
    reply_in_thread(event, say)


@app.event("message")
def handle_dm(event, say):
    """Respond to direct messages."""
    if event.get("channel_type") != "im" or event.get("subtype"):
        return
    if event.get("user") == BOT_USER_ID:
        return

    reply_in_thread(event, say)


if __name__ == "__main__":
    logger.info("Starting bot...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
