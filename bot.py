# -*- coding: utf-8 -*-
"""
Telegram-бот на aiogram 3 с:
- красивым меню (Reply-кнопки),
- пересылкой сообщений администратору ("Связаться со мной", "Предложение"),
- анонимной пересылкой жалоб ("Жалоба или просьба"),
- защитой от спама (1 сообщение в 60 секунд на пользователя),
- возможностью администратора отвечать пользователю прямо ответом (reply)
  на пересланное сообщение в Telegram — бот сам доставит ответ адресату.

Установка:
    pip install -r requirements.txt

Запуск:
    python bot.py
"""

import asyncio
import logging
from datetime import datetime
from html import escape as h

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

# ==================== НАСТРОЙКИ ====================

BOT_TOKEN = "8975069743:AAHKzk3m8BmP308DjLK5TU1a4oB10GYnDdE"   # <-- замените на токен вашего бота
ADMIN_ID = 6830774352                    # <-- замените на свой Telegram ID (узнать: команда /id)

SPAM_INTERVAL = 60  # минимальный интервал между сообщениями пользователя, секунд

ABOUT_TEXT = (
    "🕵️ <b>Кто я такой?</b>\n\n"
    "Привет! Это бот для связи со мной.\n\n"
    "Через меня можно:\n"
    "• написать мне напрямую,\n"
    "• предложить идею или сотрудничество,\n"
    "• оставить анонимную жалобу или просьбу.\n\n"
    "Связь: @ваш_юзернейм"
)

logging.basicConfig(level=logging.INFO)

# ==================== СОСТОЯНИЯ (FSM) ====================

class Form(StatesGroup):
    contact = State()
    suggestion = State()
    complaint = State()


# ==================== ТЕКСТЫ КНОПОК ====================

BTN_CONTACT = "📩 Связаться со мной"
BTN_SUGGEST = "💡 Есть интересное предложение?"
BTN_COMPLAINT = "⚠️ Жалоба или просьба"
BTN_ABOUT = "🕵️ Кто я такой?"
BTN_CANCEL = "❌ Отмена"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CONTACT)],
            [KeyboardButton(text=BTN_SUGGEST)],
            [KeyboardButton(text=BTN_COMPLAINT)],
            [KeyboardButton(text=BTN_ABOUT)],
        ],
        resize_keyboard=True,
    )


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
    )


# ==================== АНТИСПАМ ====================
# Простое хранение в памяти: user_id -> время последнего отправленного сообщения.
# Для продакшена с несколькими процессами лучше использовать Redis.

user_last_message: dict[int, float] = {}


def check_spam(user_id: int) -> float:
    """Возвращает 0, если можно отправлять, иначе — сколько секунд ещё ждать."""
    now = datetime.now().timestamp()
    last = user_last_message.get(user_id, 0)
    elapsed = now - last
    if elapsed < SPAM_INTERVAL:
        return round(SPAM_INTERVAL - elapsed)
    return 0


def mark_message_sent(user_id: int) -> None:
    user_last_message[user_id] = datetime.now().timestamp()


# ==================== СВЯЗЬ "ОТВЕТ АДМИНА -> ПОЛЬЗОВАТЕЛЬ" ====================
# Когда бот пересылает сообщение админу, мы запоминаем:
#   message_id (в чате админа) -> user_id (кому переслать ответ)
# Если админ отвечает (Reply) на это сообщение в Telegram — бот доставит
# его ответ обратно отправителю. Для жалоб это происходит без раскрытия
# личности — админ просто отвечает на сообщение, не видя, кто его автор.

reply_map: dict[int, int] = {}


# ==================== РОУТЕР ====================

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Привет! Выбери, что тебя интересует:",
        reply_markup=main_menu(),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("📋 Главное меню:", reply_markup=main_menu())


@router.message(Command("id"))
async def cmd_id(message: Message):
    # Удобная команда, чтобы быстро узнать свой Telegram ID для настройки ADMIN_ID
    await message.answer(f"🆔 Твой Telegram ID: <code>{message.from_user.id}</code>")


@router.message(Command("cancel"))
@router.message(F.text == BTN_CANCEL)
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нет активного действия для отмены.", reply_markup=main_menu())
        return
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_menu())


# ---------- Ответ администратора пользователю ----------

@router.message(F.chat.id == ADMIN_ID, F.reply_to_message)
async def admin_reply(message: Message, bot: Bot):
    replied_id = message.reply_to_message.message_id
    user_id = reply_map.get(replied_id)

    if user_id is None:
        await message.answer(
            "⚠️ Не удалось определить адресата (сообщение слишком старое "
            "или бот был перезапущен — связи сбрасываются)."
        )
        return

    try:
        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=ADMIN_ID,
            message_id=message.message_id,
        )
        await message.answer("✅ Ответ отправлен.")
    except TelegramBadRequest:
        await message.answer(
            "⚠️ Не удалось доставить ответ. Возможно, пользователь заблокировал бота."
        )


