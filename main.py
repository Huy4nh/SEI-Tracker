import os
from fastapi import FastAPI, Request
from aiogram import Dispatcher, types, Bot
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from html import escape
from chatbot import chatbot
import os, asyncio, time, html
from aiogram.filters import Command
import re
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest
from aiogram.utils.chat_action import ChatActionSender
# ===== Config =====
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required. Please set it in your .env file")

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "Applying your own webhook host here")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/ask")
WEBHOOK_URL = WEBHOOK_HOST + WEBHOOK_PATH

app = FastAPI()
dp = Dispatcher()
bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2)
)
MDV2_SPECIALS = r"_*[]()~`>#+-=|{}.!\\"

llm = chatbot("claude-3-7-sonnet-20250219")

def mdv2_escape(s: str) -> str:
    if s is None:
        return ""
    # Các ký tự phải escape trong MarkdownV2 của Telegram
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', str(s))

def mdv2_escape_outside_code(text: str) -> str:
    """Escape MarkdownV2, nhưng giữ nguyên các block ```code```."""
    if not text:
        return ""
    parts = re.split(r"(```[\s\S]*?```)", text)
    out = []
    for p in parts:
        if p.startswith("```") and p.endswith("```"):
            # giữ nguyên code block
            out.append(p)
        else:
            # escape bên ngoài code
            p = re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", p)
            out.append(p)
    return "".join(out)

def mdv2_escape_inline(text: str) -> str:
    """Escape cho đoạn inline (không có code fence)."""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", text or "")

# ============ Helper chung ============
async def _safe_edit(msg: types.Message, md_text: str):
    async def _do():
        text = md_text
        if len(text) > 3900:
            text = text[:3900] + "…"
        await msg.edit_text(
            text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True
        )

    try:
        await _do()
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 0.1)
        try:
            await _do()
        except Exception:
            try:
                await msg.bot.send_message(
                    chat_id=msg.chat.id,
                    text=md_text[:3900] + ("…" if len(md_text) > 3900 else ""),
                    parse_mode=ParseMode.MARKDOWN_V2,
                    disable_web_page_preview=True
                )
            except Exception:
                pass
    except TelegramBadRequest as e:
        s = str(e).lower()
        if "message is not modified" in s:
            return
        try:
            await msg.bot.send_message(
                chat_id=msg.chat.id,
                text=md_text[:3900] + ("…" if len(md_text) > 3900 else ""),
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True
            )
        except Exception:
            pass
    except Exception:
        pass

# ================= Handlers =================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    start_text = (
        "Xin chào! Đây là bot SEI.\n"
        "Mình sẽ rót câu trả lời theo từng phần (stream). Nếu cần bảng, bot sẽ gửi ảnh PNG.\n"
        "Cứ hỏi đi 🧠"
    )
    await message.answer(mdv2_escape_outside_code(start_text), parse_mode=ParseMode.MARKDOWN_V2)

