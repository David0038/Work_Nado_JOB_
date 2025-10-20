import os
import asyncio
import datetime
import requests
import uuid
import sqlite3
from aiogram import Bot, Dispatcher, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from fastapi import FastAPI, Request
import uvicorn

API_TOKEN = os.getenv("API_TOKEN", "8394026180:AAEHHKn30U7H_zdHWGu_cB2h9054lmo1eag")
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "1179735")
YOOKASSA_SECRET = os.getenv("YOOKASSA_SECRET", "test_J8y43wGt8go7fyMtkNNWUGlMdTmVtV41bd82cVmMpQk")

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
app = FastAPI()

conn = sqlite3.connect('worknado.db', check_same_thread=False)
cur = conn.cursor()
cur.execute('''CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, role TEXT)''')
cur.execute('''CREATE TABLE IF NOT EXISTS subscriptions(user_id INTEGER PRIMARY KEY, expires TEXT)''')
cur.execute('''CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, description TEXT, deadline TEXT, created_at TEXT)''')
conn.commit()

main_menu_customer = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📋 Вакансии")],[KeyboardButton(text="📝 Создать заказ")],[KeyboardButton(text="💳 Купить подписку")]], resize_keyboard=True)
main_menu_worker = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📋 Вакансии")]], resize_keyboard=True)
back_button = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True)

class OrderStates(StatesGroup):
    description = State()
    deadline = State()

def set_role_db(user_id: int, role: str):
    cur.execute('INSERT OR REPLACE INTO users(user_id, role) VALUES(?, ?)', (user_id, role))
    conn.commit()

def get_role_db(user_id: int):
    cur.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    row = cur.fetchone()
    return row[0] if row else None

def set_subscription_db(user_id: int, expires: datetime.datetime):
    cur.execute('INSERT OR REPLACE INTO subscriptions(user_id, expires) VALUES(?, ?)', (user_id, expires.isoformat()))
    conn.commit()

def has_active_subscription_db(user_id: int) -> bool:
    cur.execute('SELECT expires FROM subscriptions WHERE user_id = ?', (user_id,))
    row = cur.fetchone()
    if not row:
        return False
    try:
        expires = datetime.datetime.fromisoformat(row[0])
    except Exception:
        return False
    return expires > datetime.datetime.now()

@dp.message(Command("start"))
async def start(message: Message):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="👔 Я заказчик")],[KeyboardButton(text="👤 Я исполнитель")]], resize_keyboard=True)
    await message.answer("👋 Добро пожаловать в WorkNadoJobBot!\n\nВыберите, кто вы 👇", reply_markup=kb)

@dp.message(F.text == "👔 Я заказчик")
async def choose_customer(message: Message):
    set_role_db(message.from_user.id, "customer")
    await message.answer("Вы выбрали роль: 👔 Заказчик. Чтобы создавать заказы и просматривать отклики, оформите подписку — 1000 ₽ / 30 дней.", reply_markup=main_menu_customer)

@dp.message(F.text == "👤 Я исполнитель")
async def choose_worker(message: Message):
    set_role_db(message.from_user.id, "worker")
    await message.answer("Вы выбрали роль: 👤 Исполнитель. Вы можете бесплатно просматривать вакансии.", reply_markup=main_menu_worker)

@dp.message(F.text == "📋 Вакансии")
async def show_vacancies(message: Message):
    role = get_role_db(message.from_user.id)
    if role == "customer" and not has_active_subscription_db(message.from_user.id):
        await message.answer("❌ Для заказчиков доступ только по подписке. Купите подписку за 1000 ₽.", reply_markup=main_menu_customer)
        return
    cur.execute('SELECT id, description, deadline, created_at, user_id FROM orders ORDER BY id DESC')
    rows = cur.fetchall()
    if not rows:
        await message.answer("❌ Пока нет активных заказов.", reply_markup=back_button)
        return
    for r in rows:
        oid, desc, deadline, created_at, uid = r
        short = desc if len(desc) < 200 else desc[:197] + '...'
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подробнее", callback_data=f"order_{oid}")]])
        await message.answer(f"📌 Заказ #{oid}\n{short}\nСрок: {deadline}\nСоздал: {uid}", reply_markup=kb)

@dp.callback_query(F.data.startswith('order_'))
async def show_order_cb(query: CallbackQuery):
    oid = int(query.data.split('_', 1)[1])
    cur.execute('SELECT id, user_id, description, deadline, created_at FROM orders WHERE id = ?', (oid,))
    row = cur.fetchone()
    if not row:
        await query.answer('Заказ не найден', show_alert=True)
        return
    idd, uid, desc, deadline, created_at = row
    await query.message.answer(f"📄 Заказ #{idd}\n{desc}\n\nСрок: {deadline}\nСоздан: {created_at}\nЗаказчик: {uid}")
    await query.answer()

