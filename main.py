import os
import asyncio
import datetime
import requests
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor
from aiogram import Bot, Dispatcher, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from fastapi import FastAPI, Request
import uvicorn

API_TOKEN = "8394026180:AAEHHKn30U7H_zdHWGu_cB2h9054lmo1eag"
YOOKASSA_SHOP_ID = "1179735"
YOOKASSA_SECRET = "test_J8y43wGt8go7fyMtkNNWUGlMdTmVtV41bd82cVmMpQk"
DATABASE_URL = "postgresql://worknado_user:0NvvjFmjHWOXny9UdRLUjKYyKTzV5jD0@dpg-d3sgt77gi27c73b798rg-a.oregon-postgres.render.com/worknado_db"  

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
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

main_menu_customer = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📋 Вакансии")],[KeyboardButton(text="📝 Создать заказ")],[KeyboardButton(text="💳 Купить подписку")]], resize_keyboard=True)
main_menu_worker = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📋 Вакансии")]], resize_keyboard=True)
back_button = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True)

class OrderStates(StatesGroup):
    description = State()
    deadline = State()

def set_role_db(user_id: int, role: str):
    cur.execute("INSERT INTO users (user_id, role) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET role = EXCLUDED.role;", (user_id, role))
    conn.commit()

def get_role_db(user_id: int):
    cur.execute("SELECT role FROM users WHERE user_id = %s;", (user_id,))
    row = cur.fetchone()
    return row["role"] if row else None

def set_subscription_db(user_id: int, expires: datetime.datetime):
    cur.execute("INSERT INTO subscriptions (user_id, expires) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expires = EXCLUDED.expires;", (user_id, expires))
    conn.commit()

def has_active_subscription_db(user_id: int) -> bool:
    cur.execute("SELECT expires FROM subscriptions WHERE user_id = %s;", (user_id,))
    row = cur.fetchone()
    if not row or not row["expires"]:
        return False
    return row["expires"] > datetime.datetime.now()

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
    cur.execute("SELECT id, description, deadline, created_at, user_id FROM orders ORDER BY id DESC;")
    rows = cur.fetchall()
    if not rows:
        await message.answer("❌ Пока нет активных заказов.", reply_markup=back_button)
        return
    for r in rows:
        short = r["description"] if len(r["description"]) < 200 else r["description"][:197] + '...'
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подробнее", callback_data=f"order_{r['id']}")]])
        await message.answer(f"📌 Заказ #{r['id']}\n{short}\nСрок: {r['deadline']}\nСоздал: {r['user_id']}", reply_markup=kb)

@dp.callback_query(F.data.startswith('order_'))
async def show_order_cb(query: CallbackQuery):
    oid = int(query.data.split('_', 1)[1])
    cur.execute("SELECT id, user_id, description, deadline, created_at FROM orders WHERE id = %s;", (oid,))
    row = cur.fetchone()
    if not row:
        await query.answer('Заказ не найден', show_alert=True)
        return
    await query.message.answer(f"📄 Заказ #{row['id']}\n{row['description']}\n\nСрок: {row['deadline']}\nСоздан: {row['created_at']}\nЗаказчик: {row['user_id']}")
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
    created_at = datetime.datetime.now()
    cur.execute("INSERT INTO orders (user_id, description, deadline, created_at) VALUES (%s, %s, %s, %s);", (message.from_user.id, desc, deadline, created_at))
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
    msg = await message.answer(f"💰 Подписка на 30 дней — {amount} ₽.\nПосле оплаты нажмите кнопку ниже.", reply_markup=kb)
    payment_id = payment.get("id")
    if payment_id:
        for _ in range(10):
            await asyncio.sleep(10)
            check = requests.get(f"https://api.yookassa.ru/v3/payments/{payment_id}", auth=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET))
            js = check.json()
            if js.get("status") == "succeeded":
                expires = datetime.datetime.now() + datetime.timedelta(days=30)
                set_subscription_db(message.from_user.id, expires)
                await msg.edit_text("✅ Оплата получена! Подписка активна на 30 дней 🎉", reply_markup=None)
                await message.answer("Теперь вы можете создавать заказы и просматривать вакансии.", reply_markup=main_menu_customer)
                break

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

