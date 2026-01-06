import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import BOT_TOKEN
from db import (
    init_db, get_user_by_tg_id, create_user, update_user_name_and_time,
    create_focus, get_active_focus_for_user, create_checkin_simple,
    get_week_stats_for_user, set_new_focus_for_user, get_users_for_morning,
    mark_morning_sent, get_users_for_evening, get_today_checkin_status,
    mark_evening_sent, get_streak_for_user,
)

import logging
logging.basicConfig(level=logging.INFO)

class Onboarding(StatesGroup):
    waiting_for_name = State()
    waiting_for_morning_time = State()
    waiting_for_evening_time = State()
    waiting_for_domain = State()
    waiting_for_focus = State()

def is_valid_time(text: str) -> bool:
    if len(text) != 5 or text[2] != ":":
        return False
    hh, mm = text.split(":", 1)
    if not (hh.isdigit() and mm.isdigit()):
        return False
    h, m = int(hh), int(mm)
    return 0 <= h <= 23 and 0 <= m <= 59

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

domain_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Работа 💼"), KeyboardButton(text="Здоровье 🧘")],
              [KeyboardButton(text="Быт 🏠"), KeyboardButton(text="Учёба 📚")],
              [KeyboardButton(text="Другое ✨")]],
    resize_keyboard=True, one_time_keyboard=True)

checkin_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Сделано ✅")],
              [KeyboardButton(text="Частично 🌓")],
              [KeyboardButton(text="Не сделано ❌")]],
    resize_keyboard=True, one_time_keyboard=True)

checkin_manual_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Чекин 📋")]],
    resize_keyboard=True)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer("Команды:\n/start – онбординг\n/focus – сменить фокус\n/week – статистика\n/streak – серия\n")

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = get_user_by_tg_id(message.from_user.id)
    if user:
        await message.answer("Рад снова видеть 👋\nУ тебя уже есть фокус.")
        return
    create_user(message.from_user.id)
    await message.answer("Привет 👋\nКак тебя звать?")
    await state.set_state(Onboarding.waiting_for_name)

