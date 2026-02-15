import os

SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    "You are a helpful assistant in a Slack workspace. Be concise and helpful. "
    "Always format your responses using standard Markdown syntax "
    "(e.g. **bold**, *italic*, [links](url), - bullet lists, ```code blocks```).",
)
