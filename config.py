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
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.2")

# --- Prompt override ---
# If set in the environment, override the default from prompts.py
SYSTEM_PROMPT_OVERRIDE = os.environ.get("SYSTEM_PROMPT")

# --- Opik (LLM observability) ---
# Enabled only when the --trace CLI flag is passed (which sets OPIK_TRACING_ENABLED=1).
# Also requires OPIK_API_KEY to be set in the environment.
OPIK_TRACING_ENABLED = (
    os.environ.get("OPIK_TRACING_ENABLED") == "1"
    and bool(os.environ.get("OPIK_API_KEY"))
)

if OPIK_TRACING_ENABLED:
    opik.configure(
        api_key=os.environ["OPIK_API_KEY"],
        workspace=os.environ.get("OPIK_WORKSPACE", "default"),
    )
    logger.info("Opik tracing enabled (project: %s)", os.environ.get("OPIK_PROJECT_NAME", "not-jarvis"))

# --- Clients ---
app = App(token=SLACK_BOT_TOKEN)
_base_openai_client = OpenAI(api_key=OPENAI_API_KEY)
# When tracing is enabled, wrap the client so every responses.create() call
# is captured in Opik. Otherwise use the plain client with no overhead.
openai_client = (
    track_openai(
        _base_openai_client,
        project_name=os.environ.get("OPIK_PROJECT_NAME", "not-jarvis"),
    )
    if OPIK_TRACING_ENABLED
    else _base_openai_client
)
mrkdwn_converter = SlackMarkdownConverter()
