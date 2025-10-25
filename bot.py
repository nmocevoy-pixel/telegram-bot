import os
import random
import json
import io
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# === НАСТРОЙКИ ===
TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("Переменная окружения TELEGRAM_TOKEN не задана!")

IMAGES_ROOT = "images"
STATS_FILE = "stats.json"
USER_UPLOADS_ROOT = "user_uploads"

CATEGORIES = {
    "feet": "Ножки 🦶",
    "breast": "Грудь 🍒",
    "ass": "Попы 🍑",
}

user_state: dict[int, dict] = {}

# === УТИЛИТЫ ДЛЯ СТАТИСТИКИ ===
def load_stats() -> dict:
    data = {}
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    return data


def save_stats(data: dict) -> None:
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


stats = load_stats()
save_stats(stats)

# === ГАЛЕРЕЯ ПОЛЬЗОВАТЕЛЯ ===
def get_user_folder(user_id: int) -> str:
    folder = os.path.join(USER_UPLOADS_ROOT, str(user_id))
    os.makedirs(folder, exist_ok=True)
    return folder


def list_user_photos(user_id: int) -> list[str]:
    folder = get_user_folder(user_id)
    files = [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ]
    files.sort(key=lambda p: os.path.getmtime(p))
    return files


# === УТИЛИТЫ ===
def load_photos_for_category(category: str):
    folder = os.path.join(IMAGES_ROOT, category)
    if not os.path.isdir(folder):
        return []
    return [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ]


def main_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(CATEGORIES["feet"], callback_data="category:feet"),
        InlineKeyboardButton(CATEGORIES["breast"], callback_data="category:breast"),
        InlineKeyboardButton(CATEGORIES["ass"], callback_data="category:ass"),
    ], [
        InlineKeyboardButton("🎞 Играть с моими фото", callback_data="category:myphotos")
    ]]
    return InlineKeyboardMarkup(rows)


# === ХЭНДЛЕРЫ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = str(user.id)
    display_name = user.full_name or user.username or user_id

    entry = stats.get(user_id, {"uses": 0, "last_seen": None, "name": display_name})
    entry["uses"] = int(entry.get("uses", 0)) + 1
    entry["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry["name"] = display_name
    stats[user_id] = entry
    save_stats(stats)

    await context.bot.send_message(
        chat_id=chat_id,
        text="Привет! 🎮 Выбери категорию для игры или используй свои фото:",
        reply_markup=main_menu_keyboard(),
    )


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Выбери категорию:", reply_markup=main_menu_keyboard())


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not stats:
        await update.message.reply_text("Пока нет статистики.")
        return

    def _uses(v):
        try:
            return int(v.get("uses", 0))
        except Exception:
            return 0

    total_users = len(stats)
    total_uses = sum(_uses(v) for v in stats.values())
    sorted_items = sorted(stats.items(), key=lambda kv: _uses(kv[1]), reverse=True)

    lines = []
    for uid, s in sorted_items[:10]:
        name = s.get("name", uid)
        uses = _uses(s)
        last_seen = s.get("last_seen", "—")
        lines.append(f"• {name} — {uses} запуск(ов), последний визит: {last_seen}")

    await update.message.reply_text(
        f"📊 <b>Статистика</b>\n👥 Пользователей: {total_users}\n▶️ Запусков: {total_uses}\n\n"
        + "\n".join(lines),
        parse_mode="HTML",
    )


# === ИГРА ===
async def on_category_pick(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if category == "myphotos":
        photos = list_user_photos(user_id)
        if len(photos) < 2:
            await context.bot.send_message(chat_id=chat_id, text="Загрузи хотя бы 2 своих фото, чтобы начать! 📸")
            return
    else:
        photos = load_photos_for_category(category)
        if len(photos) < 2:
            await context.bot.send_message(chat_id=chat_id, text=f"Недостаточно фото в {category}.")
            return

    random.shuffle(photos)
    user_state[user_id] = {"index": 1, "winner": photos[0], "order": photos, "chat_id": chat_id, "category": category}
    await send_pair(context, user_id)


async def send_pair(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = user_state[user_id]
    chat_id = state["chat_id"]
    current_index = state["index"]
    order = state["order"]

    if current_index >= len(order):
        with open(state["winner"], "rb") as f:
            await context.bot.send_photo(chat_id=chat_id, photo=f, caption="🏆 Победитель!")
        del user_state[user_id]
        await context.bot.send_message(chat_id=chat_id, text="Хочешь ещё раунд?", reply_markup=main_menu_keyboard())
        return

    winner_photo = state["winner"]
    next_photo = order[current_index]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Фото 1 ❤️", callback_data="pick:1"),
         InlineKeyboardButton("Фото 2 💙", callback_data="pick:2")]
    ])

    with open(winner_photo, "rb") as f1, open(next_photo, "rb") as f2:
        await context.bot.send_media_group(chat_id=chat_id, media=[InputMediaPhoto(f1), InputMediaPhoto(f2)])
    await context.bot.send_message(chat_id=chat_id, text="Выбери фото 👇", reply_markup=kb)