@dp.message(Onboarding.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Ок. Во сколько утром напоминать?\nФормат: ЧЧ:ММ (например 08:30)")
    await state.set_state(Onboarding.waiting_for_morning_time)

@dp.message(Onboarding.waiting_for_morning_time)
async def process_morning_time(message: Message, state: FSMContext):
    morning_time = message.text.strip()
    if not is_valid_time(morning_time):
        await message.answer("Формат ЧЧ:ММ. Попробуй ещё раз.")
        return
    await state.update_data(morning_time=morning_time)
    await message.answer("Вечером в какое время подведение итогов?\nФормат: ЧЧ:ММ (например 21:30)")
    await state.set_state(Onboarding.waiting_for_evening_time)

@dp.message(Onboarding.waiting_for_evening_time)
async def process_evening_time(message: Message, state: FSMContext):
    evening_time = message.text.strip()
    if not is_valid_time(evening_time):
        await message.answer("Формат ЧЧ:ММ. Попробуй ещё раз.")
        return
    data = await state.get_data()
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    current_time_str = now.strftime("%H:%M")
    morning_time = data["morning_time"]
    checkin_time = evening_time
    last_morning_sent = today_str if morning_time <= current_time_str else None
    last_checkin_reminder_sent = today_str if checkin_time <= current_time_str else None
    update_user_name_and_time(
        tg_id=message.from_user.id, name=data["name"],
        morning_time=morning_time, checkin_time=checkin_time,
        start_date=today_str, last_morning_sent=last_morning_sent,
        last_checkin_reminder_sent=last_checkin_reminder_sent)
    await message.answer("С какой сферы начнём?", reply_markup=domain_kb)
    await state.set_state(Onboarding.waiting_for_domain)

@dp.message(Onboarding.waiting_for_domain)
async def process_domain(message: Message, state: FSMContext):
    domain = message.text.strip()
    await state.update_data(domain=domain)
    await message.answer("Напиши твой маленький фокус на неделю (например: делать зарядку по утрам)")
    await state.set_state(Onboarding.waiting_for_focus)

@dp.message(Onboarding.waiting_for_focus)
async def process_focus(message: Message, state: FSMContext):
    focus_title = message.text.strip()
    data = await state.get_data()
    domain = data["domain"]
    create_focus(tg_id=message.from_user.id, title=focus_title, domain=domain)
    await message.answer(f"Отлично!\n\n«{focus_title}» в сфере «{domain}»")
    await state.clear()
    await message.answer("Используй кнопку «Чекин 📋» для отметок:", reply_markup=checkin_manual_kb)

@dp.message(Command("done"))
async def cmd_done(message: Message):
    ok = create_checkin_simple(tg_id=message.from_user.id, status="done")
    if not ok:
        await message.answer("Сначала пройди /start.")
        return
    await message.answer("Круто, сегодня фокус закрыт ✅")

@dp.message(Command("partial"))
async def cmd_partial(message: Message):
    ok = create_checkin_simple(tg_id=message.from_user.id, status="partial")
    if not ok:
        await message.answer("Сначала пройди /start.")
        return
    await message.answer("Частично — тоже движение вперёд 🌓")

@dp.message(Command("fail"))
async def cmd_fail(message: Message):
    ok = create_checkin_simple(tg_id=message.from_user.id, status="fail")
    if not ok:
        await message.answer("Сначала пройди /start.")
        return
    await message.answer("Ок, бывает. Завтра ещё раз ❌")

@dp.message(F.text == "Сделано ✅")
async def handle_done(message: Message):
    user = get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Сначала пройди /start.")
        return
    
    user_id = user["id"]
    prev_status = get_today_checkin_status(user_id)
    create_checkin_simple(message.from_user.id, "done")
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    last_checkin_reminder_sent = user["last_checkin_reminder_sent"]
    evening_already_sent = (last_checkin_reminder_sent == today_str)
    
    if prev_status is None:
        text = (
            "Отлично, день засчитан 👌\n"
            "Если вдруг передумаешь — просто выбери другую кнопку, "
            "я обновлю статус за сегодня."
        )
    else:
        if evening_already_sent:
            text = (
                "Статус на сегодня обновлён на: сделано ✅\n"
                "Обновил недельную статистику."
            )
        else:
            text = (
                "Статус на сегодня обновлён на: сделано ✅\n"
                "Вечером и в статистике учту именно этот вариант."
            )
    
    await message.answer(text)

@dp.message(F.text == "Частично 🌓")
async def handle_partial(message: Message):
    user = get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Сначала пройди /start.")
        return
    
    user_id = user["id"]
    prev_status = get_today_checkin_status(user_id)
    create_checkin_simple(message.from_user.id, "partial")
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    last_checkin_reminder_sent = user["last_checkin_reminder_sent"]
    evening_already_sent = (last_checkin_reminder_sent == today_str)
    
    if prev_status is None:
        text = (
            "Зафиксировали частичный прогресс 🌓\n"
            "Если вдруг передумаешь — просто выбери другую кнопку, "
            "я обновлю статус за сегодня."
        )
    else:
        if evening_already_sent:
            text = (
                "Статус на сегодня обновлён на: сделано частично 🌓\n"
                "Обновил недельную статистику."
            )
        else:
            text = (
                "Статус на сегодня обновлён на: сделано частично 🌓\n"
                "Вечером и в статистике учту именно этот вариант."
            )
    
    await message.answer(text)

@dp.message(F.text == "Не сделано ❌")
async def handle_fail(message: Message):
    user = get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Сначала пройди /start.")
        return
    
    user_id = user["id"]
    prev_status = get_today_checkin_status(user_id)
    create_checkin_simple(message.from_user.id, "fail")
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    last_checkin_reminder_sent = user["last_checkin_reminder_sent"]
    evening_already_sent = (last_checkin_reminder_sent == today_str)
    
    if prev_status is None:
        text = (
            "Ок, бывает. Завтра попробуем ещё раз ❌\n"
            "Если вдруг передумаешь — просто выбери другую кнопку, "
            "я обновлю статус за сегодня."
        )
    else:
        if evening_already_sent:
            text = (
                "Статус на сегодня обновлён на: не сделано ❌\n"
                "Обновил недельную статистику."
            )
        else:
            text = (
                "Статус на сегодня обновлён на: не сделано ❌\n"
                "Вечером и в статистике учту именно этот вариант."
            )
    
    await message.answer(text)

@dp.message(F.text == "Чекин 📋")
async def handle_manual_checkin(message: Message):
    await message.answer("Как прошёл твой день по фокусу?", reply_markup=checkin_kb)

@dp.message(Command("reset"))
async def cmd_reset(message: Message, state: FSMContext):
    await state.clear()
    create_user(message.from_user.id)
    await message.answer("Начнём заново. Как тебя звать?")
    await state.set_state(Onboarding.waiting_for_name)

# ========== ВТОРАЯ ПОЛОВИНА НАЧИНАЕТСЯ ЗДЕСЬ ==========

async def send_morning_focus():
    now = datetime.now()
    current_time_str = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")
    users = get_users_for_morning(current_time_str, today_str)
    if not users:
        return
    to_mark = []
    for user in users:
        tg_id = user["tg_id"]
        user_id = user["id"]
        name = user["name"] or ""
        status = get_today_checkin_status(user_id)
        if status:
            to_mark.append(user_id)
            continue
        focus = get_active_focus_for_user(tg_id)
        if not focus:
            to_mark.append(user_id)
            continue
        greeting = f"{name}, новый день — тот же фокус 💡" if name else "Новый день — тот же фокус 💡"
        await bot.send_message(tg_id, f"{greeting}\n\nСегодня главное:\n«{focus['title']}»")
        to_mark.append(user_id)
    if to_mark:
        mark_morning_sent(to_mark, today_str)

def get_summary_text(status: str, name: str = None) -> str:
    prefix = f"{name}, " if name else ""
    if status == "done":
        return f"{prefix}день по фокусу — сделан ✅"
    if status == "partial":
        return f"{prefix}сегодня — сделано частично 🌓"
    return f"{prefix}сегодня — не сделано ❌"

async def send_daily_checkins():
    now = datetime.now()
    current_time_str = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")
    users = get_users_for_evening(current_time_str, today_str)
    if not users:
        return
    ids_to_mark = []
    for user in users:
        tg_id = user["tg_id"]
        user_id = user["id"]
        name = user["name"] or ""
        status = get_today_checkin_status(user_id)
        if status:
            summary = get_summary_text(status, name)
            await bot.send_message(tg_id, summary)
        else:
            prefix = f"{name}, " if name else ""
            await bot.send_message(tg_id, f"{prefix}как прошёл день по фокусу?", reply_markup=checkin_kb)
        ids_to_mark.append(user_id)
    if ids_to_mark:
        mark_evening_sent(ids_to_mark, today_str)

@dp.message(Command("week"))
async def cmd_week(message: Message):
    data = get_week_stats_for_user(message.from_user.id)
    if not data:
        await message.answer("За последние 7 дней по текущему фокусу нет данных.\nСначала задай фокус через /start и фиксируй дни.")
        return

    focus_title = data["title"]
    stats = data["stats"]
    streak = data.get("streak", 0)
    last_7_days = data.get("last_7_days", [])

    done = stats.get("done", 0)
    partial = stats.get("partial", 0)
    fail = stats.get("fail", 0)
    total = done + partial + fail

    if total == 0:
        await message.answer("За последние 7 дней по текущему фокусу нет ни одного чек-ина.\nПопробуй хотя бы пару дней подряд фиксировать результат с помощью кнопок.")
        return

    effective_done = done + partial * 0.5
    percent = round(effective_done / total * 100)

    blocks = 10
    filled = int(round(effective_done / total * blocks))
    bar = "█" * filled + "░" * (blocks - filled)

    if percent == 0:
        summary_text = "Старт всегда даётся непросто. Попробуй в ближайшие дни хотя бы пару раз отметить фокус, даже минимально."
    elif percent < 40:
        summary_text = "Ты сделал несколько шагов, это уже лучше, чем ноль. Подумай, как упростить фокус или привязать его к существующей привычке."
    elif percent < 80:
        summary_text = "У тебя уже неплохая динамика. Чуть-чуть добавить стабильности — и неделя станет почти полностью зелёной."
    elif percent < 100:
        summary_text = "Неделя почти полностью зелёная — очень круто. Продолжай в том же духе или чуть усложни фокус, если чувствуешь силы."
    else:
        summary_text = "Идеальная неделя по фокусу — 100% выполнений. Можешь либо закрепить результат, либо перейти к следующему уровню сложности."

    if streak > 1:
        summary_text += f"\n\nТы держишься уже {streak} дней подряд!"
    elif streak == 1:
        summary_text += "\n\nОтличное начало серии — первый день уже в копилке!"

    non_empty = [s for s in last_7_days if s is not None]
    padded = non_empty + [None] * (7 - len(non_empty))
    padded = padded[:7]

    def status_to_emoji(status):
        if status == "done": return "✅"
        if status == "partial": return "🌓"
        if status == "fail": return "❌"
        return "⬜"

    heatmap = "".join(status_to_emoji(status) for status in padded)

    await message.answer(
        "Недельный срез по фокусу:\n"
        f"«{focus_title}»\n\n"
        f"{heatmap}  (последние 7 дней)\n\n"
        f"✅ Сделано: {done}\n"
        f"🌓 Частично: {partial}\n"
        f"❌ Не сделано: {fail}\n\n"
        f"{bar}  {percent}% за последние 7 дней\n\n"
        f"{summary_text}"
    )

    if done == 7 and partial == 0 and fail == 0:
        await message.answer("Браво! У тебя закрыты все 7 дней по фокусу подряд 💚\nМожешь усложнить задачу или выбрать новый фокус через команду /focus.")

@dp.message(Command("focus"))
async def cmd_focus(message: Message):
    user = get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нужно пройти /start.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) == 1:
        focus = get_active_focus_for_user(message.from_user.id)
        if not focus:
            await message.answer("Сейчас у тебя нет активного фокуса.")
            return
        await message.answer(f"Твой текущий фокус:\n«{focus['title']}»\n\nЧтобы сменить, напиши:\n/focus Новый фокус")
        return
    new_title = args[1].strip()
    if not new_title:
        await message.answer("Напиши формулировку фокуса после команды.")
        return
    ok = set_new_focus_for_user(tg_id=message.from_user.id, title=new_title, domain=None)
    if not ok:
        await message.answer("Не получилось обновить фокус. Попробуй ещё раз или пройди /start.")
        return
    await message.answer(f"Обновил фокус.\n\nНовый фокус:\n«{new_title}»\n\nПродолжай отмечать дни через кнопку «Чекин 📋».")

async def setup_bot_commands():
    commands = [
        BotCommand(command="start", description="Запустить бота / онбординг"),
        BotCommand(command="focus", description="Сменить текущий фокус"),
        BotCommand(command="week", description="Статистика за неделю"),
        BotCommand(command="streak", description="Текущая серия по фокусу"),
        BotCommand(command="help", description="Список команд"),
    ]
    await bot.set_my_commands(commands)

async def main():
    init_db()
    await setup_bot_commands()
    scheduler.add_job(send_morning_focus, "interval", seconds=60)
    scheduler.add_job(send_daily_checkins, "interval", seconds=60)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
