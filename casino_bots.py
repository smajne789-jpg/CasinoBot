# Telegram Casino Bot (aiogram) — FULL UPGRADE
# ===========================================
# pip install aiogram aiosqlite aiohttp

import os
import random
import asyncio
import aiosqlite
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
CRYPTO_TOKEN = os.getenv("CRYPTO_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

CRYPTO_API = "https://pay.crypt.bot/api"
HEADERS = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}

user_states = {}

# ================= DB =================
async def init_db():
    async with aiosqlite.connect("db.sqlite") as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0)")
        await db.execute("CREATE TABLE IF NOT EXISTS invoices (invoice_id TEXT, user_id INTEGER, amount REAL, status TEXT)")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS checks (
            code TEXT PRIMARY KEY,
            amount REAL,
            activations INTEGER,
            used INTEGER DEFAULT 0,
            min_dep REAL DEFAULT 0
        )""")
        await db.execute("CREATE TABLE IF NOT EXISTS check_uses (user_id INTEGER, code TEXT)")
        await db.commit()

# ================= BALANCE =================
async def get_balance(user_id):
    async with aiosqlite.connect("db.sqlite") as db:
        cur = await db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if not row:
            await db.execute("INSERT INTO users VALUES (?,0)", (user_id,))
            await db.commit()
            return 0
        return row[0]

async def update_balance(user_id, amount):
    async with aiosqlite.connect("db.sqlite") as db:
        await db.execute("INSERT OR IGNORE INTO users VALUES (?,0)", (user_id,))
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
        await db.commit()

# ================= START =================
@dp.message_handler(commands=['start'])
async def start(msg: types.Message):
    args = msg.get_args()

    if args.startswith("check_"):
        code = args.split("_")[1]
        await activate_check(msg, code)
        return

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("👤 Профиль", callback_data="profile"))

    await msg.answer("🎰 Добро пожаловать в PAVLUCK CASINO", reply_markup=kb)

# ================= PROFILE =================
@dp.callback_query_handler(lambda c: c.data == "profile")
async def profile(call: types.CallbackQuery):
    bal = await get_balance(call.from_user.id)

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("💳 Пополнить", callback_data="deposit"),
        InlineKeyboardButton("📤 Вывод", callback_data="withdraw")
    )

    await call.message.edit_text(
        f"👤 Профиль\n🆔 {call.from_user.id}\n💰 Баланс: {bal}$",
        reply_markup=kb
    )

# ================= CHECK PROTECTION =================
async def activate_check(msg, code):
    async with aiosqlite.connect("db.sqlite") as db:
        # Проверка на повторное использование
        cur = await db.execute("SELECT 1 FROM check_uses WHERE user_id=? AND code=?", (msg.from_user.id, code))
        if await cur.fetchone():
            await msg.answer("❌ Ты уже активировал этот чек")
            return

        cur = await db.execute("SELECT amount, activations, used, min_dep FROM checks WHERE code=?", (code,))
        row = await cur.fetchone()

        if not row:
            await msg.answer("❌ Чек не найден")
            return

        amount, activations, used, min_dep = row

        if used >= activations:
            await msg.answer("❌ Чек закончился")
            return

        bal = await get_balance(msg.from_user.id)
        if bal < min_dep:
            await msg.answer(f"❌ Нужен депозит {min_dep}$")
            return

        await update_balance(msg.from_user.id, amount)

        await db.execute("UPDATE checks SET used = used + 1 WHERE code=?", (code,))
        await db.execute("INSERT INTO check_uses VALUES (?,?)", (msg.from_user.id, code))
        await db.commit()

        await msg.answer(f"✅ Чек активирован: +{amount}$")

# ================= ADMIN PANEL =================
@dp.message_handler(commands=['admin'])
async def admin_panel(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return

    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🎟 Создать чек", callback_data="create_check"),
        InlineKeyboardButton("💰 Пополнить баланс", callback_data="add_balance"),
        InlineKeyboardButton("📢 Рассылка", callback_data="broadcast")
    )

    await msg.answer("⚙️ Админ-панель", reply_markup=kb)

# ================= STATES =================
@dp.callback_query_handler(lambda c: c.data == "create_check")
async def create_check(call):
    user_states[call.from_user.id] = {"step": "amount"}
    await call.message.answer("💵 Сумма:")

@dp.callback_query_handler(lambda c: c.data == "add_balance")
async def add_balance(call):
    user_states[call.from_user.id] = {"step": "user"}
    await call.message.answer("👤 ID пользователя:")

@dp.callback_query_handler(lambda c: c.data == "broadcast")
async def broadcast(call):
    user_states[call.from_user.id] = {"step": "broadcast"}
    await call.message.answer("📢 Введи сообщение для рассылки:")

# ================= HANDLER =================
@dp.message_handler()
async def states(msg: types.Message):
    state = user_states.get(msg.from_user.id)
    if not state:
        return

    # CHECK
    if state["step"] == "amount":
        state["amount"] = float(msg.text)
        state["step"] = "act"
        await msg.answer("🔢 Активации:")

    elif state["step"] == "act":
        state["act"] = int(msg.text)
        state["step"] = "dep"
        await msg.answer("💳 Мин депозит:")

    elif state["step"] == "dep":
        code = str(random.randint(10000, 99999))

        async with aiosqlite.connect("db.sqlite") as db:
            await db.execute("INSERT INTO checks VALUES (?,?,?,?,?)",
                             (code, state["amount"], state["act"], 0, float(msg.text)))
            await db.commit()

        link = f"https://t.me/{BOT_USERNAME}?start=check_{code}"
        await msg.answer(f"✅ Чек:\n{link}")
        user_states.pop(msg.from_user.id)

    # BALANCE
    elif state["step"] == "user":
        state["target"] = int(msg.text)
        state["step"] = "sum"
        await msg.answer("💰 Сумма:")

    elif state["step"] == "sum":
        await update_balance(state["target"], float(msg.text))
        await msg.answer("✅ Готово")
        user_states.pop(msg.from_user.id)

    # BROADCAST
    elif state["step"] == "broadcast":
        async with aiosqlite.connect("db.sqlite") as db:
            cur = await db.execute("SELECT user_id FROM users")
            users = await cur.fetchall()

        sent = 0
        for u in users:
            try:
                await bot.send_message(u[0], msg.text)
                sent += 1
            except:
                pass

        await msg.answer(f"📢 Отправлено: {sent}")
        user_states.pop(msg.from_user.id)

# ================= BET LOG CHANNEL =================
BET_CHANNEL_ID = int(os.getenv("BET_CHANNEL_ID", "0"))

async def log_bet(user_id, game, bet, result):
    if BET_CHANNEL_ID == 0:
        return
    try:
        await bot.send_message(
    BET_CHANNEL_ID,
    f"""🧾 Ставка
