import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web  # <-- НОВЫЙ ИМПОРТ ДЛЯ ВЕБ-СЕРВЕРА

# 1. ТВОЙ ТОКЕН
TOKEN = "8744218448:AAHQgU7Ed3T5Yr5kKLIZ5xzjWzGy_C_He0s"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Московское время (UTC+3)
MY_TIMEZONE = timezone(timedelta(hours=3))

DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

# Праздники (Месяц-День)
HOLIDAYS = [
    "01-01",
    "01-02",
    "01-03",
    "01-04",
    "01-05",
    "01-06",
    "01-07",
    "01-08",
    "02-23",
    "03-08",
    "05-01",
    "05-09",
    "06-12",
    "11-04",
]


# --- СИСТЕМА РАНГОВ (ЗВАНИЙ) ---
def get_rank(xp):
    if xp < 20:
        return "🌱 Черемша"
    elif xp < 50:
        return "🗡 Опытный Рома Букин"
    elif xp < 100:
        return "🛠 Покруче чем Рома Букин "
    elif xp < 250:
        return "🔥 Брат Макана"
    elif xp < 500:
        return "🎖 Ветеран туалетных войск"
    elif xp < 1000:
        return "👑 Грандмастер, колбастер, сосистер "
    else:
        return "🌌 Живая Легенда"


# 2. Создаем базу данных
def init_db():
    conn = sqlite3.connect("rpg_tracker.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, character_name TEXT, character_class TEXT,
            monthly_goal_hours INTEGER DEFAULT 0, xp REAL DEFAULT 0, gold INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS work_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, date TEXT, 
            hours REAL, xp REAL, gold INTEGER
        )
    """)
    conn.commit()
    conn.close()


# 3. Клавиатуры
def get_main_keyboard():
    kb = [
        [KeyboardButton(text="⏱ Отметить смену"), KeyboardButton(text="🛡 Мой профиль")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def get_date_keyboard():
    now = datetime.now(MY_TIMEZONE)
    kb = []
    row = []

    for i in range(7):
        day = now - timedelta(days=i)
        day_num = day.weekday()
        btn_text = f"{DAYS_RU[day_num]}, {day.strftime('%d.%m')}"
        row.append(KeyboardButton(text=btn_text))

        if len(row) == 2:
            kb.append(row)
            row = []

    if row:
        kb.append(row)

    kb.append([KeyboardButton(text="Отмена")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


# 4. Шаги
class CharacterCreation(StatesGroup):
    waiting_for_name = State()
    waiting_for_class = State()


class WorkLogging(StatesGroup):
    waiting_for_date = State()
    waiting_for_start = State()
    waiting_for_end = State()


# --- СТАРТ И РЕГИСТРАЦИЯ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    conn = sqlite3.connect("rpg_tracker.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (message.from_user.id,))
    user = cursor.fetchone()
    conn.close()

    if user:
        await message.answer(
            f"С возвращением, {user[1]}! Готов к труду?",
            reply_markup=get_main_keyboard(),
        )
    else:
        await message.answer("Добро пожаловать в Гильдию Трудяг! ⚔️\nКак тебя зовут?")
        await state.set_state(CharacterCreation.waiting_for_name)


@dp.message(CharacterCreation.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer(
        "Отличное имя! Теперь выбери свой класс (подсказка: инструктор):"
    )
    await state.set_state(CharacterCreation.waiting_for_class)


@dp.message(CharacterCreation.waiting_for_class)
async def process_class(message: types.Message, state: FSMContext):
    char_class = message.text
    user_data = await state.get_data()
    name = user_data["name"]

    conn = sqlite3.connect("rpg_tracker.db")
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO users (user_id, character_name, character_class, monthly_goal_hours, xp, gold)
                      VALUES (?, ?, ?, ?, ?, ?)""",
        (message.from_user.id, name, char_class, 0, 0.0, 0),
    )
    conn.commit()
    conn.close()

    await message.answer(
        f"🎉 Персонаж {name} успешно создан!", reply_markup=get_main_keyboard()
    )
    await state.clear()


