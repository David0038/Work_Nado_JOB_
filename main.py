import os
import asyncio
import datetime
import requests
from aiogram import Bot, Dispatcher, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from fastapi import FastAPI, Request
import uvicorn
import httpx

API_TOKEN = "8394026180:AAEHHKn30U7H_zdHWGu_cB2h9054lmo1eag"
YOOKASSA_SHOP_ID = "test_1179735"
YOOKASSA_SECRET = "test_J8y43wGt8go7fyMtkNNWUGlMdTmVtV41bd82cVmMpQk"

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
app = FastAPI()

roles = {}
subscriptions = {}

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Вакансии")],
        [KeyboardButton(text="📝 Создать заказ")],
        [KeyboardButton(text="💳 Купить подписку")]
    ],
    resize_keyboard=True
)

def has_active_subscription(user_id: int) -> bool:
    return subscriptions.get(user_id, datetime.datetime.min) > datetime.datetime.now()

@dp.message(Command("start"))
async def start(message: Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👔 Я заказчик")],
            [KeyboardButton(text="👤 Я исполнитель")]
        ],
        resize_keyboard=True
    )
    await message.answer(
        "👋 Добро пожаловать в WorkNadoJobBot!\n\n"
        "💼 Здесь заказчики и исполнители находят друг друга.\n\n"
        "🔹 *Исполнители* — могут бесплатно просматривать вакансии.\n"
        "🔹 *Заказчики* — публикуют заказы с подпиской 1000 ₽ / 30 дней.\n\n"
        "Выберите, кто вы 👇",
        reply_markup=kb
    )

@dp.message(F.text == "👔 Я заказчик")
async def choose_customer(message: Message):
    roles[message.from_user.id] = "customer"
    await message.answer(
        "Вы выбрали роль: 👔 Заказчик.\n\n"
        "Чтобы создавать заказы и просматривать отклики, оформите подписку — 1000 ₽ / 30 дней.",
        reply_markup=main_menu
    )

@dp.message(F.text == "👤 Я исполнитель")
async def choose_worker(message: Message):
    roles[message.from_user.id] = "worker"
    await message.answer(
        "Вы выбрали роль: 👤 Исполнитель.\nВы можете бесплатно просматривать вакансии.",
        reply_markup=main_menu
    )

@dp.message(F.text == "📋 Вакансии")
async def show_vacancies(message: Message):
    role = roles.get(message.from_user.id)
    if role == "customer" and not has_active_subscription(message.from_user.id):
        await message.answer("❌ Для заказчиков доступ только по подписке. Купите подписку за 1000 ₽.", reply_markup=main_menu)
        return
    await message.answer(
        "✅ Список вакансий:\n"
        "1️⃣ Разработка Telegram-бота — 10 000 ₽\n"
        "2️⃣ Дизайн логотипа — 5 000 ₽\n"
        "3️⃣ Копирайтинг — 3 000 ₽"
    )

@dp.message(F.text == "📝 Создать заказ")
async def create_order(message: Message):
    if roles.get(message.from_user.id) != "customer":
        await message.answer("❌ Только заказчики могут создавать заказы.")
        return
    if not has_active_subscription(message.from_user.id):
        await message.answer("❌ Для создания заказов нужна подписка (1000 ₽).", reply_markup=main_menu)
        return
    await message.answer("✏️ Напишите описание вашего заказа.\n\n(Этот раздел в разработке.)")

@dp.message(F.text == "💳 Купить подписку")
async def buy_subscription(message: Message):
    if roles.get(message.from_user.id) != "customer":
        await message.answer("❌ Подписка нужна только заказчикам.")
        return

    amount = "1000.00"
    data = {
        "amount": {"value": amount, "currency": "RUB"},
        "capture": True,
        "description": "Подписка на WorkNadoJobBot (30 дней)",
        "confirmation": {"type": "redirect", "return_url": "https://t.me/WorkNadoJobBot"},
        "metadata": {"user_id": message.from_user.id}
    }

    response = requests.post(
        "https://api.yookassa.ru/v3/payments",
        auth=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET),
        json=data,
        headers={"Content-Type": "application/json"}
    )

    payment = response.json()
    if "confirmation" not in payment:
        await message.answer(f"⚠️ Ошибка при создании платежа.\n\nОтвет сервера:\n{payment}")
        return

    confirmation_url = payment["confirmation"]["confirmation_url"]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💳 Оплатить через ЮKassa", url=confirmation_url)]]
    )

    await message.answer(
        f"💰 Подписка на 30 дней — {amount} ₽.\n\nПосле оплаты доступ откроется автоматически ✅",
        reply_markup=kb
    )

@app.post("/yookassa/callback")
async def yookassa_callback(request: Request):
    data = await request.json()
    if data.get("event") == "payment.succeeded":
        user_id = int(data["object"]["metadata"]["user_id"])
        subscriptions[user_id] = datetime.datetime.now() + datetime.timedelta(days=30)
        await bot.send_message(user_id, "✅ Оплата получена! Подписка активна на 30 дней 🎉")
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"status": "WorkNadoJobBot работает 🚀"}

@app.get("/ping")
async def ping():
    return {"status": "alive"}

async def ping_self():
    while True:
        try:
            async with httpx.AsyncClient() as client:
                await client.get("https://work-nado-job.onrender.com/ping")
        except:
            pass
        await asyncio.sleep(300)

async def main():
    loop = asyncio.get_event_loop()
    loop.create_task(dp.start_polling(bot))
    loop.create_task(ping_self())
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
