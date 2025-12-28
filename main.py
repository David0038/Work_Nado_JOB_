import os
import uuid
import asyncio
import datetime
import psycopg
from psycopg.rows import dict_row
import requests

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

from fastapi import FastAPI, Request
import uvicorn

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
SECRET = os.getenv("YOOKASSA_SECRET")
BASE_URL = os.getenv("BASE_URL")
PORT = int(os.getenv("PORT", 8000))

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
    name TEXT,
    phone TEXT,
    city TEXT,
    salary TEXT,
    schedule TEXT,
    description TEXT,
    photo_id TEXT,
    created_at TIMESTAMP
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS payments (
    payment_id TEXT PRIMARY KEY,
    user_id BIGINT
);
""")

customer_free = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="💳 Купить подписку")]],
    resize_keyboard=True
)

customer_paid = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Создать вакансию")],
        [KeyboardButton(text="📋 Мои вакансии")]
    ],
    resize_keyboard=True
)

worker_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔍 Вакансии по городу")]],
    resize_keyboard=True
)

class OrderFSM(StatesGroup):
    photo = State()
    name = State()
    phone = State()
    city = State()
    salary = State()
    schedule = State()
    description = State()

class SearchFSM(StatesGroup):
    city = State()

def set_role(uid, role):
    cur.execute(
        "INSERT INTO users (user_id, role) VALUES (%s,%s) "
        "ON CONFLICT (user_id) DO UPDATE SET role=EXCLUDED.role",
        (uid, role)
    )

def has_sub(uid):
    cur.execute("SELECT expires FROM subscriptions WHERE user_id=%s", (uid,))
    r = cur.fetchone()
    return r and r["expires"] > datetime.datetime.now()

def activate_sub(uid):
    cur.execute(
        "INSERT INTO subscriptions (user_id, expires) VALUES (%s,%s) "
        "ON CONFLICT (user_id) DO UPDATE SET expires=EXCLUDED.expires",
        (uid, datetime.datetime.now() + datetime.timedelta(days=30))
    )

def create_payment(uid):
    pid = str(uuid.uuid4())
    data = {
        "amount": {"value": "499.00", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": f"{BASE_URL}/success"},
        "capture": True,
        "description": "Подписка на вакансии",
        "metadata": {"user_id": uid}
    }
    try:
        r = requests.post(
            "https://api.yookassa.ru/v3/payments",
            json=data,
            auth=(SHOP_ID, SECRET),
            headers={"Idempotence-Key": pid},
            timeout=10
        )
        if r.status_code not in [200, 201]:
            raise Exception(f"YooKassa API вернул {r.status_code}: {r.text}")

        r_json = r.json()
        if "confirmation" not in r_json or "confirmation_url" not in r_json["confirmation"]:
            raise Exception(f"Неверный ответ ЮKassa: {r_json}")

        cur.execute("INSERT INTO payments VALUES (%s,%s)", (r_json["id"], uid))
        return r_json["confirmation"]["confirmation_url"]

    except Exception as e:
        raise Exception(f"Ошибка при создании платежа: {e}")

@dp.message(Command("start"))
async def start(m: Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👔 Я заказчик")],
            [KeyboardButton(text="👤 Я исполнитель")]
        ],
        resize_keyboard=True
    )
    await m.answer("Выберите роль", reply_markup=kb)

@dp.message(F.text == "👔 Я заказчик")
async def cust(m: Message):
    set_role(m.from_user.id, "customer")
    if has_sub(m.from_user.id):
        await m.answer("Кабинет заказчика", reply_markup=customer_paid)
    else:
        await m.answer("Для размещения вакансий нужна подписка", reply_markup=customer_free)

@dp.message(F.text == "💳 Купить подписку")
async def pay(m: Message):
    try:
        url = create_payment(m.from_user.id)
        await m.answer(f"Оплатите подписку:\n{url}")
    except Exception as e:
        await m.answer(str(e))

@dp.message(F.text == "📝 Создать вакансию")
async def create(m: Message, s: FSMContext):
    if not has_sub(m.from_user.id):
        return
    await s.set_state(OrderFSM.photo)
    await m.answer("Отправьте фото")

@dp.message(OrderFSM.photo)
async def o1(m: Message, s: FSMContext):
    await s.update_data(photo=m.photo[-1].file_id)
    await s.set_state(OrderFSM.name)
    await m.answer("Имя и фамилия")

@dp.message(OrderFSM.name)
async def o2(m: Message, s: FSMContext):
    await s.update_data(name=m.text)
    await s.set_state(OrderFSM.phone)
    await m.answer("Телефон")

@dp.message(OrderFSM.phone)
async def o3(m: Message, s: FSMContext):
    await s.update_data(phone=m.text)
    await s.set_state(OrderFSM.city)
    await m.answer("Город")

@dp.message(OrderFSM.city)
async def o4(m: Message, s: FSMContext):
    await s.update_data(city=m.text)
    await s.set_state(OrderFSM.salary)
    await m.answer("Зарплата")

@dp.message(OrderFSM.salary)
async def o5(m: Message, s: FSMContext):
    await s.update_data(salary=m.text)
    await s.set_state(OrderFSM.schedule)
    await m.answer("График")

@dp.message(OrderFSM.schedule)
async def o6(m: Message, s: FSMContext):
    await s.update_data(schedule=m.text)
    await s.set_state(OrderFSM.description)
    await m.answer("Описание")

@dp.message(OrderFSM.description)
async def o7(m: Message, s: FSMContext):
    d = await s.get_data()
    cur.execute(
        """
        INSERT INTO orders (user_id,name,phone,city,salary,schedule,description,photo_id,created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            m.from_user.id,
            d["name"],
            d["phone"],
            d["city"],
            d["salary"],
            d["schedule"],
            m.text,
            d["photo"],
            datetime.datetime.now()
        )
    )
    await s.clear()
    await m.answer("Вакансия опубликована", reply_markup=customer_paid)

@dp.message(F.text == "👤 Я исполнитель")
async def worker(m: Message):
    set_role(m.from_user.id, "worker")
    await m.answer("Кабинет исполнителя", reply_markup=worker_menu)

@dp.message(F.text == "🔍 Вакансии по городу")
async def search(m: Message, s: FSMContext):
    await s.set_state(SearchFSM.city)
    await m.answer("Введите город")

@dp.message(SearchFSM.city)
async def show(m: Message, s: FSMContext):
    cur.execute("SELECT * FROM orders WHERE city ILIKE %s", (f"%{m.text}%",))
    rows = cur.fetchall()
    for o in rows:
        await bot.send_photo(
            m.chat.id,
            o["photo_id"],
            caption=f"{o['city']}\n{o['salary']}\n{o['schedule']}\n{o['description']}\n{o['name']}\n{o['phone']}"
        )
    await s.clear()

@app.post("/yookassa")
async def webhook(r: Request):
    data = await r.json()
    if data.get("event") == "payment.succeeded":
        uid = int(data["object"]["metadata"]["user_id"])
        activate_sub(uid)
    return {"ok": True}

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
