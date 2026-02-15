import os
from dotenv import load_dotenv
import logging
from slack_bolt import App
from openai import OpenAI
from markdown_to_mrkdwn import SlackMarkdownConverter

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

# --- Slack ---
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]  # xapp-... token for Socket Mode

# --- OpenAI ---
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

# --- Clients ---
app = App(token=SLACK_BOT_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
mrkdwn_converter = SlackMarkdownConverter()