@dp.message()
async def handle_text_message(message: Message):
    best_text = ""
    # Lấy nội dung text/caption (nếu không có thì báo nhẹ)
    user_text = message.text or message.caption or ""
    if not user_text.strip():
        await message.answer(mdv2_escape_outside_code("Hiện tại bot chỉ hỗ trợ tin nhắn văn bản 📄"), parse_mode=ParseMode.MARKDOWN_V2)
        # đừng gửi thêm "Đang xử lý..." nữa
        return

    sid = str(message.chat.id)
    out_msg = await message.answer(
        mdv2_escape_inline("⏳ Đang xử lý..."),
        parse_mode=ParseMode.MARKDOWN_V2
    )

    loop = asyncio.get_running_loop()
    buf_text = ""
    tool_lines: list[str] = []
    last_edit = 0.0
    EDIT_INTERVAL = 0.2  # an toàn hơn cho Telegram
    MAX_TOOL_LINES = 8
    last_sent_html = ""   # chống edit trùng
    edit_lock = asyncio.Lock()  # serialize edit

    async def _edit_serialized(msg: types.Message, html_text: str):
        async with edit_lock:
            await _safe_edit(msg, html_text)

    def _post_task(coro, label: str = ""):
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        def _cb(f):
            try:
                f.result()
            except Exception as e:
                print(f"[ERR {label}] {type(e).__name__}: {e}", flush=True)
        fut.add_done_callback(_cb)
        return fut

    async def _send_photo(msg: types.Message, path: str, caption: str | None = None):
        p = os.path.abspath((path or "").strip().strip('"').strip("'"))
        print(f"[SEND PHOTO] try -> {p}", flush=True)
        if not os.path.exists(p):
            print(f"[MISS PHOTO] {p}", flush=True)
            await msg.answer(
                mdv2_escape_inline(f"⚠️ Không tìm thấy file ảnh: {p}"),
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return False
        await msg.answer_photo(
            FSInputFile(p),
            caption=caption or "",
            parse_mode=None  # KHÔNG dùng MDV2 cho caption
        )
        print(f"[SENT PHOTO ✅] {p}", flush=True)
        return True

    # Đẩy coroutine về event loop từ thread khác
    def _post(coro):
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception:
            pass

    # Hàm cập nhật UI gộp phần văn bản + phần tool
    def _compose_and_edit():
        nonlocal last_sent_html
        # làm sạch ngay trong lúc stream để UI không lộ 'sei:...' hay ảnh markdown
        main = buf_text
        main = re.sub(r'(?m)^\s*sei[:_][\w:]+(?:\([^)]*\))?\s*$', '', main)   # xóa dòng 'sei:staking_apr' / 'sei:...()'
        main = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', main)                      # xóa ![...](...)
        main = re.sub(r'\n{3,}', '\n\n', main).strip()

        safe_main = mdv2_escape_outside_code(main)
        if tool_lines:
            safe_main = f"{safe_main}\n\n" + "\n".join(tool_lines)

        if safe_main == last_sent_html:
            return
        last_sent_html = safe_main
        _post(_edit_serialized(out_msg, safe_main))



    # Sink nhận sự kiện streaming từ LLM
    def sink(ev: dict):
        nonlocal buf_text, tool_lines, last_edit, last_sent_html, best_text
        t = ev.get("type")
        now = time.monotonic()
        if t == "tool_call":
            # Ẩn tool_call khỏi UI người dùng
            # (tuỳ chọn) in terminal để debug:
            try:
                print(f"[TOOL CALL] {ev.get('name')} args={ev.get('args')}", flush=True)
            except Exception:
                pass
            # KHÔNG append vào tool_lines
            if (now - last_edit) >= EDIT_INTERVAL:
                _compose_and_edit()
                last_edit = now

        # elif t == "tool_result":
        #     image_path = ev.get("image_path")
        #     tool_text  = ev.get("text")

        #     if image_path:
        #         try:
        #             import os
        #             abspath = os.path.abspath(image_path)
        #             print(f"[SEND PHOTO] -> {abspath}", flush=True)   # <— log terminal
        #             if not os.path.exists(abspath):
        #                 _post(message.answer(
        #                     mdv2_escape_inline(f"⚠️ Không tìm thấy file ảnh: {abspath}")
        #                 ))
        #             else:
        #                 _post(message.answer_photo(
        #                     FSInputFile(abspath),
        #                     caption="Bảng đã tạo",   # caption thuần
        #                     parse_mode=None          # tắt MDV2 ở ảnh
        #                 ))
        #                 # Tuỳ bạn: có thể hiển thị dòng xác nhận thay vì 'gọi tool'
        #                 tool_lines.append(mdv2_escape_inline("📷 Ảnh bảng đã gửi."))
        #         except Exception as e:
        #             _post(message.answer(
        #                 mdv2_escape_inline(f"Lỗi gửi ảnh: {type(e).__name__}: {e}")
        #             ))
        #         return
        elif t == "tool_result":
            image_path = ev.get("image_path")
            tool_text  = ev.get("text")

            if image_path:
                print(f"[SEND PHOTO] (tool) -> {image_path}", flush=True)
                _post_task(_send_photo(message, image_path, "Bảng đã tạo"), "send_photo_tool")
                # (tuỳ chọn) hiển thị 1 dòng xác nhận
                tool_lines.append(mdv2_escape_inline("📷 Ảnh bảng đã gửi."))
                return

            # nếu muốn hiển thị text rút gọn từ tool:
            if tool_text and tool_text.strip():
                snippet = tool_text.strip()
                if len(snippet) > 600: snippet = snippet[:600] + "…"
                tool_lines.append("🔎 " + mdv2_escape_outside_code(snippet))
                if len(tool_lines) > MAX_TOOL_LINES:
                    tool_lines[:] = tool_lines[-MAX_TOOL_LINES:]
                if (now - last_edit) >= EDIT_INTERVAL:
                    _compose_and_edit()
                    last_edit = now



        elif t == "text_delta":
            delta = ev.get("text", "")
            if not delta:
                return
            buf_text += delta
            # luôn cập nhật best_text
            nonlocal best_text
            if len(buf_text) > len(best_text):
                best_text = buf_text
            if (now - last_edit) >= EDIT_INTERVAL or ("\n" in delta):
                _compose_and_edit()
                last_edit = now
            try:
                print(delta, end="", flush=True)
            except Exception:
                pass


        elif t == "done":
            # Gửi ảnh chốt (như bạn đang làm) ...
            for p in ev.get("images") or []:
                try:
                    print(f"[SEND PHOTO] (final) -> {p}", flush=True)
                    # _post_task(_send_photo(message, p, "Kết quả"), "send_photo_final")
                    # tool_lines.append(mdv2_escape_inline("📷 Ảnh bảng đã gửi."))
                except Exception as e:
                    _post(message.answer(
                        mdv2_escape_outside_code(f"Lỗi gửi ảnh: {type(e).__name__}: {e}"),
                        parse_mode=ParseMode.MARKDOWN_V2
                    ))

            # Ưu tiên bản dài nhất giữa ev.final_text và best_text/buf_text
            ft = (ev.get("final_text") or "").strip()
            candidate = ft if len(ft) >= len(best_text) else best_text
            candidate = candidate.strip() or "(đang trống)"

            # Lọc rác lần cuối ở UI: xóa dòng 'sei:...' & markdown images nếu còn
            candidate = re.sub(r'(?m)^\s*sei[:_][\w:]+(?:\([^)]*\))?\s*$', '', candidate)
            candidate = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', candidate)
            candidate = re.sub(r'\n{3,}', '\n\n', candidate).strip()

            safe = mdv2_escape_outside_code(candidate)
            if tool_lines:
                safe = f"{safe}\n\n" + "\n".join(tool_lines)

            async def _final():
                await asyncio.sleep(0.7)
                await _edit_serialized(out_msg, safe)
            _post(_final())


    # Chạy LLM (tự nhận diện kiểu trả về: generator hay dict)
    def run_llm():
        # try:
        rv = llm.asking_stream(
            user_text,
            session_id=sid,
            telegram=True,
            sink=sink,
            print_live=True # in ra UI qua sink, không in console
        )

        # Trường hợp 1: asking_stream là GENERATOR -> iterate để nhận event
        is_generator_like = hasattr(rv, "__iter__") and not isinstance(rv, dict) and not isinstance(rv, (str, bytes))
        if is_generator_like:
            for _ in rv:
                pass
            return

        # Trường hợp 2: asking_stream trả DICT (tự in nội bộ + trả kết quả cuối)
        if isinstance(rv, dict):
            ev = {"type": "done", "final_text": rv.get("text") or "", "images": rv.get("images") or []}
            sink(ev)
            return

        # Trường hợp lạ: vẫn kết thúc gọn bằng done rỗng để UI update
        sink({"type": "done", "final_text": "", "images": []})

        # except Exception as e:
        #     # Báo lỗi lên UI nhưng không làm crash request
        #     _post(_safe_edit(out_msg, f"❌ Lỗi xử lý: <code>{html.escape(type(e).__name__)}: {html.escape(str(e))}</code>"))

    # Gọi executor để không block event loop
    fut = loop.run_in_executor(None, run_llm)

    # Giữ trạng thái 'typing...' xuyên suốt đến khi LLM xong
    async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
        await fut  # đợi stream hoàn tất
        # except Exception as e:
        #     # Chặn 500 & báo lỗi ra chat
        #     err = f"❌ Lỗi xử lý ngoài: <code>{html.escape(type(e).__name__)}: {html.escape(str(e))}</code>"
        #     await _safe_edit(out_msg, err)


# ================= Webhook =================
@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    update = types.Update(**await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.on_event("startup")
async def on_startup():
    try:
        await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
    except Exception as e:
        print("Set webhook error:", e)

@app.on_event("shutdown")
async def on_shutdown():
    try:
        await bot.delete_webhook()
    except Exception:
        pass