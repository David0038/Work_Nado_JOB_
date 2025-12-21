import os
import asyncio
import datetime
import uuid
import requests
import psycopg2

from psycopg2.extras import RealDictCursor
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
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET = os.getenv("YOOKASSA_SECRET")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 8000))

if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("Environment variables are not set")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
app = FastAPI()

conn = psycopg2.connect(DATABASE_URL, sslmode="require")
cur = conn.cursor(cursor_factory=RealDictCursor)

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
conn.commit()

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
    conn.commit()

def get_role(user_id: int):
    cur.execute("SELECT role FROM users WHERE user_id=%s;", (user_id,))
    row = cur.fetchone()
    return row["role"] if row else None

def set_subscription(user_id: int, expires: datetime.datetime):
    cur.execute(
        "INSERT INTO subscriptions (user_id, expires) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET expires = EXCLUDED.expires;",
        (user_id, expires)
    )
    conn.commit()

def has_subscription(user_id: int):
    cur.execute("SELECT expires FROM subscriptions WHERE user_id=%s;", (user_id,))
    row = cur.fetchone()
    return bool(row and row["expires"] > datetime.datetime.now())

@dp.message(Command("start"))
async def start(message: Message):
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

@dp.message(F.text == "📋 Вакансии")
async def show_orders(message: Message):
    role = get_role(message.from_user.id)
    if role == "customer" and not has_subscription(message.from_user.id):
        await message.answer("Нужна подписка", reply_markup=main_menu_customer)
        return
    cur.execute("SELECT * FROM orders ORDER BY id DESC;")
    orders = cur.fetchall()
    if not orders:
        await message.answer("Нет заказов", reply_markup=back_button)
        return
    for o in orders:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Подробнее", callback_data=f"order_{o['id']}")]
            ]
        )
        await message.answer(
            f"Заказ #{o['id']}\n{o['description']}\nСрок: {o['deadline']}",
            reply_markup=kb
        )

@dp.callback_query(F.data.startswith("order_"))
async def order_detail(cb: CallbackQuery):
    order_id = int(cb.data.split("_")[1])
    cur.execute("SELECT * FROM orders WHERE id=%s;", (order_id,))
    o = cur.fetchone()
    if o:
        await cb.message.answer(
            f"Заказ #{o['id']}\n{o['description']}\nСрок: {o['deadline']}"
        )
    await cb.answer()

@dp.message(F.text == "📝 Создать заказ")
async def create_order(message: Message, state: FSMContext):
    if not has_subscription(message.from_user.id):
        await message.answer("Нужна подписка", reply_markup=main_menu_customer)
        return
    await state.set_state(OrderStates.description)
    await message.answer("Опишите заказ", reply_markup=back_button)

@dp.message(OrderStates.description)
async def order_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(OrderStates.deadline)
    await message.answer("Укажите срок")

@dp.message(OrderStates.deadline)
async def order_dead(message: Message, state: FSMContext):
    data = await state.get_data()
    cur.execute(
        "INSERT INTO orders (user_id, description, deadline, created_at) "
        "VALUES (%s, %s, %s, %s);",
        (message.from_user.id, data["description"], message.text, datetime.datetime.now())
    )
    conn.commit()
    await state.clear()
    await message.answer("Заказ создан", reply_markup=main_menu_customer)

@app.get("/")
async def health():
    return {"status": "ok"}

async def main():
    asyncio.create_task(dp.start_polling(bot))
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT)
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
