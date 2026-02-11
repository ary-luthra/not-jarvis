# not-jarvis

A Slack bot that calls the OpenAI API to respond to messages.

## How it works

- Uses **Slack Socket Mode** — no public URL or server needed
- Responds when **@mentioned** in channels or messaged **directly (DM)**
- Keeps **thread context** — replies in-thread and remembers the conversation history within that thread

## Setup

### 1. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App** > **From scratch**
2. Name it whatever you want, pick your workspace

### 2. Enable Socket Mode

1. Go to **Settings > Basic Information > App-Level Tokens**
2. Click **Generate Token and Scopes**, name it anything, and add the `connections:write` scope
3. Copy the `xapp-...` token — this is your `SLACK_APP_TOKEN`
4. Go to **Settings > Socket Mode** and toggle it **on**

### 3. Set Bot Permissions

Go to **Features > OAuth & Permissions > Scopes** and add these **Bot Token Scopes**:

- `app_mentions:read`
- `chat:write`
- `channels:history`
- `groups:history`
- `im:history`
- `im:read`
- `im:write`

### 4. Enable Events

1. Go to **Features > Event Subscriptions** and toggle **on**
2. Under **Subscribe to bot events**, add:
   - `app_mention`
   - `message.im`

### 5. Install to Workspace

1. Go to **Settings > Install App** and click **Install to Workspace**
2. Copy the `xoxb-...` token — this is your `SLACK_BOT_TOKEN`

### 6. Get an OpenAI API key

Get one from [platform.openai.com/api-keys](https://platform.openai.com/api-keys).

### 7. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your three tokens
```

### 8. Run

```bash
pip install -r requirements.txt
# Load your .env however you prefer, e.g.:
export $(cat .env | xargs)
python bot.py
```

The bot will connect via WebSocket and print `⚡️ Bolt app is running!` when ready.

## Usage

- **In a channel**: Invite the bot, then `@YourBot what is the meaning of life?`
- **In a DM**: Just send a message directly to the bot

Replies happen in-thread. The bot reads the full thread for context, so follow-up questions work naturally.
