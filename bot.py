import os
import random
import json
import io
from datetime import datetime

# === для графика в /stats ===
import matplotlib
matplotlib.use("Agg")  # без GUI — удобно на Windows/сервере
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
)

# === НАСТРОЙКИ ===
TOKEN = os.getenv("BOT_TOKEN")
IMAGES_ROOT = "images"      # ожидается: images/feet, images/breast, images/ass
STATS_FILE = "stats.json"   # тут копим статистику

# Категории для меню
CATEGORIES = {
    "feet": "Ножки 🦶",
    "breast": "Грудь 🍒",
    "ass": "Попы 🍑",
}

# состояние игры: {user_id: {"index": int, "winner": str, "order": list[str], "chat_id": int, "category": str}}
user_state: dict[int, dict] = {}

# === СТАТИСТИКА ===
def load_stats() -> dict:
    """Загружаем статистику и приводим к нормальной схеме.
       Допускаем старый формат: {user_id: 3} -> {uses:3, ...}"""
    data = {}
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if isinstance(raw, dict):
                    for uid, v in raw.items():
                        if isinstance(v, int):
                            data[uid] = {"uses": int(v), "last_seen": None, "name": None}
                        elif isinstance(v, dict):
                            data[uid] = {
                                "uses": int(v.get("uses", 0)),
                                "last_seen": v.get("last_seen"),
                                "name": v.get("name"),
                            }
                        # если тип неизвестен — пропускаем запись
        except Exception:
            pass
    return data

def save_stats(data: dict) -> None:
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

stats = load_stats()
# сразу перезапишем нормализованный файл (без мусора)
save_stats(stats)


# === УТИЛИТЫ ===
def load_photos_for_category(category: str):
    """Возвращает список путей к фоткам для выбранной категории."""
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
        InlineKeyboardButton(CATEGORIES["feet"],   callback_data="category:feet"),
        InlineKeyboardButton(CATEGORIES["breast"], callback_data="category:breast"),
        InlineKeyboardButton(CATEGORIES["ass"],    callback_data="category:ass"),
    ]]
    return InlineKeyboardMarkup(rows)


# === ХЭНДЛЕРЫ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветствие + выбор категории + обновление статистики."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id
    user_id_str = str(user_id)
    display_name = user.full_name or (user.username and f"@{user.username}") or user_id_str

    # обновляем статистику (без глобального присваивания — меняем словарь по месту)
    entry = stats.get(user_id_str, {"uses": 0, "last_seen": None, "name": None})
    entry["uses"] = int(entry.get("uses", 0)) + 1
    entry["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not entry.get("name"):
        entry["name"] = display_name
    stats[user_id_str] = entry
    save_stats(stats)

    text = (
        "Привет! Выбери категорию, в которой будем сравнивать фото:\n\n"
        f"{CATEGORIES['feet']}  |  {CATEGORIES['breast']}  |  {CATEGORIES['ass']}\n\n"
        "В любой момент открой меню — команда /menu"
    )
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=main_menu_keyboard())


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать меню категорий."""
    await update.message.reply_text("Выбери категорию:", reply_markup=main_menu_keyboard())


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Красивый /stats: текст + бар-диаграмма (топ-20 по запускам)."""
    if not stats:
        await update.message.reply_text("Пока нет статистики.")
        return

    # безопасные вычисления даже при странных значениях
    def _uses(v):
        try:
            return int(v.get("uses", 0)) if isinstance(v, dict) else int(v)
        except Exception:
            return 0

    total_users = len(stats)
    total_uses = sum(_uses(v) for v in stats.values())

    # отсортируем по uses по убыванию
    sorted_items = sorted(
        stats.items(),
        key=lambda kv: _uses(kv[1]),
        reverse=True
    )

    # текст — ограничим топ-50
    lines = []
    for uid, s in sorted_items[:50]:
        if isinstance(s, dict):
            name = s.get("name") or uid
            uses = _uses(s)
            last_seen = s.get("last_seen", "—")
        else:
            name = uid
            uses = _uses(s)
            last_seen = "—"
        lines.append(f"• {name} — {uses} запуск(ов), последний визит: {last_seen}")

    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Пользователей: <b>{total_users}</b>\n"
        f"▶️ Запусков всего: <b>{total_uses}</b>\n\n"
        + ("\n".join(lines) if lines else "Пока пусто")
    )
    await update.message.reply_text(text, parse_mode="HTML")

    # график — топ-20
    top_for_chart = sorted_items[:20]
    labels, values = [], []
    for uid, s in top_for_chart:
        if isinstance(s, dict):
            name = s.get("name") or uid
            val = _uses(s)
        else:
            name = uid
            val = _uses(s)
        label = name if len(str(name)) <= 14 else (str(name)[:12] + "…")
        labels.append(label)
        values.append(val)

    if any(values):
        fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
        ax.bar(labels, values)
        ax.set_title("Запуски по пользователям (топ-20)")
        ax.set_ylabel("Кол-во запусков")
        ax.set_xlabel("Пользователи")
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)

        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=buf,
            caption="График запусков (топ-20 по количеству)",
        )
    else:
        await update.message.reply_text("Пока график пуст — запусков ещё нет.")