@dp.message(F.text == "📝 Создать заказ")
async def create_order(message: Message, state: FSMContext):
    role = get_role_db(message.from_user.id)
    if role != "customer":
        await message.answer("❌ Только заказчики могут создавать заказы.", reply_markup=main_menu_customer)
        return
    if not has_active_subscription_db(message.from_user.id):
        await message.answer("❌ Для создания заказов нужна подписка (1000 ₽).", reply_markup=main_menu_customer)
        return
    await state.set_state(OrderStates.description)
    await message.answer("✏️ Опишите ваш заказ (коротко).", reply_markup=back_button)

@dp.message(OrderStates.description)
async def order_description(message: Message, state: FSMContext):
    if message.text == '⬅️ Назад':
        await state.clear()
        await message.answer('Отменено', reply_markup=main_menu_customer)
        return
    await state.update_data(description=message.text)
    await state.set_state(OrderStates.deadline)
    await message.answer('Укажите срок выполнения (например: 3 дня, 2025-11-01).', reply_markup=back_button)

@dp.message(OrderStates.deadline)
async def order_deadline(message: Message, state: FSMContext):
    if message.text == '⬅️ Назад':
        await state.clear()
        await message.answer('Отменено', reply_markup=main_menu_customer)
        return
    data = await state.get_data()
    desc = data.get('description')
    deadline = message.text
    created_at = datetime.datetime.now().isoformat(sep=' ', timespec='seconds')
    cur.execute('INSERT INTO orders(user_id, description, deadline, created_at) VALUES(?, ?, ?, ?)', (message.from_user.id, desc, deadline, created_at))
    conn.commit()
    await state.clear()
    await message.answer('✅ Заказ создан и добавлен в список вакансий.', reply_markup=main_menu_customer)

@dp.message(F.text == "💳 Купить подписку")
async def buy_subscription(message: Message):
    role = get_role_db(message.from_user.id)
    if role != "customer":
        await message.answer("❌ Подписка нужна только заказчикам.", reply_markup=main_menu_customer)
        return
    amount = "1000.00"
    data = {
        "amount": {"value": amount, "currency": "RUB"},
        "capture": True,
        "description": "Подписка на WorkNadoJobBot (30 дней)",
        "confirmation": {"type": "redirect", "return_url": "https://t.me/WorkNadoJobBot"},
        "metadata": {"user_id": message.from_user.id}
    }
    idempotence_key = str(uuid.uuid4())
    try:
        response = requests.post("https://api.yookassa.ru/v3/payments", auth=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET), json=data, headers={"Content-Type": "application/json", "Idempotence-Key": idempotence_key}, timeout=15)
    except Exception as e:
        await message.answer(f"⚠️ Ошибка при создании платежа. {e}", reply_markup=main_menu_customer)
        return
    payment = response.json()
    if "confirmation" not in payment:
        await message.answer(f"⚠️ Ошибка при создании платежа.\n\n{payment}", reply_markup=main_menu_customer)
        return
    confirmation_url = payment["confirmation"]["confirmation_url"]
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Оплатить через ЮKassa", url=confirmation_url)]])
    await message.answer(f"💰 Подписка на 30 дней — {amount} ₽.", reply_markup=kb)

@dp.message(F.text == "⬅️ Назад")
async def go_back(message: Message):
    role = get_role_db(message.from_user.id)
    if role == "customer":
        await message.answer("Вы вернулись в главное меню.", reply_markup=main_menu_customer)
    elif role == "worker":
        await message.answer("Вы вернулись в главное меню.", reply_markup=main_menu_worker)
    else:
        await start(message)

@app.post("/yookassa/callback")
async def yookassa_callback(request: Request):
    data = await request.json()
    if data.get("event") == "payment.succeeded":
        user_id = int(data["object"]["metadata"]["user_id"])
        expires = datetime.datetime.now() + datetime.timedelta(days=30)
        set_subscription_db(user_id, expires)
        await bot.send_message(user_id, "✅ Оплата получена! Подписка активна на 30 дней 🎉", reply_markup=main_menu_customer)
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"status": "WorkNadoJobBot работает 🚀"}

async def main():
    loop = asyncio.get_event_loop()
    loop.create_task(dp.start_polling(bot))
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())

