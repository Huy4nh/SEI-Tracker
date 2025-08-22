import os
from fastapi import FastAPI, Request
from aiogram import Dispatcher, types, Bot
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from html import escape

from chatbot import chatbot

# ===== Config =====
TOKEN = os.getenv("BOT_TOKEN", "7698200862:AAGawmKwiC7B_wGkM_LCH3Zc2UrCAMUTeAY")
WEBHOOK_HOST = "https://unified-wahoo-daring.ngrok-free.app"
WEBHOOK_PATH = "/ask"
WEBHOOK_URL = WEBHOOK_HOST + WEBHOOK_PATH

# ===== Init =====
app = FastAPI()
dp = Dispatcher()
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
llm = chatbot("claude-3-5-haiku-20241022")

# ===== Handlers =====
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Xin chào! Hỏi bất cứ điều gì về SEI.\n"
        "Khi cần bảng, bot sẽ tự vẽ ảnh PNG bằng tool."
    )

@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    llm.reset(str(message.chat.id))
    await message.answer("Đã xoá lịch sử hội thoại của chat này.")

@dp.message()
async def handle_text_message(message: Message):
    sid = str(message.chat.id)
    reply = llm.asking(message.text, session_id=sid, telegram=True)
    print(f"Reply: {reply}")
    # 1) Ảnh PNG nếu có
    for p in reply.get("images", []):
        try:
            await message.answer_photo(FSInputFile(p), caption="Bảng PNG")
        except Exception:
            pass

    # 2) Phần giải thích (HTML)
    if reply.get("text"):
        await message.answer(escape(reply["text"]), parse_mode=ParseMode.HTML)

# ===== Webhook =====
@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    update = types.Update(**await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()
