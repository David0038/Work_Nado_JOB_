import os
import asyncio
import datetime
import requests
import uuid
from aiogram import Bot, Dispatcher, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from fastapi import FastAPI, Request
import uvicorn

API_TOKEN = os.getenv("API_TOKEN", "8394026180:AAEHHKn30U7H_zdHWGu_cB2h9054lmo1eag")
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "1179735")
YOOKASSA_SECRET = os.getenv("YOOKASSA_SECRET", "test_J8y43wGt8go7fyMtkNNWUGlMdTmVtV41bd82cVmMpQk")

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
app = FastAPI()

roles = {}
subscriptions = {}
orders = {}
order_steps = {}

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
        "👋 Добро пожаловать в WorkNadoJobBot!\n\n💼 Здесь заказчики и исполнители находят друг друга.",
        reply_markup=kb
    )

@dp.message(F.text == "👔 Я заказчик")
async def choose_customer(message: Message):
    roles[message.from_user.id] = "customer"
    await message.answer("Вы выбрали роль заказчика.", reply_markup=main_menu_customer)

@dp.message(F.text == "👤 Я исполнитель")
async def choose_worker(message: Message):
    roles[message.from_user.id] = "worker"
    await message.answer("Вы выбрали роль исполнителя.", reply_markup=main_menu_worker)

@dp.message(F.text == "📋 Вакансии")
async def show_vacancies(message: Message):
    role = roles.get(message.from_user.id)
    if role == "customer" and not has_active_subscription(message.from_user.id):
        await message.answer("❌ Для заказчиков доступ только по подписке.", reply_markup=main_menu_customer)
        return
    if not orders:
        await message.answer("Пока нет активных заказов.", reply_markup=back_button)
        return
    kb = InlineKeyboardMarkup()
    for order_id, order in orders.items():
        kb.add(InlineKeyboardButton(text=f"{order['title']} — {order['price']} ₽", callback_data=f"order_{order_id}"))
    await message.answer("✅ Список вакансий:", reply_markup=kb)

@dp.callback_query(F.data.startswith("order_"))
async def order_detail(callback):
    order_id = callback.data.split("_")[1]
    order = orders.get(order_id)
    if not order:
        await callback.message.edit_text("❌ Заказ не найден.")
        return
    text = (f"📋 *{order['title']}*\n"
            f"💰 Оплата: {order['price']} ₽\n"
            f"⏰ Срок: {order['deadline']}\n"
            f"📝 Описание: {order['description']}")
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton(text="✅ Откликнуться", callback_data=f"apply_{order_id}"))
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("apply_"))
async def apply_order(callback):
    order_id = callback.data.split("_")[1]
    order = orders.get(order_id)
    if order:
        customer_id = order['customer_id']
        await bot.send_message(customer_id, f"👤 Исполнитель @{callback.from_user.username} откликнулся на ваш заказ '{order['title']}'!")
        await callback.answer("Отклик отправлен!")

@dp.message(F.text == "📝 Создать заказ")
async def create_order(message: Message):
    if roles.get(message.from_user.id) != "customer":
        await message.answer("❌ Только заказчики могут создавать заказы.", reply_markup=main_menu_customer)
        return
    if not has_active_subscription(message.from_user.id):
        await message.answer("❌ Для создания заказов нужна подписка.", reply_markup=main_menu_customer)
        return
    order_steps[message.from_user.id] = {"step": "title"}
    await message.answer("Введите краткое название заказа:", reply_markup=back_button)

@dp.message()
async def process_order_steps(message: Message):
    step_data = order_steps.get(message.from_user.id)
    if not step_data:
        return
    step = step_data["step"]
    if step == "title":
        step_data["title"] = message.text
        step_data["step"] = "description"
        await message.answer("Введите описание заказа:")
    elif step == "description":
        step_data["description"] = message.text
        step_data["step"] = "deadline"
        await message.answer("Укажите срок выполнения (например: 3 дня):")
    elif step == "deadline":
        step_data["deadline"] = message.text
        step_data["step"] = "price"
        await message.answer("Укажите сумму оплаты (в ₽):")
    elif step == "price":
        step_data["price"] = message.text
        order_id = str(uuid.uuid4())
        orders[order_id] = {
            "title": step_data["title"],
            "description": step_data["description"],
            "deadline": step_data["deadline"],
            "price": step_data["price"],
            "customer_id": message.from_user.id
        }
        del order_steps[message.from_user.id]
        await message.answer("✅ Заказ опубликован!", reply_markup=main_menu_customer)

@dp.message(F.text == "💳 Купить подписку")
async def buy_subscription(message: Message):
    if roles.get(message.from_user.id) != "customer":
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
    response = requests.post(
        "https://api.yookassa.ru/v3/payments",
        auth=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET),
        json=data,
        headers={"Content-Type": "application/json", "Idempotence-Key": idempotence_key}
    )
    payment = response.json()
    if "confirmation" not in payment:
        await message.answer(f"⚠️ Ошибка при создании платежа: {payment}", reply_markup=main_menu_customer)
        return
    confirmation_url = payment["confirmation"]["confirmation_url"]
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Оплатить через ЮKassa", url=confirmation_url)]])
    await message.answer(f"💰 Подписка на 30 дней — {amount} ₽. После оплаты доступ откроется автоматически.", reply_markup=kb)

@dp.message(F.text == "⬅️ Назад")
async def go_back(message: Message):
    role = roles.get(message.from_user.id)
    if role == "customer":
        await message.answer("Вы вернулись в меню.", reply_markup=main_menu_customer)
    elif role == "worker":
        await message.answer("Вы вернулись в меню.", reply_markup=main_menu_worker)
    else:
        await start(message)

@app.post("/yookassa/callback")
async def yookassa_callback(request: Request):
    data = await request.json()
    if data.get("event") == "payment.succeeded":
        user_id = int(data["object"]["metadata"]["user_id"])
        subscriptions[user_id] = datetime.datetime.now() + datetime.timedelta(days=30)
        await bot.send_message(user_id, "✅ Оплата получена! Подписка активна.", reply_markup=main_menu_customer)
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
