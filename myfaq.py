import logging
import asyncio
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import executor
import sqlite3
import aiosqlite
from datetime import datetime, timedelta
import json
from collections import defaultdict

API_TOKEN = 'ТУТА ТОКЕН.'
ADMIN_ID = 6806110770
RATE_LIMIT = 5
user_last_action = defaultdict(datetime.now)
blocked_users = set()
START_COMMAND_LIMIT = 3
START_COMMAND_WINDOW = 60
start_command_attempts = defaultdict(list)

class BanDurations:
    TWELVE_HOURS = 12 * 3600
    ONE_DAY = 24 * 3600
    ONE_WEEK = 7 * 24 * 3600
    ONE_MONTH = 30 * 24 * 3600
    ONE_YEAR = 365 * 24 * 3600
    PERMANENT = -1

class Config:
    def __init__(self):
        self.load_config()

    def load_config(self):
        try:
            with open('config.json', 'r') as f:
                self.data = json.load(f)
                if 'is_online' not in self.data:
                    self.data['is_online'] = False
                    self.save_config()
        except FileNotFoundError:
            self.data = {
                'forum_link': 'lolz.live/kqlol/',
                'telegram_username': 'selyaqiyana',
                'image_url': 'https://a-static.besthdwallpaper.com/spirit-blossom-kindred-anime-fa-league-of-legends-lol-wallpaper-2048x1536-95391_26.jpg',
                'total_users': 0,
                'daily_users': 0,
                'is_online': False
            }
            self.save_config()

    def save_config(self):
        with open('config.json', 'w') as f:
            json.dump(self.data, f, indent=4)

class AdminStates(StatesGroup):
    waiting_for_forum_link = State()
    waiting_for_telegram = State()
    waiting_for_image = State()
    waiting_for_broadcast = State()

