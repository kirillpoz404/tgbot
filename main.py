import os
import requests
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes
)

# === Конфигурация ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_KEY")
MODEL = "mistralai/mistral-7b"

# === Хранилище задач (в памяти) ===
user_tasks = {}
reminder_jobs = {}

# === ChatGPT через OpenRouter ===
async def ask_ai(prompt: str):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    data = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "Ты дружелюбный AI-ассистент, отвечай кратко и по существу."},
            {"role": "user", "content": prompt}
        ]
    }

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers, json=data, timeout=30
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Ошибка при обращении к OpenRouter API: {e}"

# === Команды ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет 👋 Я твой AI-помощник!\n\n"
        "Доступные команды:\n"
        "/todo — добавить задачу\n"
        "/tasks — список задач\n"
        "/done — удалить задачу\n"
        "/remind — напоминать каждые 5 часов\n\n"
        "А ещё я умею отвечать на любые вопросы 🧠"
    )

async def todo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    task_text = " ".join(context.args)

    if not task_text:
        await update.message.reply_text("✏️ Используй: `/todo купить хлеб`")
        return

    user_tasks.setdefault(user_id, []).append(task_text)
    await update.message.reply_text(f"✅ Задача добавлена: {task_text}")

async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    tasks = user_tasks.get(user_id, [])

    if not tasks:
        await update.message.reply_text("📭 У тебя пока нет задач.")
        return

    task_list = "\n".join([f"{i+1}. {t}" for i, t in enumerate(tasks)])
    await update.message.reply_text(f"🗒 Твои задачи:\n\n{task_list}")

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    tasks = user_tasks.get(user_id, [])

    if not tasks:
        await update.message.reply_text("❌ Нет задач для удаления.")
        return

    try:
        task_num = int(context.args[0]) - 1
        removed = tasks.pop(task_num)
        await update.message.reply_text(f"🗑 Задача удалена: {removed}")
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Используй: `/done 1` чтобы удалить первую задачу.")

async def remind_user(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.chat_id
    tasks = user_tasks.get(user_id, [])
    if tasks:
        task_list = "\n".join([f"• {t}" for t in tasks])
        await context.bot.send_message(
            chat_id=user_id,
            text=f"⏰ Напоминание! У тебя есть задачи:\n\n{task_list}"
        )

async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id

    if user_id in reminder_jobs:
        reminder_jobs[user_id].schedule_removal()
        del reminder_jobs[user_id]
        await update.message.reply_text("🔕 Напоминания отключены.")
        return

    job = context.job_queue.run_repeating(remind_user, interval=5 * 60 * 60, first=5, chat_id=user_id)
    reminder_jobs[user_id] = job
    await update.message.reply_text("🔔 Теперь я буду напоминать о задачах каждые 5 часов!")

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    reply = await asyncio.to_thread(ask_ai, user_message)
    await update.message.reply_text(reply)

# === Запуск ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("todo", todo))
    app.add_handler(CommandHandler("tasks", tasks))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("remind", remind))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    print("🤖 Бот запущен!")
    app.run_polling()

