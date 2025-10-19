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
keyboard=[[KeyboardButton(text="📋 Вакансии")]], resize_keyboard=True
)


back_button = ReplyKeyboardMarkup(
keyboard=[[KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True
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
asyncio.run(main())
