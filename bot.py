import asyncio
from db import get_today_checkin_status, create_checkin_simple, get_user_by_tg_id


from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from pytz import timezone as pytz_timezone
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ACHIEVEMENT_LEVELS, ACHIEVEMENT_THRESHOLDS

from db import (
    init_db,
    get_user_by_tg_id,
    create_user,
    update_user_name_and_time,
    create_focus,
    get_active_focus_for_user,
    create_checkin_simple,
    get_users_for_checkin,  # пока не используем, но можно оставить
    get_week_stats_for_user,
    set_new_focus_for_user,
    get_users_for_morning,
    mark_morning_sent,
    get_users_for_evening,
    get_today_checkin_status,
    mark_evening_sent,
    get_streak_for_user,
)

import logging
logging.basicConfig(level=logging.INFO)

class Onboarding(StatesGroup):
    waiting_for_name = State()
    waiting_for_morning_time = State()
    waiting_for_evening_time = State()
    waiting_for_timezone = State()
    waiting_for_domain = State()
    waiting_for_focus = State()

def is_valid_time(text: str) -> bool:
    if len(text) != 5 or text[2] != ":":
        return False
    hh, mm = text.split(":", 1)
    if not (hh.isdigit() and mm.isdigit()):
        return False
    h = int(hh)
    m = int(mm)
    return 0 <= h <= 23 and 0 <= m <= 59

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

scheduler = AsyncIOScheduler()

def get_achievement_level(streak: int) -> int:
    level = 0
    for idx, days in enumerate(ACHIEVEMENT_THRESHOLDS, start=1):
        if streak >= days:
            level = idx
        else:
            break
    return level

# --- клавиатуры ---

# Часовые пояса РФ и их аналоги
TIMEZONE_OPTIONS = [
    ("Москва/Стамбул (UTC+3)", "Europe/Moscow"),
    ("Калининград (UTC+2)", "Europe/Kaliningrad"),
    ("Екатеринбург/Пакистан (UTC+5)", "Asia/Yekaterinburg"),
    ("Новосибирск/Бангкок (UTC+6)", "Asia/Novosibirsk"),
    ("Иркутск/Бангкок (UTC+7)", "Asia/Krasnoyarsk"),
    ("Якутск/Гон-Конг (UTC+8)", "Asia/Yakutsk"),
    ("Магадан/Сеул (UTC+9)", "Asia/Magadan"),
    ("Петропавловск-Камчатский (UTC+11)", "Asia/Kamchatka"),
]

timezone_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=tz[0])] for tz in TIMEZONE_OPTIONS],
    resize_keyboard=True,
    one_time_keyboard=True,
)

domain_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Работа 💼"), KeyboardButton(text="Здоровье 🧘")],
        [KeyboardButton(text="Быт 🏠"), KeyboardButton(text="Учёба/развитие 📚")],
        [KeyboardButton(text="Другое ✨")],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)

checkin_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Сделано ✅")],
        [KeyboardButton(text="Сделано частично 🌓")],
        [KeyboardButton(text="Не сделано ❌")],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)

checkin_manual_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Чекин 📋")],
    ],
    resize_keyboard=True,
)


# --- команды и онбординг ---

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Доступные команды:\n"
        "/start – начать заново, пройти онбординг\n"
        "/focus – сменить текущий фокус\n"
        "/week – статистика за неделю\n"
        "/help – показать это сообщение\n"
        "\n"
        "А ещё бот сам пишет:\n"
        "• утром — с напоминанием о фокусе\n"
        "• вечером — с подведением итогов"
    )


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = await get_user_by_tg_id(message.from_user.id)
    if user:
        await message.answer(
            "Рад снова видеть 👋\n"
            "У тебя уже есть фокус. Используй кнопку «Чекин 📋», чтобы отмечать дни."
        )
        return

    await create_user(message.from_user.id)
    await message.answer(
        "Привет 👋\n"
        "Я помогу тебе мягко зайти в системность самодисциплины. Мы не будем сворачивать горы - только маленькие подъемные достижения. Мягко, но регулярно.\n\n"
        "Для начала — как к тебе обращаться?"
    )
    await state.set_state(Onboarding.waiting_for_name)


