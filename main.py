import os
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from openai import OpenAI

# --- ИНИЦИАЛИЗАЦИЯ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_KEY")

if not TELEGRAM_TOKEN or not OPENAI_KEY:
    raise ValueError("❌ Missing TELEGRAM_TOKEN or OPENAI_KEY in .env file")

client = OpenAI(api_key=OPENAI_KEY)

# --- БАЗА ДАННЫХ ---
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS tasks (
    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    title TEXT NOT NULL,
    description TEXT,
    due_date TIMESTAMP,
    completed INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
)
""")

conn.commit()

# --- КОМАНДЫ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cursor.execute("""
        INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)
        VALUES (?, ?, ?, ?)
    """, (user.id, user.username, user.first_name, user.last_name))
    conn.commit()

    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n"
        "Я твой персональный ассистент и органайзер.\n"
        "Используй /add для добавления задачи, /tasks для просмотра задач или просто напиши мне вопрос."
    )


async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Использование: /add <название задачи>")
        return

    title = " ".join(context.args)
    cursor.execute("INSERT INTO tasks (user_id, title) VALUES (?, ?)", (update.effective_user.id, title))
    conn.commit()
    await update.message.reply_text(f"✅ Задача добавлена: {title}")


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT title, completed FROM tasks WHERE user_id=?", (update.effective_user.id,))
    tasks = cursor.fetchall()

    if not tasks:
        await update.message.reply_text("У тебя пока нет задач 🗒️")
        return

    response = "\n".join(
        [f"{'✅' if t[1] else '🔹'} {t[0]}" for t in tasks]
    )
    await update.message.reply_text(f"Твои задачи:\n{response}")


async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    await update.message.chat.send_action("typing")

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ты умный, дружелюбный ассистент, который помогает пользователю с задачами и идеями."},
                {"role": "user", "content": user_message}
            ]
        )
        reply = completion.choices[0].message.content
        await update.message.reply_text(reply)

    except Exception as e:
        await update.message.reply_text("⚠️ Ошибка при обращении к OpenAI API")
        print("OpenAI error:", e)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — начать работу\n"
        "/add <текст> — добавить задачу\n"
        "/tasks — показать список задач\n"
        "Просто напиши мне — и я помогу советом 💬"
    )


# --- ЗАПУСК ПРИЛОЖЕНИЯ ---
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_task))
    app.add_handler(CommandHandler("tasks", list_tasks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_chat))

    print("🤖 Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
