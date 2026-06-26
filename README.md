# ByteSize Brain Bot (`@ByteSizeBrainBot`)

An interactive daily technical and logic trivia bot that generates high-quality multiple-choice questions using the GitHub LLM API (`openai/gpt-4.1-nano`) and delivers them to Telegram using native quiz polls.

Features:
- 📊 **Native Quiz Polls**: Delivers native Telegram quiz cards. Telegram handles option selection, score reveals, and correct/incorrect logic client-side.
- 🧠 **Daily Technical Themes**: Generates intermediate-to-advanced software engineering questions matching a weekly schedule:
  * **Monday**: Data Structures
  * **Tuesday**: Algorithms & Complexity
  * **Wednesday**: Databases & SQL
  * **Thursday**: System Design & Networking
  * **Friday**: Programming Languages & Runtimes
  * **Saturday**: DevOps, Git & OS
  * **Sunday**: Tech History, Logic & Riddles
- 🔒 **Webhook Security & Allowlist**:
  - Validates webhook tokens using `X-Telegram-Bot-Api-Secret-Token`.
  - Checks incoming messages against a Supabase allowlist table.
- 📈 **Auditing & History**: Logs all API requests to Supabase `request_audit` and stores sent questions in a `quiz_history` table to avoid duplication.
- ⚡ **Cron Trigger**: Integrates with Vercel Crons to post daily quizzes automatically at a designated time.


---

## Setup Instructions

### 1. Telegram Bot Configuration
1. Create a new bot by messaging [@BotFather](https://t.me/BotFather) on Telegram and save the `TELEGRAM_BOT_TOKEN`.
2. Disable Group Privacy if you wish to run the bot in group chats (optional).

### 2. Supabase Setup
Follow the [Supabase Setup Guide](docs/supabase_setup.md) to set up your PostgreSQL tables (`quiz_history`, `allowed_users`, and `request_audit`).

### 3. Vercel Deployment & Environment Variables
Deploy this repository to Vercel and add these environment variables:

| Variable | Description |
| :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | Token received from @BotFather. |
| `TELEGRAM_CHAT_ID` | The channel, group, or user chat ID where daily quizzes should be sent. |
| `GITHUB_TOKEN` | Your GitHub token for access to the LLM Models API. |
| `SUPABASE_URL` | Your Supabase Project API URL. |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role secret API key (bypasses RLS to write audit logs). |
| `TELEGRAM_WEBHOOK_SECRET` | A secure, random string used to sign and verify incoming webhook requests from Telegram. |
| `TELEGRAM_ADMIN_USER_IDS` | Comma-separated list of Telegram User IDs who have administrator roles. |

---

## Registering Webhook
Use curl to register your Vercel deployment URL with Telegram (replace placeholders):
```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
     -H "Content-Type: application/json" \
     -d '{"url": "https://<your-vercel-domain>.vercel.app/api/telegram", "secret_token": "<TELEGRAM_WEBHOOK_SECRET>", "allowed_updates": ["message"]}'
```

---

## Webhook Commands
- `/quiz` — Generates a new quiz question on the fly and posts it to the chat.
- `/help` — Displays a helpful interface with lists of bot commands.

**Admin-Only Commands:**
- `/allow <username_or_id> [role]` — Registers/activates a user to use the bot.
- `/revoke <username_or_id>` — Disables a user's access.
- `/users` — Lists all registered users inside chat.

---

## Local Testing
1. Clone the project.
2. Create a `.env` file in the root directory:
   ```env
   TELEGRAM_BOT_TOKEN="your_bot_token"
   TELEGRAM_CHAT_ID="your_target_chat_id"
   GITHUB_TOKEN="your_github_token"
   SUPABASE_URL="your_supabase_url"
   SUPABASE_SERVICE_ROLE_KEY="your_supabase_key"
   TELEGRAM_ADMIN_USER_IDS="your_telegram_id"
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run local server:
   ```bash
   python api/index.py
   ```
5. Trigger a manual quiz locally using Python CLI:
   ```bash
   export $(cat .env | xargs)
   python -c "from src.quiz_generator import generate_quiz; from src.telegram_client import send_poll; q=generate_quiz(); send_poll(int('$TELEGRAM_CHAT_ID'), q['question'], q['options'], q['correct_option_id'], q['explanation'])"
   ```

---

## 🛠️ API & Webhook Testing (curl & requests)
For detailed instructions and code examples on how to manually trigger quizzes or simulate Telegram webhook requests locally or in production using `curl` or the Python `requests` library, see the [API Testing Guide](docs/api_testing.md).
