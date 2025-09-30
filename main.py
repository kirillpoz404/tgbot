
import sqlite3
import openai
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dateutil import parser
from datetime import datetime
import os
# ==== НАСТРОЙКИ ====
TELEGRAM_TOKEN = "TELEGRAM_TOKEN"
OPENAI_KEY = "OPENAI_KEY"

openai.api_key = OPENAI_KEY

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)
scheduler = AsyncIOScheduler()

# ==== БАЗА ДАННЫХ ====
conn = sqlite3.connect("assistant.db")
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    task TEXT,
    done INTEGER DEFAULT 0
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    note TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    text TEXT,
    remind_at TEXT
)""")
conn.commit()


# ==== GPT ====
def ask_gpt(prompt: str) -> str:
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300
    )
    return response.choices[0].message["content"]


def check_reminder_with_gpt(message: str) -> dict:
    """
    GPT решает, похоже ли сообщение на напоминание.
    Если да, возвращает { "reminder": true, "text": "...", "time": "2025-09-27 18:00" }
    """
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Ты помощник. Твоя задача — извлекать напоминания."},
            {"role": "user", "content": f"Сообщение: '{message}'. Если это напоминание, верни JSON вида: {{'reminder': true, 'text': '...', 'time': 'YYYY-MM-DD HH:MM'}}. Если нет — {{'reminder': false}}"}
        ],
        max_tokens=100
    )
    content = response.choices[0].message["content"]

    try:
        import json
        result = json.loads(content.replace("'", '"'))  # на случай кавычек
        return result
    except:
        return {"reminder": False}


# ==== ХЕНДЛЕРЫ ====
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer("Привет 👋! Я твой ассистент.\n"
                         "Я могу быть умным собеседником, хранить задачи, заметки и напоминания.\n"
                         "Попробуй написать: 'напомни завтра в 10 купить молоко' 😉")


# --- TODO ---
@dp.message_handler(commands=["todo"])
async def add_todo(message: types.Message):
    task = message.get_args()
    if not task:
        await message.answer("Напиши задачу после команды: `/todo Купить хлеб`")
        return
    cur.execute("INSERT INTO todos (user_id, task) VALUES (?, ?)",
                (message.from_user.id, task))
    conn.commit()
    await message.answer(f"Задача добавлена: ✅ {task}")


@dp.message_handler(commands=["tasks"])
async def show_tasks(message: types.Message):
    cur.execute("SELECT id, task, done FROM todos WHERE user_id=?",
                (message.from_user.id,))
    tasks = cur.fetchall()
    if not tasks:
        await message.answer("У тебя пока нет задач 📝")
    else:
        text = "\n".join([f"{'✅' if done else '🔹'} {tid}. {task}"
                          for tid, task, done in tasks])
        await message.answer(text)


# --- NOTES ---
@dp.message_handler(commands=["note"])
async def add_note(message: types.Message):
    note = message.get_args()
    if not note:
        await message.answer("Напиши заметку после команды: `/note Идея для проекта`")
        return
    cur.execute("INSERT INTO notes (user_id, note) VALUES (?, ?)",
                (message.from_user.id, note))
    conn.commit()
    await message.answer("Заметка сохранена 📝")


@dp.message_handler(commands=["notes"])
async def show_notes(message: types.Message):
    cur.execute("SELECT id, note FROM notes WHERE user_id=?",
                (message.from_user.id,))
    notes = cur.fetchall()
    if not notes:
        await message.answer("Заметок пока нет 📒")
    else:
        text = "\n".join([f"🔹 {nid}. {note}" for nid, note in notes])
        await message.answer(text)


# --- REMINDERS ---
async def send_reminder(user_id, text):
    await bot.send_message(user_id, f"🔔 Напоминание: {text}")


@dp.message_handler(commands=["remind"])
async def add_reminder(message: types.Message):
    args = message.get_args()
    if not args:
        await message.answer("Формат: `/remind Позвонить маме 27.09.2025 18:00`")
        return

    try:
        dt = parser.parse(args, fuzzy=True, dayfirst=True)
        text = args.replace(str(dt.date()), "").replace(str(dt.time()), "").strip()

        cur.execute("INSERT INTO reminders (user_id, text, remind_at) VALUES (?, ?, ?)",
                    (message.from_user.id, text, dt.isoformat()))
        conn.commit()

        scheduler.add_job(send_reminder, "date", run_date=dt,
                          args=[message.from_user.id, text])

        await message.answer(f"Напоминание сохранено ⏰: {text} в {dt}")
    except Exception:
        await message.answer("Не смог разобрать дату/время 😔 Попробуй так: `/remind Текст 27.09.2025 18:00`")


# --- GPT + Автопроверка на напоминание ---
@dp.message_handler()
async def chat_with_gpt(message: types.Message):
    # Сначала спросим у GPT — это напоминание?
    result = check_reminder_with_gpt(message.text)

    if result.get("reminder"):
        try:
            dt = parser.parse(result["time"], fuzzy=True, dayfirst=True)
            text = result["text"]

            cur.execute("INSERT INTO reminders (user_id, text, remind_at) VALUES (?, ?, ?)",
                        (message.from_user.id, text, dt.isoformat()))
            conn.commit()

            scheduler.add_job(send_reminder, "date", run_date=dt,
                              args=[message.from_user.id, text])

            await message.answer(f"Понял! Я создал напоминание ⏰: {text} в {dt}")
            return
        except Exception:
            await message.answer("Вижу, что это напоминание, но не смог распознать дату/время 😔 Попробуй написать в формате: `напомни завтра в 18:00 ...`")

    # Если это не напоминание — обычный чат с GPT
    reply = ask_gpt(message.text)
    await message.answer(reply)


# ==== ЗАПУСК ====
if __name__ == "__main__":
    scheduler.start()
    executor.start_polling(dp, skip_updates=True)
TG