# ---------- Кнопка "Кто я такой?" ----------

@router.message(F.text == BTN_ABOUT)
async def about(message: Message):
    await message.answer(ABOUT_TEXT, reply_markup=main_menu())


# ---------- Кнопки, запускающие диалог ----------

@router.message(F.text == BTN_CONTACT)
async def ask_contact(message: Message, state: FSMContext):
    await state.set_state(Form.contact)
    await message.answer(
        "📩 Напиши своё сообщение — я передам его адресату.\n"
        "Можно отправить текст, фото, видео, документ или голосовое сообщение.\n\n"
        "Для отмены нажми «❌ Отмена».",
        reply_markup=cancel_menu(),
    )


@router.message(F.text == BTN_SUGGEST)
async def ask_suggestion(message: Message, state: FSMContext):
    await state.set_state(Form.suggestion)
    await message.answer(
        "💡 Опиши своё предложение — оно обязательно будет рассмотрено!\n\n"
        "Для отмены нажми «❌ Отмена».",
        reply_markup=cancel_menu(),
    )


@router.message(F.text == BTN_COMPLAINT)
async def ask_complaint(message: Message, state: FSMContext):
    await state.set_state(Form.complaint)
    await message.answer(
        "⚠️ Напиши свою жалобу или просьбу.\n"
        "Сообщение будет отправлено <b>полностью анонимно</b> — без указания "
        "твоего имени, username и ID.\n\n"
        "Для отмены нажми «❌ Отмена».",
        reply_markup=cancel_menu(),
    )


# ---------- Универсальная логика пересылки ----------

async def forward_to_admin(
    message: Message,
    state: FSMContext,
    bot: Bot,
    anonymous: bool,
    label: str,
) -> None:
    user_id = message.from_user.id

    wait_left = check_spam(user_id)
    if wait_left > 0:
        await message.answer(
            f"⏳ Слишком часто! Подожди ещё {wait_left} сек. перед отправкой нового сообщения."
        )
        return

    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")

    if anonymous:
        header_text = f"{label}\n🕓 {timestamp}"
    else:
        user = message.from_user
        username = f"@{h(user.username)}" if user.username else "нет username"
        header_text = (
            f"{label}\n"
            f"👤 Имя: {h(user.full_name)}\n"
            f"🔗 Username: {username}\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"🕓 {timestamp}"
        )

    try:
        header_msg = await bot.send_message(ADMIN_ID, header_text)
        content_msg = await bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except TelegramBadRequest as e:
        logging.error("Ошибка пересылки администратору: %s", e)
        await message.answer(
            "⚠️ Не удалось отправить сообщение. Попробуй позже.",
            reply_markup=main_menu(),
        )
        return

    # Запоминаем, кому переслать ответ админа (даже для анонимных сообщений —
    # сама личность отправителя при этом администратору не показывается).
    reply_map[header_msg.message_id] = user_id
    reply_map[content_msg.message_id] = user_id

    mark_message_sent(user_id)
    await state.clear()
    await message.answer("✅ Сообщение отправлено! Спасибо.", reply_markup=main_menu())


@router.message(Form.contact)
async def process_contact(message: Message, state: FSMContext, bot: Bot):
    await forward_to_admin(message, state, bot, anonymous=False, label="📩 Новое сообщение")


@router.message(Form.suggestion)
async def process_suggestion(message: Message, state: FSMContext, bot: Bot):
    await forward_to_admin(message, state, bot, anonymous=False, label="💡 Новое предложение")


@router.message(Form.complaint)
async def process_complaint(message: Message, state: FSMContext, bot: Bot):
    await forward_to_admin(message, state, bot, anonymous=True, label="⚠️ Анонимная жалоба/просьба")


# ---------- Фоллбэк на любые прочие сообщения ----------

@router.message()
async def fallback(message: Message):
    await message.answer(
        "Пожалуйста, выбери действие из меню 👇",
        reply_markup=main_menu(),
    )


# ==================== ЗАПУСК ====================

async def main() -> None:
    if BOT_TOKEN == "ВАШ_ТОКЕН_ОТ_BOTFATHER":
        raise SystemExit(
            "Укажи свой токен в переменной BOT_TOKEN в начале файла bot.py "
            "(получить у @BotFather)."
        )

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Бот запущен.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
