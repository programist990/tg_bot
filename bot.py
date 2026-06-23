# -*- coding: utf-8 -*-
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

BOT_TOKEN = "8975069743:AAHKzk3m8BmP308DjLK5TU1a4oB10GYnDdE"   
ADMIN_ID = 6830774352                    

ABOUT_TEXT = (
    "🕵️ <b>Кто я такой?</b>\n\n"
    "Привет! Это бот для связи со мной.\n\n"
    "Через меня можно:\n"
    "• написать мне напрямую,\n"
    "• предложить идею или сотрудничество,\n"
    "• оставить анонимную жалобу или просьбу.\n\n"
    "Связь: @Daviid033"
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
            [KeyboardButton(text="🚫 Не нажимать")],  
        ],
        resize_keyboard=True,
    )


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
    )


# ==================== СВЯЗЬ "ОТВЕТ АДМИНА -> ПОЛЬЗОВАТЕЛЬ" ====================

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
            "или бот был перезапущен)."
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

@router.message(F.text == "🚫 Не нажимать")
async def dont_press(message: Message):
    await message.answer_photo(
        photo="https://i.pinimg.com/736x/3d/03/5c/3d035cf5c1dd05be1964b8b58bee16b3.jpg",
    )


async def forward_to_admin(
    message: Message,
    state: FSMContext,
    bot: Bot,
    anonymous: bool,
    label: str,
) -> None:
    user_id = message.from_user.id
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
        await state.clear()
        return

    reply_map[header_msg.message_id] = user_id
    reply_map[content_msg.message_id] = user_id

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
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Бот запущен.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