@dp.message(Onboarding.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer(
        "Ок, запомнил.\n"
        "Во сколько напоминать утром/днём о фокусе?\n"
        "Напиши в формате ЧЧ:ММ, например 08:30 или 10:00."
    )
    await state.set_state(Onboarding.waiting_for_morning_time)


@dp.message(Onboarding.waiting_for_morning_time)
async def process_morning_time(message: Message, state: FSMContext):
    morning_time = message.text.strip()

    if not is_valid_time(morning_time):
        await message.answer(
            "Слушай, время понимаю только в формате ЧЧ:ММ.\n"
            "Например: 08:30 или 10:00.\n"
            "Напиши время ещё раз, пожалуйста."
        )
        return

    await state.update_data(morning_time=morning_time)

    await message.answer(
        "А теперь время вечернего подведения итогов.\n"
        "Напиши в формате ЧЧ:ММ, например 21:30 или 22:00."
    )
    await state.set_state(Onboarding.waiting_for_evening_time)



@dp.message(Onboarding.waiting_for_evening_time)
async def process_evening_time(message: Message, state: FSMContext):
    print(f"DEBUG: process_evening_time called with text='{message.text}'")
    evening_time = message.text.strip()

    if not is_valid_time(evening_time):
        await message.answer(
            "Время итогов тоже нужно в формате ЧЧ:ММ.\n"
            "Например: 21:30 или 22:00.\n"
            "Напиши время ещё раз. пожалуйста."
        )
        return

    data = await state.get_data()

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    current_time_str = now.strftime("%H:%M")

    morning_time = data["morning_time"]
    checkin_time = evening_time

    last_morning_sent = today_str if morning_time <= current_time_str else None
    last_checkin_reminder_sent = today_str if checkin_time <= current_time_str else None

    await state.update_data(evening_time=evening_time)
    
    await message.answer(
        "В каком часовом поясе ты находишься? Это нужно, чтобы я правильно понимал твое время уведомлений.",
        reply_markup=timezone_kb,
    )
    await state.set_state(Onboarding.waiting_for_timezone)

@dp.message(Onboarding.waiting_for_timezone)
async def process_timezone(message: Message, state: FSMContext):
    selected_text = message.text.strip()
    
    # Найти pytz timezone по выбранному тексту
    timezone_str = None
    for display_name, tz_name in TIMEZONE_OPTIONS:
        if display_name == selected_text:
            timezone_str = tz_name
            break
    
    if not timezone_str:
        await message.answer(
            "Выбери из предложенных вариантов, пожалуйста."
        )
        return
    
    data = await state.get_data()
    now_utc = datetime.now(pytz_timezone('UTC'))
    user_tz = pytz_timezone(timezone_str)
    now_user_tz = now_utc.astimezone(user_tz)
    today_str = now_user_tz.strftime("%Y-%m-%d")
    current_time_str = now_user_tz.strftime("%H:%M")
    
    morning_time_user = data["morning_time"]
    evening_time_user = data["evening_time"]
    
    # Конвертируем время пользователя в UTC
    from datetime import datetime as dt_class
    # Парсим время как если бы оно было в user_tz
    morning_dt = dt_class.strptime(morning_time_user, "%H:%M").replace(
        tzinfo=user_tz, year=now_user_tz.year, month=now_user_tz.month, day=now_user_tz.day
    )
    evening_dt = dt_class.strptime(evening_time_user, "%H:%M").replace(
        tzinfo=user_tz, year=now_user_tz.year, month=now_user_tz.month, day=now_user_tz.day
    )
    
    # Конвертируем в UTC
    morning_utc = morning_dt.astimezone(pytz_timezone('UTC'))
    evening_utc = evening_dt.astimezone(pytz_timezone('UTC'))
    
    morning_time_utc = morning_utc.strftime("%H:%M")
    evening_time_utc = evening_utc.strftime("%H:%M")
    
    last_morning_sent = today_str if morning_time_user <= current_time_str else None
    last_evening_sent = today_str if evening_time_user <= current_time_str else None
    
    await update_user_name_and_time(
        tg_id=message.from_user.id,
        name=data["name"],
        morning_time=morning_time_utc,
        checkin_time=evening_time_utc,
        start_date=today_str,
        last_morning_sent=last_morning_sent,
        last_checkin_reminder_sent=last_evening_sent,
        timezone=timezone_str,
    )
    
    await message.answer(
        "С какой сферы начнём?\n"
        "Выбери один вариант или напиши свой.",
        reply_markup=domain_kb,
    )
    await state.set_state(Onboarding.waiting_for_domain)


@dp.message(Onboarding.waiting_for_domain)
async def process_domain(message: Message, state: FSMContext):
    domain = message.text.strip()
    await state.update_data(domain=domain)
    await message.answer(
        "Напиши одним предложением, какой маленький фокус взять на ближайшую неделю.\n\n"
        "Например:\n"
        "— делать одно важное дело до обеда\n"
        "— ложиться в спать до 23:00\n"
        "— 15 минут читать перед сном",
        reply_markup=None,
    )
    await state.set_state(Onboarding.waiting_for_focus)


@dp.message(Onboarding.waiting_for_focus)
async def process_focus(message: Message, state: FSMContext):
    focus_title = message.text.strip()
    data = await state.get_data()
    domain = data["domain"]

    await create_focus(
        user_tg_id=message.from_user.id,
        title=focus_title,
        domain=domain,
    )

    await message.answer(
        "Отлично. На этой неделе работаем только с этим:\n\n"
        f"«{focus_title}» в сфере «{domain}».\n\n"
        "Если сделаешь раньше и захочешь зафиксировать результат за сегодня до вечерного подведения итогов - нажми кнопку «Чекин»."
    )

    await state.clear()

    await message.answer(
        "Чтобы потом быстро отмечать результат за день, у тебя всегда под рукой есть кнопка:",
        reply_markup=checkin_manual_kb,
    )


# --- чек-ины старыми командами (можно оставить как бэкап или выпилить позже) ---

@dp.message(Command("checkin"))
async def cmd_checkin(message: Message):
    user = await get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нужно пройти онбординг — нажми /start.")
        return

    focus = await get_active_focus_for_user(message.from_user.id)
    if not focus:
        await message.answer("У тебя пока нет активного фокуса.")
        return

    await message.answer(
        "Твой текущий фокус:\n"
        f"«{focus['title']}»\n\n"
        "Но теперь вместо команд используй кнопку «Чекин 📋» и варианты ответа."
    )


@dp.message(Command("done"))
async def cmd_done(message: Message):
    ok = await create_checkin_simple(
        tg_id=message.from_user.id,
        status="done",
    )
    if not ok:
        await message.answer("Не получилось сохранить. Убедись, что прошёл онбординг через /start.")
        return
    await message.answer("Круто, сегодня фокус закрыт ✅")


@dp.message(Command("partial"))
async def cmd_partial(message: Message):
    ok = await create_checkin_simple(
        tg_id=message.from_user.id,
        status="partial",
    )
    if not ok:
        await message.answer("Не получилось сохранить. Убедись, что прошёл онбординг через /start.")
        return
    await message.answer("Частично — тоже движение вперёд ☑")


@dp.message(Command("fail"))
async def cmd_fail(message: Message):
    ok = await create_checkin_simple(
        tg_id=message.from_user.id,
        status="fail",
    )
    if not ok:
        await message.answer("Не получилось сохранить. Убедись, что прошёл онбординг через /start.")
        return
    await message.answer("Ок, честно зафиксировали. Завтра попробуем ещё раз ❌")


# --- отладка и reset ---

@dp.message(Command("debug_time"))
async def cmd_debug_time(message: Message):
    user = await get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Юзер не найден в базе.")
        return

    await message.answer(
        f"morning_time: {user['morning_time']!r}\n"
        f"checkin_time: {user['checkin_time']!r}"
    )


@dp.message(Command("reset"))
async def cmd_reset(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Начнём заново. Как тебя звать?")
    await create_user(message.from_user.id)
    await state.set_state(Onboarding.waiting_for_name)


# --- утренние напоминания ---

async def send_morning_focus():
    now_utc = datetime.now(pytz_timezone('UTC'))
    today_str_utc = now_utc.strftime("%Y-%m-%d")

    users = await get_users_for_morning(today_str_utc)
    if not users:
        return

    to_mark: list[int] = []

    for user in users:
        tg_id = user["tg_id"]
        user_id = user["id"]
        name = user["name"] or ""
        
        # Конвертируем текущее UTC время в timezone пользователя
        user_tz = pytz_timezone(user.get("timezone", "Europe/Moscow"))
        now_user = now_utc.astimezone(user_tz)
        current_time_str = now_user.strftime("%H:%M")
        today_str = now_user.strftime("%Y-%m-%d")
        
        # Сравниваем: пришло ли время для этого пользователя
        morning_time = user["morning_time"]
        if morning_time > current_time_str:
            # Ещё не пришло время
            continue

        # если уже есть чек-ин за сегодня – утро пропускаем,
        # но помечаем, чтобы больше не слать за этот день
        status = await get_today_checkin_status(user_id, today_str)
        if status:
            to_mark.append(user_id)
            continue

        focus = await get_active_focus_for_user(tg_id)
        if not focus:
            to_mark.append(user_id)
            continue

        greeting = f"{name}, новый день — тот же фокус 💡" if name else "Новый день — тот же фокус 💡"

        await bot.send_message(
            tg_id,
            f"{greeting}\n\n"
            f"Сегодня главное для тебя:\n"
            f"«{focus['title']}»\n\n"
            "Сделай это — и день уже не зря.",
        )

        to_mark.append(user_id)

    if to_mark:
        await mark_morning_sent(to_mark, today_str_utc)


# --- вечерние итоги ---

def get_summary_text(status: str, name: str | None = None) -> str:
    prefix = f"{name}, " if name else ""
    if status == "done":
        return (
            f"{prefix}день по фокусу — сделан.\n\n"
            "Молодец, так держать. Ещё один шаг к новой привычке."
        )
    if status == "partial":
        return (
            f"{prefix}сегодня по фокусу — сделано частично.\n\n"
            "Это уже движение вперёд. Продолжай в том же духе."
        )
    if status == "fail":
        return (
            f"{prefix}сегодня по фокусу — не сделано.\n\n"
            "Цель у тебя уже есть, это важно. Помни о ней и завтра постарайся выполнить — у тебя получится."
        )

async def send_daily_checkins():
    now_utc = datetime.now(pytz_timezone('UTC'))
    today_str_utc = now_utc.strftime("%Y-%m-%d")

    users = await get_users_for_evening(today_str_utc)
    if not users:
        return

    ids_to_mark: list[int] = []

    for user in users:
        tg_id = user["tg_id"]
        user_id = user["id"]
        name = user["name"] or ""
        
        # Конвертируем текущее UTC время в timezone пользователя
        user_tz = pytz_timezone(user.get("timezone", "Europe/Moscow"))
        now_user = now_utc.astimezone(user_tz)
        current_time_str = now_user.strftime("%H:%M")
        today_str = now_user.strftime("%Y-%m-%d")
        
        # Сравниваем: пришло ли время для этого пользователя
        checkin_time = user["checkin_time"]
        if checkin_time > current_time_str:
            # Ещё не пришло время
            continue

        status = await get_today_checkin_status(user_id, today_str)

        if status:
            # уже есть отметка — шлём итог
            summary = get_summary_text(status, name)
            await bot.send_message(tg_id, summary)
        else:
            # ещё не отмечался — задаём вопрос
            prefix = f"{name}, " if name else ""
            await bot.send_message(
                tg_id,
                f"{prefix}как прошёл твой день по фокусу?\n\nВыбери один вариант:",
                reply_markup=checkin_kb,
            )

        ids_to_mark.append(user_id)

    if ids_to_mark:
        await mark_evening_sent(ids_to_mark, today_str_utc)


# --- статистика за неделю ---

@dp.message(Command("week"))
async def cmd_week(message: Message):
    data = await get_week_stats_for_user(message.from_user.id)
    if not data:
        await message.answer(
            "За последние 7 дней по текущему фокусу нет данных.\n"
            "Сначала задай фокус через /start и фиксируй дни."
        )
        return

    focus_title = data["focus_title"]
    stats = data["stats"]
    streak = data.get("streak", 0)
    last_7_days = data.get("last_7_days", [])

    done = stats.get("done", 0)
    partial = stats.get("partial", 0)
    fail = stats.get("fail", 0)
    total = done + partial + fail

    if total == 0:
        await message.answer(
            "За последние 7 дней по текущему фокусу нет ни одного чек-ина.\n"
            "Попробуй хотя бы пару дней подряд фиксировать результат с помощью кнопок."
        )
        return

    # считаем «вес» частичных дней как 0.5
    effective_done = done + partial * 0.5
    percent = round(effective_done / total * 100)

    # простой текстовый прогресс-бар на 10 делений
    blocks = 10
    filled = int(round(effective_done / total * blocks))
    bar = "█" * filled + "░" * (blocks - filled)

    # подбираем общий текст по результату недели
    if percent == 0:
        summary_text = (
            "Старт всегда даётся непросто. "
            "Попробуй в ближайшие дни хотя бы пару раз отметить фокус, даже минимально."
        )
    elif percent < 40:
        summary_text = (
            "Ты сделал несколько шагов, это уже лучше, чем ноль. "
            "Подумай, как упростить фокус или привязать его к существующей привычке."
        )
    elif percent < 80:
        summary_text = (
            "У тебя уже неплохая динамика. "
            "Чуть-чуть добавить стабильности — и неделя станет почти полностью зелёной."
        )
    elif percent < 100:
        summary_text = (
            "Неделя почти полностью зелёная — очень круто. "
            "Продолжай в том же духе или чуть усложни фокус, если чувствуешь силы."
        )
    else:  # percent == 100
        summary_text = (
            "Идеальная неделя по фокусу — 100% выполнений. "
            "Можешь либо закрепить результат, либо перейти к следующему уровню сложности."
        )

    # добавляем фразу про серию дней
    if streak > 1:
        summary_text += f"\n\nТы держишься уже {streak} дней подряд!"
    elif streak == 1:
        summary_text += "\n\nОтличное начало серии — первый день уже в копилке!"

    level = get_achievement_level(streak)
    if level > 0:
        emoji = ACHIEVEMENT_LEVELS[level]
        if level < len(ACHIEVEMENT_THRESHOLDS):
            next_days = ACHIEVEMENT_THRESHOLDS[level]
            days_left = max(0, next_days - streak)
            summary_text += (
                f"\n\n🏅 Ачивка: уровень {level} {emoji}"
                f"\n⏭ До следующего уровня: {days_left} дн."
            )
        else:
            summary_text += (
                f"\n\n🏅 Ачивка: уровень {level} {emoji}"
                f"\n🎉 Ты на максимальном уровне по серии!"
            )
    else:
        first_target = ACHIEVEMENT_THRESHOLDS[0]
        summary_text += (
            f"\n\n🏅 Пока без ачивки."
            f"\nЦель: {first_target} зелёных дней подряд."
        )


    # heatmap за последние 7 дней:
    # берём только дни с чек-ином, сдвигаем к началу, остальное добиваем пустыми
    non_empty = [s for s in last_7_days if s is not None]
    padded = non_empty + [None] * (7 - len(non_empty))
    padded = padded[:7]

    def status_to_emoji(status: str | None) -> str:
        if status == "done":
            return "✅"
        if status == "partial":
            return "🌓"
        if status == "fail":
            return "❌"
        return "⬜"

    heatmap = "".join(status_to_emoji(status) for status in padded)

    # основное сообщение со статистикой
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

    # если неделя полностью зелёная — подсказка сменить/усложнить фокус
    if done == 7 and partial == 0 and fail == 0:
        await message.answer(
            "Браво! У тебя закрыты все 7 дней по фокусу подряд 💚\n"
            "Можешь усложнить задачу или выбрать новый фокус через команду /focus."
        )


@dp.message(Command("streak"))
async def cmd_streak(message: Message):
    data = await get_streak_for_user(message.from_user.id)
    if not data:
        await message.answer(
            "Пока нет данных по текущему фокусу.\n"
            "Сначала задай фокус через /start и сделай пару чек-инов."
        )
        return

    focus_title = data["focus_title"]
    current = data["current_streak"]
    best = data["best_streak"]

    if current == 0 and best == 0:
        text = (
            "По текущему фокусу ещё нет завершённых дней.\n"
            "Начни с первого чек-ина — дальше будет проще держать серию."
        )
    else:
        lines = [f"Фокус: «{focus_title}»\n"]
        lines.append(f"Текущая серия: {current} дн.")
        lines.append(f"Лучшая серия: {best} дн.")

        if current == 0:
            lines.append("\nСейчас серии нет — можно начать новую уже сегодня.")
        elif current < best:
            lines.append("\nТы на пути к своему рекорду, продолжай держаться!")
        elif current == best and current > 0:
            lines.append("\nТы повторяешь свой рекорд — ещё один шаг, чтобы его побить.")
        else:  # current > best
            lines.append("\nЭто новый рекорд серии — очень мощно!")

        text = "\n".join(lines)

    await message.answer(text)


# --- смена фокуса ---

@dp.message(Command("focus"))
async def cmd_focus(message: Message):
    user = await get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нужно пройти онбординг через /start.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) == 1:
        focus = await get_active_focus_for_user(message.from_user.id)
        if not focus:
            await message.answer("Сейчас у тебя нет активного фокуса.")
            return

        await message.answer(
            "Твой текущий фокус:\n"
            f"«{focus['title']}»\n\n"
            "Чтобы сменить его, напиши, например:\n"
            "/focus Делать зарядку 10 минут до обеда"
        )
        return

    new_title = args[1].strip()
    if not new_title:
        await message.answer(
            "Напиши формулировку фокуса после команды, например:\n"
            "/focus Ложиться в кровать до 23:00"
        )
        return

    ok = await set_new_focus_for_user(
        tg_id=message.from_user.id,
        title=new_title,
        domain=None,
    )

    if not ok:
        await message.answer("Не получилось обновить фокус. Попробуй ещё раз или пройди /start.")
        return

    await message.answer(
        "Обновил фокус.\n\n"
        f"Новый фокус на ближайшее время:\n"
        f"«{new_title}»\n\n"
        "Продолжай отмечать дни через кнопку «Чекин 📋»."
    )


# --- кнопки чек-ина ---

@dp.message(F.text == "Сделано ✅")
async def handle_done(message: Message):
    user = await get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нужно пройти онбординг — нажми /start.")
        return

    prev_status = await get_today_checkin_status(user["id"])
    await create_checkin_simple(message.from_user.id, "done")

    # проверяем, был ли уже вечерний чек-ин сегодня
    today_str = datetime.now().strftime("%Y-%m-%d")
    evening_already_sent = (user["last_checkin_reminder_sent"] == today_str)

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

    # --- ачивки по стрику зелёных дней ---
    data = await get_streak_for_user(message.from_user.id)
    if data:
        current_streak = data.get("current_streak", 0)

        # считаем, что до сегодняшнего дня стрик был на 1 меньше
        old_level = get_achievement_level(max(0, current_streak - 1))
        new_level = get_achievement_level(current_streak)

        if new_level > old_level and new_level > 0:
            emoji = ACHIEVEMENT_LEVELS[new_level]
            days_required = ACHIEVEMENT_THRESHOLDS[new_level - 1]

            await message.answer(
                "🎉 Новая ачивка!\n"
                f"{emoji} Ты держишься уже {current_streak} дней подряд.\n"
                f"Это уровень {new_level} (порог {days_required} дней)."
            )

    await message.answer(text)




@dp.message(F.text == "Сделано частично 🌓")
async def handle_partial(message: Message):
    user = await get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нужно пройти онбординг — нажми /start.")
        return

    prev_status = await get_today_checkin_status(user["id"])
    await create_checkin_simple(message.from_user.id, "partial")

    today_str = datetime.now().strftime("%Y-%m-%d")
    evening_already_sent = (user["last_checkin_reminder_sent"] == today_str)

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
    user = await get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нужно пройти онбординг — нажми /start.")
        return

    prev_status = await get_today_checkin_status(user["id"])
    await create_checkin_simple(message.from_user.id, "fail")

    today_str = datetime.now().strftime("%Y-%m-%d")
    evening_already_sent = (user["last_checkin_reminder_sent"] == today_str)

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
    await message.answer(
        "Как прошёл твой день по фокусу?\n\nВыбери один вариант:",
        reply_markup=checkin_kb,
    )


@dp.message(Command("status"))
async def cmd_status(message: Message):
    user = await get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нужно пройти онбординг — нажми /start.")
        return

    status = await get_today_checkin_status(user["id"])
    if not status:
        text = "За сегодня ещё нет отметки по фокусу.\n\nВыбери свой статус:"
    else:
        text = "Сейчас за сегодня у тебя отмечено:\n"
        if status == "done":
            text += "— сделано ✅\n\n"
        elif status == "partial":
            text += "— сделано частично 🌓\n\n"
        else:
            text += "— не сделано ❌\n\n"
        text += "Если хочешь, можешь изменить статус ниже."

    await message.answer(text, reply_markup=checkin_kb)



# --- команды меню ---

async def setup_bot_commands():
    commands = [
        BotCommand(command="start", description="Запустить бота / онбординг"),
        BotCommand(command="focus", description="Сменить текущий фокус"),
        BotCommand(command="week", description="Статистика за неделю"),
        BotCommand(command="streak", description="Текущая серия по фокусу"),
        BotCommand(command="help", description="Список команд"),
    ]
    await bot.set_my_commands(commands)

# --- main ---

@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    await message.answer("Используй кнопку для чекинов:", reply_markup=checkin_manual_kb)


async def main():
    await init_db()
    await setup_bot_commands()

    scheduler.add_job(send_morning_focus, "interval", seconds=60)
    scheduler.add_job(send_daily_checkins, "interval", seconds=60)
    scheduler.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