# --- КНОПКА: МОЙ ПРОФИЛЬ ---
@dp.message(F.text == "🛡 Мой профиль")
async def btn_profile(message: types.Message):
    conn = sqlite3.connect("rpg_tracker.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (message.from_user.id,))
    user = cursor.fetchone()
    conn.close()

    if user:
        xp = user[4]
        rank = get_rank(xp)

        await message.answer(
            f"👤 Имя: {user[1]}\n"
            f"⚔️ Класс: {user[2]}\n"
            f"🏆 Звание: {rank}\n"
            f"✨ Опыт: {round(xp, 1)} XP\n"
            f"💰 Золото: {user[5]}"
        )


# --- КНОПКА: ОТМЕТИТЬ СМЕНУ ---
@dp.message(F.text == "⏱ Отметить смену")
async def btn_work_start(message: types.Message, state: FSMContext):
    await message.answer(
        "За какой день отмечаем смену?\nВыбери кнопку с датой или напиши её вручную (ДД.ММ):",
        reply_markup=get_date_keyboard(),
    )
    await state.set_state(WorkLogging.waiting_for_date)


@dp.message(WorkLogging.waiting_for_date)
async def process_date(message: types.Message, state: FSMContext):
    text = message.text
    now = datetime.now(MY_TIMEZONE)

    if text.lower() == "отмена":
        await message.answer("Ввод отменен.", reply_markup=get_main_keyboard())
        await state.clear()
        return

    target_date = None

    for i in range(7):
        day = now - timedelta(days=i)
        day_num = day.weekday()
        expected_btn_text = f"{DAYS_RU[day_num]}, {day.strftime('%d.%m')}"
        if text == expected_btn_text:
            target_date = day
            break

    if target_date is None:
        try:
            parsed = datetime.strptime(text, "%d.%m")
            target_date = now.replace(month=parsed.month, day=parsed.day)
        except ValueError:
            await message.answer(
                "Пожалуйста, выбери дату кнопкой или введи её как ДД.ММ (например, 15.05):"
            )
            return

    await state.update_data(target_date=target_date.strftime("%Y-%m-%d"))
    await message.answer(
        f"Принято, дата: {target_date.strftime('%d.%m.%Y')}.\nВо сколько началась смена? (ЧЧ:ММ)",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(WorkLogging.waiting_for_start)


@dp.message(WorkLogging.waiting_for_start)
async def process_start_time(message: types.Message, state: FSMContext):
    if ":" not in message.text or len(message.text) > 5:
        await message.answer(
            "Неверный формат! Нужно ЧЧ:ММ (например, 09:00). Попробуй еще раз:"
        )
        return
    await state.update_data(start_time=message.text)
    await message.answer("Принято! А во сколько смена закончилась? (ЧЧ:ММ)")
    await state.set_state(WorkLogging.waiting_for_end)


@dp.message(WorkLogging.waiting_for_end)
async def process_end_time(message: types.Message, state: FSMContext):
    end_time_str = message.text
    user_data = await state.get_data()

    start_time_str = user_data["start_time"]
    target_date_str = user_data["target_date"]

    try:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d")
        start_dt = datetime.strptime(start_time_str, "%H:%M")
        end_dt = datetime.strptime(end_time_str, "%H:%M")

        if end_dt < start_dt:
            end_dt += timedelta(days=1)

        total_minutes = int((end_dt - start_dt).total_seconds() / 60)

        if total_minutes <= 0 or total_minutes > 1440:
            await message.answer(
                "Ошибка во времени. Нажми «Отметить смену» и попробуй снова.",
                reply_markup=get_main_keyboard(),
            )
            await state.clear()
            return

        whole_hours = total_minutes // 60
        remainder_minutes = total_minutes % 60

        if remainder_minutes < 15:
            rounded_hours = float(whole_hours)
        elif remainder_minutes < 45:
            rounded_hours = whole_hours + 0.5
        else:
            rounded_hours = whole_hours + 1.0

        date_mm_dd = target_date.strftime("%m-%d")
        is_weekend_or_holiday = target_date.weekday() >= 5 or date_mm_dd in HOLIDAYS

        rate = 200
        if is_weekend_or_holiday and start_dt.hour < 12:
            rate = 250

        if rounded_hours < 4:
            earned_gold = 800
        else:
            earned_gold = int(rounded_hours * rate)

        earned_xp = rounded_hours

        conn = sqlite3.connect("rpg_tracker.db")
        cursor = conn.cursor()

        cursor.execute(
            "SELECT xp FROM users WHERE user_id = ?", (message.from_user.id,)
        )
        old_xp = cursor.fetchone()[0]

        cursor.execute(
            "UPDATE users SET xp = xp + ?, gold = gold + ? WHERE user_id = ?",
            (earned_xp, earned_gold, message.from_user.id),
        )
        cursor.execute(
            "INSERT INTO work_logs (user_id, date, hours, xp, gold) VALUES (?, ?, ?, ?, ?)",
            (
                message.from_user.id,
                target_date_str,
                rounded_hours,
                earned_xp,
                earned_gold,
            ),
        )
        conn.commit()

        cursor.execute(
            "SELECT xp, gold FROM users WHERE user_id = ?", (message.from_user.id,)
        )
        user = cursor.fetchone()
        conn.close()

        new_xp = user[0]

        old_rank = get_rank(old_xp)
        new_rank = get_rank(new_xp)

        rank_up_message = ""
        if old_rank != new_rank:
            rank_up_message = (
                f"\n\n🎊 ПОЗДРАВЛЯЕМ! Ты получил(а) новое звание: {new_rank}! 🎊"
            )

        holiday_text = (
            " (Праздничный тариф! 🎉)"
            if (date_mm_dd in HOLIDAYS and start_dt.hour < 12)
            else ""
        )

        await message.answer(
            f"✅ Смена за {target_date.strftime('%d.%m')} учтена!{holiday_text}\n"
            f"Округленное рабочее время: {rounded_hours} ч.\n\n"
            f"Заработано:\n✨ Опыт: +{earned_xp} XP\n💰 Золото: +{earned_gold}{rank_up_message}\n\n"
            f"Твой баланс: {round(new_xp, 1)} XP, {user[1]} Золота.",
            reply_markup=get_main_keyboard(),
        )
        await state.clear()

    except ValueError:
        await message.answer("Ошибка в формате! Введи время окончания еще раз (ЧЧ:ММ):")


@dp.message(Command("delete"))
async def cmd_delete(message: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("rpg_tracker.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE user_id = ?", (message.from_user.id,))
    conn.commit()
    conn.close()
    await message.answer(
        "💥 Персонаж удален. Напиши /start для создания.",
        reply_markup=ReplyKeyboardRemove(),
    )


# --- СЕКРЕТНАЯ КОМАНДА ДЛЯ ТЕСТА ОТЧЕТОВ ---
@dp.message(Command("test_report"))
async def cmd_test_report(message: types.Message):
    await message.answer(
        "🛠 Запускаю тестовую рассылку Свитков...\n(Обычно они приходят сами 14-го и в конце месяца)"
    )
    await send_report_14th()
    await send_report_end_of_month()


# --- ОТЧЕТЫ ---
async def build_and_send_report(start_date, end_date, period_text):
    conn = sqlite3.connect("rpg_tracker.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, character_name, xp, gold FROM users")
    users = cursor.fetchall()

    for user_row in users:
        user_id = user_row[0]
        char_name = user_row[1]
        total_xp = user_row[2]
        total_gold = user_row[3]
        rank = get_rank(total_xp)

        cursor.execute(
            """
            SELECT SUM(hours), SUM(xp), SUM(gold) 
            FROM work_logs 
            WHERE user_id = ? AND date >= ? AND date <= ?
        """,
            (user_id, start_date, end_date),
        )
        period_data = cursor.fetchone()

        p_hours = period_data[0] or 0
        p_xp = period_data[1] or 0
        p_gold = period_data[2] or 0

        text = (
            f"📜 <b>Королевский Свиток Отчета</b> 📜\n"
            f"Итоги периода: {period_text}\n\n"
            f"👤 Герой: {char_name}\n"
            f"🏆 Звание: {rank}\n\n"
            f"📊 <b>За этот период:</b>\n"
            f"⏱ Отработано: {round(p_hours, 1)} ч.\n"
            f"✨ Получено опыта: +{round(p_xp, 1)} XP\n"
            f"💰 Заработано золота: +{p_gold}\n\n"
            f"💼 <b>Общий баланс:</b>\n"
            f"✨ Опыт: {round(total_xp, 1)} XP\n"
            f"💰 Золото: {total_gold}\n\n"
            f"Гильдия гордится тобой! Продолжай в том же духе. ⚔️"
        )
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
        except Exception:
            pass
    conn.close()


async def send_report_14th():
    now = datetime.now(MY_TIMEZONE)
    start_date = now.replace(day=1).strftime("%Y-%m-%d")
    end_date = now.replace(day=14).strftime("%Y-%m-%d")
    await build_and_send_report(start_date, end_date, "с 1 по 14 число")


async def send_report_end_of_month():
    now = datetime.now(MY_TIMEZONE)
    start_date = now.replace(day=15).strftime("%Y-%m-%d")
    end_date = now.strftime("%Y-%m-%d")
    await build_and_send_report(start_date, end_date, "с 15 по конец месяца")


# --- НОВЫЙ БЛОК: ВЕБ-СЕРВЕР ДЛЯ UPTIMEROBOT ---
async def web_handler(request):
    return web.Response(text="Я живой!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8000)
    await site.start()
    print("Веб-сервер запущен на порту 8000! Жду пингов от UptimeRobot...")


async def main():
    init_db()

    # 1. Сначала запускаем веб-сервер
    await start_web_server()

    # 2. Запускаем расписание отчетов
    scheduler = AsyncIOScheduler(timezone=MY_TIMEZONE)
    scheduler.add_job(send_report_14th, "cron", day=14, hour=23, minute=30)
    scheduler.add_job(send_report_end_of_month, "cron", day="last", hour=23, minute=30)
    scheduler.start()

    # 3. Запускаем самого бота
    print("Бот успешно запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

# 1. Удаление смены (нужно знать ID смены)
@dp.message(Command("del_shift"))
async def del_shift(message: types.Message):
    # Допустим, пользователь пишет /del_shift 5 (где 5 - это ID смены)
    args = message.text.split()
    if len(args) > 1:
        shift_id = args[1]
        cursor.execute("DELETE FROM shifts WHERE id = ?", (shift_id,))
        conn.commit()
        await message.answer(f"Смена с ID {shift_id} удалена!")
    else:
        await message.answer("Укажите ID смены. Посмотреть ID можно в списке смен.")

# 2. Список смен за месяц
@dp.message(Command("month_report"))
async def month_report(message: types.Message):
    # Допустим, пользователь пишет /month_report 05.2026
    args = message.text.split()
    month = args[1] if len(args) > 1 else datetime.now().strftime("%m.%Y")
    
    # Запрос к БД
    cursor.execute("SELECT date, hours, gold FROM shifts WHERE date LIKE ?", (f'%.{month}',))
    shifts = cursor.fetchall()
    
    if not shifts:
        await message.answer(f"За {month} смен не найдено.")
        return

    text = f"Отчет за {month}:\n"
    for s in shifts:
        text += f"Дата: {s[0]} | Часы: {s[1]} | Золото: {s[2]}\n"
    await message.answer(text)

# --- КОМАНДА: Список смен за месяц (/list MM.YYYY) ---
@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    args = message.text.split()
    # Если месяц не указан, берем текущий
    month_year = args[1] if len(args) > 1 else datetime.now(MY_TIMEZONE).strftime("%m.%Y")
    
    # Преобразуем формат в YYYY-MM для SQL (например, 05.2026 -> 2026-05%)
    try:
        parts = month_year.split('.')
        search_pattern = f"{parts[1]}-{parts[0]}%"
    except:
        await message.answer("Используй формат: /list 05.2026")
        return

    conn = sqlite3.connect("rpg_tracker.db")
    cursor = conn.cursor()
    cursor.execute("SELECT log_id, date, hours, gold FROM work_logs WHERE date LIKE ? AND user_id = ?", 
                   (search_pattern, message.from_user.id))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await message.answer(f"За {month_year} смен не найдено.")
        return

    text = f"📜 Смены за {month_year}:\n\n"
    for row in rows:
        text += f"🆔 ID: {row[0]} | 📅 {row[1]} | ⏱ {row[2]}ч | 💰 {row[3]}\n"
    text += "\nУдалить смену: /del_shift <ID>"
    await message.answer(text)

# --- КОМАНДА: Удаление смены (/del_shift ID) ---
@dp.message(Command("del_shift"))
async def cmd_del_shift(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажи ID смены: /del_shift 123")
        return
    
    log_id = args[1]
    conn = sqlite3.connect("rpg_tracker.db")
    cursor = conn.cursor()
    
    # 1. Проверяем, существует ли смена
    cursor.execute("SELECT hours, xp, gold FROM work_logs WHERE log_id = ? AND user_id = ?", 
                   (log_id, message.from_user.id))
    shift = cursor.fetchone()
    
    if shift:
        # 2. Вычитаем данные из профиля
        cursor.execute("UPDATE users SET xp = xp - ?, gold = gold - ? WHERE user_id = ?", 
                       (shift[1], shift[2], message.from_user.id))
        # 3. Удаляем саму смену
        cursor.execute("DELETE FROM work_logs WHERE log_id = ?", (log_id,))
        conn.commit()
        await message.answer(f"✅ Смена №{log_id} удалена, баланс скорректирован.")
    else:
        await message.answer("Смена не найдена (проверь ID в /list).")
    
    conn.close()