async def on_category_pick(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str):
    """Запустить новую «сессию сравнения» по категории."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    photos = load_photos_for_category(category)
    if len(photos) < 2:
        nice_name = CATEGORIES.get(category, category)
        await context.bot.send_message(
            chat_id=chat_id,
            text=(f"В категории {nice_name} недостаточно фото. "
                  f"Положи минимум 2 файла (.jpg/.jpeg/.png) в папку {IMAGES_ROOT}/{category} и попробуй снова."),
        )
        return

    random.shuffle(photos)
    user_state[user_id] = {
        "index": 1,
        "winner": photos[0],
        "order": photos,
        "chat_id": chat_id,
        "category": category,
    }
    await send_pair(context, user_id)


async def send_pair(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Отправляем пару фото для выбора (через chat_id из состояния)."""
    state = user_state[user_id]
    chat_id = state["chat_id"]
    current_index = state["index"]
    order = state["order"]

    # если фото закончились — показываем победителя
    if current_index >= len(order):
        with open(state["winner"], "rb") as f:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=f,
                caption=f"🏆 Победитель в категории {CATEGORIES.get(state['category'], state['category'])}!",
            )
        del user_state[user_id]
        # предложим заново выбрать категорию
        await context.bot.send_message(chat_id=chat_id, text="Хочешь ещё раунд? Выбирай категорию:", reply_markup=main_menu_keyboard())
        return

    winner_photo = state["winner"]
    next_photo = order[current_index]

    keyboard = [[
        InlineKeyboardButton("Фото 1 ❤️", callback_data="pick:1"),
        InlineKeyboardButton("Фото 2 💙", callback_data="pick:2"),
    ]]
    markup = InlineKeyboardMarkup(keyboard)

    # сначала альбом, потом кнопки
    with open(winner_photo, "rb") as f1, open(next_photo, "rb") as f2:
        media = [
            InputMediaPhoto(f1, caption="Фото 1 ❤️"),
            InputMediaPhoto(f2, caption="Фото 2 💙"),
        ]
        await context.bot.send_media_group(chat_id=chat_id, media=media)

    await context.bot.send_message(chat_id=chat_id, text="Выбери, какое тебе больше нравится 👇", reply_markup=markup)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Общий обработчик inline-кнопок."""
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()

    # выбор категории
    if data.startswith("category:"):
        category = data.split(":", 1)[1]
        await on_category_pick(update, context, category)
        return

    # выбор победителя (1/2)
    if data.startswith("pick:"):
        state = user_state.get(user_id)
        if not state:
            await query.message.reply_text("Сессия закончилась. Нажми /menu.")
            return

        order = state["order"]
        current_index = state["index"]
        next_photo = order[current_index]

        winner = state["winner"] if data == "pick:1" else next_photo
        state["winner"] = winner
        state["index"] += 1

        await query.message.reply_text("✅ Окей, идём дальше!")
        await send_pair(context, user_id)
        return

    # неизвестный колбэк
    await query.message.reply_text("Неизвестная команда. Нажми /menu.")


# === ЗАПУСК ===
if __name__ == "__main__":
    import asyncio

    # ЯВНО создаём и назначаем цикл событий для текущего потока
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = ApplicationBuilder().token(TOKEN).build()

    # хендлеры
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu",  menu_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CallbackQueryHandler(on_button))

    print("✅ Бот запущен и готов! PID:", os.getpid())

    # запускаем без дополнительных policy/close_loop
    app.run_polling()
