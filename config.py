import os
from dotenv import load_dotenv
import logging
from slack_bolt import App
from openai import OpenAI
from markdown_to_mrkdwn import SlackMarkdownConverter
import opik
from opik.integrations.openai import track_openai

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

# --- Slack ---
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]  # xapp-... token for Socket Mode

# --- OpenAI ---
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

# --- Prompt override ---
# If set in the environment, override the default from prompts.py
SYSTEM_PROMPT_OVERRIDE = os.environ.get("SYSTEM_PROMPT")

# --- Opik (LLM observability) ---
# Configure from env vars: OPIK_API_KEY, OPIK_WORKSPACE, OPIK_PROJECT_NAME
# If OPIK_API_KEY is not set, Opik will run in no-op mode and tracing is skipped.
if os.environ.get("OPIK_API_KEY"):
    opik.configure(
        api_key=os.environ["OPIK_API_KEY"],
        workspace=os.environ.get("OPIK_WORKSPACE", "default"),
        use_local=False,
    )
    logger.info("Opik tracing enabled (project: %s)", os.environ.get("OPIK_PROJECT_NAME", "not-jarvis"))

# --- Clients ---
app = App(token=SLACK_BOT_TOKEN)
_base_openai_client = OpenAI(api_key=OPENAI_API_KEY)
# Wrap with Opik to trace all responses.create() calls. If Opik is not
# configured the wrapper is transparent and has no overhead.
openai_client = track_openai(
    _base_openai_client,
    project_name=os.environ.get("OPIK_PROJECT_NAME", "not-jarvis"),
)
mrkdwn_converter = SlackMarkdownConverter()