# === ЛИЧНАЯ ГАЛЕРЕЯ ===
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    folder = get_user_folder(user.id)
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{photo.file_unique_id}.jpg"
    path = os.path.join(folder, filename)
    await file.download_to_drive(path)

    await update.message.reply_text("✅ Фото сохранено в твою приватную галерею!\n"
                                    "• /myphotos — показать фото\n"
                                    "• /clear_my — удалить все\n"
                                    "• /play_my — играть с ними")


async def my_photos_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    photos = list_user_photos(user_id)
    if not photos:
        await context.bot.send_message(chat_id=chat_id, text="Ты ещё не загрузил фото.")
        return

    for path in photos[-6:]:
        base = os.path.basename(path)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ Удалить", callback_data=f"del:{base}")]])
        with open(path, "rb") as f:
            await context.bot.send_photo(chat_id=chat_id, photo=f, caption=base, reply_markup=kb)


async def clear_my_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    photos = list_user_photos(user_id)
    if not photos:
        await context.bot.send_message(chat_id=chat_id, text="Удалять нечего 😄")
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, удалить всё", callback_data="confirm_del_all"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_del_all")]
    ])
    await context.bot.send_message(chat_id=chat_id, text=f"Удалить {len(photos)} фото?", reply_markup=kb)


# === ОБРАБОТКА КНОПОК ===
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()

    if data.startswith("category:"):
        category = data.split(":", 1)[1]
        await on_category_pick(update, context, category)
        return

    if data.startswith("pick:"):
        state = user_state.get(user_id)
        if not state:
            await query.message.reply_text("Сессия закончилась.")
            return

        order = state["order"]
        current_index = state["index"]
        next_photo = order[current_index]
        state["winner"] = state["winner"] if data == "pick:1" else next_photo
        state["index"] += 1
        await query.message.reply_text("✅ Дальше!")
        await send_pair(context, user_id)
        return

    if data.startswith("del:"):
        base = data.split(":", 1)[1]
        folder = get_user_folder(user_id)
        path = os.path.join(folder, base)
        if os.path.isfile(path):
            os.remove(path)
            await query.message.delete()
        await query.message.reply_text("🗑️ Фото удалено.")
        return

    if data == "confirm_del_all":
        folder = get_user_folder(user_id)
        count = 0
        for f in os.listdir(folder):
            p = os.path.join(folder, f)
            if os.path.isfile(p):
                os.remove(p)
                count += 1
        await query.message.edit_text(f"Удалено {count} фото 🧹")
        return

    if data == "cancel_del_all":
        await query.message.edit_text("Отменено ❌")
        return


# === ЗАПУСК ===
if __name__ == "__main__":
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("myphotos", my_photos_cmd))
    app.add_handler(CommandHandler("clear_my", clear_my_cmd))
    app.add_handler(CommandHandler("play_my", lambda u, c: on_category_pick(u, c, "myphotos")))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(on_button))

    print("✅ Бот запущен и готов! PID:", os.getpid())
    app.run_polling()
