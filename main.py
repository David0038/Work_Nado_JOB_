import os
import asyncio
import datetime
import psycopg
from psycopg.rows import dict_row

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    Message, CallbackQuery
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

from fastapi import FastAPI
import uvicorn

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 8000))

if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("BOT_TOKEN и DATABASE_URL должны быть установлены")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
app = FastAPI()

conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    role TEXT
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id BIGINT PRIMARY KEY,
    expires TIMESTAMP
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    description TEXT,
    deadline TEXT,
    created_at TIMESTAMP
);
""")

main_menu_customer = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Вакансии")],
        [KeyboardButton(text="📝 Создать заказ")],
        [KeyboardButton(text="💳 Купить подписку")]
    ],
    resize_keyboard=True
)

main_menu_worker = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📋 Вакансии")]],
    resize_keyboard=True
)

back_button = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="⬅️ Назад")]],
    resize_keyboard=True
)

class OrderStates(StatesGroup):
    description = State()
    deadline = State()

def set_role(user_id: int, role: str):
    cur.execute(
        "INSERT INTO users (user_id, role) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET role = EXCLUDED.role;",
        (user_id, role)
    )

def get_role(user_id: int):
    cur.execute("SELECT role FROM users WHERE user_id=%s;", (user_id,))
    row = cur.fetchone()
    return row["role"] if row else None

def has_subscription(user_id: int):
    cur.execute("SELECT expires FROM subscriptions WHERE user_id=%s;", (user_id,))
    row = cur.fetchone()
    return bool(row and row["expires"] > datetime.datetime.now())

@dp.message(Command("start"))
async def start_cmd(message: Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👔 Я заказчик")],
            [KeyboardButton(text="👤 Я исполнитель")]
        ],
        resize_keyboard=True
    )
    await message.answer("Добро пожаловать", reply_markup=kb)

@dp.message(F.text == "👔 Я заказчик")
async def choose_customer(message: Message):
    set_role(message.from_user.id, "customer")
    await message.answer("Роль: заказчик", reply_markup=main_menu_customer)

@dp.message(F.text == "👤 Я исполнитель")
async def choose_worker(message: Message):
    set_role(message.from_user.id, "worker")
    await message.answer("Роль: исполнитель", reply_markup=main_menu_worker)

@app.get("/")
async def health():
    return {"status": "ok"}

async def main():
    await asyncio.gather(
        dp.start_polling(bot),
        uvicorn.Server(
            uvicorn.Config(app, host="0.0.0.0", port=PORT)
        ).serve()
    )

if __name__ == "__main__":
    asyncio.run(main())