async def init_db():
    async with aiosqlite.connect('bot_database.db') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_date TIMESTAMP,
                last_activity TIMESTAMP,
                interaction_count INTEGER DEFAULT 0,
                is_blocked INTEGER DEFAULT 0,
                ban_until TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS spam_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                attempt_time TIMESTAMP,
                         
                foreign key (user_id) references users(user_id)
            )
        ''')
        await db.commit()

async def check_start_spam(user_id: int) -> tuple[bool, int]:
    """
    Check if user is spamming /start command
    Returns (is_spam, attempts_count)
    """
    current_time = datetime.now()
    
    user_attempts = start_command_attempts[user_id]
    user_attempts.append(current_time)
    
    user_attempts = [attempt for attempt in user_attempts 
                    if (current_time - attempt) < timedelta(seconds=START_COMMAND_WINDOW)]
    start_command_attempts[user_id] = user_attempts
    
    return (len(user_attempts) > START_COMMAND_LIMIT, len(user_attempts))

logging.basicConfig(level=logging.INFO)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage, loop=loop)
config = Config()

def get_admin_keyboard():
    keyboard = InlineKeyboardMarkup()
    status_text = "🟢 Сменить статус на Офлайн" if config.data['is_online'] else "🔴 Сменить статус на Онлайн"
    keyboard.add(InlineKeyboardButton(status_text, callback_data="toggle_status"))
    keyboard.add(InlineKeyboardButton("📊 Статистика", callback_data="show_stats"))
    keyboard.add(InlineKeyboardButton("📨 Рассылка", callback_data="start_broadcast"))
    keyboard.add(InlineKeyboardButton("👥 Активные пользователи", callback_data="active_users"))
    keyboard.add(InlineKeyboardButton("🚫 Управление блокировками", callback_data="manage_blocks"))
    keyboard.add(InlineKeyboardButton("📋 Лог спама", callback_data="spam_log"))
    keyboard.add(InlineKeyboardButton("🔄 Изменить ссылку на форум", callback_data="change_forum"))
    keyboard.add(InlineKeyboardButton("📱 Изменить Telegram username", callback_data="change_telegram"))
    keyboard.add(InlineKeyboardButton("🖼 Изменить картинку", callback_data="change_image"))
    keyboard.add(InlineKeyboardButton("🔙 Вернуться в меню", callback_data="main_menu"))
    return keyboard

def get_main_keyboard(user_id=None):
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("📚 FAQ", callback_data="faq"),
        InlineKeyboardButton("📞 Связаться", url=f"https://t.me/{config.data['telegram_username']}")
    )
    status = "🟢 Онлайн" if config.data['is_online'] else "🔴 Офлайн"
    keyboard.add(InlineKeyboardButton(f"Статус администратора: {status}", callback_data="check_status"))
    keyboard.add(InlineKeyboardButton("💝 Сделать приятно", url="https://lolz.live/payment/balance-transfer?user_id=5680221&hold=1&_noRedirect=1"))
    if user_id == ADMIN_ID:
        keyboard.add(InlineKeyboardButton("🔐 Админ панель", callback_data="admin_panel"))
    return keyboard

def get_faq_keyboard(user_id=None):
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("📞 Связаться", url=f"https://t.me/{config.data['telegram_username']}")
    )
    keyboard.add(InlineKeyboardButton("💝 Сделать приятно", url="https://lolz.live/payment/balance-transfer?user_id=5680221&hold=1&_noRedirect=1"))
    keyboard.add(InlineKeyboardButton("🔙 Вернуться назад", callback_data="back_to_start"))
    if user_id == ADMIN_ID:
        keyboard.add(InlineKeyboardButton("🔐 Админ панель", callback_data="admin_panel"))
    return keyboard

start_command_usage = defaultdict(int)

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    user_id = message.from_user.id
    
    if user_id == ADMIN_ID:
        await show_start_menu(message)
        return

    async with aiosqlite.connect('bot_database.db') as db:
        cursor = await db.execute('SELECT is_blocked, ban_until FROM users WHERE user_id = ?', (user_id,))
        result = await cursor.fetchone()
        if result and result[0]:
            try:
                await message.delete()
            except:
                pass
            if result[1]:
                ban_until = datetime.strptime(result[1], '%Y-%m-%d %H:%M:%S.%f')
                remaining = ban_until - datetime.now()
                if remaining.total_seconds() > 0:
                    hours = remaining.total_seconds() // 3600
                    await message.answer(f"⛔️ Вы заблокированы еще на {int(hours)} часов.")
            else:
                await message.answer("⛔️ Вы заблокированы в боте!")
            return

    start_command_usage[user_id] += 1
    if start_command_usage[user_id] > 1:
        async with aiosqlite.connect('bot_database.db') as db:
            await db.execute('''
                INSERT INTO spam_attempts (user_id, attempt_time)
                VALUES (?, ?)
            ''', (user_id, datetime.now()))
            await db.commit()
        
        await notify_admin_about_spam(
            user_id,
            message.from_user.username,
            message.from_user.first_name
        )
        
        await message.answer("⚠️ Пожалуйста, не спамьте командой /start!")
        return

    await show_start_menu(message)

@dp.message_handler(lambda message: True, state="*")
async def handle_all_messages(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if user_id == ADMIN_ID:
        return
        
    async with aiosqlite.connect('bot_database.db') as db:
        cursor = await db.execute('SELECT is_blocked FROM users WHERE user_id = ?', (user_id,))
        result = await cursor.fetchone()
        if result and result[0]:
            try:
                await message.delete()
            except:
                pass
            return

@dp.message_handler(commands=['admin'])
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("🔐 Панель администратора:", reply_markup=get_admin_keyboard())

async def show_start_menu(message: types.Message):
    """Показывает стартовое меню бота"""
    async with aiosqlite.connect('bot_database.db') as db:
        await db.execute('''
            INSERT OR REPLACE INTO users 
            (user_id, username, first_name, last_name, joined_date, last_activity, interaction_count)
            VALUES (?, ?, ?, ?, COALESCE((SELECT joined_date FROM users WHERE user_id = ?), ?), ?, 
                   COALESCE((SELECT interaction_count FROM users WHERE user_id = ?), 0) + 1)
        ''', (
            message.from_user.id, message.from_user.username,
            message.from_user.first_name, message.from_user.last_name,
            message.from_user.id, datetime.now(), datetime.now(),
            message.from_user.id
        ))
        await db.commit()

    welcome_text = f"""
🌟 *Добро пожаловать в официального бота!*

👋 Привет, {message.from_user.first_name}!
📌 Здесь ты найдешь всю необходимую информацию о моих услугах

💫 *Что я умею:*
• Предоставлю всю важную информацию
• Помогу связаться с администратором
• Расскажу об актуальных предложениях

🔥 *Выбери интересующий раздел в меню ниже* ⬇️
"""
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except:
        pass
    
    await message.answer_photo(
        photo=config.data['image_url'],
        caption=welcome_text,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

async def update_user_activity(user_id):
    async with aiosqlite.connect('bot_database.db') as db:
        await db.execute('''
            UPDATE users 
            SET last_activity = ? 
            WHERE user_id = ?
        ''', (datetime.now(), user_id))
        await db.commit()


@dp.callback_query_handler(lambda c: c.data == "show_stats")
async def show_statistics(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect('bot_database.db') as db:
        cursor = await db.execute('SELECT COUNT(*) FROM users')
        total_users = (await cursor.fetchone())[0]

        cursor = await db.execute('''
            SELECT COUNT(*) FROM users 
            WHERE last_activity > datetime('now', '-1 day')
        ''')
        active_users = (await cursor.fetchone())[0]

        cursor = await db.execute('''
            SELECT first_name, username, interaction_count 
            FROM users 
            ORDER BY interaction_count DESC 
            LIMIT 5
        ''')
        top_users = await cursor.fetchall()

    stats_text = f"""
📊 *Статистика бота*

👥 Всего пользователей: {total_users}
🔥 Активных за 24 часа: {active_users}

🏆 *Топ активных пользователей:*
"""
    for i, user in enumerate(top_users, 1):
        name = user[0] or f"@{user[1]}" or "Пользователь"
        stats_text += f"{i}. {name} - {user[2]} действий\n"

    await callback_query.message.edit_caption(
        caption=stats_text,
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard()
    )

@dp.callback_query_handler(lambda c: c.data == "manage_blocks")
async def manage_blocks(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        return
    
    async with aiosqlite.connect('bot_database.db') as db:
        cursor = await db.execute('''
            SELECT user_id, username, first_name, is_blocked, ban_until 
            FROM users 
            WHERE is_blocked = 1 OR user_id IN (
                SELECT user_id FROM users 
                ORDER BY last_activity DESC 
                LIMIT 10
            )
        ''')
        users = await cursor.fetchall()

    keyboard = InlineKeyboardMarkup(row_width=1)
    for user in users:
        user_id, username, first_name, is_blocked, ban_until = user
        display_name = first_name or f"@{username}" or f"User:{user_id}"
        
        if is_blocked:
            if ban_until:
                remaining = datetime.strptime(ban_until, '%Y-%m-%d %H:%M:%S.%f') - datetime.now()
                status = f"🔒 {remaining.days}д {remaining.seconds//3600}ч"
            else:
                status = "🔒 Permanent"
        else:
            status = "🔓"
            
        keyboard.add(InlineKeyboardButton(
            f"{status} {display_name}", 
            callback_data=f"user_{user_id}"
        ))
    
    keyboard.add(InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
    
    await callback_query.message.edit_caption(
        caption="🚫 *Управление блокировками*\n\nВыберите пользователя для управления блокировкой:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

@dp.callback_query_handler(lambda c: c.data == "spam_log")
async def show_spam_log(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect('bot_database.db') as db:
        cursor = await db.execute('''
            SELECT 
                users.first_name,
                users.username,
                users.user_id,
                COUNT(spam_attempts.id) as spam_count,
                MAX(spam_attempts.attempt_time) as last_attempt
            FROM spam_attempts
            JOIN users ON spam_attempts.user_id = users.user_id
            GROUP BY users.user_id
            ORDER BY last_attempt DESC
            LIMIT 20
        ''')
        attempts = await cursor.fetchall()

    log_text = "📋 *Лог попыток спама:*\n\n"
    for attempt in attempts:
        name = attempt[0] or f"@{attempt[1]}" or f"ID:{attempt[2]}"
        spam_count = attempt[3]
        last_time = datetime.strptime(attempt[4], '%Y-%m-%d %H:%M:%S.%f')
        log_text += f"👤 *{name}*\n"
        log_text += f"📊 Количество попыток: {spam_count}\n"
        log_text += f"🕒 Последняя попытка: {last_time.strftime('%H:%M %d.%m.%Y')}\n\n"

    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))

    await callback_query.message.edit_caption(
        caption=log_text,
        parse_mode="Markdown",
        reply_markup=keyboard
    )

@dp.callback_query_handler(lambda c: c.data == "active_users")
async def show_active_users(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect('bot_database.db') as db:
        cursor = await db.execute('''
            SELECT first_name, username, last_activity 
            FROM users 
            WHERE last_activity > datetime('now', '-1 day')
            ORDER BY last_activity DESC
        ''')
        active_users = await cursor.fetchall()

    active_users_text = "👥 *Активные пользователи за 24 часа:*\n\n"
    for user in active_users:
        name = user[0] or f"@{user[1]}" or "Пользователь"
        last_active = datetime.strptime(user[2], '%Y-%m-%d %H:%M:%S.%f')
        active_users_text += f"• {name} - {last_active.strftime('%H:%M %d.%m.%Y')}\n"

    await callback_query.message.edit_caption(
        caption=active_users_text,
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard()
    )

@dp.callback_query_handler(lambda c: c.data == "back_to_start")
async def back_to_start(callback_query: types.CallbackQuery):
    welcome_text = f"""
🌟 *Добро пожаловать в официального бота!*

👋 Привет, {callback_query.from_user.first_name}!
📌 Здесь ты найдешь всю необходимую информацию о моих услугах

💫 *Что я умею:*
• Предоставлю всю важную информацию
• Помогу связаться с администратором
• Расскажу об актуальных предложениях

🔥 *Выбери интересующий раздел в меню ниже* ⬇️
"""
    await callback_query.message.edit_caption(
        caption=welcome_text,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(callback_query.from_user.id)
    )

@dp.callback_query_handler(lambda c: c.data == "faq")
async def show_faq(callback_query: types.CallbackQuery):
    async with aiosqlite.connect('bot_database.db') as db:
        await db.execute('''
            UPDATE users 
            SET interaction_count = interaction_count + 1,
                last_activity = ?
            WHERE user_id = ?
        ''', (datetime.now(), callback_query.from_user.id))
        await db.commit()

    faq_text = f"""
📌 *FAQ:*

🌐 *Форумник:* {config.data['forum_link']}
💬 *Правила сделок:* Все сделки через личку предварительно.
🆔 *Telegram ID:* 6806110770
🚀 *БУСТ В ЛИГЕ ЛЕГЕНД:* Отметьте "БУСТ" при обращении.
❓ *Форум:* По вопросам форума - в личку.
🤖 *Автореги:* По вопросам EPS - в личку.
"""
    await callback_query.message.edit_caption(
        caption=faq_text,
        parse_mode="Markdown",
        reply_markup=get_faq_keyboard(callback_query.from_user.id)
    )
@dp.callback_query_handler(lambda c: c.data == "admin_panel")
async def admin_panel_handler(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        return
    
    admin_text = "🔐 *Панель администратора*"
    await callback_query.message.edit_caption(
        caption=admin_text,
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard()
    )

@dp.callback_query_handler(lambda c: c.data == "main_menu")
async def return_to_main_menu(callback_query: types.CallbackQuery):
    welcome_text = """
🌟 *Добро пожаловать в официального бота!*

🔥 *Выберите интересующий раздел в меню ниже* ⬇️
"""
    try:
        await callback_query.message.edit_caption(
            caption=welcome_text,
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(callback_query.from_user.id)
        )
    except:
        try:
            await callback_query.message.delete()
        except:
            pass
        
        await callback_query.message.answer_photo(
            photo=config.data['image_url'],
            caption=welcome_text,
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(callback_query.from_user.id)
        )

@dp.callback_query_handler(lambda c: c.data.startswith("user_"))
async def user_ban_menu(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        return
        
    user_id = int(callback_query.data.split("_")[1])
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("12 часов", callback_data=f"ban_{user_id}_{BanDurations.TWELVE_HOURS}"),
        InlineKeyboardButton("1 день", callback_data=f"ban_{user_id}_{BanDurations.ONE_DAY}"),
        InlineKeyboardButton("1 неделя", callback_data=f"ban_{user_id}_{BanDurations.ONE_WEEK}"),
        InlineKeyboardButton("1 месяц", callback_data=f"ban_{user_id}_{BanDurations.ONE_MONTH}"),
        InlineKeyboardButton("1 год", callback_data=f"ban_{user_id}_{BanDurations.ONE_YEAR}"),
        InlineKeyboardButton("Навсегда", callback_data=f"ban_{user_id}_{BanDurations.PERMANENT}"),
    )
    keyboard.add(InlineKeyboardButton("Разблокировать", callback_data=f"unban_{user_id}"))
    keyboard.add(InlineKeyboardButton("🔙 Назад", callback_data="manage_blocks"))
    
    await callback_query.message.edit_caption(
        caption=f"Выберите действие для пользователя ID:{user_id}:",
        reply_markup=keyboard
    )

@dp.callback_query_handler(lambda c: c.data.startswith(("ban_", "unban_")))
async def handle_ban_unban(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        return
        
    action, user_id = callback_query.data.split("_")[:2]
    user_id = int(user_id)
    
    if action == "ban":
        duration = int(callback_query.data.split("_")[2])
        await ban_user(user_id, duration)
        duration_text = "навсегда" if duration == BanDurations.PERMANENT else f"на {duration//3600} часов"
        await callback_query.answer(f"Пользователь заблокирован {duration_text}")
    else:
        await unban_user(user_id)
        await callback_query.answer("Пользователь разблокирован")
    
    await manage_blocks(callback_query)

@dp.callback_query_handler(lambda c: c.data.startswith("change_"))
async def handle_admin_actions(callback_query: types.CallbackQuery, state: FSMContext):
    if callback_query.from_user.id != ADMIN_ID:
        return
    
    action = callback_query.data.split("_")[1]
    if action == "forum":
        await AdminStates.waiting_for_forum_link.set()
        await callback_query.message.answer("Введите новую ссылку на форум:")
    elif action == "telegram":
        await AdminStates.waiting_for_telegram.set()
        await callback_query.message.answer("Введите новый Telegram username (без @):")
    elif action == "image":
        await AdminStates.waiting_for_image.set()
        await callback_query.message.answer("Отправьте новую ссылку на изображение:")

@dp.message_handler(state=AdminStates.waiting_for_forum_link)
async def process_forum_link(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    config.data['forum_link'] = message.text
    config.save_config()
    await state.finish()
    await message.answer("✅ Ссылка на форум обновлена!", reply_markup=get_admin_keyboard())

@dp.message_handler(state=AdminStates.waiting_for_telegram)
async def process_telegram(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    config.data['telegram_username'] = message.text.replace("@", "")
    config.save_config()
    await state.finish()
    await message.answer("✅ Telegram username обновлен!", reply_markup=get_admin_keyboard())

@dp.message_handler(state=AdminStates.waiting_for_image)
async def process_image(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    config.data['image_url'] = message.text
    config.save_config()
    await state.finish()
    await message.answer("✅ Ссылка на изображение обновлена!", reply_markup=get_admin_keyboard())

@dp.callback_query_handler(lambda c: c.data == "check_status")
async def check_status(callback_query: types.CallbackQuery):
    status = "🟢 Администратор онлайн" if config.data['is_online'] else "🔴 Администратор офлайн"
    await callback_query.answer(f"{status}", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == "toggle_status")
async def toggle_status(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        return
    
    config.data['is_online'] = not config.data['is_online']
    config.save_config()
    
    status = "🟢 Онлайн" if config.data['is_online'] else "🔴 Офлайн"
    await callback_query.answer(f"Ваш статус изменен на: {status}")
    
    admin_text = "🔐 *Панель администратора*"
    await callback_query.message.edit_caption(
        caption=admin_text,
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard()
    )

@dp.callback_query_handler(lambda c: c.data == "start_broadcast")
async def start_broadcast(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        return
    
    await AdminStates.waiting_for_broadcast.set()
    await callback_query.message.answer("📨 Введите сообщение для рассылки:")

@dp.message_handler(state=AdminStates.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    await state.finish()
    status_message = await message.answer("📨 Начинаю рассылку...")
    
    async with aiosqlite.connect('bot_database.db') as db:
        cursor = await db.execute('SELECT user_id FROM users WHERE is_blocked = 0 AND user_id != ?', (ADMIN_ID,))
        users = await cursor.fetchall()
    
    total_users = len(users)
    successful = 0
    failed = 0
    failed_users = []
    
    for user in users:
        try:
            await bot.send_message(user[0], message.text, parse_mode="Markdown")
            successful += 1
        except Exception as e:
            failed += 1
            failed_users.append(user[0])
        
        await asyncio.sleep(0.05)
    
    success_rate = (successful / total_users) * 100 if total_users > 0 else 0
    
    report = f"""
📊 *Статистика рассылки:*

📧 Всего пользователей для рассылки: {total_users}
✅ Успешно доставлено: {successful}
❌ Не доставлено: {failed}
📈 Процент успеха: {success_rate:.1f}%

"""
    if failed_users:
        report += "\n❌ *ID пользователей с ошибкой доставки:*\n"
        report += "\n".join([f"• `{uid}`" for uid in failed_users[:10]])
        if len(failed_users) > 10:
            report += f"\n_...и еще {len(failed_users) - 10} пользователей_"
    
    await status_message.edit_text(report, parse_mode="Markdown")
    
    await message.answer("🔐 Панель администратора:", reply_markup=get_admin_keyboard())

@dp.callback_query_handler()
async def process_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    
    async with aiosqlite.connect('bot_database.db') as db:
        cursor = await db.execute('SELECT is_blocked FROM users WHERE user_id = ?', (user_id,))
        result = await cursor.fetchone()
        if result and result[0] and user_id != ADMIN_ID:
            await callback_query.answer("Вы заблокированы в боте!", show_alert=True)
            return

    last_action = user_last_action[user_id]
    if datetime.now() - last_action < timedelta(seconds=RATE_LIMIT) and user_id != ADMIN_ID:
        await callback_query.answer("Подождите перед следующим действием!", show_alert=True)
        
        async with aiosqlite.connect('bot_database.db') as db:
            await db.execute('''
                INSERT INTO spam_attempts (user_id, attempt_time)
                VALUES (?, ?)
            ''', (user_id, datetime.now()))
            await db.commit()
        return

    user_last_action[user_id] = datetime.now()
    await update_user_activity(user_id)
    await callback_query.answer()

async def unban_user_after_delay(user_id: int):
    """Unban user after 24 hours"""
    await asyncio.sleep(24 * 3600)
    
    async with aiosqlite.connect('bot_database.db') as db:
        await db.execute('''
            UPDATE users 
            SET is_blocked = 0
            WHERE user_id = ?
        ''', (user_id,))
        await db.commit()
    
    blocked_users.discard(user_id)
    try:
        await bot.send_message(user_id, "✅ Ваша блокировка была снята. Пожалуйста, не спамьте командой /start.")
    except:
        pass

async def on_startup(dp):
    await init_db()
    logging.info('Bot started successfully!')

async def ban_user(user_id: int, duration: int = None):
    """
    Ban user for specified duration
    duration in seconds, None for permanent ban
    """
    ban_until = datetime.now() + timedelta(seconds=duration) if duration and duration > 0 else None
    
    async with aiosqlite.connect('bot_database.db') as db:
        await db.execute('''
            UPDATE users 
            SET is_blocked = 1,
                ban_until = ?
            WHERE user_id = ?
        ''', (ban_until, user_id))
        await db.commit()
    
    blocked_users.add(user_id)
    
    try:
        if duration and duration > 0:
            hours = duration // 3600
            await bot.send_message(user_id, f"⛔️ Вы заблокированы на {hours} часов.")
            asyncio.create_task(unban_user_after_delay(user_id, duration))
        else:
            await bot.send_message(user_id, "⛔️ Вы заблокированы навсегда.")
    except:
        pass

async def unban_user(user_id: int):
    """Unban user immediately"""
    async with aiosqlite.connect('bot_database.db') as db:
        await db.execute('''
            UPDATE users 
            SET is_blocked = 0,
                ban_until = NULL
            WHERE user_id = ?
        ''', (user_id,))
        await db.commit()
    
    blocked_users.discard(user_id)
    try:
        await bot.send_message(user_id, "✅ Ваша блокировка была снята администратором.")
    except:
        pass

async def unban_user_after_delay(user_id: int, delay: int):
    """Unban user after specified delay in seconds"""
    await asyncio.sleep(delay)
    
    async with aiosqlite.connect('bot_database.db') as db:
        cursor = await db.execute('SELECT is_blocked, ban_until FROM users WHERE user_id = ?', (user_id,))
        result = await cursor.fetchone()
        
        if not result or not result[0]:
            return
            
        if result[1]:
            ban_until = datetime.strptime(result[1], '%Y-%m-%d %H:%M:%S.%f')
            if ban_until > datetime.now() + timedelta(seconds=1):
                return
    
    await unban_user(user_id)

async def notify_admin_about_spam(user_id: int, username: str = None, first_name: str = None):
    """Уведомляет админа о попытке спама"""
    display_name = first_name or f"@{username}" or f"ID:{user_id}"
    admin_message = f"⚠️ *Обнаружен спам!*\n\n👤 Пользователь: {display_name}\n🆔 ID: `{user_id}`"
    
    try:
        await bot.send_message(
            ADMIN_ID,
            admin_message,
            parse_mode="Markdown"
        )
    except:
        pass

if __name__ == '__main__':
    try:
        executor.start_polling(
            dp,
            skip_updates=True,
            on_startup=on_startup,
            timeout=20
        )
    except Exception as e:
        logging.error(f"Critical error: {e}")
    finally:
        loop.run_until_complete(dp.storage.close())
        loop.run_until_complete(dp.storage.wait_closed())
        loop.close()