📌 {game}
💰 {bet}$
📊 {result}"""
)
    except:
        pass

# ================= GAMES =================
@dp.message_handler(commands=['even'])
async def even_game(msg: types.Message):
    bet = float(msg.get_args())
    roll = random.randint(1, 6)

    if roll % 2 == 0:
        win = bet * 2
        await update_balance(msg.from_user.id, win)
        result = f"Выигрыш {win}$ (выпало {roll})"
        await msg.answer(f"🎲 {roll}
✅ {win}$")
    else:
        await update_balance(msg.from_user.id, -bet)
        result = f"Проигрыш (выпало {roll})"
        await msg.answer(f"🎲 {roll}
❌")

    await log_bet(msg.from_user.id, "Чёт x2", bet, result)

@dp.message_handler(commands=['odd'])
async def odd_game(msg: types.Message):
    bet = float(msg.get_args())
    roll = random.randint(1, 6)

    if roll % 2 != 0:
        win = bet * 2
        await update_balance(msg.from_user.id, win)
        result = f"Выигрыш {win}$ ({roll})"
        await msg.answer(f"🎲 {roll}
✅ {win}$")
    else:
        await update_balance(msg.from_user.id, -bet)
        result = f"Проигрыш ({roll})"
        await msg.answer(f"🎲 {roll}
❌")

    await log_bet(msg.from_user.id, "Нечёт x2", bet, result)

@dp.message_handler(commands=['seven'])
async def seven(msg: types.Message):
    bet = float(msg.get_args())
    d1, d2 = random.randint(1,6), random.randint(1,6)

    if d1 + d2 == 7:
        win = bet * 5
        await update_balance(msg.from_user.id, win)
        result = f"Выигрыш {win}$ ({d1}+{d2})"
        await msg.answer(f"🎲 {d1}+{d2}
✅ {win}$")
    else:
        await update_balance(msg.from_user.id, -bet)
        result = f"Проигрыш ({d1}+{d2})"
        await msg.answer(f"🎲 {d1}+{d2}
❌")

    await log_bet(msg.from_user.id, "Ровно 7 x5", bet, result)

@dp.message_handler(commands=['whale'])
async def whale(msg: types.Message):
    bet = float(msg.get_args())
    num = random.randint(1, 100)

    if num == 100:
        win = bet * 100
        await update_balance(msg.from_user.id, win)
        result = f"JACKPOT {win}$ (100)"
        await msg.answer(f"🐳 {num}
💰 {win}$")
    else:
        await update_balance(msg.from_user.id, -bet)
        result = f"Проигрыш ({num})"
        await msg.answer(f"🐳 {num}
❌")

    await log_bet(msg.from_user.id, "🐳 x100", bet, result)

# ================= RUN =================
if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    executor.start_polling(dp, skip_updates=True)
