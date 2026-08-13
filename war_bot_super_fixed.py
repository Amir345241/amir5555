import logging
import sqlite3
import json
import random
import time
import os
import shutil
import asyncio
import traceback
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters, ContextTypes

# ========== توکن و تنظیمات ==========
# روی Railway توکن را داخل کد نمی‌نویسیم؛ از Environment Variable خونده می‌شه (BOT_TOKEN).
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError(
        "❌ متغیر محیطی BOT_TOKEN تنظیم نشده! "
        "توی Railway برو به تب Variables و BOT_TOKEN رو با توکن ربات‌ات اضافه کن."
    )
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "7845464086").split(",") if x.strip()]
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-1002157518380"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== مرحله‌های ConversationHandler ==========
COUNTRY_NAME, BET_AMOUNT, CLAN_NAME, DUEL_OPPONENT = range(4)

# ========== دیتابیس ==========
# اگر روی Railway یک Volume ساختی (مثلاً روی /data)، متغیر DB_PATH را روی
# /data/game.db بذار تا دیتابیس بعد از هر ری‌دیپلوی پاک نشه. اگر چیزی ست نکنی،
# همون game.db کنار کد ساخته می‌شه (که با هر دیپلوی جدید روی Railway از بین می‌ره).
DB_NAME = os.environ.get("DB_PATH", "game.db")

# مطمئن می‌شیم پوشه‌ی مقصد (مثلاً /data روی Volume ریلوی) از قبل وجود داره،
# وگرنه sqlite3.connect با ارور "unable to open database file" مواجه می‌شه.
_db_dir = os.path.dirname(DB_NAME)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)

def db_connect():
    """اتصال استاندارد به دیتابیس با WAL mode و busy_timeout
    تا کوئری‌های همزمان (خصوصاً هنگام آپلود دیتابیس جدید) باعث قفل و کند شدن کل ربات نشوند."""
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

# ========== ۱۵ سلاح جنگی + ۱۵ سلاح دفاعی ==========
OFFENSIVE_EQUIPMENT = {
    "soldiers": {"name": "🪖 سرباز پیاده", "power": 1, "price": 100, "flag": ""},
    "tanks": {"name": "🚜 تانک", "power": 5, "price": 500, "flag": ""},
    "fighters": {"name": "✈️ جنگنده", "power": 10, "price": 1000, "flag": ""},
    "ships": {"name": "🚢 ناو جنگی", "power": 8, "price": 2000, "flag": ""},
    "missiles": {"name": "🚀 موشک بالستیک", "power": 15, "price": 3000, "flag": ""},
    "attack_helicopters": {"name": "🚁 بالگرد هجومی", "power": 12, "price": 2500, "flag": ""},
    "tactical_bombers": {"name": "💣 بمب‌افکن تاکتیکی", "power": 18, "price": 4000, "flag": ""},
    "mi28": {"name": "🇷🇺 بالگرد میل-۲۸", "power": 14, "price": 3200, "flag": "🇷🇺"},
    "puma_ifv": {"name": "🇩🇪 نفربر پوما", "power": 7, "price": 1800, "flag": "🇩🇪"},
    "boxer_ifv": {"name": "🇳🇱 نفربر زرهی بوکسر", "power": 8, "price": 2200, "flag": "🇳🇱"},
    "tiger_heli": {"name": "🇪🇺 بالگرد یوروکپتر تایگر", "power": 16, "price": 4500, "flag": "🇪🇺"},
    "ew_trucks": {"name": "💻 کامیون جنگ الکترونیک", "power": 6, "price": 3500, "flag": ""},
    "grenade_launchers": {"name": "💣 نارنجک‌انداز", "power": 4, "price": 800, "flag": ""},
    "pzh2000": {"name": "🇩🇪 توپخانه PzH 2000", "power": 20, "price": 5500, "flag": "🇩🇪"},
    "cruise_missiles": {"name": "🚀 موشک کروز", "power": 25, "price": 8000, "flag": ""},
}

DEFENSIVE_EQUIPMENT = {
    "defense": {"name": "🛡️ پدافند", "power": 3, "price": 2500, "flag": ""},
    "bunkers": {"name": "🏰 سنگر بتونی", "power": 5, "price": 3000, "flag": ""},
    "air_defense": {"name": "🎯 سامانه پدافندی", "power": 10, "price": 6000, "flag": ""},
    "scout_helicopters": {"name": "🚁 بالگرد شناسایی", "power": 4, "price": 2000, "flag": ""},
    "s400": {"name": "🇷🇺 سامانه S-400", "power": 30, "price": 15000, "flag": "🇷🇺"},
    "patriot": {"name": "🇺🇸 پاتریوت", "power": 28, "price": 14000, "flag": "🇺🇸"},
    "walls": {"name": "🛡️ دیوار دفاعی", "power": 3, "price": 1500, "flag": ""},
    "anti_tank_mines": {"name": "💣 مین ضدتانک", "power": 8, "price": 2500, "flag": ""},
    "snipers": {"name": "🔫 تک‌تیرانداز", "power": 6, "price": 1200, "flag": ""},
    "scout_drones": {"name": "🚁 پهپاد شناسایی", "power": 5, "price": 3500, "flag": ""},
    "advanced_radar": {"name": "🎯 رادار پیشرفته", "power": 7, "price": 4500, "flag": ""},
    "laser_shield": {"name": "🛡️ سپر لیزری", "power": 15, "price": 20000, "flag": ""},
    "watchtowers": {"name": "🏰 برج دیده‌بانی", "power": 4, "price": 1800, "flag": ""},
    "abm_missiles": {"name": "💣 موشک ضدبالستیک", "power": 22, "price": 12000, "flag": ""},
    "ew_systems": {"name": "🎯 سامانه جنگ الکترونیک", "power": 9, "price": 7000, "flag": ""},
}

ALL_EQUIPMENT = {**OFFENSIVE_EQUIPMENT, **DEFENSIVE_EQUIPMENT}

DEFAULT_EQUIPMENT = {k: 0 for k in ALL_EQUIPMENT.keys()}
DEFAULT_VIP_BUILDINGS = {"hospital":0,"factory":0,"refinery":0,"university":0,"airport":0,"shelter_advanced":0}

def init_db():
    conn = db_connect()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            country_name TEXT,
            gold INTEGER DEFAULT 1000,
            oil INTEGER DEFAULT 500,
            army INTEGER DEFAULT 5,
            economy INTEGER DEFAULT 10,
            tech INTEGER DEFAULT 5,
            population INTEGER DEFAULT 100,
            equipment TEXT DEFAULT ''' + repr(json.dumps(DEFAULT_EQUIPMENT)) + ''',
            nuke BOOLEAN DEFAULT 0,
            shelter BOOLEAN DEFAULT 0,
            alliance TEXT DEFAULT '',
            clan TEXT DEFAULT '',
            last_attack_time INTEGER DEFAULT 0,
            last_free_money INTEGER DEFAULT 0,
            last_company_time INTEGER DEFAULT 0,
            last_daily_mission INTEGER DEFAULT 0,
            last_daily_gift INTEGER DEFAULT 0,
            total_wins INTEGER DEFAULT 0,
            total_losses INTEGER DEFAULT 0,
            statement TEXT DEFAULT '',
            subsidiary TEXT DEFAULT '',
            secret_chat TEXT DEFAULT '',
            is_vip BOOLEAN DEFAULT 0,
            vip_buildings TEXT DEFAULT ''' + repr(json.dumps(DEFAULT_VIP_BUILDINGS)) + ''',
            drugs INTEGER DEFAULT 0,
            cyber_attacks INTEGER DEFAULT 0,
            is_banned BOOLEAN DEFAULT 0,
            total_bets INTEGER DEFAULT 0,
            total_bet_wins INTEGER DEFAULT 0,
            daily_streak INTEGER DEFAULT 0,
            shares TEXT DEFAULT '{}',
            duel_wins INTEGER DEFAULT 0,
            duel_losses INTEGER DEFAULT 0,
            group_points INTEGER DEFAULT 0,
            spins INTEGER DEFAULT 0,
            last_spin INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            referred_by INTEGER DEFAULT 0,
            mining_power INTEGER DEFAULT 1,
            last_mine INTEGER DEFAULT 0,
            achievement_points INTEGER DEFAULT 0,
            lucky_streak INTEGER DEFAULT 0,
            shield_active_until INTEGER DEFAULT 0,
            bank_gold INTEGER DEFAULT 0,
            nuke_scientists INTEGER DEFAULT 0,
            nuke_factory INTEGER DEFAULT 0,
            nuke_research INTEGER DEFAULT 0,
            terror_resistance INTEGER DEFAULT 0,
            peace_offers TEXT DEFAULT '{}'
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS clans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            owner_id INTEGER,
            members TEXT DEFAULT '[]',
            gold INTEGER DEFAULT 0,
            oil INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            created_at INTEGER
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS npc_countries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            gold INTEGER,
            oil INTEGER,
            army INTEGER,
            equipment TEXT,
            is_alive BOOLEAN DEFAULT 1,
            defense_power INTEGER DEFAULT 5,
            share_price INTEGER DEFAULT 100
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS attack_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attacker_id INTEGER,
            attacker_name TEXT,
            defender_id INTEGER,
            defender_name TEXT,
            result TEXT,
            gold_stolen INTEGER,
            oil_stolen INTEGER,
            timestamp INTEGER
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            sender_name TEXT,
            receiver_id INTEGER,
            receiver_name TEXT,
            amount INTEGER,
            timestamp INTEGER
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS required_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT UNIQUE,
            channel_name TEXT,
            invite_link TEXT,
            added_by INTEGER,
            added_at INTEGER
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS coupons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            type TEXT,
            amount INTEGER,
            max_uses INTEGER,
            used_count INTEGER DEFAULT 0,
            expires_at INTEGER,
            created_by INTEGER,
            created_at INTEGER
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS coupon_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coupon_id INTEGER,
            user_id INTEGER,
            used_at INTEGER
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            added_by INTEGER,
            added_at INTEGER
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS admin_permissions (
            user_id INTEGER,
            permission TEXT,
            PRIMARY KEY (user_id, permission)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            unlocked_at INTEGER
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS world_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_text TEXT,
            event_type TEXT,
            created_at INTEGER,
            expires_at INTEGER,
            active BOOLEAN DEFAULT 1
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS treasures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gold INTEGER,
            oil INTEGER,
            found_by INTEGER DEFAULT 0,
            created_at INTEGER,
            expires_at INTEGER
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS pending_attacks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attacker_id INTEGER,
            defender_id INTEGER,
            percent INTEGER,
            arrival_time INTEGER,
            status TEXT DEFAULT 'pending',
            created_at INTEGER
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS peace_treaties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country1_id INTEGER,
            country2_id INTEGER,
            expires_at INTEGER,
            created_at INTEGER
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS statements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            country_name TEXT,
            text TEXT,
            created_at INTEGER
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS secret_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            receiver_id INTEGER,
            text TEXT,
            created_at INTEGER,
            is_read BOOLEAN DEFAULT 0
        )
    ''')

    # Migrate old users with old equipment format
    try:
        c.execute("SELECT user_id, equipment FROM users")
        for row in c.fetchall():
            uid, equip_str = row
            try:
                equip = json.loads(equip_str)
                if isinstance(equip, dict) and "soldiers" in equip and len(equip) < 10:
                    # Old format, migrate
                    new_equip = DEFAULT_EQUIPMENT.copy()
                    for k, v in equip.items():
                        if k in new_equip:
                            new_equip[k] = v
                    c.execute("UPDATE users SET equipment = ? WHERE user_id = ?", (json.dumps(new_equip), uid))
            except:
                pass
    except:
        pass

    c.execute('SELECT COUNT(*) FROM npc_countries')
    if c.fetchone()[0] == 0:
        npcs = [
            ("🇪🇸 اسپانیا", 5000, 2000, 10, json.dumps({**DEFAULT_EQUIPMENT, "soldiers":10,"tanks":2,"fighters":1,"defense":1}), 8, 100),
            ("🇦🇫 افغانستان", 3000, 1000, 8, json.dumps({**DEFAULT_EQUIPMENT, "soldiers":8,"tanks":1,"defense":0}), 5, 80),
            ("🏛️ هخامنشیان", 8000, 3000, 15, json.dumps({**DEFAULT_EQUIPMENT, "soldiers":15,"tanks":3,"fighters":2,"ships":1,"missiles":1,"defense":2}), 12, 150),
            ("🇮🇷 ایران", 10000, 5000, 20, json.dumps({**DEFAULT_EQUIPMENT, "soldiers":20,"tanks":5,"fighters":3,"ships":2,"missiles":2,"defense":3}), 15, 200),
            ("🇵🇰 پاکستان", 6000, 2500, 12, json.dumps({**DEFAULT_EQUIPMENT, "soldiers":12,"tanks":2,"fighters":1,"ships":1,"missiles":1,"defense":1}), 10, 120),
            ("🇰🇿 قزاقستان", 4000, 3000, 8, json.dumps({**DEFAULT_EQUIPMENT, "soldiers":8,"tanks":1,"defense":0}), 6, 90),
            ("🇦🇱 آلبانیا", 2000, 800, 5, json.dumps({**DEFAULT_EQUIPMENT, "soldiers":5,"defense":0}), 4, 70),
            ("🇿🇼 زیمبابوه", 1500, 500, 4, json.dumps({**DEFAULT_EQUIPMENT, "soldiers":4,"defense":0}), 3, 60),
            ("🤝 مشترک", 7000, 2000, 14, json.dumps({**DEFAULT_EQUIPMENT, "soldiers":14,"tanks":3,"fighters":2,"ships":1,"missiles":1,"defense":2}), 11, 130),
            ("⚔️ شورشی ها", 2500, 1000, 6, json.dumps({**DEFAULT_EQUIPMENT, "soldiers":6,"tanks":1,"defense":0}), 5, 85)
        ]
        for npc in npcs:
            c.execute('INSERT INTO npc_countries (name, gold, oil, army, equipment, defense_power, share_price) VALUES (?, ?, ?, ?, ?, ?, ?)', npc)

    conn.commit()
    conn.close()

init_db()

# ========== توابع کمکی ==========
def get_user(user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0], "country_name": row[1], "gold": row[2], "oil": row[3],
            "army": row[4], "economy": row[5], "tech": row[6], "population": row[7],
            "equipment": json.loads(row[8]), "nuke": bool(row[9]), "shelter": bool(row[10]),
            "alliance": row[11], "clan": row[12], "last_attack_time": row[13],
            "last_free_money": row[14], "last_company_time": row[15], "last_daily_mission": row[16],
            "last_daily_gift": row[17], "total_wins": row[18], "total_losses": row[19],
            "statement": row[20] or '', "subsidiary": row[21] or '',
            "secret_chat": row[22] or '', "is_vip": bool(row[23]),
            "vip_buildings": json.loads(row[24]) if row[24] else DEFAULT_VIP_BUILDINGS,
            "drugs": row[25] or 0, "cyber_attacks": row[26] or 0,
            "is_banned": bool(row[27]), "total_bets": row[28] or 0,
            "total_bet_wins": row[29] or 0, "daily_streak": row[30] or 0,
            "shares": json.loads(row[31]) if row[31] else {}, "duel_wins": row[32] or 0,
            "duel_losses": row[33] or 0, "group_points": row[34] or 0,
            "spins": row[35] or 0, "last_spin": row[36] or 0,
            "referrals": row[37] or 0, "referred_by": row[38] or 0,
            "mining_power": row[39] or 1, "last_mine": row[40] or 0,
            "achievement_points": row[41] or 0, "lucky_streak": row[42] or 0,
            "shield_active_until": row[43] or 0,
            "bank_gold": row[44] or 0,
            "nuke_scientists": row[45] or 0,
            "nuke_factory": row[46] or 0,
            "nuke_research": row[47] or 0,
            "terror_resistance": row[48] or 0,
            "peace_offers": json.loads(row[49]) if row[49] else {}
        }
    return None

def get_all_users():
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT user_id, country_name, gold, oil, army, economy, tech, total_wins, total_losses, is_vip, clan FROM users WHERE is_banned = 0')
    rows = c.fetchall()
    conn.close()
    return [{"user_id": r[0], "name": r[1], "gold": r[2], "oil": r[3], "army": r[4], "economy": r[5], "tech": r[6], "wins": r[7], "losses": r[8], "is_vip": bool(r[9]), "clan": r[10]} for r in rows]

def create_user(user_id, country_name):
    conn = db_connect()
    try:
        c = conn.cursor()
        c.execute('INSERT INTO users (user_id, country_name, equipment, vip_buildings, shares, peace_offers) VALUES (?, ?, ?, ?, ?, ?)',
                  (user_id, country_name, json.dumps(DEFAULT_EQUIPMENT), json.dumps(DEFAULT_VIP_BUILDINGS), '{}', '{}'))
        conn.commit()
    finally:
        conn.close()

def update_user(user_id, **kwargs):
    conn = db_connect()
    try:
        c = conn.cursor()
        for key, value in kwargs.items():
            if key in ["equipment", "vip_buildings", "shares", "peace_offers"]:
                value = json.dumps(value)
            c.execute(f'UPDATE users SET {key} = ? WHERE user_id = ?', (value, user_id))
        conn.commit()
    finally:
        conn.close()

def get_npc_countries():
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT id, name, gold, oil, army, equipment, defense_power, share_price FROM npc_countries WHERE is_alive = 1')
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "gold": r[2], "oil": r[3], "army": r[4], "equipment": json.loads(r[5]), "defense_power": r[6], "share_price": r[7]} for r in rows]

def get_npc_by_id(npc_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT id, name, gold, oil, army, equipment, defense_power, share_price FROM npc_countries WHERE id = ? AND is_alive = 1', (npc_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "name": row[1], "gold": row[2], "oil": row[3], "army": row[4], "equipment": json.loads(row[5]), "defense_power": row[6], "share_price": row[7]}
    return None

def update_npc(npc_id, **kwargs):
    conn = db_connect()
    try:
        c = conn.cursor()
        for key, value in kwargs.items():
            if key == "equipment":
                value = json.dumps(value)
            c.execute(f'UPDATE npc_countries SET {key} = ? WHERE id = ?', (value, npc_id))
        conn.commit()
    finally:
        conn.close()

def calculate_attack_power(equipment, army, tech, vip_buildings=None):
    power = army * 2
    for key, info in OFFENSIVE_EQUIPMENT.items():
        power += equipment.get(key, 0) * info["power"]
    power += tech * 2
    if vip_buildings:
        power += vip_buildings.get("airport", 0) * 20
        power += vip_buildings.get("factory", 0) * 15
    return power

def calculate_defense_power(equipment, army, tech, vip_buildings=None):
    power = army * 1.5
    for key, info in DEFENSIVE_EQUIPMENT.items():
        power += equipment.get(key, 0) * info["power"]
    power += tech * 1.5
    if vip_buildings:
        power += vip_buildings.get("shelter_advanced", 0) * 25
        power += vip_buildings.get("hospital", 0) * 5
    return power

def add_attack_log(attacker_id, attacker_name, defender_id, defender_name, result, gold_stolen, oil_stolen):
    conn = db_connect()
    c = conn.cursor()
    c.execute('INSERT INTO attack_logs (attacker_id, attacker_name, defender_id, defender_name, result, gold_stolen, oil_stolen, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
              (attacker_id, attacker_name, defender_id, defender_name, result, gold_stolen, oil_stolen, int(time.time())))
    conn.commit()
    conn.close()

def add_transfer_log(sender_id, sender_name, receiver_id, receiver_name, amount):
    conn = db_connect()
    c = conn.cursor()
    c.execute('INSERT INTO transfers (sender_id, sender_name, receiver_id, receiver_name, amount, timestamp) VALUES (?, ?, ?, ?, ?, ?)',
              (sender_id, sender_name, receiver_id, receiver_name, amount, int(time.time())))
    conn.commit()
    conn.close()

async def send_to_channel(app, text):
    try:
        await app.bot.send_message(chat_id=CHANNEL_ID, text=text)
    except Exception as e:
        logger.error(f"خطا در ارسال به کانال: {e}")

def get_clan(clan_name):
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT * FROM clans WHERE name = ?', (clan_name,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "name": row[1], "owner_id": row[2], "members": json.loads(row[3]), "gold": row[4], "oil": row[5], "level": row[6], "wins": row[7], "losses": row[8], "created_at": row[9]}
    return None

def create_clan(clan_name, owner_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute('INSERT INTO clans (name, owner_id, members, created_at) VALUES (?, ?, ?, ?)',
              (clan_name, owner_id, json.dumps([owner_id]), int(time.time())))
    conn.commit()
    conn.close()

def update_clan(clan_name, **kwargs):
    conn = db_connect()
    c = conn.cursor()
    for key, value in kwargs.items():
        if key == "members":
            value = json.dumps(value)
        c.execute(f'UPDATE clans SET {key} = ? WHERE name = ?', (value, clan_name))
    conn.commit()
    conn.close()

def get_admins():
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT user_id FROM admins')
    rows = c.fetchall()
    conn.close()
    admin_list = [r[0] for r in rows]
    admin_list.extend(ADMIN_IDS)
    return list(set(admin_list))

def is_admin(user_id):
    return user_id in get_admins()

def get_required_channels():
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT channel_id, channel_name, invite_link FROM required_channels')
    rows = c.fetchall()
    conn.close()
    return [{"channel_id": r[0], "channel_name": r[1], "invite_link": r[2]} for r in rows]

def add_required_channel(channel_id, channel_name, invite_link, added_by):
    conn = db_connect()
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO required_channels (channel_id, channel_name, invite_link, added_by, added_at) VALUES (?, ?, ?, ?, ?)',
              (str(channel_id), channel_name, invite_link, added_by, int(time.time())))
    conn.commit()
    conn.close()

def remove_required_channel(channel_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute('DELETE FROM required_channels WHERE channel_id = ?', (str(channel_id),))
    conn.commit()
    conn.close()

def create_coupon(code, ctype, amount, max_uses, expires_hours, created_by):
    conn = db_connect()
    c = conn.cursor()
    expires_at = int(time.time()) + (expires_hours * 3600) if expires_hours > 0 else 0
    c.execute('INSERT INTO coupons (code, type, amount, max_uses, expires_at, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
              (code.upper(), ctype, amount, max_uses, expires_at, created_by, int(time.time())))
    conn.commit()
    conn.close()

def get_coupon(code):
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT * FROM coupons WHERE code = ?', (code.upper(),))
    row = c.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "code": row[1], "type": row[2], "amount": row[3], "max_uses": row[4], "used_count": row[5], "expires_at": row[6]}
    return None

def use_coupon(coupon_id, user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute('UPDATE coupons SET used_count = used_count + 1 WHERE id = ?', (coupon_id,))
    c.execute('INSERT INTO coupon_uses (coupon_id, user_id, used_at) VALUES (?, ?, ?)', (coupon_id, user_id, int(time.time())))
    conn.commit()
    conn.close()

def has_used_coupon(coupon_id, user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM coupon_uses WHERE coupon_id = ? AND user_id = ?', (coupon_id, user_id))
    count = c.fetchone()[0]
    conn.close()
    return count > 0

def add_admin(user_id, added_by):
    conn = db_connect()
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO admins (user_id, added_by, added_at) VALUES (?, ?, ?)',
              (user_id, added_by, int(time.time())))
    conn.commit()
    conn.close()

def remove_admin_db(user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

# ========== Admin Permissions ==========
ADMIN_PERMISSIONS = {
    "stats": "📊 آمار کاربران",
    "add_gold": "💰 افزودن طلا",
    "add_oil": "🛢️ افزودن نفت",
    "vip": "👑 اعطای VIP",
    "ban": "🚫 بن کاربر",
    "users": "📋 لیست کاربران",
    "npcs": "🌍 لیست NPC ها",
    "add_country": "➕ اضافه کردن کشور",
    "logs": "📊 گزارش حملات",
    "getdb": "📁 دریافت دیتابیس",
    "uploaddb": "📤 افزودن دیتابیس",
    "channels": "📢 کانال اجباری",
    "coupons": "🎟️ مدیریت کوپن",
    "global_gold": "💰 طلای همگانی",
    "global_oil": "🛢️ نفت همگانی",
    "add_admin": "➕ افزودن ادمین",
    "list_admins": "📋 لیست ادمین‌ها",
    "broadcast": "📣 پیام همگانی",
}

# Maps every admin_* callback_data to the permission key that gates it
ADMIN_ACTION_PERM_MAP = {
    "admin_stats": "stats",
    "admin_add_gold": "add_gold",
    "admin_add_oil": "add_oil",
    "admin_vip": "vip",
    "admin_ban": "ban",
    "admin_users": "users",
    "admin_npcs": "npcs",
    "admin_add_country": "add_country",
    "admin_logs": "logs",
    "admin_getdb": "getdb",
    "admin_upload_db": "uploaddb",
    "admin_channels": "channels",
    "admin_add_channel": "channels",
    "admin_remove_channel": "channels",
    "admin_coupons": "coupons",
    "admin_create_coupon": "coupons",
    "admin_global_gold": "global_gold",
    "admin_global_oil": "global_oil",
    "admin_add_admin": "add_admin",
    "admin_list_admins": "list_admins",
    "admin_broadcast": "broadcast",
}

def get_admin_permissions(user_id):
    """Returns the set of permission keys this admin has. Super-admins (ADMIN_IDS) implicitly have all."""
    if user_id in ADMIN_IDS:
        return set(ADMIN_PERMISSIONS.keys())
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT permission FROM admin_permissions WHERE user_id = ?', (user_id,))
    rows = c.fetchall()
    conn.close()
    return set(r[0] for r in rows)

def has_admin_permission(user_id, perm):
    if user_id in ADMIN_IDS:
        return True
    return perm in get_admin_permissions(user_id)

def set_admin_permission(user_id, perm, enabled):
    conn = db_connect()
    c = conn.cursor()
    if enabled:
        c.execute('INSERT OR IGNORE INTO admin_permissions (user_id, permission) VALUES (?, ?)', (user_id, perm))
    else:
        c.execute('DELETE FROM admin_permissions WHERE user_id = ? AND permission = ?', (user_id, perm))
    conn.commit()
    conn.close()

def build_admin_permissions_keyboard(target_id):
    perms = get_admin_permissions(target_id)
    keyboard = []
    for key, label in ADMIN_PERMISSIONS.items():
        mark = "✅" if key in perms else "❌"
        keyboard.append([InlineKeyboardButton(f"{mark} {label}", style="primary", callback_data=f"admin_perm_toggle_{target_id}_{key}")])
    keyboard.append([InlineKeyboardButton("🔙 پایان و بازگشت", style="primary", callback_data="admin_list_admins")])
    return InlineKeyboardMarkup(keyboard)

def get_active_treasure():
    conn = db_connect()
    c = conn.cursor()
    now = int(time.time())
    c.execute('SELECT id, gold, oil FROM treasures WHERE found_by = 0 AND expires_at > ? ORDER BY created_at DESC LIMIT 1', (now,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "gold": row[1], "oil": row[2]}
    return None

def create_treasure():
    conn = db_connect()
    c = conn.cursor()
    now = int(time.time())
    gold = random.randint(500, 3000)
    oil = random.randint(200, 1000)
    c.execute('INSERT INTO treasures (gold, oil, created_at, expires_at) VALUES (?, ?, ?, ?)',
              (gold, oil, now, now + 3600))
    conn.commit()
    conn.close()

def claim_treasure(treasure_id, user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute('UPDATE treasures SET found_by = ? WHERE id = ? AND found_by = 0', (user_id, treasure_id))
    updated = c.rowcount > 0
    conn.commit()
    conn.close()
    return updated

def add_achievement(user_id, atype):
    conn = db_connect()
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO achievements (user_id, type, unlocked_at) VALUES (?, ?, ?)',
              (user_id, atype, int(time.time())))
    conn.commit()
    conn.close()

def get_achievements(user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT type, unlocked_at FROM achievements WHERE user_id = ?', (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def check_achievements(user_id):
    user = get_user(user_id)
    if not user:
        return []
    existing = [a[0] for a in get_achievements(user_id)]
    new_achievements = []

    checks = [
        ("first_blood", user["total_wins"] >= 1),
        ("warlord", user["total_wins"] >= 50),
        ("conqueror", user["total_wins"] >= 100),
        ("rich", user["gold"] >= 50000),
        ("millionaire", user["gold"] >= 500000),
        ("vip_master", user["is_vip"]),
        ("clan_leader", user["clan"] and get_clan(user["clan"]) and get_clan(user["clan"])["owner_id"] == user_id),
        ("duelist", user["duel_wins"] >= 10),
        ("stock_trader", sum(user.get("shares", {}).values()) >= 10),
        ("bet_master", user["total_bet_wins"] >= 20),
        ("miner", user.get("mining_power", 1) >= 5),
        ("popular", user.get("referrals", 0) >= 5),
        ("daily_warrior", user["daily_streak"] >= 7),
        ("nuclear_power", user["nuke"]),
        ("shield_master", user["shield_active_until"] > time.time()),
        ("peace_maker", len(user.get("peace_offers", {})) >= 3),
        ("banker", user.get("bank_gold", 0) >= 100000),
    ]

    for atype, condition in checks:
        if condition and atype not in existing:
            add_achievement(user_id, atype)
            new_achievements.append(atype)

    return new_achievements

ACHIEVEMENT_NAMES = {
    "first_blood": "🩸 اولین خون", "warlord": "⚔️ فرمانده جنگی", "conqueror": "👑 فاتح",
    "rich": "💰 ثروتمند", "millionaire": "💎 میلیونر", "vip_master": "👑 استاد VIP",
    "clan_leader": "🏰 رهبر کلن", "duelist": "🤺 دوئلیست", "stock_trader": "📈 معامله‌گر",
    "bet_master": "🎰 قمارباز حرفه‌ای", "miner": "⛏️ معدنچی", "popular": "🌟 محبوب",
    "daily_warrior": "🔥 جنگجوی روزانه", "nuclear_power": "☢️ قدرت هسته‌ای", "shield_master": "🛡️ استاد دفاع",
    "peace_maker": "🕊️ صلح‌طلب", "banker": "🏦 بانکدار"
}

async def check_channel_membership(user_id, context):
    """تمام کانال‌های اجباری را چک می‌کند و لیست کانال‌هایی که کاربر هنوز عضو نشده را برمی‌گرداند."""
    channels = get_required_channels()
    if not channels:
        return True, []
    not_joined = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(ch["channel_id"], user_id)
            if member.status in ["left", "kicked"]:
                not_joined.append(ch)
        except Exception as e:
            # اگر ربات دیگه به این کانال دسترسی نداره (مثلاً از ادمینی حذف شده)، به جای رد شدن بی‌سروصدا لاگ می‌گیریم
            logger.warning(f"عدم امکان بررسی عضویت کانال {ch['channel_id']} برای کاربر {user_id}: {e}")
            continue
    return (len(not_joined) == 0), not_joined

def build_join_keyboard(not_joined):
    keyboard = []
    for ch in not_joined:
        link = ch.get("invite_link") or f"https://t.me/{str(ch['channel_id']).replace('@', '')}"
        keyboard.append([InlineKeyboardButton(f"📢 {ch.get('channel_name', ch['channel_id'])}", style="primary", url=link)])
    keyboard.append([InlineKeyboardButton("✅ عضو شدم", style="success", callback_data="check_membership")])
    return InlineKeyboardMarkup(keyboard)

async def enforce_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """قبل از اجرای هر اکشن ربات (دکمه یا پیام متنی) صدا زده می‌شود.
    اگر کاربر عضو همه‌ی کانال/گروه‌های اجباری نباشد، لیست کامل آن‌ها را نشان می‌دهد و False برمی‌گرداند."""
    user_id = update.effective_user.id
    if is_admin(user_id):
        return True
    is_member, not_joined = await check_channel_membership(user_id, context)
    if is_member:
        return True
    text = "📢 برای استفاده از ربات لطفاً ابتدا در کانال/گروه‌های زیر عضو شوید:\n\nبعد از عضویت روی «✅ عضو شدم» کلیک کنید."
    reply_markup = build_join_keyboard(not_joined)
    if update.callback_query:
        await update.callback_query.answer("🚫 ابتدا باید عضو کانال‌ها شوید!", show_alert=True)
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        except Exception:
            pass
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    return False

def has_shield(user):
    return user.get("shield_active_until", 0) > int(time.time())

def has_peace_treaty(user1_id, user2_id):
    conn = db_connect()
    c = conn.cursor()
    now = int(time.time())
    c.execute('SELECT id FROM peace_treaties WHERE ((country1_id = ? AND country2_id = ?) OR (country1_id = ? AND country2_id = ?)) AND expires_at > ?',
              (user1_id, user2_id, user2_id, user1_id, now))
    row = c.fetchone()
    conn.close()
    return row is not None

def add_peace_treaty(user1_id, user2_id, hours=24):
    conn = db_connect()
    c = conn.cursor()
    now = int(time.time())
    c.execute('DELETE FROM peace_treaties WHERE (country1_id = ? AND country2_id = ?) OR (country1_id = ? AND country2_id = ?)',
              (user1_id, user2_id, user2_id, user1_id))
    c.execute('INSERT INTO peace_treaties (country1_id, country2_id, expires_at, created_at) VALUES (?, ?, ?, ?)',
              (user1_id, user2_id, now + hours*3600, now))
    conn.commit()
    conn.close()

def add_pending_attack(attacker_id, defender_id, percent, arrival_time):
    conn = db_connect()
    c = conn.cursor()
    c.execute('INSERT INTO pending_attacks (attacker_id, defender_id, percent, arrival_time, status, created_at) VALUES (?, ?, ?, ?, ?, ?)',
              (attacker_id, defender_id, percent, arrival_time, 'pending', int(time.time())))
    attack_id = c.lastrowid
    conn.commit()
    conn.close()
    return attack_id

def get_pending_attack(attack_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT * FROM pending_attacks WHERE id = ? AND status = 'pending'", (attack_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "attacker_id": row[1], "defender_id": row[2], "percent": row[3], "arrival_time": row[4], "status": row[5]}
    return None

def cancel_pending_attack(attack_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute("UPDATE pending_attacks SET status = 'cancelled' WHERE id = ?", (attack_id,))
    conn.commit()
    conn.close()

def resolve_pending_attack(attack_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute("UPDATE pending_attacks SET status = 'resolved' WHERE id = ?", (attack_id,))
    conn.commit()
    conn.close()

def format_time_remaining(seconds):
    if seconds <= 0:
        return "0 ثانیه"
    m, s = divmod(int(seconds), 60)
    if m > 0:
        return f"{m} دقیقه و {s} ثانیه"
    return f"{s} ثانیه"

def calculate_casualties(equipment, intensity=0.2):
    """intensity: 0.1 to 0.3 for loser, 0.0 to 0.1 for winner"""
    losses = {}
    for key, count in equipment.items():
        if count > 0:
            lost = min(count, max(0, int(count * random.uniform(0, intensity) + random.randint(0, 3))))
            if lost > 0:
                losses[key] = lost
    return losses

def format_casualties(losses):
    if not losses:
        return "• بدون خسارت تجهیزاتی"
    lines = []
    items = list(losses.items())
    for i in range(0, len(items), 2):
        line = ""
        for j in range(2):
            if i + j < len(items):
                key, count = items[i+j]
                info = ALL_EQUIPMENT.get(key, {"name": key, "flag": ""})
                line += f"• {info['flag']} {info['name']} ×{count}   "
        lines.append(line.strip())
    return "\n".join(lines)

# ========== دکمه‌های منوی دسته‌بندی‌شده ==========
def get_main_menu(user):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 کشور من", style="primary", callback_data="my_country"),
         InlineKeyboardButton("🎲 پول رایگان", style="success", callback_data="free_money")],
        [InlineKeyboardButton("🏛 سیاسی", style="primary", callback_data="political_menu"),
         InlineKeyboardButton("💰 اقتصادی", style="primary", callback_data="economic_menu"),
         InlineKeyboardButton("⚔️ نظامی", style="primary", callback_data="military_menu")],
        [InlineKeyboardButton("🏰 کلن‌ها", style="primary", callback_data="clans"),
         InlineKeyboardButton("📊 رتبه‌بندی", style="primary", callback_data="rankings"),
         InlineKeyboardButton("🎁 هدیه روزانه", style="success", callback_data="daily_gift")],
        [InlineKeyboardButton("🎯 ماموریت روزانه", style="primary", callback_data="daily_mission"),
         InlineKeyboardButton("🎰 شرط‌بندی", style="primary", callback_data="betting"),
         InlineKeyboardButton("⚔️ دوئل", style="danger", callback_data="duel")],
        [InlineKeyboardButton("📈 بازار سهام", style="primary", callback_data="stock_market"),
         InlineKeyboardButton("🗺️ شکار گنج", style="primary", callback_data="treasure_hunt"),
         InlineKeyboardButton("⛏️ معدن‌کاوی", style="success", callback_data="mining")],
        [InlineKeyboardButton("🎡 گردونه شانس", style="success", callback_data="lucky_wheel"),
         InlineKeyboardButton("🏆 مسابقه گروهی", style="primary", callback_data="group_contest"),
         InlineKeyboardButton("👥 دعوت دوستان", style="success", callback_data="referral")],
        [InlineKeyboardButton("📰 روزنامه", style="primary", callback_data="newspaper"),
         InlineKeyboardButton("🎪 تورنمنت", style="primary", callback_data="tournament"),
         InlineKeyboardButton("🏅 دستاوردها", style="primary", callback_data="achievements")],
    ])

def get_political_menu(user):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤝 اتحاد", style="success", callback_data="alliance"),
         InlineKeyboardButton("🏅 دیپلماسی", style="primary", callback_data="diplomacy")],
        [InlineKeyboardButton("📢 بیانیه رسمی", style="primary", callback_data="official_statement"),
         InlineKeyboardButton("📮 نظر کشورها", style="primary", callback_data="country_opinions")],
        [InlineKeyboardButton("⚔️ قوانین جنگ", style="primary", callback_data="war_laws"),
         InlineKeyboardButton("🏆 رتبه‌بندی‌ها", style="primary", callback_data="rankings")],
        [InlineKeyboardButton("🌍 رویداد جهانی", style="primary", callback_data="world_events"),
         InlineKeyboardButton("🕊️ گفتگوی محرمانه", style="primary", callback_data="secret_chat")],
        [InlineKeyboardButton("🎖️ دستاوردها", style="primary", callback_data="achievements"),
         InlineKeyboardButton("👥 زیرمجموعه‌گیری", style="success", callback_data="referral")],
        [InlineKeyboardButton("🕊️ پیمان صلح", style="success", callback_data="peace_menu"),
         InlineKeyboardButton("📋 وضعیت صلح", style="success", callback_data="peace_status")],
        [InlineKeyboardButton("🔙 بازگشت به منو", style="primary", callback_data="menu")]
    ])

def get_economic_menu(user):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏢 شرکت‌ها", style="primary", callback_data="companies"),
         InlineKeyboardButton("📦 صادرات/واردات", style="primary", callback_data="trade")],
        [InlineKeyboardButton("🛢️ نفت و انرژی", style="primary", callback_data="oil_energy"),
         InlineKeyboardButton("🏦 بانک", style="primary", callback_data="bank_menu")],
        [InlineKeyboardButton("🏴 بازار سیاه", style="danger", callback_data="black_market"),
         InlineKeyboardButton("🏗️ پروژه‌های ملی", style="primary", callback_data="national_projects")],
        [InlineKeyboardButton("💰 انتقال طلا", style="primary", callback_data="transfer_gold"),
         InlineKeyboardButton("📈 بازار سهام", style="primary", callback_data="stock_market")],
        [InlineKeyboardButton("🎟️ وارد کردن کوپن", style="primary", callback_data="enter_coupon")],
        [InlineKeyboardButton("🔙 بازگشت به منو", style="primary", callback_data="menu")]
    ])

def get_military_menu(user):
    keyboard = [
        [InlineKeyboardButton("🔫 بازار تسلیحات", style="primary", callback_data="arms_market"),
         InlineKeyboardButton("💣 حمله", style="danger", callback_data="attack_menu")],
        [InlineKeyboardButton("🤝 معامله تسلیحات", style="primary", callback_data="arms_deal"),
         InlineKeyboardButton("🎯 حمله گروهی", style="danger", callback_data="group_attack_menu")],
        [InlineKeyboardButton("☢️ حمله اتمی", style="danger", callback_data="nuke_attack"),
         InlineKeyboardButton("🕵️ جاسوسی", style="danger", callback_data="spy")],
        [InlineKeyboardButton("💣 خرابکاری هسته‌ای", style="danger", callback_data="nuclear_sabotage"),
         InlineKeyboardButton("🕶️ امنیت و ترور", style="danger", callback_data="security_terror")],
        [InlineKeyboardButton("🧪 دانشمندان هسته‌ای", style="primary", callback_data="nuke_scientists_menu"),
         InlineKeyboardButton("🏭 کارخانه هسته‌ای", style="primary", callback_data="nuke_factory_menu")],
        [InlineKeyboardButton("🗺️ نقشه جنگی", style="primary", callback_data="war_map"),
         InlineKeyboardButton("🛡️ سپر دفاعی", style="primary", callback_data="shield_buy")],
        [InlineKeyboardButton("🔙 بازگشت به منو", style="primary", callback_data="menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_attack_menu(user):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ حمله به NPC", style="danger", callback_data="military_attack"),
         InlineKeyboardButton("⚔️ حمله به کاربر", style="danger", callback_data="attack_user")],
        [InlineKeyboardButton("🛡️ خرید سپر دفاعی", style="success", callback_data="shield_buy"),
         InlineKeyboardButton("📋 حملات در راه", style="primary", callback_data="pending_attacks")],
        [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="military_menu")]
    ])

# ========== شروع /start ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)

    if not await enforce_channel_membership(update, context):
        return ConversationHandler.END

    if not user:
        await update.message.reply_text("🌟 به جنگ جهانی ریات خوش آمدید!\nلطفاً نام کشور خود را وارد کنید:")
        return COUNTRY_NAME
    else:
        if user.get("is_banned"):
            await update.message.reply_text("🚫 شما توسط ادمین بن شده‌اید!")
            return ConversationHandler.END
        new_achs = check_achievements(user_id)
        if new_achs:
            ach_text = "\n".join([f"🏅 {ACHIEVEMENT_NAMES.get(a, a)}" for a in new_achs])
            await update.message.reply_text(f"🎉 تبریک! دستاوردهای جدید:\n{ach_text}")
        await show_main_menu(update, context)
        return ConversationHandler.END

async def receive_country_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    country_name = update.message.text.strip()
    if not country_name:
        await update.message.reply_text("نام کشور نمی‌تواند خالی باشد. دوباره وارد کنید:")
        return COUNTRY_NAME
    create_user(user_id, country_name)
    await update.message.reply_text(f"✅ کشور {country_name} با موفقیت ثبت شد!\nشروع با ۱,۰۰۰ طلا و ۵۰۰ نفت")
    await show_main_menu(update, context)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ثبت نام لغو شد. برای شروع مجدد /start را بزنید.")
    return ConversationHandler.END

# ========== نمایش منوی اصلی ==========
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        if update.callback_query:
            await update.callback_query.edit_message_text("ابتدا /start کنید")
        else:
            await update.message.reply_text("ابتدا /start کنید")
        return

    new_achs = check_achievements(user_id)
    vip_tag = " 👑 VIP" if user.get("is_vip") else ""
    shield_status = ""
    if has_shield(user):
        remaining = user["shield_active_until"] - int(time.time())
        shield_status = f"\n🛡️ سپر فعال: {format_time_remaining(remaining)}"

    text = (f"⚔️ جنگ جهانی ریات\n🏳️ {user['country_name']}{vip_tag}{shield_status}\n\n"
            f"💰 طلا: {user['gold']:,} | 🛢️ نفت: {user['oil']:,}\n"
            f"⚔️ ارتش: {user['army']} | 🏭 اقتصاد: {user['economy']}\n"
            f"🏰 کلن: {user['clan'] or 'ندارد'}\n\n"
            f"📋 یکی از گزینه‌ها را انتخاب کنید:")

    if new_achs:
        ach_text = "\n".join([f"🏅 {ACHIEVEMENT_NAMES.get(a, a)}" for a in new_achs])
        text += f"\n\n🎉 دستاوردهای جدید:\n{ach_text}"
        update_user(user_id, achievement_points=user.get("achievement_points", 0) + len(new_achs) * 100)

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text, reply_markup=get_main_menu(user))
    else:
        await update.message.reply_text(text, reply_markup=get_main_menu(user))

# ========== بررسی عضویت ==========
async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    is_member, not_joined = await check_channel_membership(user_id, context)
    if is_member:
        await query.edit_message_text("✅ عضویت شما تایید شد!\n/start را بزنید.")
    else:
        await query.answer("❌ هنوز عضو همه کانال‌ها نشده‌اید!", show_alert=True)
        try:
            await query.edit_message_reply_markup(reply_markup=build_join_keyboard(not_joined))
        except Exception:
            pass

# ========== منوهای دسته‌بندی ==========
async def political_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    await query.edit_message_text(
        f"🏛 بخش سیاسی\n🏳️ {user['country_name']}\n\nیکی از گزینه‌ها را انتخاب کنید:",
        reply_markup=get_political_menu(user)
    )

async def economic_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    await query.edit_message_text(
        f"💰 بخش اقتصادی\n🏳️ {user['country_name']}\n💰 طلا: {user['gold']:,}\n\nیکی از گزینه‌ها را انتخاب کنید:",
        reply_markup=get_economic_menu(user)
    )

async def military_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    shield_text = ""
    if has_shield(user):
        remaining = user["shield_active_until"] - int(time.time())
        shield_text = f"\n🛡️ سپر فعال: {format_time_remaining(remaining)}"
    await query.edit_message_text(
        f"⚔️ بخش نظامی\n🏳️ {user['country_name']}{shield_text}\n⚔️ ارتش: {user['army']}\n\nیکی از گزینه‌ها را انتخاب کنید:",
        reply_markup=get_military_menu(user)
    )

async def attack_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    await query.edit_message_text(
        f"💣 مرکز عملیات نظامی\n🏳️ {user['country_name']}\n\nهدف خود را انتخاب کنید:",
        reply_markup=get_attack_menu(user)
    )

# ========== کشور من ==========
async def my_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    equip = user["equipment"]
    buildings = user["vip_buildings"]
    shares = user.get("shares", {})
    shield_text = "✅ فعال" if has_shield(user) else "❌ غیرفعال"

    text = (
        f"🏳️ {user['country_name']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 طلا: {user['gold']:,}\n"
        f"🛢️ نفت: {user['oil']:,}\n"
        f"🏦 بانک: {user.get('bank_gold', 0):,}\n"
        f"👥 جمعیت: {user['population']:,}\n"
        f"⚔️ ارتش: {user['army']}\n"
        f"🏭 اقتصاد: {user['economy']}\n"
        f"🔬 فناوری: {user['tech']}\n"
        f"🏰 کلن: {user['clan'] or 'ندارد'}\n"
        f"⛏️ قدرت معدن: {user.get('mining_power', 1)}\n"
        f"👥 زیرمجموعه: {user.get('referrals', 0)}\n"
        f"🛡️ سپر دفاعی: {shield_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 تجهیزات جنگی:\n"
    )
    for key, info in OFFENSIVE_EQUIPMENT.items():
        val = equip.get(key, 0)
        if val > 0:
            text += f"• {info['name']}: {val}\n"

    text += f"━━━━━━━━━━━━━━━━━━━━\n🛡️ تجهیزات دفاعی:\n"
    for key, info in DEFENSIVE_EQUIPMENT.items():
        val = equip.get(key, 0)
        if val > 0:
            text += f"• {info['name']}: {val}\n"

    text += (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 پیروزی‌ها: {user['total_wins']}\n"
        f"💔 شکست‌ها: {user['total_losses']}\n"
        f"⚔️ دوئل‌ها: {user['duel_wins']} برد - {user['duel_losses']} باخت\n"
        f"🎰 شرط‌بندی‌ها: {user['total_bets']}\n"
        f"🎯 برد شرط‌ها: {user['total_bet_wins']}\n"
        f"🔥 استریک روزانه: {user['daily_streak']}\n"
        f"📊 امتیاز گروه: {user['group_points']}\n"
        f"🏅 امتیاز دستاورد: {user.get('achievement_points', 0)}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 سهام:\n"
    )
    if shares:
        for country, amount in shares.items():
            text += f"• {country}: {amount}\n"
    else:
        text += "• هیچ سهمی ندارید\n"

    text += (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤝 اتحاد: {user['alliance'] or 'ندارد'}\n"
        f"☢️ سلاح هسته‌ای: {'دارد' if user['nuke'] else 'ندارد'}\n"
        f"🏠 پناهگاه: {'دارد' if user['shelter'] else 'ندارد'}\n"
        f"👑 VIP: {'بله' if user['is_vip'] else 'خیر'}\n"
    )

    if user["is_vip"]:
        text += (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏗️ ساختمان‌های VIP:\n"
            f"• 🏥 بیمارستان: {buildings.get('hospital', 0)}\n"
            f"• 🏭 کارخانه: {buildings.get('factory', 0)}\n"
            f"• 🛢️ پالایشگاه: {buildings.get('refinery', 0)}\n"
            f"• 🎓 دانشگاه: {buildings.get('university', 0)}\n"
            f"• ✈️ فرودگاه: {buildings.get('airport', 0)}\n"
            f"• 🛡️ پناهگاه پیشرفته: {buildings.get('shelter_advanced', 0)}\n"
            f"• 💊 مواد مخدر: {user.get('drugs', 0)}\n"
            f"• 💻 حملات سایبری: {user.get('cyber_attacks', 0)}\n"
        )

    keyboard = [[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ========== بازار تسلیحات (۳۰ سلاح جدید) ==========
async def arms_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    keyboard = []
    # Offensive weapons - 2 per row
    off_keys = list(OFFENSIVE_EQUIPMENT.keys())
    for i in range(0, len(off_keys), 2):
        row = []
        for j in range(2):
            if i + j < len(off_keys):
                key = off_keys[i+j]
                info = OFFENSIVE_EQUIPMENT[key]
                row.append(InlineKeyboardButton(f"{info['name']} ({info['price']:,} طلا)", style="primary", callback_data=f"buy_{key}"))
        if row:
            keyboard.append(row)

    keyboard.append([InlineKeyboardButton("➡️ سلاح‌های دفاعی", style="primary", callback_data="defense_market")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="military_menu")])

    text = f"🛒 بازار تسلیحات جنگی\n💰 طلا: {user['gold']:,}\n\n📋 سلاح‌های تهاجمی:"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def defense_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    keyboard = []
    def_keys = list(DEFENSIVE_EQUIPMENT.keys())
    for i in range(0, len(def_keys), 2):
        row = []
        for j in range(2):
            if i + j < len(def_keys):
                key = def_keys[i+j]
                info = DEFENSIVE_EQUIPMENT[key]
                row.append(InlineKeyboardButton(f"{info['name']} ({info['price']:,} طلا)", style="primary", callback_data=f"buy_{key}"))
        if row:
            keyboard.append(row)

    keyboard.append([InlineKeyboardButton("⬅️ سلاح‌های جنگی", style="primary", callback_data="arms_market")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="military_menu")])

    text = f"🛒 بازار تسلیحات دفاعی\n💰 طلا: {user['gold']:,}\n\n📋 سلاح‌های دفاعی:"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def buy_equipment(update: Update, context: ContextTypes.DEFAULT_TYPE, item_key):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.answer("خطا!", show_alert=True)
        return

    info = ALL_EQUIPMENT.get(item_key)
    if not info:
        await query.answer("سلاح نامعتبر!", show_alert=True)
        return

    price = info["price"]
    if user["gold"] < price:
        await query.answer(f"طلای کافی ندارید! نیاز: {price:,}", show_alert=True)
        return

    equip = user["equipment"]
    equip[item_key] = equip.get(item_key, 0) + 1
    new_gold = user["gold"] - price

    update_user(user_id, gold=new_gold, equipment=equip)
    await query.answer(f"✅ {info['name']} خریداری شد!", show_alert=True)
    await query.edit_message_text(
        f"✅ {info['name']} با موفقیت خریداری شد!\n💰 طلای باقی‌مانده: {new_gold:,}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به بازار", style="primary", callback_data="arms_market")]])
    )

# ========== سپر دفاعی ==========
async def shield_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    SHIELD_PRICE = 5000000
    SHIELD_DURATION = 3600  # 1 hour

    if user["gold"] < SHIELD_PRICE:
        await query.answer(f"طلای کافی ندارید! نیاز: {SHIELD_PRICE:,} طلا", show_alert=True)
        return

    new_gold = user["gold"] - SHIELD_PRICE
    shield_until = int(time.time()) + SHIELD_DURATION
    update_user(user_id, gold=new_gold, shield_active_until=shield_until)

    await query.answer("🛡️ سپر دفاعی فعال شد!", show_alert=True)
    await query.edit_message_text(
        f"🛡️ سپر دفاعی فعال شد!\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ شما به مدت ۱ ساعت در برابر حملات مصون هستید.\n"
        f"💰 پرداخت: {SHIELD_PRICE:,} طلا\n"
        f"💰 طلای باقی‌مانده: {new_gold:,}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="military_menu")]])
    )

# ========== حمله با تأخیر و هشدار ==========
async def attack_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    last = user.get("last_attack_time", 0)
    now = int(time.time())
    cooldown = 300 if user["is_vip"] else 900
    if now - last < cooldown:
        remaining = cooldown - (now - last)
        await query.answer(f"⏳ {format_time_remaining(remaining)} صبر کنید!", show_alert=True)
        return

    all_users = get_all_users()
    other_users = [u for u in all_users if u["user_id"] != user_id]

    if not other_users:
        await query.edit_message_text("❌ هیچ کاربر دیگری وجود ندارد!")
        return

    keyboard = []
    row = []
    for u in other_users[:20]:
        # Check peace treaty
        if has_peace_treaty(user_id, u["user_id"]):
            continue
        row.append(InlineKeyboardButton(f"🏳️ {u['name']}", style="danger", callback_data=f"attack_user_{u['user_id']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="attack_menu")])

    await query.edit_message_text(
        f"⚔️ حمله به کاربر\n🎯 کاربر هدف را انتخاب کنید:\n\n⚠️ کاربران دارای پیمان صلح نمایش داده نمی‌شوند.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def select_attack_percent(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id):
    query = update.callback_query
    await query.answer()

    target = get_user(target_user_id)
    if not target:
        await query.edit_message_text("❌ کاربر یافت نشد!")
        return

    if has_peace_treaty(query.from_user.id, target_user_id):
        await query.answer("🕊️ با این کشور پیمان صلح دارید!", show_alert=True)
        return

    context.user_data['attack_target'] = target_user_id

    keyboard = [
        [InlineKeyboardButton("۱۰%", style="primary", callback_data="attack_pct_10"), InlineKeyboardButton("۲۰%", style="primary", callback_data="attack_pct_20")],
        [InlineKeyboardButton("۳۰%", style="primary", callback_data="attack_pct_30"), InlineKeyboardButton("۴۰%", style="primary", callback_data="attack_pct_40")],
        [InlineKeyboardButton("۵۰%", style="primary", callback_data="attack_pct_50"), InlineKeyboardButton("۶۰%", style="primary", callback_data="attack_pct_60")],
        [InlineKeyboardButton("۷۰%", style="primary", callback_data="attack_pct_70"), InlineKeyboardButton("۸۰%", style="primary", callback_data="attack_pct_80")],
        [InlineKeyboardButton("۹۰%", style="primary", callback_data="attack_pct_90"), InlineKeyboardButton("۱۰۰%", style="primary", callback_data="attack_pct_100")],
        [InlineKeyboardButton("❌ انصراف", style="primary", callback_data="attack_menu")]
    ]
    await query.edit_message_text(
        f"🎯 حمله به {target['country_name']}\n"
        f"⚔️ قدرت حریف: {int(calculate_defense_power(target['equipment'], target['army'], target['tech'], target.get('vip_buildings')))}\n"
        f"🎯 چند درصد از نیروهای خود را استفاده می‌کنید؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def execute_attack_warning(update: Update, context: ContextTypes.DEFAULT_TYPE, percent):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    user = get_user(user_id)
    target_id = context.user_data.get('attack_target')
    target = get_user(target_id)

    if not user or not target:
        await query.edit_message_text("❌ خطا در دریافت اطلاعات")
        return

    if has_peace_treaty(user_id, target_id):
        await query.answer("🕊️ با این کشور پیمان صلح دارید!", show_alert=True)
        return

    # Calculate travel time: 60-180 seconds
    travel_time = random.randint(60, 180)
    arrival_time = int(time.time()) + travel_time

    # Store pending attack
    attack_id = add_pending_attack(user_id, target_id, percent, arrival_time)

    # Send warning to defender
    warning_text = (
        f"🚨 هشدار! حمله‌ای در راهه!\n\n"
        f"کشور {user['country_name']} با {percent}٪ از نیروهایش به شما حمله کرده.\n"
        f"⏳ زمان تخمینی رسیدن: {format_time_remaining(travel_time)}\n\n"
        f"فرصت دارید واکنش نشون بدید:"
    )
    warning_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛡️ خرید سپر دفاعی (۵,۰۰۰,۰۰۰ طلا)", style="success", callback_data=f"defense_shield_{attack_id}")],
        [InlineKeyboardButton("🕵️ جاسوسی سریع", style="danger", callback_data=f"defense_spy_{attack_id}")],
        [InlineKeyboardButton("⚔️ ضدحمله", style="danger", callback_data=f"defense_counter_{attack_id}")],
        [InlineKeyboardButton("⏳ عدم اقدام", style="primary", callback_data=f"defense_wait_{attack_id}")]
    ])

    try:
        await context.bot.send_message(chat_id=target_id, text=warning_text, reply_markup=warning_keyboard)
    except Exception as e:
        logger.error(f"Failed to send warning: {e}")

    # Confirm to attacker
    await query.edit_message_text(
        f"🚀 حمله آغاز شد!\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 هدف: {target['country_name']}\n"
        f"📊 درصد نیرو: {percent}%\n"
        f"⏳ زمان رسیدن: {format_time_remaining(travel_time)}\n"
        f"🆔 کد عملیات: #{attack_id}\n\n"
        f"منتظر نتیجه باشید...",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]])
    )

    # Schedule delayed resolution
    asyncio.create_task(delayed_attack_resolver(attack_id, context.application))

async def delayed_attack_resolver(attack_id, app):
    await asyncio.sleep(60)  # Check every minute, but we need precise timing
    # Actually we sleep the exact time needed
    attack = get_pending_attack(attack_id)
    if not attack:
        return

    wait_time = attack["arrival_time"] - int(time.time())
    if wait_time > 0:
        await asyncio.sleep(wait_time)

    await resolve_delayed_attack(attack_id, app)

async def resolve_delayed_attack(attack_id, app):
    attack = get_pending_attack(attack_id)
    if not attack:
        return

    resolve_pending_attack(attack_id)
    attacker_id = attack["attacker_id"]
    defender_id = attack["defender_id"]
    percent = attack["percent"]

    attacker = get_user(attacker_id)
    defender = get_user(defender_id)

    if not attacker or not defender:
        return

    # Check if defender has shield
    if has_shield(defender):
        try:
            await app.bot.send_message(
                chat_id=attacker_id,
                text=(
                    f"🛡️ حمله به {defender['country_name']} شکست خورد!\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"❌ حریف دارای سپر دفاعی بود و حمله خنثی شد!\n"
                    f"⚔️ تلفات شما: ۰ | تلفات حریف: ۰"
                )
            )
        except:
            pass
        try:
            await app.bot.send_message(
                chat_id=defender_id,
                text=(
                    f"🛡️ سپر دفاعی شما کار کرد!\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"✅ حمله {attacker['country_name']} با موفقیت دفع شد!\n"
                    f"💰 بدون هیچ‌گونه خسارت!"
                )
            )
        except:
            pass
        await send_to_channel(app, (
            f"⚔️ گزارش حمله کاربری\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🗡️ مهاجم: {attacker['country_name']}\n"
            f"🛡️ مدافع: {defender['country_name']}\n"
            f"🛡️ نتیجه: حمله توسط سپر دفاعی خنثی شد"
        ))
        return

    # Calculate powers
    percent_float = percent / 100
    attack_power = calculate_attack_power(attacker["equipment"], attacker["army"], attacker["tech"], attacker.get("vip_buildings")) * percent_float
    defense_power = calculate_defense_power(defender["equipment"], defender["army"], defender["tech"], defender.get("vip_buildings"))

    win_chance = attack_power / (attack_power + defense_power) * 100
    is_win = random.random() * 100 < win_chance

    if is_win:
        gold_stolen = int(defender["gold"] * (0.1 + random.random() * 0.2))
        oil_stolen = int(defender["oil"] * (0.1 + random.random() * 0.2))

        new_attacker_gold = attacker["gold"] + gold_stolen
        new_attacker_oil = attacker["oil"] + oil_stolen
        new_defender_gold = max(0, defender["gold"] - gold_stolen)
        new_defender_oil = max(0, defender["oil"] - oil_stolen)

        # Casualties
        attacker_losses = calculate_casualties(attacker["equipment"], 0.05)
        defender_losses = calculate_casualties(defender["equipment"], 0.25)

        # Apply attacker losses
        attacker_equip = attacker["equipment"].copy()
        for k, v in attacker_losses.items():
            attacker_equip[k] = max(0, attacker_equip.get(k, 0) - v)

        # Apply defender losses
        defender_equip = defender["equipment"].copy()
        for k, v in defender_losses.items():
            defender_equip[k] = max(0, defender_equip.get(k, 0) - v)

        update_user(attacker_id, gold=new_attacker_gold, oil=new_attacker_oil, total_wins=attacker["total_wins"]+1,
                   equipment=attacker_equip, last_attack_time=int(time.time()))
        update_user(defender_id, gold=new_defender_gold, oil=new_defender_oil, total_losses=defender["total_losses"]+1,
                   equipment=defender_equip)

        add_attack_log(attacker_id, attacker["country_name"], defender_id, defender["country_name"], "پیروزی (کاربر)", gold_stolen, oil_stolen)

        attacker_text = (
            f"🚨 حمله‌ای که به {defender['country_name']} داشتید، رسید!\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎉 پیروزی!\n"
            f"💰 غنیمت طلا: {gold_stolen:,}\n"
            f"🛢️ غنیمت نفت: {oil_stolen:,}\n"
            f"⚔️ تلفات شما: {sum(attacker_losses.values())} | تلفات حریف: {sum(defender_losses.values())}\n"
            f"🎒 تجهیزات ازدست‌رفته شما:\n{format_casualties(attacker_losses)}\n"
            f"🎒 تجهیزات ازدست‌رفته حریف:\n{format_casualties(defender_losses)}"
        )

        defender_text = (
            f"🚨 حمله‌ای که از {attacker['country_name']} در راه بود، رسید!\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💔 شکست!\n"
            f"💰 -{gold_stolen:,} طلا\n"
            f"🛢️ -{oil_stolen:,} نفت\n"
            f"⚔️ تلفات شما: {sum(defender_losses.values())} | تلفات مهاجم: {sum(attacker_losses.values())}\n"
            f"🎒 تجهیزات ازدست‌رفته شما:\n{format_casualties(defender_losses)}\n"
            f"🎒 تجهیزات ازدست‌رفته مهاجم:\n{format_casualties(attacker_losses)}"
        )
    else:
        gold_lost = int(attacker["gold"] * (0.05 + random.random() * 0.15))
        oil_lost = int(attacker["oil"] * (0.05 + random.random() * 0.15))

        attacker_losses = calculate_casualties(attacker["equipment"], 0.20)
        defender_losses = calculate_casualties(defender["equipment"], 0.08)

        attacker_equip = attacker["equipment"].copy()
        for k, v in attacker_losses.items():
            attacker_equip[k] = max(0, attacker_equip.get(k, 0) - v)

        defender_equip = defender["equipment"].copy()
        for k, v in defender_losses.items():
            defender_equip[k] = max(0, defender_equip.get(k, 0) - v)

        update_user(attacker_id, gold=max(0, attacker["gold"]-gold_lost), oil=max(0, attacker["oil"]-oil_lost),
                   total_losses=attacker["total_losses"]+1, equipment=attacker_equip, last_attack_time=int(time.time()))
        update_user(defender_id, equipment=defender_equip)

        add_attack_log(attacker_id, attacker["country_name"], defender_id, defender["country_name"], "شکست (کاربر)", 0, 0)

        attacker_text = (
            f"🚨 حمله به {defender['country_name']} شکست خورد!\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💔 شکست!\n"
            f"💰 -{gold_lost:,} طلا\n"
            f"🛢️ -{oil_lost:,} نفت\n"
            f"⚔️ تلفات شما: {sum(attacker_losses.values())} | تلفات حریف: {sum(defender_losses.values())}\n"
            f"🎒 تجهیزات ازدست‌رفته شما:\n{format_casualties(attacker_losses)}"
        )

        defender_text = (
            f"🚨 حمله {attacker['country_name']} دفع شد!\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎉 پیروزی دفاعی!\n"
            f"💰 بدون از دست دادن طلا\n"
            f"🛢️ بدون از دست دادن نفت\n"
            f"⚔️ تلفات شما: {sum(defender_losses.values())} | تلفات مهاجم: {sum(attacker_losses.values())}\n"
            f"🎒 تجهیزات ازدست‌رفته شما:\n{format_casualties(defender_losses)}\n"
            f"🎒 تجهیزات ازدست‌رفته مهاجم:\n{format_casualties(attacker_losses)}"
        )

    try:
        await app.bot.send_message(chat_id=attacker_id, text=attacker_text)
    except:
        pass
    try:
        await app.bot.send_message(chat_id=defender_id, text=defender_text)
    except:
        pass

    # Send to channel
    channel_text = (
        f"⚔️ گزارش حمله کاربری\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🗡️ مهاجم: {attacker['country_name']}\n"
        f"🛡️ مدافع: {defender['country_name']}\n"
        f"{'✅ نتیجه: پیروزی مهاجم' if is_win else '❌ نتیجه: شکست مهاجم'}\n"
        f"💰 طلا: {gold_stolen if is_win else -gold_lost:,}"
    )
    await send_to_channel(app, channel_text)

# ========== واکنش مدافع به هشدار ==========
async def defense_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE, action, attack_id):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    attack = get_pending_attack(attack_id)

    if not attack:
        await query.answer("⏳ این حمله قبلاً منقضی شده!", show_alert=True)
        return

    if attack["defender_id"] != user_id:
        await query.answer("❌ این هشدار برای شما نیست!", show_alert=True)
        return

    if action == "shield":
        SHIELD_PRICE = 5000000
        if user["gold"] < SHIELD_PRICE:
            await query.answer(f"طلای کافی ندارید! نیاز: {SHIELD_PRICE:,}", show_alert=True)
            return
        new_gold = user["gold"] - SHIELD_PRICE
        shield_until = int(time.time()) + 3600
        update_user(user_id, gold=new_gold, shield_active_until=shield_until)
        await query.answer("🛡️ سپر دفاعی فعال شد!", show_alert=True)
        await query.edit_message_text(
            f"🛡️ سپر دفاعی با موفقیت فعال شد!\n"
            f"💰 پرداخت: {SHIELD_PRICE:,} طلا\n"
            f"⏳ مدت: ۱ ساعت\n"
            f"✅ حمله در راه خنثی خواهد شد!"
        )

    elif action == "spy":
        attacker = get_user(attack["attacker_id"])
        if not attacker:
            await query.answer("خطا!", show_alert=True)
            return
        power = calculate_attack_power(attacker["equipment"], attacker["army"], attacker["tech"], attacker.get("vip_buildings"))
        await query.answer("🕵️ اطلاعات به دست آمد!", show_alert=True)
        await query.edit_message_text(
            f"🕵️ گزارش جاسوسی\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 مهاجم: {attacker['country_name']}\n"
            f"⚔️ قدرت تخمینی: {int(power)}\n"
            f"📊 درصد حمله: {attack['percent']}%\n"
            f"💰 طلای مهاجم: {attacker['gold']:,}\n"
            f"🛢️ نفت مهاجم: {attacker['oil']:,}"
        )

    elif action == "counter":
        # Counter-attack: defender immediately attacks back with 50% power
        attacker = get_user(attack["attacker_id"])
        if not attacker:
            await query.answer("خطا!", show_alert=True)
            return

        counter_power = calculate_defense_power(user["equipment"], user["army"], user["tech"], user.get("vip_buildings")) * 0.5
        attacker_power = calculate_attack_power(attacker["equipment"], attacker["army"], attacker["tech"], attacker.get("vip_buildings")) * (attack["percent"] / 100)

        if counter_power > attacker_power * 0.3:
            # Cancel the pending attack
            cancel_pending_attack(attack_id)
            damage = int(attacker["gold"] * 0.05)
            update_user(attack["attacker_id"], gold=max(0, attacker["gold"] - damage))
            await query.answer("⚔️ ضدحمله موفق! حمله دشمن دفع شد!", show_alert=True)
            await query.edit_message_text(
                f"⚔️ ضدحمله موفق!\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ حمله {attacker['country_name']} دفع شد!\n"
                f"💰 {damage:,} طلا به دشمن آسیب زدید!"
            )
            try:
                await context.bot.send_message(
                    chat_id=attack["attacker_id"],
                    text=f"❌ حمله شما توسط {user['country_name']} دفع شد!\n💰 {damage:,} طلا آسیب دیدید."
                )
            except:
                pass
            await send_to_channel(context.application, (
                f"⚔️ گزارش حمله کاربری\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🗡️ مهاجم: {attacker['country_name']}\n"
                f"🛡️ مدافع: {user['country_name']}\n"
                f"⚔️ نتیجه: ضدحمله مدافع موفق بود\n"
                f"💰 خسارت به مهاجم: {damage:,} طلا"
            ))
        else:
            await query.answer("⚔️ ضدحمله ناموفق! نیروی کافی ندارید.", show_alert=True)
            await query.edit_message_text("❌ ضدحمله ناموفق بود. نیروی کافی برای دفع حمله ندارید.")

    elif action == "wait":
        await query.answer("⏳ منتظر رسیدن حمله هستید...", show_alert=True)
        await query.edit_message_text("⏳ شما تصمیم گرفتید منتظر بمانید. حمله به زودی می‌رسد...")

# ========== پیمان صلح ==========
async def peace_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    keyboard = [
        [InlineKeyboardButton("🕊️ ارائه پیمان صلح", style="success", callback_data="peace_offer")],
        [InlineKeyboardButton("📋 دریافت‌های صلح", style="success", callback_data="peace_inbox")],
        [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="political_menu")]
    ]
    await query.edit_message_text(
        f"🕊️ پیمان صلح\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"با پیمان صلح، دو کشور به مدت ۲۴ ساعت نمی‌توانند به هم حمله کنند.\n\n"
        f"📋 انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def peace_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🕊️ آیدی عددی کشور مورد نظر برای پیمان صلح را وارد کنید:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="peace_menu")]])
    )
    context.user_data['waiting_for'] = 'peace_offer'

async def peace_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    offers = user.get("peace_offers", {})

    if not offers:
        await query.edit_message_text(
            "📭 هیچ پیشنهاد صلحی وجود ندارد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="peace_menu")]])
        )
        return

    keyboard = []
    text = "📨 پیشنهادات صلح:\n"
    for sender_id, sender_name in list(offers.items()):
        text += f"• {sender_name}\n"
        keyboard.append([
            InlineKeyboardButton(f"✅ قبول {sender_name}", style="primary", callback_data=f"peace_accept_{sender_id}"),
            InlineKeyboardButton(f"❌ رد {sender_name}", style="primary", callback_data=f"peace_reject_{sender_id}")
        ])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="peace_menu")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def peace_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    conn = db_connect()
    c = conn.cursor()
    now = int(time.time())
    c.execute('SELECT country1_id, country2_id, expires_at FROM peace_treaties WHERE (country1_id = ? OR country2_id = ?) AND expires_at > ?', (user_id, user_id, now))
    rows = c.fetchall()
    conn.close()

    if not rows:
        await query.edit_message_text(
            "🕊️ شما هیچ پیمان صلح فعالی ندارید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="political_menu")]])
        )
        return

    text = "🕊️ پیمان‌های صلح فعال:\n"
    for row in rows:
        other_id = row[1] if row[0] == user_id else row[0]
        other = get_user(other_id)
        other_name = other["country_name"] if other else str(other_id)
        remaining = row[2] - now
        text += f"• {other_name} - {format_time_remaining(remaining)} باقی‌مانده\n"

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="political_menu")]]))

async def peace_accept(update: Update, context: ContextTypes.DEFAULT_TYPE, sender_id):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    offers = user.get("peace_offers", {})

    if str(sender_id) not in offers:
        await query.edit_message_text("❌ پیشنهاد یافت نشد!")
        return

    add_peace_treaty(user_id, int(sender_id), 24)
    del offers[str(sender_id)]
    update_user(user_id, peace_offers=offers)

    await query.edit_message_text(
        f"🕊️ پیمان صلح پذیرفته شد!\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ به مدت ۲۴ ساعت طرفین نمی‌توانند به هم حمله کنند."
    )
    try:
        await context.bot.send_message(
            chat_id=sender_id,
            text=f"🕊️ {user['country_name']} پیمان صلح شما را پذیرفت!\n✅ ۲۴ ساعت صلح برقرار است."
        )
    except:
        pass

async def peace_reject(update: Update, context: ContextTypes.DEFAULT_TYPE, sender_id):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    offers = user.get("peace_offers", {})

    if str(sender_id) in offers:
        del offers[str(sender_id)]
        update_user(user_id, peace_offers=offers)

    await query.edit_message_text("❌ پیشنهاد صلح رد شد.")

# ========== سیاسی - دیپلماسی ==========
async def diplomacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    await query.edit_message_text(
        f"🏅 دیپلماسی\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 قدرت دیپلماتیک: {user['economy'] * 10}\n"
        f"🤝 اتحاد فعلی: {user['alliance'] or 'ندارد'}\n\n"
        f"💡 با دیپلماسی قوی می‌توانید:\n"
        f"• هزینه‌های جنگ را کاهش دهید\n"
        f"• امکانات تجاری دریافت کنید\n"
        f"• از حملات پیشگیری کنید",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🤝 ایجاد اتحاد", style="success", callback_data="alliance")],
            [InlineKeyboardButton("📨 ارسال پیام دیپلماتیک", style="primary", callback_data="diplomacy_msg")],
            [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="political_menu")]
        ])
    )

async def official_statement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📢 متن بیانیه رسمی خود را وارد کنید:\n"
        "(این پیام برای همه کاربران ارسال خواهد شد)",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="political_menu")]])
    )
    context.user_data['waiting_for'] = 'official_statement'

async def country_opinions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT country_name, text, created_at FROM statements ORDER BY created_at DESC LIMIT 10')
    rows = c.fetchall()
    conn.close()

    text = "📮 نظرات و بیانیه‌های کشورها\n━━━━━━━━━━━━━━━━━━━━\n\n"
    if rows:
        for row in rows:
            date_str = datetime.fromtimestamp(row[2]).strftime("%Y-%m-%d %H:%M")
            text += f"🏳️ {row[0]} - {date_str}\n{row[1]}\n\n"
    else:
        text += "• هیچ بیانیه‌ای ثبت نشده\n"

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 ثبت بیانیه", style="success", callback_data="official_statement")],
        [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="political_menu")]
    ]))

async def war_laws(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    laws = (
        "⚔️ قوانین جنگ جهانی\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "۱. حمله اتمی فقط در صورت داشتن سلاح هسته‌ای مجاز است\n"
        "۲. کشورهای دارای پیمان صلح نمی‌توانند به هم حمله کنند\n"
        "۳. استفاده از سپر دفاعی در جنگ عادلانه است\n"
        "۴. غارت منابع بیش از ۵۰٪ طلای حریف ممنوع است\n"
        "۵. حملات پشت‌سرهم (کمتر از ۱۵ دقیقه) نقض قوانین است\n"
        "۶. کشورهای VIP حق استفاده از سلاح‌های پیشرفته را دارند\n"
        "۷. هرگونه تقلب در شرط‌بندی جرم جنگی محسوب می‌شود"
    )
    await query.edit_message_text(laws, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="political_menu")]
    ]))

async def world_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = db_connect()
    c = conn.cursor()
    now = int(time.time())
    c.execute('SELECT event_text, event_type, created_at FROM world_events WHERE active = 1 AND expires_at > ? ORDER BY created_at DESC LIMIT 5', (now,))
    rows = c.fetchall()
    conn.close()

    text = "🌍 رویدادهای جهانی\n━━━━━━━━━━━━━━━━━━━━\n\n"
    if rows:
        for row in rows:
            date_str = datetime.fromtimestamp(row[2]).strftime("%Y-%m-%d %H:%M")
            emoji = "🌋" if row[1] == "disaster" else "💰" if row[1] == "economic" else "⚔️" if row[1] == "war" else "📢"
            text += f"{emoji} {row[0]}\n🕐 {date_str}\n\n"
    else:
        text += "• هیچ رویداد فعالی وجود ندارد\n"

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="political_menu")]
    ]))

async def secret_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🕊️ گفتگوی محرمانه\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📨 برای ارسال پیام محرمانه، فرمت زیر را وارد کنید:\n"
        "آیدی_عددی | متن پیام\n"
        "مثال: 123456789 | پیام محرمانه شما...",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="political_menu")]])
    )
    context.user_data['waiting_for'] = 'secret_chat'

# ========== اقتصادی - بانک ==========
async def bank_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    interest = int(user.get("bank_gold", 0) * 0.05)
    await query.edit_message_text(
        f"🏦 بانک مرکزی\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 طلای شما: {user['gold']:,}\n"
        f"🏦 سپرده بانکی: {user.get('bank_gold', 0):,}\n"
        f"📈 سود روزانه: {interest:,} طلا (۵٪)\n"
        f"💡 سپرده‌گذاری در بانک از غارت حملات محافظت می‌کند!\n\n"
        f"📋 انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 واریز به بانک", style="success", callback_data="bank_deposit"),
             InlineKeyboardButton("💸 برداشت از بانک", style="primary", callback_data="bank_withdraw")],
            [InlineKeyboardButton("📈 دریافت سود", style="success", callback_data="bank_interest")],
            [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="economic_menu")]
        ])
    )

async def bank_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "💰 مقدار طلا برای واریز به بانک را وارد کنید:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="bank_menu")]])
    )
    context.user_data['waiting_for'] = 'bank_deposit'

async def bank_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "💸 مقدار طلا برای برداشت از بانک را وارد کنید:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="bank_menu")]])
    )
    context.user_data['waiting_for'] = 'bank_withdraw'

async def bank_interest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    interest = int(user.get("bank_gold", 0) * 0.05)
    if interest <= 0:
        await query.answer("سپرده‌ای ندارید!", show_alert=True)
        return
    new_bank = user.get("bank_gold", 0) + interest
    update_user(user_id, bank_gold=new_bank)
    await query.answer(f"✅ {interest:,} طلا سود دریافت شد!", show_alert=True)
    await query.edit_message_text(
        f"📈 سود دریافت شد!\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 سود: {interest:,} طلا\n"
        f"🏦 موجودی بانک: {new_bank:,}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="bank_menu")]])
    )

# ========== اقتصادی - شرکت‌ها ==========
async def companies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    now = int(time.time())
    last = user.get("last_company_time", 0)
    cooldown = 3600
    can_collect = now - last >= cooldown
    income = user["economy"] * 50

    keyboard = [
        [InlineKeyboardButton(f"💰 دریافت درآمد ({income:,} طلا)", style="success", callback_data="company_collect")] if can_collect else [],
        [InlineKeyboardButton("🏭 ارتقای اقتصاد", style="success", callback_data="national_projects")],
        [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="economic_menu")]
    ]
    keyboard = [k for k in keyboard if k]

    remaining = max(0, cooldown - (now - last))
    text = (
        f"🏢 مرکز شرکت‌ها\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏭 سطح اقتصاد: {user['economy']}\n"
        f"💰 درآمد هر ساعت: {income:,} طلا\n"
    )
    if not can_collect:
        text += f"⏳ تا دریافت بعدی: {format_time_remaining(remaining)}\n"
    else:
        text += "✅ آماده دریافت درآمد!\n"

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def company_collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    now = int(time.time())
    if now - user.get("last_company_time", 0) < 3600:
        await query.answer("⏳ هنوز زمان نرسیده!", show_alert=True)
        return
    income = user["economy"] * 50
    update_user(user_id, gold=user["gold"] + income, last_company_time=now)
    await query.answer(f"✅ {income:,} طلا دریافت شد!", show_alert=True)
    await query.edit_message_text(
        f"💰 درآمد شرکت‌ها\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ {income:,} طلا دریافت شد!\n"
        f"💰 موجودی جدید: {user['gold'] + income:,}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="companies")]])
    )

# ========== اقتصادی - صادرات/واردات ==========
async def trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    oil_price = random.randint(8, 15)
    gold_price = random.randint(95, 105)

    await query.edit_message_text(
        f"📦 مرکز تجارت\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 نرخ‌های امروز:\n"
        f"🛢️ نفت: {oil_price} طلا / واحد\n"
        f"💰 طلا: {gold_price} نفت / واحد\n\n"
        f"💰 طلای شما: {user['gold']:,}\n"
        f"🛢️ نفت شما: {user['oil']:,}\n\n"
        f"📋 انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🛢️ فروش ۱۰۰ نفت ({100*oil_price:,} طلا)", style="primary", callback_data="trade_sell_100")],
            [InlineKeyboardButton(f"🛢️ فروش ۵۰۰ نفت ({500*oil_price:,} طلا)", style="primary", callback_data="trade_sell_500")],
            [InlineKeyboardButton(f"💰 خرید ۱۰۰ نفت ({int(100/gold_price*100):,} طلا)", style="success", callback_data="trade_buy_100")],
            [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="economic_menu")]
        ])
    )

async def trade_action(update: Update, context: ContextTypes.DEFAULT_TYPE, action, amount):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    oil_price = random.randint(8, 15)

    if action == "sell":
        if user["oil"] < amount:
            await query.answer("نفت کافی ندارید!", show_alert=True)
            return
        earned = amount * oil_price
        update_user(user_id, oil=user["oil"] - amount, gold=user["gold"] + earned)
        await query.answer(f"✅ {earned:,} طلا دریافت شد!", show_alert=True)
        await query.edit_message_text(
            f"📦 صادرات موفق!\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🛢️ فروخته شده: {amount}\n"
            f"💰 دریافتی: {earned:,} طلا",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="trade")]])
        )
    else:
        cost = int(amount / oil_price * 100) // 100
        if user["gold"] < cost:
            await query.answer("طلای کافی ندارید!", show_alert=True)
            return
        update_user(user_id, gold=user["gold"] - cost, oil=user["oil"] + amount)
        await query.answer(f"✅ {amount} نفت خریداری شد!", show_alert=True)
        await query.edit_message_text(
            f"📦 واردات موفق!\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🛢️ خریداری شده: {amount}\n"
            f"💰 پرداخت: {cost:,} طلا",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="trade")]])
        )

# ========== اقتصادی - نفت و انرژی ==========
async def oil_energy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    price = random.randint(10, 20)
    await query.edit_message_text(
        f"🛢️ نفت و انرژی\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 طلا: {user['gold']:,}\n"
        f"🛢️ نفت: {user['oil']:,}\n"
        f"📈 قیمت فروش نفت: {price} طلا / واحد\n\n"
        f"📋 انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🛢️ فروش ۵۰ نفت ({50*price} طلا)", style="primary", callback_data="sell_oil_50")],
            [InlineKeyboardButton(f"🛢️ فروش ۱۰۰ نفت ({100*price} طلا)", style="primary", callback_data="sell_oil_100")],
            [InlineKeyboardButton(f"🛢️ فروش ۵۰۰ نفت ({500*price} طلا)", style="primary", callback_data="sell_oil_500")],
            [InlineKeyboardButton(f"🛢️ فروش ۱۰۰۰ نفت ({1000*price} طلا)", style="primary", callback_data="sell_oil_1000")],
            [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="economic_menu")]
        ])
    )

async def sell_oil(update: Update, context: ContextTypes.DEFAULT_TYPE, amount):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    price = random.randint(10, 20)
    total = amount * price

    if user["oil"] < amount:
        await query.answer("نفت کافی ندارید!", show_alert=True)
        return

    update_user(user_id, oil=user["oil"] - amount, gold=user["gold"] + total)
    await query.answer(f"✅ {total:,} طلا دریافت شد!", show_alert=True)
    await query.edit_message_text(
        f"🛢️ فروش نفت\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🛢️ فروخته شده: {amount}\n"
        f"💰 دریافتی: {total:,} طلا",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="oil_energy")]])
    )

# ========== نظامی - دانشمندان و کارخانه هسته‌ای ==========
async def nuke_scientists_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    research_needed = 100
    current = user.get("nuke_research", 0)

    await query.edit_message_text(
        f"🧪 مرکز دانشمندان هسته‌ای\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👨‍🔬 دانشمندان استخدام‌شده: {user.get('nuke_scientists', 0)}\n"
        f"📊 پیشرفت تحقیقات: {current}/{research_needed}\n"
        f"☢️ سلاح هسته‌ای: {'دارد' if user['nuke'] else 'ندارد'}\n"
        f"💰 هزینه استخدام هر دانشمند: ۵۰,۰۰۰ طلا\n"
        f"💰 طلای شما: {user['gold']:,}\n\n"
        f"📋 هر دانشمند هر ساعت ۱ واحد تحقیق تولید می‌کند.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👨‍🔬 استخدام دانشمند", style="success", callback_data="hire_scientist")],
            [InlineKeyboardButton("📈 دریافت تحقیق", style="success", callback_data="collect_research")],
            [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="military_menu")]
        ])
    )

async def hire_scientist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    cost = 50000
    if user["gold"] < cost:
        await query.answer("طلای کافی ندارید!", show_alert=True)
        return
    update_user(user_id, gold=user["gold"] - cost, nuke_scientists=user.get("nuke_scientists", 0) + 1)
    await query.answer("✅ دانشمند استخدام شد!", show_alert=True)
    await nuke_scientists_menu(update, context)

async def collect_research(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    scientists = user.get("nuke_scientists", 0)
    if scientists == 0:
        await query.answer("دانشمندی ندارید!", show_alert=True)
        return
    new_research = user.get("nuke_research", 0) + scientists
    nuke_acquired = False
    if new_research >= 100 and not user["nuke"]:
        new_research = 0
        nuke_acquired = True
        update_user(user_id, nuke_research=new_research, nuke=True)
    else:
        update_user(user_id, nuke_research=new_research)

    msg = f"📈 {scientists} واحد تحقیق دریافت شد!\n📊 پیشرفت: {new_research}/100"
    if nuke_acquired:
        msg = "☢️ تبریک! سلاح هسته‌ای ساخته شد!"
    await query.answer(msg.split("\n")[0], show_alert=True)
    await query.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="nuke_scientists_menu")]])
    )

async def nuke_factory_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    factory_level = user.get("nuke_factory", 0)
    cost = 100000 * (factory_level + 1)

    await query.edit_message_text(
        f"🏭 کارخانه هسته‌ای\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏭 سطح کارخانه: {factory_level}\n"
        f"⚡ تولید مواد هسته‌ای: {factory_level * 10}/ساعت\n"
        f"💰 هزینه ارتقا: {cost:,} طلا\n"
        f"💰 طلای شما: {user['gold']:,}\n\n"
        f"📋 کارخانه مواد هسته‌ای برای حملات اتمی تولید می‌کند.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🏭 ارتقا ({cost:,} طلا)", style="success", callback_data="upgrade_factory")],
            [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="military_menu")]
        ])
    )

async def upgrade_factory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    factory_level = user.get("nuke_factory", 0)
    cost = 100000 * (factory_level + 1)
    if user["gold"] < cost:
        await query.answer("طلای کافی ندارید!", show_alert=True)
        return
    update_user(user_id, gold=user["gold"] - cost, nuke_factory=factory_level + 1)
    await query.answer("✅ کارخانه ارتقا یافت!", show_alert=True)
    await nuke_factory_menu(update, context)

# ========== نظامی - امنیت و ترور ==========
async def security_terror(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    await query.edit_message_text(
        f"🕶️ مرکز امنیت و ترور\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ مقاومت در برابر ترور: {user.get('terror_resistance', 0)}\n"
        f"💰 طلای شما: {user['gold']:,}\n\n"
        f"📋 انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛡️ افزایش امنیت (۱۰,۰۰۰ طلا)", style="success", callback_data="increase_security")],
            [InlineKeyboardButton("🗡️ ترور رهبر دشمن (۵۰,۰۰۰ طلا)", style="danger", callback_data="assassination")],
            [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="military_menu")]
        ])
    )

async def increase_security(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    cost = 10000
    if user["gold"] < cost:
        await query.answer("طلای کافی ندارید!", show_alert=True)
        return
    update_user(user_id, gold=user["gold"] - cost, terror_resistance=user.get("terror_resistance", 0) + 10)
    await query.answer("✅ امنیت افزایش یافت!", show_alert=True)
    await query.edit_message_text(
        f"🛡️ امنیت افزایش یافت!\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 مقاومت در برابر ترور: +۱۰\n"
        f"💰 پرداخت: {cost:,} طلا",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="security_terror")]])
    )

async def assassination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🗡️ آیدی عددی هدف ترور را وارد کنید:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="security_terror")]])
    )
    context.user_data['waiting_for'] = 'assassination_target'

# ========== نظامی - خرابکاری هسته‌ای ==========
async def nuclear_sabotage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = get_user(query.from_user.id)
    if not user:
        await query.answer()
        await query.edit_message_text("ابتدا /start کنید")
        return
    if not user["is_vip"]:
        await query.answer("❌ این بخش فقط برای VIP هاست!", show_alert=True)
        return
    await query.answer()

    await query.edit_message_text(
        f"💣 مرکز خرابکاری هسته‌ای\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 هزینه هر خرابکاری: ۱۰۰,۰۰۰ طلا\n"
        f"💰 طلای شما: {user['gold']:,}\n\n"
        f"📋 هدف را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 خرابکاری در NPC", style="danger", callback_data="sabotage_npc")],
            [InlineKeyboardButton("👤 خرابکاری در کاربر", style="danger", callback_data="sabotage_user")],
            [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="military_menu")]
        ])
    )

SABOTAGE_COST = 100000

async def sabotage_npc_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = get_user(query.from_user.id)
    if not user:
        await query.answer()
        await query.edit_message_text("ابتدا /start کنید")
        return
    if not user["is_vip"]:
        await query.answer("❌ این بخش فقط برای VIP هاست!", show_alert=True)
        return
    await query.answer()

    npcs = get_npc_countries()
    if not npcs:
        await query.edit_message_text(
            "❌ هیچ NPC فعالی وجود ندارد!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="nuclear_sabotage")]])
        )
        return

    keyboard = []
    row = []
    for npc in npcs[:20]:
        row.append(InlineKeyboardButton(f"🤖 {npc['name']}", style="danger", callback_data=f"sabotage_target_npc_{npc['id']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="nuclear_sabotage")])

    await query.edit_message_text(
        f"🤖 خرابکاری در NPC\n💰 هزینه: {SABOTAGE_COST:,} طلا\n💰 موجودی: {user['gold']:,}\n\n🎯 هدف را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def sabotage_user_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = get_user(query.from_user.id)
    if not user:
        await query.answer()
        await query.edit_message_text("ابتدا /start کنید")
        return
    if not user["is_vip"]:
        await query.answer("❌ این بخش فقط برای VIP هاست!", show_alert=True)
        return
    await query.answer()

    all_users = get_all_users()
    other_users = [u for u in all_users if u["user_id"] != query.from_user.id]
    if not other_users:
        await query.edit_message_text(
            "❌ هیچ کاربر دیگری وجود ندارد!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="nuclear_sabotage")]])
        )
        return

    keyboard = []
    row = []
    for u in other_users[:20]:
        row.append(InlineKeyboardButton(f"🏳️ {u['name']}", style="danger", callback_data=f"sabotage_target_user_{u['user_id']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="nuclear_sabotage")])

    await query.edit_message_text(
        f"👤 خرابکاری در کاربر\n💰 هزینه: {SABOTAGE_COST:,} طلا\n💰 موجودی: {user['gold']:,}\n\n🎯 هدف را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def execute_sabotage_npc(update: Update, context: ContextTypes.DEFAULT_TYPE, npc_id):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user["is_vip"]:
        await query.answer("❌ این بخش فقط برای VIP هاست!", show_alert=True)
        return
    if user["gold"] < SABOTAGE_COST:
        await query.answer("طلای کافی ندارید!", show_alert=True)
        return
    npc = get_npc_by_id(npc_id)
    if not npc:
        await query.answer("❌ این NPC یافت نشد!", show_alert=True)
        return

    update_user(user_id, gold=user["gold"] - SABOTAGE_COST)

    if random.random() < 0.35:
        await query.answer("❌ خرابکاری ناموفق! مامور شما دستگیر شد!", show_alert=True)
        await query.edit_message_text(
            f"💣 خرابکاری ناموفق!\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"❌ مامور شما در {npc['name']} دستگیر شد!\n"
            f"💰 هزینه از دست رفته: {SABOTAGE_COST:,}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="nuclear_sabotage")]])
        )
        return

    gold_lost = int(npc["gold"] * (0.2 + random.random() * 0.2))
    oil_lost = int(npc["oil"] * (0.2 + random.random() * 0.2))
    army_lost = max(1, int(npc["army"] * 0.15))
    update_npc(npc_id, gold=max(0, npc["gold"] - gold_lost), oil=max(0, npc["oil"] - oil_lost), army=max(0, npc["army"] - army_lost))

    await query.answer("✅ خرابکاری موفق!", show_alert=True)
    await query.edit_message_text(
        f"💣 خرابکاری موفق!\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 هدف: {npc['name']}\n"
        f"💰 طلای نابود شده: {gold_lost:,}\n"
        f"🛢️ نفت نابود شده: {oil_lost:,}\n"
        f"⚔️ ارتش نابود شده: {army_lost}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="nuclear_sabotage")]])
    )

async def execute_sabotage_user(update: Update, context: ContextTypes.DEFAULT_TYPE, target_id):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user["is_vip"]:
        await query.answer("❌ این بخش فقط برای VIP هاست!", show_alert=True)
        return
    if user["gold"] < SABOTAGE_COST:
        await query.answer("طلای کافی ندارید!", show_alert=True)
        return
    target = get_user(target_id)
    if not target:
        await query.answer("❌ کاربر یافت نشد!", show_alert=True)
        return

    update_user(user_id, gold=user["gold"] - SABOTAGE_COST)

    if random.random() < 0.45:
        await query.answer("❌ خرابکاری ناموفق! مامور شما دستگیر شد!", show_alert=True)
        await query.edit_message_text(
            f"💣 خرابکاری ناموفق!\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"❌ مامور شما در {target['country_name']} دستگیر شد!\n"
            f"💰 هزینه از دست رفته: {SABOTAGE_COST:,}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="nuclear_sabotage")]])
        )
        return

    if target.get("nuke"):
        update_user(target_id, nuke=False)
        result_text = f"☢️ سلاح هسته‌ای {target['country_name']} منهدم شد!"
        try:
            await context.bot.send_message(target_id, f"💣 خرابکاری هسته‌ای!\n━━━━━━━━━━━━━━━━━━━━\n☢️ سلاح هسته‌ای شما توسط خرابکاران منهدم شد!")
        except:
            pass
    else:
        research_lost = min(target.get("nuke_research", 0), random.randint(20, 40))
        scientists_lost = min(target.get("nuke_scientists", 0), 1)
        update_user(target_id, nuke_research=max(0, target.get("nuke_research", 0) - research_lost),
                    nuke_scientists=max(0, target.get("nuke_scientists", 0) - scientists_lost))
        result_text = f"🧪 {research_lost} واحد تحقیق و {scientists_lost} دانشمند {target['country_name']} از بین رفت!"
        try:
            await context.bot.send_message(target_id, f"💣 خرابکاری هسته‌ای!\n━━━━━━━━━━━━━━━━━━━━\n🧪 برنامه هسته‌ای شما هدف خرابکاری قرار گرفت!\n📉 {research_lost} واحد تحقیق و {scientists_lost} دانشمند از دست دادید!")
        except:
            pass

    await query.answer("✅ خرابکاری موفق!", show_alert=True)
    await query.edit_message_text(
        f"💣 خرابکاری موفق!\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 هدف: {target['country_name']}\n"
        f"{result_text}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="nuclear_sabotage")]])
    )

# ========== انتقال طلا ==========
async def transfer_gold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    all_users = get_all_users()
    other_users = [u for u in all_users if u["user_id"] != query.from_user.id]
    if not other_users:
        await query.edit_message_text("❌ هیچ کاربر دیگری وجود ندارد!")
        return

    keyboard = []
    row = []
    for u in other_users[:20]:
        row.append(InlineKeyboardButton(f"🏳️ {u['name']}", style="success", callback_data=f"transfer_to_{u['user_id']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="economic_menu")])

    await query.edit_message_text(
        f"💰 انتقال طلا\n💰 موجودی: {user['gold']:,}\n\n🎯 دریافت‌کننده را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def select_transfer_amount(update: Update, context: ContextTypes.DEFAULT_TYPE, target_id):
    query = update.callback_query
    await query.answer()
    context.user_data['transfer_target'] = target_id
    target = get_user(target_id)
    await query.edit_message_text(
        f"💰 انتقال طلا به {target['country_name']}\n\nمقدار طلا را وارد کنید:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="economic_menu")]])
    )
    context.user_data['waiting_for'] = 'transfer_amount'

async def receive_transfer_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    target_id = context.user_data.get('transfer_target')
    target = get_user(target_id)

    if not target:
        await update.message.reply_text("❌ کاربر یافت نشد!")
        return

    try:
        amount = int(update.message.text)
    except:
        await update.message.reply_text("❌ عدد معتبر وارد کنید!")
        return

    if amount <= 0:
        await update.message.reply_text("❌ مقدار باید مثبت باشد!")
        return
    if amount > user["gold"]:
        await update.message.reply_text(f"❌ طلای کافی ندارید! (موجودی: {user['gold']:,})")
        return

    update_user(user_id, gold=user["gold"] - amount)
    update_user(target_id, gold=target["gold"] + amount)
    add_transfer_log(user_id, user["country_name"], target_id, target["country_name"], amount)

    await update.message.reply_text(
        f"✅ انتقال موفق!\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 {amount:,} طلا به {target['country_name']} انتقال یافت."
    )
    context.user_data['waiting_for'] = None
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"💰 دریافت طلا!\n━━━━━━━━━━━━━━━━━━━━\n🏳️ {user['country_name']} به شما {amount:,} طلا فرستاد!"
        )
    except:
        pass

# ========== پول رایگان ==========
async def free_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    now = int(time.time())
    last = user.get("last_free_money", 0)
    cooldown = 1800 if user["is_vip"] else 3600

    if now - last < cooldown:
        remaining = cooldown - (now - last)
        await query.answer(f"⏳ {format_time_remaining(remaining)} صبر کنید!", show_alert=True)
        return

    amount = random.randint(200, 800) if user["is_vip"] else random.randint(100, 400)
    update_user(user_id, gold=user["gold"] + amount, last_free_money=now)
    await query.answer(f"✅ {amount:,} طلا دریافت شد!", show_alert=True)
    await query.edit_message_text(
        f"🎲 پول رایگان\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ {amount:,} طلا دریافت شد!\n"
        f"💰 موجودی جدید: {user['gold'] + amount:,}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]])
    )

# ========== اتحاد ==========
async def alliance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    if user["alliance"]:
        await query.edit_message_text(
            f"🤝 اتحاد فعلی: {user['alliance']}\n\n"
            f"📋 انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو اتحاد", style="danger", callback_data="cancel_alliance")],
                [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="political_menu")]
            ])
        )
    else:
        npcs = get_npc_countries()
        keyboard = []
        row = []
        for npc in npcs[:6]:
            row.append(InlineKeyboardButton(npc["name"], style="success", callback_data=f"ally_{npc['id']}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="political_menu")])
        await query.edit_message_text(
            "🤝 انتخاب متحد:\nبا اتحاد، ۱۰٪ قدرت دفاعی بیشتر می‌گیرید.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def create_alliance(update: Update, context: ContextTypes.DEFAULT_TYPE, npc_id):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    npc = get_npc_by_id(npc_id)
    if not npc:
        await query.edit_message_text("❌ کشور یافت نشد!")
        return
    update_user(user_id, alliance=npc["name"])
    await query.answer(f"✅ با {npc['name']} متحد شدید!", show_alert=True)
    await query.edit_message_text(
        f"✅ اتحاد برقرار شد!\n🤝 متحد شما: {npc['name']}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="political_menu")]])
    )

async def cancel_alliance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    update_user(user_id, alliance="")
    await query.answer("❌ اتحاد لغو شد!", show_alert=True)
    await query.edit_message_text("❌ اتحاد لغو شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="political_menu")]]))

# ========== جاسوسی ==========
async def spy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    cost = 500 if user["is_vip"] else 1000
    all_users = get_all_users()
    other_users = [u for u in all_users if u["user_id"] != query.from_user.id]
    if not other_users:
        await query.edit_message_text("❌ هیچ کاربری برای جاسوسی وجود ندارد!")
        return

    keyboard = []
    row = []
    for u in other_users[:10]:
        row.append(InlineKeyboardButton(f"🏳️ {u['name']}", style="danger", callback_data=f"spy_{u['user_id']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="military_menu")])

    await query.edit_message_text(
        f"🕵️ مرکز جاسوسی\n💰 هزینه: {cost} طلا\n💰 موجودی: {user['gold']:,}\n\n🎯 هدف را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def execute_spy(update: Update, context: ContextTypes.DEFAULT_TYPE, target_id):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    target = get_user(target_id)
    if not target:
        await query.answer("کاربر یافت نشد!", show_alert=True)
        return

    cost = 500 if user["is_vip"] else 1000
    if user["gold"] < cost:
        await query.answer("طلای کافی ندارید!", show_alert=True)
        return

    update_user(user_id, gold=user["gold"] - cost)

    if random.random() < 0.3:
        await query.answer("❌ جاسوسی ناموفق! دستگیر شدید!", show_alert=True)
        await query.edit_message_text(
            f"🕵️ جاسوسی ناموفق!\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"❌ مامور شما دستگیر شد!\n"
            f"💰 هزینه از دست رفته: {cost}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="military_menu")]])
        )
        return

    power = calculate_attack_power(target["equipment"], target["army"], target["tech"], target.get("vip_buildings"))
    await query.edit_message_text(
        f"🕵️ گزارش جاسوسی از {target['country_name']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 طلا: {target['gold']:,}\n"
        f"🛢️ نفت: {target['oil']:,}\n"
        f"⚔️ ارتش: {target['army']}\n"
        f"🏭 اقتصاد: {target['economy']}\n"
        f"🔬 فناوری: {target['tech']}\n"
        f"⚔️ قدرت تخمینی: {int(power)}\n"
        f"🏰 کلن: {target['clan'] or 'ندارد'}\n"
        f"👑 VIP: {'بله' if target['is_vip'] else 'خیر'}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="military_menu")]])
    )

# ========== حمله اتمی ==========
async def nuke_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    if not user["nuke"]:
        await query.edit_message_text(
            "☢️ شما سلاح هسته‌ای ندارید!\n"
            "برای ساخت از پروژه‌های ملی اقدام کنید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="military_menu")]])
        )
        return

    all_users = get_all_users()
    other_users = [u for u in all_users if u["user_id"] != query.from_user.id]
    if not other_users:
        await query.edit_message_text("❌ هیچ کاربری وجود ندارد!")
        return

    keyboard = []
    row = []
    for u in other_users[:10]:
        row.append(InlineKeyboardButton(f"🏳️ {u['name']}", style="danger", callback_data=f"nuke_{u['user_id']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="military_menu")])

    await query.edit_message_text(
        "☢️ حمله اتمی\n⚠️ این حمله خسارات سنگین وارد می‌کند!\n\n🎯 هدف را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def execute_nuke(update: Update, context: ContextTypes.DEFAULT_TYPE, target_id):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    target = get_user(target_id)
    if not target:
        await query.edit_message_text("❌ کاربر یافت نشد!")
        return

    damage_gold = int(target["gold"] * 0.5)
    damage_oil = int(target["oil"] * 0.5)

    update_user(target_id, gold=max(0, target["gold"] - damage_gold), oil=max(0, target["oil"] - damage_oil))
    update_user(user_id, nuke=False)

    await query.edit_message_text(
        f"☢️ حمله اتمی انجام شد!\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 هدف: {target['country_name']}\n"
        f"💰 خسارت طلا: {damage_gold:,}\n"
        f"🛢️ خسارت نفت: {damage_oil:,}\n"
        f"⚠️ سلاح هسته‌ای شما مصرف شد!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="military_menu")]])
    )
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"☢️ حمله اتمی!\n━━━━━━━━━━━━━━━━━━━━\n🏳️ {user['country_name']} به شما حمله اتمی کرد!\n💰 -{damage_gold:,} طلا\n🛢️ -{damage_oil:,} نفت"
        )
    except:
        pass
    await send_to_channel(context.application, f"☢️ حمله اتمی!\n🗡️ {user['country_name']} → 🛡️ {target['country_name']}\n💰 خسارت: {damage_gold:,} طلا")

# ========== پروژه‌های ملی ==========
async def national_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return

    keyboard = [
        [InlineKeyboardButton("🏭 توسعه اقتصاد (۵۰۰ طلا)", style="success", callback_data="project_economy"),
         InlineKeyboardButton("🔬 توسعه فناوری (۵۰۰ طلا)", style="success", callback_data="project_tech")],
        [InlineKeyboardButton("👥 افزایش جمعیت (۳۰۰ طلا)", style="success", callback_data="project_population"),
         InlineKeyboardButton("☢️ سلاح هسته‌ای (۵,۰۰۰ طلا)", style="primary", callback_data="project_nuke")],
        [InlineKeyboardButton("🏠 پناهگاه اتمی (۱,۰۰۰ طلا)", style="primary", callback_data="project_shelter"),
         InlineKeyboardButton("⚔️ توسعه ارتش (۴۰۰ طلا)", style="success", callback_data="project_army")],
    ]
    if user["is_vip"]:
        keyboard.append([InlineKeyboardButton("👑 خرید VIP (۲۰,۰۰۰,۰۰۰ طلا)", style="success", callback_data="buy_vip")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="economic_menu")])

    await query.edit_message_text(
        f"🏗️ پروژه‌های ملی\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 طلا: {user['gold']:,}\n"
        f"📊 اقتصاد: {user['economy']}\n"
        f"🔬 فناوری: {user['tech']}\n"
        f"👥 جمعیت: {user['population']:,}\n"
        f"☢️ سلاح هسته‌ای: {'دارد' if user['nuke'] else 'ندارد'}\n"
        f"🏠 پناهگاه: {'دارد' if user['shelter'] else 'ندارد'}\n"
        f"👑 VIP: {'بله' if user['is_vip'] else 'خیر'}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 پروژه‌های قابل اجرا:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def execute_project(update: Update, context: ContextTypes.DEFAULT_TYPE, project, cost):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    if user["gold"] < cost:
        await query.answer(f"طلای کافی ندارید! نیاز: {cost:,}", show_alert=True)
        return
    new_gold = user["gold"] - cost
    updates = {"gold": new_gold}
    msg = ""
    if project == "economy":
        updates["economy"] = user["economy"] + 5
        msg = f"🏭 اقتصاد به {user['economy'] + 5} افزایش یافت!"
    elif project == "tech":
        updates["tech"] = user["tech"] + 5
        msg = f"🔬 فناوری به {user['tech'] + 5} افزایش یافت!"
    elif project == "population":
        updates["population"] = user["population"] + 100
        msg = f"👥 جمعیت به {user['population'] + 100} افزایش یافت!"
    elif project == "nuke":
        if user["nuke"]:
            await query.answer("شما قبلاً سلاح هسته‌ای دارید!", show_alert=True)
            return
        updates["nuke"] = True
        msg = "☢️ سلاح هسته‌ای ساخته شد!"
    elif project == "shelter":
        if user["shelter"]:
            await query.answer("شما قبلاً پناهگاه دارید!", show_alert=True)
            return
        updates["shelter"] = True
        msg = "🏠 پناهگاه اتمی ساخته شد!"
    elif project == "army":
        updates["army"] = user["army"] + 3
        msg = f"⚔️ ارتش به {user['army'] + 3} افزایش یافت!"
    update_user(user_id, **updates)
    await query.answer("✅ پروژه تکمیل شد!", show_alert=True)
    await query.edit_message_text(
        f"✅ {msg}\n💰 طلای باقی‌مانده: {new_gold:,}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پروژه‌ها", style="primary", callback_data="national_projects")]])
    )

async def buy_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    if user["is_vip"]:
        await query.answer("شما قبلاً VIP هستید!", show_alert=True)
        return
    if user["gold"] < 20000000:
        await query.answer("طلای کافی ندارید! نیاز: ۲۰,۰۰۰,۰۰۰", show_alert=True)
        return
    new_gold = user["gold"] - 20000000
    update_user(user_id, gold=new_gold, is_vip=True)
    await query.answer("👑 شما VIP شدید!", show_alert=True)
    await query.edit_message_text(
        f"👑 تبریک! شما VIP شدید!\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ امکانات VIP:\n"
        f"• 🏥 ساخت بیمارستان\n"
        f"• 🏭 ساخت کارخانه اسلحه‌سازی\n"
        f"• 🛢️ ساخت پالایشگاه نفت\n"
        f"• 🎓 ساخت دانشگاه\n"
        f"• ✈️ ساخت فرودگاه\n"
        f"• 🛡️ ساخت پناهگاه پیشرفته\n"
        f"• 💊 خرید و فروش مواد مخدر\n"
        f"• 💻 حمله سایبری\n"
        f"• ⏳ زمان حمله کمتر (۵ دقیقه)\n"
        f"• 💰 پول رایگان بیشتر\n"
        f"• 🕵️ جاسوسی پیشرفته\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 طلای باقی‌مانده: {new_gold:,}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]])
    )

# ========== بازار سیاه ==========
async def black_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    rand_price = random.randint(50, 200)
    keyboard = [
        [InlineKeyboardButton(f"💰 خرید اسلحه قاچاق ({rand_price} طلا)", style="danger", callback_data=f"black_weapon_{rand_price}"),
         InlineKeyboardButton(f"🛢️ خرید نفت قاچاق ({rand_price//2} طلا)", style="danger", callback_data=f"black_oil_{rand_price//2}")],
    ]
    if user["is_vip"]:
        keyboard.append([InlineKeyboardButton("💎 خرید موشک قاچاق (۵,۰۰۰ طلا)", style="danger", callback_data="black_missile"),
                        InlineKeyboardButton("💎 خرید پهپاد قاچاق (۳,۰۰۰ طلا)", style="danger", callback_data="black_drone")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="economic_menu")])
    await query.edit_message_text(
        f"🏴 بازار سیاه\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ کالاهای قاچاق!\n"
        f"💰 طلا: {user['gold']:,}\n\n"
        f"📋 پیشنهادات امروز:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def black_market_buy(update: Update, context: ContextTypes.DEFAULT_TYPE, item, price):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    if user["gold"] < price:
        await query.answer(f"طلای کافی ندارید! نیاز: {price}", show_alert=True)
        return
    new_gold = user["gold"] - price
    if "weapon" in item:
        equip = user["equipment"].copy()
        equip["soldiers"] = equip.get("soldiers", 0) + 10
        update_user(user_id, gold=new_gold, equipment=equip)
        msg = "🪖 ۱۰ سرباز قاچاق دریافت کردید!"
    elif "oil" in item:
        new_oil = user["oil"] + 50
        update_user(user_id, gold=new_gold, oil=new_oil)
        msg = "🛢️ ۵۰ نفت قاچاق دریافت کردید!"
    elif "missile" in item:
        equip = user["equipment"].copy()
        equip["cruise_missiles"] = equip.get("cruise_missiles", 0) + 3
        update_user(user_id, gold=new_gold, equipment=equip)
        msg = "🚀 ۳ موشک کروز قاچاق دریافت کردید!"
    elif "drone" in item:
        equip = user["equipment"].copy()
        equip["scout_drones"] = equip.get("scout_drones", 0) + 2
        update_user(user_id, gold=new_gold, equipment=equip)
        msg = "🚁 ۲ پهپاد قاچاق دریافت کردید!"
    else:
        msg = "✅ خرید انجام شد!"
    await query.edit_message_text(
        f"✅ خرید قاچاق موفق!\n━━━━━━━━━━━━━━━━━━━━\n{msg}\n💰 طلای باقی‌مانده: {new_gold:,}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به بازار سیاه", style="primary", callback_data="black_market")]])
    )

# ========== نقشه جنگی ==========
async def war_map(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    npcs = get_npc_countries()
    text = "🗺️ نقشه جنگی\n━━━━━━━━━━━━━━━━━━━━\n\n"
    if not npcs:
        text += "❌ هیچ کشوری برای نبرد وجود ندارد!"
    else:
        for npc in npcs:
            power = calculate_attack_power(npc['equipment'], npc['army'], npc['defense_power'])
            text += f"🏳️ {npc['name']}\n⚔️ قدرت: {power}\n💰 طلا: {npc['gold']:,}\n📈 سهام: {npc['share_price']}\n━━━━━━━━━━━━━━━━━━━━\n"
    users = get_all_users()
    if users:
        text += "\n👥 کاربران:\n"
        for u in users[:5]:
            user_obj = get_user(u["user_id"])
            if user_obj:
                power = calculate_attack_power(user_obj["equipment"], user_obj["army"], user_obj["tech"], user_obj.get("vip_buildings"))
                text += f"🏳️ {u['name']} | ⚔️ {power}\n"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="military_menu")]]))

# ========== رتبه‌بندی ==========
async def rankings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT country_name, gold, total_wins, economy, is_vip, clan FROM users ORDER BY gold DESC LIMIT 10')
    rows = c.fetchall()
    conn.close()
    if not rows:
        await query.edit_message_text("❌ هیچ کاربری وجود ندارد")
        return
    text = "🏆 رتبه‌بندی کشورها\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, row in enumerate(rows, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        vip = " 👑" if row[4] else ""
        clan = f" [{row[5]}]" if row[5] else ""
        text += f"{medal} {row[0]}{vip}{clan}\n💰 طلا: {row[1]:,}\n🏆 پیروزی‌ها: {row[2]}\n🏭 اقتصاد: {row[3]}\n━━━━━━━━━━━━━━━━━━━━\n"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]]))

# ========== شرط‌بندی ==========
async def betting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    npcs = get_npc_countries()
    if len(npcs) < 2:
        await query.edit_message_text("کشور کافی برای شرط‌بندی وجود ندارد!")
        return
    selected = random.sample(npcs, 2)
    country1, country2 = selected[0], selected[1]
    context.user_data['bet_country1'] = country1
    context.user_data['bet_country2'] = country2
    keyboard = [
        [InlineKeyboardButton(f"🎯 {country1['name']} (شانس {random.randint(30, 70)}%)", style="primary", callback_data="bet_1")],
        [InlineKeyboardButton(f"🎯 {country2['name']} (شانس {random.randint(30, 70)}%)", style="primary", callback_data="bet_2")],
        [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]
    ]
    await query.edit_message_text(
        f"🎰 شرط‌بندی\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 طلای شما: {user['gold']:,}\n"
        f"📋 دو کشور برای شرط:\n"
        f"۱. {country1['name']} (قدرت: {calculate_attack_power(country1['equipment'], country1['army'], country1['defense_power'])})\n"
        f"۲. {country2['name']} (قدرت: {calculate_attack_power(country2['equipment'], country2['army'], country2['defense_power'])})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"ابتدا کشور را انتخاب کنید، سپس مقدار شرط را وارد کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def receive_bet_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    try:
        amount = int(update.message.text)
    except:
        await update.message.reply_text("❌ عدد معتبر وارد کنید!")
        return
    if amount < 100:
        await update.message.reply_text("❌ حداقل شرط ۱۰۰ طلا است!")
        return
    if amount > user["gold"]:
        await update.message.reply_text(f"❌ طلای کافی ندارید! (موجودی: {user['gold']:,})")
        return
    country1 = context.user_data.get('bet_country1')
    country2 = context.user_data.get('bet_country2')
    bet_choice = context.user_data.get('bet_choice')
    if not country1 or not country2 or not bet_choice:
        await update.message.reply_text("❌ خطا! دوباره شرط ببندید.")
        return
    power1 = calculate_attack_power(country1['equipment'], country1['army'], country1['defense_power'])
    power2 = calculate_attack_power(country2['equipment'], country2['army'], country2['defense_power'])
    win_chance = power1 / (power1 + power2) * 100
    is_win = random.random() * 100 < win_chance
    if bet_choice == "bet_2":
        is_win = not is_win
    if is_win:
        winnings = amount * 2
        new_gold = user["gold"] + winnings
        update_user(user_id, gold=new_gold, total_bets=user["total_bets"]+1, total_bet_wins=user["total_bet_wins"]+1)
        await update.message.reply_text(
            f"🎉 برنده شدید!\n━━━━━━━━━━━━━━━━━━━━\n✅ {country1['name'] if bet_choice=='bet_1' else country2['name']} پیروز شد!\n💰 برد شما: {winnings:,} طلا\n💰 موجودی جدید: {new_gold:,}"
        )
    else:
        new_gold = user["gold"] - amount
        update_user(user_id, gold=new_gold, total_bets=user["total_bets"]+1)
        await update.message.reply_text(
            f"💔 باختید!\n━━━━━━━━━━━━━━━━━━━━\n❌ {country2['name'] if bet_choice=='bet_1' else country1['name']} پیروز شد!\n💸 {amount:,} طلا از دست دادید.\n💰 موجودی جدید: {new_gold:,}"
        )
    context.user_data['waiting_for'] = None

# ========== کلن‌ها ==========
async def clans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    if user["clan"]:
        clan = get_clan(user["clan"])
        if clan:
            text = (
                f"🏰 کلن {clan['name']}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 رهبر: {clan['owner_id']}\n"
                f"👥 اعضا: {len(clan['members'])} نفر\n"
                f"💰 طلا: {clan['gold']:,}\n"
                f"🛢️ نفت: {clan['oil']:,}\n"
                f"📈 سطح: {clan['level']}\n"
                f"🏆 برد: {clan['wins']} | شکست: {clan['losses']}\n"
            )
            keyboard = [
                [InlineKeyboardButton("📋 لیست اعضا", style="primary", callback_data="clan_members")],
                [InlineKeyboardButton("🚪 خروج از کلن", style="danger", callback_data="clan_leave")],
                [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            update_user(user_id, clan="")
            await query.edit_message_text("کلن شما حذف شده است!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]]))
    else:
        keyboard = [
            [InlineKeyboardButton("🏰 ایجاد کلن جدید", style="success", callback_data="clan_create")],
            [InlineKeyboardButton("📋 لیست کلن‌ها", style="primary", callback_data="clan_list")],
            [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]
        ]
        await query.edit_message_text(
            f"🏰 کلن‌ها\n━━━━━━━━━━━━━━━━━━━━\nشما عضو هیچ کلنی نیستید.\n\n📋 انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def clan_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🏰 نام کلن را وارد کنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="clans")]]))
    context.user_data['waiting_for'] = 'clan_name'

async def receive_clan_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    clan_name = update.message.text.strip()
    if not clan_name:
        await update.message.reply_text("نام کلن نمی‌تواند خالی باشد!")
        return
    if get_clan(clan_name):
        await update.message.reply_text("❌ این نام قبلاً ثبت شده است!")
        return
    create_clan(clan_name, user_id)
    update_user(user_id, clan=clan_name)
    await update.message.reply_text(f"✅ کلن {clan_name} با موفقیت ایجاد شد!\nشما رهبر کلن هستید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]]))
    context.user_data['waiting_for'] = None

async def clan_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT name, owner_id, level, wins FROM clans ORDER BY level DESC LIMIT 10')
    rows = c.fetchall()
    conn.close()
    if not rows:
        await query.edit_message_text("❌ هیچ کلنی وجود ندارد!")
        return
    text = "🏰 لیست کلن‌ها\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, row in enumerate(rows, 1):
        text += f"{i}. {row[0]}\n👤 رهبر: {row[1]}\n📈 سطح: {row[2]} | 🏆 برد: {row[3]}\n━━━━━━━━━━━━━━━━━━━━\n"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="clans")]]))

async def clan_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user or not user["clan"]:
        await query.edit_message_text("شما عضو هیچ کلنی نیستید!")
        return
    clan = get_clan(user["clan"])
    if not clan:
        await query.edit_message_text("کلن یافت نشد!")
        return
    members_text = "📋 اعضای کلن\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for member_id in clan["members"]:
        member = get_user(member_id)
        if member:
            members_text += f"• {member['country_name']} (ID: {member_id})\n"
    await query.edit_message_text(members_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="clans")]]))

async def clan_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user or not user["clan"]:
        await query.edit_message_text("شما عضو هیچ کلنی نیستید!")
        return
    clan = get_clan(user["clan"])
    if clan["owner_id"] == user_id:
        await query.edit_message_text("شما رهبر کلن هستید، ابتدا رهبری را به دیگری واگذار کنید!")
        return
    members = clan["members"]
    members.remove(user_id)
    update_clan(user["clan"], members=members)
    update_user(user_id, clan="")
    await query.edit_message_text("✅ شما از کلن خارج شدید!")

# ========== دوئل ==========
async def duel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    keyboard = [
        [InlineKeyboardButton("⚔️ درخواست دوئل", style="danger", callback_data="duel_request")],
        [InlineKeyboardButton("📊 آمار دوئل‌ها", style="danger", callback_data="duel_stats")],
        [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]
    ]
    await query.edit_message_text(
        f"⚔️ دوئل\n━━━━━━━━━━━━━━━━━━━━\n🏆 برد: {user['duel_wins']}\n💔 باخت: {user['duel_losses']}\n━━━━━━━━━━━━━━━━━━━━\n📋 انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def duel_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⚔️ آیدی عددی حریف را وارد کنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="duel")]]))
    context.user_data['waiting_for'] = 'duel_opponent'

async def receive_duel_opponent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    try:
        opponent_id = int(update.message.text)
    except:
        await update.message.reply_text("❌ آیدی عددی معتبر وارد کنید!")
        return
    if opponent_id == user_id:
        await update.message.reply_text("❌ نمی‌توانید با خودتان دوئل کنید!")
        return
    opponent = get_user(opponent_id)
    if not opponent:
        await update.message.reply_text("❌ کاربر یافت نشد!")
        return
    user_power = calculate_attack_power(user["equipment"], user["army"], user["tech"], user.get("vip_buildings"))
    opponent_power = calculate_attack_power(opponent["equipment"], opponent["army"], opponent["tech"], opponent.get("vip_buildings"))
    if user_power > opponent_power:
        gold_win = int(opponent["gold"] * 0.1)
        new_gold = user["gold"] + gold_win
        new_opponent_gold = opponent["gold"] - gold_win
        update_user(user_id, gold=new_gold, duel_wins=user["duel_wins"]+1)
        update_user(opponent_id, gold=new_opponent_gold, duel_losses=opponent["duel_losses"]+1)
        result_text = f"⚔️ نتیجه دوئل\n━━━━━━━━━━━━━━━━━━━━\n✅ {user['country_name']} پیروز شد!\n💰 برد: {gold_win:,} طلا\n⚔️ قدرت شما: {user_power}\n⚔️ قدرت حریف: {opponent_power}"
    else:
        gold_lost = int(user["gold"] * 0.1)
        new_gold = user["gold"] - gold_lost
        new_opponent_gold = opponent["gold"] + gold_lost
        update_user(user_id, gold=new_gold, duel_losses=user["duel_losses"]+1)
        update_user(opponent_id, gold=new_opponent_gold, duel_wins=opponent["duel_wins"]+1)
        result_text = f"⚔️ نتیجه دوئل\n━━━━━━━━━━━━━━━━━━━━\n❌ {opponent['country_name']} پیروز شد!\n💸 طلای از دست رفته: {gold_lost:,}\n⚔️ قدرت شما: {user_power}\n⚔️ قدرت حریف: {opponent_power}"
    await update.message.reply_text(result_text)
    context.user_data['waiting_for'] = None

async def duel_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    total = user['duel_wins'] + user['duel_losses']
    win_rate = int(user['duel_wins'] / total * 100) if total > 0 else 0
    await query.edit_message_text(
        f"📊 آمار دوئل‌ها\n━━━━━━━━━━━━━━━━━━━━\n🏆 برد: {user['duel_wins']}\n💔 باخت: {user['duel_losses']}\n📈 درصد برد: {win_rate}%",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="duel")]])
    )

# ========== بازار سهام ==========
async def stock_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    npcs = get_npc_countries()
    keyboard = []
    for npc in npcs:
        keyboard.append([InlineKeyboardButton(f"📈 {npc['name']} (قیمت: {npc['share_price']})", style="primary", callback_data=f"stock_{npc['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="economic_menu")])
    shares = user.get("shares", {})
    text = f"📈 بازار سهام\n━━━━━━━━━━━━━━━━━━━━\n💰 طلا: {user['gold']:,}\n\n"
    if shares:
        text += "📋 سهام شما:\n"
        for country, amount in shares.items():
            text += f"• {country}: {amount}\n"
    else:
        text += "❌ هیچ سهمی ندارید\n"
    text += f"\n📋 انتخاب کنید:"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def stock_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, npc_id):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    npc = get_npc_by_id(npc_id)
    if not npc:
        await query.edit_message_text("❌ کشور یافت نشد!")
        return
    keyboard = [
        [InlineKeyboardButton("💰 خرید سهام", style="success", callback_data=f"stock_buy_{npc_id}")],
        [InlineKeyboardButton("💰 فروش سهام", style="primary", callback_data=f"stock_sell_{npc_id}")],
        [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="stock_market")]
    ]
    await query.edit_message_text(
        f"📈 {npc['name']}\n━━━━━━━━━━━━━━━━━━━━\n💰 قیمت سهام: {npc['share_price']}\n💰 طلای شما: {user['gold']:,}\n📊 سهام شما: {user.get('shares', {}).get(npc['name'], 0)}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def stock_buy(update: Update, context: ContextTypes.DEFAULT_TYPE, npc_id):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    npc = get_npc_by_id(npc_id)
    if not npc:
        await query.edit_message_text("❌ کشور یافت نشد!")
        return
    price = npc["share_price"]
    if user["gold"] < price:
        await query.answer(f"طلای کافی ندارید! نیاز: {price}", show_alert=True)
        return
    shares = user.get("shares", {})
    shares[npc["name"]] = shares.get(npc["name"], 0) + 1
    new_gold = user["gold"] - price
    new_price = int(price * (1 + random.random() * 0.1))
    update_npc(npc_id, share_price=new_price)
    update_user(user_id, gold=new_gold, shares=shares)
    await query.edit_message_text(
        f"✅ خرید سهام موفق!\n━━━━━━━━━━━━━━━━━━━━\n🏳️ {npc['name']}\n💰 قیمت: {price}\n📈 قیمت جدید: {new_price}\n💰 طلای باقی‌مانده: {new_gold:,}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به بازار", style="primary", callback_data="stock_market")]])
    )

async def stock_sell(update: Update, context: ContextTypes.DEFAULT_TYPE, npc_id):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    npc = get_npc_by_id(npc_id)
    if not npc:
        await query.edit_message_text("❌ کشور یافت نشد!")
        return
    shares = user.get("shares", {})
    if npc["name"] not in shares or shares[npc["name"]] == 0:
        await query.answer("شما این سهم را ندارید!", show_alert=True)
        return
    shares[npc["name"]] -= 1
    if shares[npc["name"]] == 0:
        del shares[npc["name"]]
    price = npc["share_price"]
    new_gold = user["gold"] + price
    new_price = max(50, int(price * (1 - random.random() * 0.1)))
    update_npc(npc_id, share_price=new_price)
    update_user(user_id, gold=new_gold, shares=shares)
    await query.edit_message_text(
        f"✅ فروش سهام موفق!\n━━━━━━━━━━━━━━━━━━━━\n🏳️ {npc['name']}\n💰 قیمت: {price}\n📈 قیمت جدید: {new_price}\n💰 طلای جدید: {new_gold:,}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به بازار", style="primary", callback_data="stock_market")]])
    )

# ========== ماموریت روزانه ==========
async def daily_mission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    now = int(time.time())
    last = user.get("last_daily_mission", 0)
    if now - last < 86400:
        remaining = 86400 - (now - last)
        await query.answer(f"⏳ {format_time_remaining(remaining)} دیگر", show_alert=True)
        return
    missions = [
        {"type": "حمله", "target": 3, "reward": 500},
        {"type": "خرید", "target": 5, "reward": 300},
        {"type": "فروش", "target": 10, "reward": 400},
        {"type": "جاسوسی", "target": 2, "reward": 200},
    ]
    mission = random.choice(missions)
    update_user(user_id, last_daily_mission=now)
    await query.edit_message_text(
        f"🎯 ماموریت روزانه\n━━━━━━━━━━━━━━━━━━━━\n📋 ماموریت: {mission['target']} بار {mission['type']}\n🎁 جایزه: {mission['reward']} طلا\n🔥 استریک: {user['daily_streak'] + 1}\n━━━━━━━━━━━━━━━━━━━━\n✅ ماموریت جدید ثبت شد!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]])
    )

# ========== هدیه روزانه ==========
async def daily_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    now = int(time.time())
    last = user.get("last_daily_gift", 0)
    if now - last < 86400:
        remaining = 86400 - (now - last)
        await query.answer(f"⏳ {format_time_remaining(remaining)} دیگر", show_alert=True)
        return
    gifts = [
        {"name": "طلا", "amount": random.randint(100, 500)},
        {"name": "نفت", "amount": random.randint(50, 200)},
        {"name": "سرباز", "amount": random.randint(1, 5)},
        {"name": "موشک", "amount": random.randint(1, 3)},
    ]
    gift = random.choice(gifts)
    new_streak = user["daily_streak"] + 1
    streak_bonus = new_streak * 10
    if gift["name"] == "طلا":
        new_gold = user["gold"] + gift["amount"] + streak_bonus
        update_user(user_id, gold=new_gold, last_daily_gift=now, daily_streak=new_streak)
        msg = f"💰 {gift['amount']} طلا + 🎁 {streak_bonus} پاداش استریک"
    elif gift["name"] == "نفت":
        new_oil = user["oil"] + gift["amount"]
        update_user(user_id, oil=new_oil, last_daily_gift=now, daily_streak=new_streak)
        msg = f"🛢️ {gift['amount']} نفت"
    elif gift["name"] == "سرباز":
        equip = user["equipment"].copy()
        equip["soldiers"] = equip.get("soldiers", 0) + gift["amount"]
        update_user(user_id, equipment=equip, last_daily_gift=now, daily_streak=new_streak)
        msg = f"🪖 {gift['amount']} سرباز"
    elif gift["name"] == "موشک":
        equip = user["equipment"].copy()
        equip["missiles"] = equip.get("missiles", 0) + gift["amount"]
        update_user(user_id, equipment=equip, last_daily_gift=now, daily_streak=new_streak)
        msg = f"🚀 {gift['amount']} موشک"
    await query.edit_message_text(
        f"🎁 هدیه روزانه\n━━━━━━━━━━━━━━━━━━━━\n✅ شما دریافت کردید: {msg}\n🔥 استریک: {new_streak}\n💪 پاداش استریک: {streak_bonus} طلا اضافه شد!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]])
    )

# ========== مسابقه گروهی ==========
async def group_contest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT country_name, group_points FROM users ORDER BY group_points DESC LIMIT 5')
    rows = c.fetchall()
    conn.close()
    text = "🏆 مسابقه گروهی\n━━━━━━━━━━━━━━━━━━━━\n\n📊 امتیاز شما: {}\n\n🏅 برترین‌های گروه:\n".format(user["group_points"])
    for i, row in enumerate(rows, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} {row[0]}: {row[1]} امتیاز\n"
    keyboard = [
        [InlineKeyboardButton("🎯 شرکت در مسابقه", style="success", callback_data="contest_join")],
        [InlineKeyboardButton("📋 قوانین مسابقه", style="primary", callback_data="contest_rules")],
        [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def contest_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    points = random.randint(1, 10)
    new_points = user["group_points"] + points
    update_user(user_id, group_points=new_points)
    await query.edit_message_text(
        f"🎯 شما در مسابقه شرکت کردید!\n📊 {points} امتیاز دریافت کردید!\n📊 امتیاز کل: {new_points}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="group_contest")]])
    )

async def contest_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rules = (
        "📋 قوانین مسابقه گروهی\n━━━━━━━━━━━━━━━━━━━━\n"
        "۱. هر کاربر می‌تواند روزانه ۵ بار در مسابقه شرکت کند.\n"
        "۲. هر بار شرکت = ۱ تا ۱۰ امتیاز تصادفی.\n"
        "۳. در پایان هر هفته به ۳ نفر برتر جایزه تعلق می‌گیرد.\n"
        "۴. جایزه اول: ۵,۰۰۰ طلا\n"
        "۵. جایزه دوم: ۳,۰۰۰ طلا\n"
        "۶. جایزه سوم: ۱,۰۰۰ طلا\n"
        "۷. مسابقه هر هفته یکشنبه ساعت ۲۴:۰۰ بازنشانی می‌شود."
    )
    await query.edit_message_text(rules, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="group_contest")]]))

# ========== 🎡 گردونه شانس ==========
async def lucky_wheel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    now = int(time.time())
    last = user.get("last_spin", 0)
    cooldown = 3600
    if now - last < cooldown:
        remaining = cooldown - (now - last)
        await query.answer(f"⏳ {format_time_remaining(remaining)} تا چرخش بعدی!", show_alert=True)
        return
    prizes = [
        {"emoji": "💰", "name": "طلا", "amount": random.randint(100, 1000), "type": "gold"},
        {"emoji": "🛢️", "name": "نفت", "amount": random.randint(50, 500), "type": "oil"},
        {"emoji": "🪖", "name": "سرباز", "amount": random.randint(1, 10), "type": "soldiers"},
        {"emoji": "🚀", "name": "موشک", "amount": random.randint(1, 5), "type": "missiles"},
        {"emoji": "💎", "name": "الماس ویژه", "amount": 5000, "type": "gold"},
        {"emoji": "☢️", "name": "سلاح هسته‌ای", "amount": 1, "type": "nuke"},
        {"emoji": "🎁", "name": "جایزه بزرگ", "amount": random.randint(2000, 5000), "type": "gold"},
        {"emoji": "😢", "name": "هیچی!", "amount": 0, "type": "nothing"},
    ]
    prize = random.choices(prizes, weights=[25, 20, 20, 15, 8, 5, 5, 2])[0]
    update_user(user_id, last_spin=now)
    if prize["type"] == "gold":
        update_user(user_id, gold=user["gold"] + prize["amount"])
    elif prize["type"] == "oil":
        update_user(user_id, oil=user["oil"] + prize["amount"])
    elif prize["type"] == "soldiers":
        equip = user["equipment"].copy()
        equip["soldiers"] = equip.get("soldiers", 0) + prize["amount"]
        update_user(user_id, equipment=equip)
    elif prize["type"] == "missiles":
        equip = user["equipment"].copy()
        equip["missiles"] = equip.get("missiles", 0) + prize["amount"]
        update_user(user_id, equipment=equip)
    elif prize["type"] == "nuke":
        update_user(user_id, nuke=True)
    msg = f"{prize['emoji']} {prize['name']}"
    if prize["type"] != "nothing":
        msg += f" x{prize['amount']:,}"
    await query.edit_message_text(
        f"🎡 گردونه شانس\n━━━━━━━━━━━━━━━━━━━━\n🎯 نتیجه چرخش:\n\n🎉 {msg}\n\n⏳ چرخش بعدی: ۱ ساعت دیگر",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]])
    )

# ========== ⛏️ معدن‌کاوی ==========
async def mining(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    now = int(time.time())
    last = user.get("last_mine", 0)
    cooldown = 1800
    if now - last < cooldown:
        remaining = cooldown - (now - last)
        await query.answer(f"⏳ {format_time_remaining(remaining)} تا حفاری بعدی!", show_alert=True)
        return
    mining_power = user.get("mining_power", 1)
    base_gold = random.randint(50, 200)
    gold_found = base_gold * mining_power
    upgrade_msg = ""
    if random.random() < 0.1:
        mining_power += 1
        update_user(user_id, mining_power=mining_power)
        upgrade_msg = f"\n✨ قدرت معدن شما به {mining_power} ارتقا یافت!"
    update_user(user_id, gold=user["gold"] + gold_found, last_mine=now)
    await query.edit_message_text(
        f"⛏️ معدن‌کاوی\n━━━━━━━━━━━━━━━━━━━━\n💰 {gold_found:,} طلا استخراج شد!{upgrade_msg}\n⛏️ قدرت معدن: {mining_power}\n⏳ حفاری بعدی: ۳۰ دقیقه",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]])
    )

# ========== 🗺️ شکار گنج ==========
async def treasure_hunt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    treasure = get_active_treasure()
    if not treasure:
        create_treasure()
        treasure = get_active_treasure()
    if not treasure:
        await query.edit_message_text("❌ خطا در ایجاد گنج!")
        return
    user_power = calculate_attack_power(user["equipment"], user["army"], user["tech"], user.get("vip_buildings"))
    find_chance = min(80, 20 + user_power / 10)
    if random.random() * 100 < find_chance:
        if claim_treasure(treasure["id"], user_id):
            update_user(user_id, gold=user["gold"] + treasure["gold"], oil=user["oil"] + treasure["oil"])
            await query.edit_message_text(
                f"🗺️ شکار گنج\n━━━━━━━━━━━━━━━━━━━━\n🎉 گنج پیدا شد!\n💰 طلا: {treasure['gold']:,}\n🛢️ نفت: {treasure['oil']:,}\n⚔️ قدرت شما: {int(user_power)} | شانس: {int(find_chance)}%",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]])
            )
        else:
            await query.edit_message_text(
                f"🗺️ شکار گنج\n━━━━━━━━━━━━━━━━━━━━\n😢 کسی دیگر این گنج را پیدا کرد!\nدوباره تلاش کنید...",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]])
            )
    else:
        await query.edit_message_text(
            f"🗺️ شکار گنج\n━━━━━━━━━━━━━━━━━━━━\n😢 گنجی پیدا نشد!\n⚔️ قدرت شما: {int(user_power)} | شانس: {int(find_chance)}%\n💡 با تقویت ارتش شانس خود را افزایش دهید!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]])
        )

# ========== 🏅 دستاوردها ==========
async def achievements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    achs = get_achievements(user_id)
    new_achs = check_achievements(user_id)
    text = f"🏅 دستاوردها\n━━━━━━━━━━━━━━━━━━━━\n\n📊 امتیاز کل: {user.get('achievement_points', 0)}\n\n"
    if achs:
        text += "✅ دستاوردهای کسب شده:\n"
        for a in achs:
            name = ACHIEVEMENT_NAMES.get(a[0], a[0])
            date_str = datetime.fromtimestamp(a[1]).strftime("%Y-%m-%d")
            text += f"• {name} ({date_str})\n"
    else:
        text += "❌ هنوز دستاوردی کسب نکرده‌اید!\n"
    text += "\n📋 دستاوردهای قابل کسب:\n"
    for key, name in ACHIEVEMENT_NAMES.items():
        if key not in [a[0] for a in achs]:
            text += f"• 🔒 {name}\n"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]]))

# ========== 👥 دعوت دوستان ==========
async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    bot_username = context.bot.username
    link = f"https://t.me/{bot_username}?start={user_id}"
    await query.edit_message_text(
        f"👥 دعوت دوستان\n━━━━━━━━━━━━━━━━━━━━\n📊 تعداد دعوت شده: {user.get('referrals', 0)}\n\n🔗 لینک دعوت شما:\n{link}\n\n🎁 به ازای هر دوست:\n• 💰 ۵۰۰ طلا\n• 🛢️ ۲۰۰ نفت\n• 🪖 ۲ سرباز\n\n📤 لینک را برای دوستانتان بفرستید!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]])
    )

# ========== 📰 روزنامه ==========
async def newspaper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT attacker_name, defender_name, result, gold_stolen, timestamp FROM attack_logs ORDER BY timestamp DESC LIMIT 5')
    attacks = c.fetchall()
    c.execute('SELECT sender_name, receiver_name, amount, timestamp FROM transfers ORDER BY timestamp DESC LIMIT 5')
    transfers = c.fetchall()
    c.execute('SELECT event_text, event_type, created_at FROM world_events WHERE active = 1 AND expires_at > ? ORDER BY created_at DESC LIMIT 3', (int(time.time()),))
    events = c.fetchall()
    conn.close()
    text = "📰 روزنامه جنگ جهانی\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📅 تاریخ: {datetime.now().strftime('%Y-%m-%d')}\n\n"
    text += "⚔️ آخرین حملات:\n"
    if attacks:
        for a in attacks:
            time_str = datetime.fromtimestamp(a[4]).strftime("%H:%M")
            text += f"🕐 {time_str} - {a[0]} → {a[1]} | {a[2]} | 💰{a[3]}\n"
    else:
        text += "• هیچ حمله‌ای ثبت نشده\n"
    text += "\n💰 آخرین انتقال‌ها:\n"
    if transfers:
        for t in transfers:
            time_str = datetime.fromtimestamp(t[3]).strftime("%H:%M")
            text += f"🕐 {time_str} - {t[0]} → {t[1]} | 💰{t[2]:,}\n"
    else:
        text += "• هیچ انتقالی ثبت نشده\n"
    if events:
        text += "\n🌍 رویدادهای جهانی:\n"
        for e in events:
            emoji = "🌋" if e[1] == "disaster" else "💰" if e[1] == "economic" else "⚔️"
            text += f"{emoji} {e[0]}\n"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]]))

# ========== 🎪 تورنمنت ==========
async def tournament(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    all_users = get_all_users()
    if len(all_users) < 4:
        await query.edit_message_text(
            "🎪 تورنمنت\n━━━━━━━━━━━━━━━━━━━━\n❌ حداقل ۴ کاربر برای تورنمنت لازم است!\nدوستانتان را دعوت کنید...",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]])
        )
        return
    participants = random.sample(all_users, min(4, len(all_users)))
    text = "🎪 تورنمنت نبرد\n━━━━━━━━━━━━━━━━━━━━\n\n⚔️ مرحله نیمه‌نهایی:\n"
    p1, p2 = participants[0], participants[1]
    p1_power = calculate_attack_power(get_user(p1["user_id"])["equipment"], p1["army"], p1["tech"])
    p2_power = calculate_attack_power(get_user(p2["user_id"])["equipment"], p2["army"], p2["tech"])
    winner1 = p1 if p1_power > p2_power else p2
    text += f"🥊 {p1['name']} ({p1_power}) vs {p2['name']} ({p2_power})\n✅ برنده: {winner1['name']}\n\n"
    p3, p4 = participants[2], participants[3]
    p3_power = calculate_attack_power(get_user(p3["user_id"])["equipment"], p3["army"], p3["tech"])
    p4_power = calculate_attack_power(get_user(p4["user_id"])["equipment"], p4["army"], p4["tech"])
    winner2 = p3 if p3_power > p4_power else p4
    text += f"🥊 {p3['name']} ({p3_power}) vs {p4['name']} ({p4_power})\n✅ برنده: {winner2['name']}\n\n"
    text += "🏆 فینال:\n"
    w1_power = calculate_attack_power(get_user(winner1["user_id"])["equipment"], winner1["army"], winner1["tech"])
    w2_power = calculate_attack_power(get_user(winner2["user_id"])["equipment"], winner2["army"], winner2["tech"])
    champion = winner1 if w1_power > w2_power else winner2
    text += f"🥊 {winner1['name']} ({w1_power}) vs {winner2['name']} ({w2_power})\n\n🎉 قهرمان: {champion['name']} 🏆\n💰 جایزه: ۱,۰۰۰ طلا"
    if champion["user_id"] == user_id:
        update_user(user_id, gold=user["gold"] + 1000)
        text += "\n\n✨ شما برنده ۱,۰۰۰ طلا شدید!"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]]))

# ========== پنل VIP ==========
async def vip_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user["is_vip"]:
        await query.edit_message_text("❌ شما VIP نیستید!")
        return
    keyboard = [
        [InlineKeyboardButton("🏥 ساخت بیمارستان (۵,۰۰۰ طلا)", style="success", callback_data="vip_hospital"),
         InlineKeyboardButton("🏭 ساخت کارخانه (۱۰,۰۰۰ طلا)", style="success", callback_data="vip_factory")],
        [InlineKeyboardButton("🛢️ ساخت پالایشگاه (۷,۵۰۰ طلا)", style="success", callback_data="vip_refinery"),
         InlineKeyboardButton("🎓 ساخت دانشگاه (۵,۰۰۰ طلا)", style="success", callback_data="vip_university")],
        [InlineKeyboardButton("✈️ ساخت فرودگاه (۱۵,۰۰۰ طلا)", style="success", callback_data="vip_airport"),
         InlineKeyboardButton("🛡️ پناهگاه پیشرفته (۱۲,۰۰۰ طلا)", style="primary", callback_data="vip_shelter_adv")],
        [InlineKeyboardButton("💊 خرید مواد مخدر (۲,۰۰۰ طلا)", style="danger", callback_data="vip_buy_drugs"),
         InlineKeyboardButton("💰 فروش مواد مخدر (۴,۰۰۰ طلا)", style="danger", callback_data="vip_sell_drugs")],
        [InlineKeyboardButton("💻 حمله سایبری (۵,۰۰۰ طلا)", style="danger", callback_data="vip_cyber_attack")],
        [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]
    ]
    buildings = user["vip_buildings"]
    await query.edit_message_text(
        f"👑 پنل VIP\n━━━━━━━━━━━━━━━━━━━━\n💰 طلا: {user['gold']:,}\n💊 مواد مخدر: {user.get('drugs', 0)}\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🏗️ ساختمان‌ها:\n• 🏥 بیمارستان: {buildings.get('hospital', 0)}\n• 🏭 کارخانه: {buildings.get('factory', 0)}\n"
        f"• 🛢️ پالایشگاه: {buildings.get('refinery', 0)}\n• 🎓 دانشگاه: {buildings.get('university', 0)}\n"
        f"• ✈️ فرودگاه: {buildings.get('airport', 0)}\n• 🛡️ پناهگاه پیشرفته: {buildings.get('shelter_advanced', 0)}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n📋 انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def build_vip_building(update: Update, context: ContextTypes.DEFAULT_TYPE, building, cost, effect_desc):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user["is_vip"]:
        await query.answer("شما VIP نیستید!", show_alert=True)
        return
    if user["gold"] < cost:
        await query.answer(f"طلای کافی ندارید! نیاز: {cost:,}", show_alert=True)
        return
    buildings = user["vip_buildings"].copy()
    buildings[building] = buildings.get(building, 0) + 1
    new_gold = user["gold"] - cost
    if building == "hospital":
        update_user(user_id, gold=new_gold, vip_buildings=buildings, population=user["population"] + 500)
    elif building == "factory":
        update_user(user_id, gold=new_gold, vip_buildings=buildings, army=user["army"] + 10)
    elif building == "refinery":
        update_user(user_id, gold=new_gold, vip_buildings=buildings, oil=user["oil"] + 200)
    elif building == "university":
        update_user(user_id, gold=new_gold, vip_buildings=buildings, tech=user["tech"] + 10)
    elif building == "airport":
        update_user(user_id, gold=new_gold, vip_buildings=buildings, economy=user["economy"] + 15)
    elif building == "shelter_advanced":
        update_user(user_id, gold=new_gold, vip_buildings=buildings, shelter=True)
    else:
        update_user(user_id, gold=new_gold, vip_buildings=buildings)
    await query.answer(f"✅ {effect_desc} ساخته شد!", show_alert=True)
    await query.edit_message_text(
        f"✅ {effect_desc} با موفقیت ساخته شد!\n💰 طلای باقی‌مانده: {new_gold:,}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل VIP", style="primary", callback_data="vip_panel")]])
    )

async def drugs_trade(update: Update, context: ContextTypes.DEFAULT_TYPE, action):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user["is_vip"]:
        await query.answer("شما VIP نیستید!", show_alert=True)
        return
    if action == "buy":
        if user["gold"] < 2000:
            await query.answer("طلای کافی ندارید!", show_alert=True)
            return
        new_gold = user["gold"] - 2000
        new_drugs = user.get("drugs", 0) + 10
        update_user(user_id, gold=new_gold, drugs=new_drugs)
        await query.edit_message_text(
            f"💊 خرید مواد مخدر موفق!\n━━━━━━━━━━━━━━━━━━━━\n✅ ۱۰ واحد خریداری شد\n💰 پرداخت: ۲,۰۰۰ طلا\n💊 موجودی: {new_drugs}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل VIP", style="primary", callback_data="vip_panel")]])
        )
    elif action == "sell":
        drugs = user.get("drugs", 0)
        if drugs < 10:
            await query.answer("مواد مخدر کافی ندارید!", show_alert=True)
            return
        if random.random() < 0.2:
            update_user(user_id, drugs=0)
            await query.edit_message_text(
                "💀 دستگیر شدید!\n━━━━━━━━━━━━━━━━━━━━\n❌ پلیس شما را دستگیر کرد!\n💊 تمام مواد مخدر ضبط شد!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل VIP", style="primary", callback_data="vip_panel")]])
            )
            return
        gold_earned = 4000
        new_gold = user["gold"] + gold_earned
        new_drugs = drugs - 10
        update_user(user_id, gold=new_gold, drugs=new_drugs)
        await query.edit_message_text(
            f"💰 فروش مواد مخدر موفق!\n━━━━━━━━━━━━━━━━━━━━\n✅ ۱۰ واحد فروخته شد\n💰 دریافت: ۴,۰۰۰ طلا\n💊 موجودی: {new_drugs}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل VIP", style="primary", callback_data="vip_panel")]])
        )

async def cyber_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user["is_vip"]:
        await query.answer("شما VIP نیستید!", show_alert=True)
        return
    if user["gold"] < 5000:
        await query.answer("طلای کافی ندارید!", show_alert=True)
        return
    npcs = get_npc_countries()
    if not npcs:
        await query.edit_message_text("هیچ کشوری برای حمله وجود ندارد!")
        return
    target = random.choice(npcs)
    stolen = int(target["gold"] * random.uniform(0.1, 0.3))
    new_gold = user["gold"] + stolen - 5000
    new_npc_gold = target["gold"] - stolen
    update_npc(target["id"], gold=max(0, new_npc_gold))
    update_user(user_id, gold=new_gold)
    await query.edit_message_text(
        f"💻 حمله سایبری موفق!\n━━━━━━━━━━━━━━━━━━━━\n🎯 هدف: {target['name']}\n💰 طلای دزدیده: {stolen:,}\n💸 هزینه: ۵,۰۰۰ طلا\n💰 سود خالص: {stolen - 5000:,} طلا",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل VIP", style="primary", callback_data="vip_panel")]])
    )

# ========== حمله به NPC ==========
async def military_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.answer()
        await query.edit_message_text("ابتدا /start کنید")
        return
    await query.answer()

    npcs = get_npc_countries()
    if not npcs:
        await query.edit_message_text(
            "❌ هیچ NPC فعالی وجود ندارد!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="attack_menu")]])
        )
        return

    keyboard = []
    row = []
    for npc in npcs[:20]:
        row.append(InlineKeyboardButton(f"🤖 {npc['name']}", style="danger", callback_data=f"npc_{npc['id']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="attack_menu")])

    await query.edit_message_text(
        "⚔️ حمله به NPC\n\n🎯 هدف را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def execute_npc_attack(update: Update, context: ContextTypes.DEFAULT_TYPE, npc_id, percent):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    npc = get_npc_by_id(npc_id)
    if not user or not npc:
        await query.edit_message_text("❌ خطا در دریافت اطلاعات")
        return
    percent_float = int(percent) / 100
    attack_power = calculate_attack_power(user["equipment"], user["army"], user["tech"], user.get("vip_buildings")) * percent_float
    defense_power = calculate_defense_power(npc["equipment"], npc["army"], npc["defense_power"])
    win_chance = attack_power / (attack_power + defense_power) * 100
    is_win = random.random() * 100 < win_chance
    if is_win:
        gold_stolen = int(npc["gold"] * (0.3 + random.random() * 0.3))
        oil_stolen = int(npc["oil"] * (0.3 + random.random() * 0.3))
        new_gold = user["gold"] + gold_stolen
        new_oil = user["oil"] + oil_stolen
        new_wins = user["total_wins"] + 1
        attacker_losses = calculate_casualties(user["equipment"], 0.05)
        defender_losses = calculate_casualties(npc["equipment"], 0.25)
        attacker_equip = user["equipment"].copy()
        for k, v in attacker_losses.items():
            attacker_equip[k] = max(0, attacker_equip.get(k, 0) - v)
        npc_equip = npc["equipment"].copy()
        for k, v in defender_losses.items():
            npc_equip[k] = max(0, npc_equip.get(k, 0) - v)
        update_user(user_id, gold=new_gold, oil=new_oil, total_wins=new_wins, equipment=attacker_equip, last_attack_time=int(time.time()))
        update_npc(npc_id, gold=max(0, npc["gold"] - gold_stolen), oil=max(0, npc["oil"] - oil_stolen), equipment=npc_equip)
        add_attack_log(user_id, user["country_name"], npc_id, npc["name"], "پیروزی", gold_stolen, oil_stolen)
        result_text = (
            f"🎉 پیروزی در حمله!\n━━━━━━━━━━━━━━━━━━━━\n⚔️ قدرت شما: {int(attack_power)} | حریف: {int(defense_power)}\n"
            f"🎯 شانس پیروزی: {int(win_chance)}%\n💰 غنیمت طلا: {gold_stolen:,}\n🛢️ غنیمت نفت: {oil_stolen:,}\n"
            f"⚔️ تلفات شما: {sum(attacker_losses.values())} | تلفات حریف: {sum(defender_losses.values())}\n"
            f"🎒 تجهیزات ازدست‌رفته شما:\n{format_casualties(attacker_losses)}\n"
            f"🎒 تجهیزات ازدست‌رفته حریف:\n{format_casualties(defender_losses)}"
        )
        await send_to_channel(context.application, f"⚔️ گزارش حمله\n━━━━━━━━━━━━━━━━━━━━\n🗡️ مهاجم: {user['country_name']}\n🛡️ مدافع: {npc['name']}\n✅ نتیجه: پیروزی\n💰 غنیمت: {gold_stolen:,} طلا")
    else:
        gold_lost = int(user["gold"] * (0.05 + random.random() * 0.15))
        oil_lost = int(user["oil"] * (0.05 + random.random() * 0.15))
        new_losses = user["total_losses"] + 1
        attacker_losses = calculate_casualties(user["equipment"], 0.20)
        attacker_equip = user["equipment"].copy()
        for k, v in attacker_losses.items():
            attacker_equip[k] = max(0, attacker_equip.get(k, 0) - v)
        update_user(user_id, gold=max(0, user["gold"] - gold_lost), oil=max(0, user["oil"] - oil_lost),
                   total_losses=new_losses, equipment=attacker_equip, last_attack_time=int(time.time()))
        add_attack_log(user_id, user["country_name"], npc_id, npc["name"], "شکست", 0, 0)
        result_text = (
            f"💔 شکست در حمله!\n━━━━━━━━━━━━━━━━━━━━\n⚔️ قدرت شما: {int(attack_power)} | حریف: {int(defense_power)}\n"
            f"🎯 شانس پیروزی: {int(win_chance)}%\n💰 طلای از دست رفته: {gold_lost:,}\n🛢️ نفت از دست رفته: {oil_lost:,}\n"
            f"⚔️ تلفات شما: {sum(attacker_losses.values())}\n🎒 تجهیزات ازدست‌رفته:\n{format_casualties(attacker_losses)}"
        )
        await send_to_channel(context.application, f"⚔️ گزارش حمله\n━━━━━━━━━━━━━━━━━━━━\n🗡️ مهاجم: {user['country_name']}\n🛡️ مدافع: {npc['name']}\n❌ نتیجه: شکست\n💰 خسارت: {gold_lost:,} طلا")
    await query.edit_message_text(result_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منو", style="primary", callback_data="menu")]]))

# ========== مدیریت کل‌بک‌ها ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data != "check_membership":
        if not await enforce_channel_membership(update, context):
            return

    if data in ADMIN_ACTION_PERM_MAP:
        if not is_admin(query.from_user.id):
            await query.answer("🚫 شما دسترسی ادمین ندارید!", show_alert=True)
            return
        if not has_admin_permission(query.from_user.id, ADMIN_ACTION_PERM_MAP[data]):
            await query.answer("🚫 شما به این بخش دسترسی ندارید!", show_alert=True)
            return

    if data == "menu":
        await show_main_menu(update, context)
    elif data == "check_membership":
        await check_membership(update, context)
    elif data == "my_country":
        await my_country(update, context)
    elif data == "political_menu":
        await political_menu(update, context)
    elif data == "economic_menu":
        await economic_menu(update, context)
    elif data == "military_menu":
        await military_menu(update, context)
    elif data == "attack_menu":
        await attack_menu(update, context)
    elif data == "transfer_gold":
        await transfer_gold(update, context)
    elif data == "enter_coupon":
        await enter_coupon(update, context)
    elif data.startswith("transfer_to_"):
        target_id = int(data.split("_")[2])
        await select_transfer_amount(update, context, target_id)
    elif data == "arms_market":
        await arms_market(update, context)
    elif data == "defense_market":
        await defense_market(update, context)
    elif data.startswith("buy_") and data != "buy_vip":
        item_key = data[4:]
        await buy_equipment(update, context, item_key)
    elif data == "military_attack":
        await military_attack(update, context)
    elif data == "attack_user":
        await attack_user(update, context)
    elif data.startswith("attack_user_"):
        target_id = int(data.split("_")[2])
        await select_attack_percent(update, context, target_id)
    elif data.startswith("attack_pct_"):
        percent = data.split("_")[2]
        await execute_attack_warning(update, context, percent)
    elif data.startswith("npc_attack_"):
        parts = data.split("_")
        npc_id = int(parts[2])
        percent = parts[3]
        await execute_npc_attack(update, context, npc_id, percent)
    elif data.startswith("npc_"):
        npc_id = int(data.split("_")[1])
        keyboard = []
        for p in ["10", "20", "30", "40", "50", "60", "70", "80", "90", "100"]:
            keyboard.append(InlineKeyboardButton(f"{p}%", style="primary", callback_data=f"npc_attack_{npc_id}_{p}"))
        rows = [keyboard[i:i+2] for i in range(0, len(keyboard), 2)]
        rows.append([InlineKeyboardButton("❌ انصراف", style="primary", callback_data="military_attack")])
        await query.answer()
        await query.edit_message_text("🎯 درصد نیرو را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(rows))
    elif data.startswith("defense_shield_"):
        attack_id = int(data.split("_")[2])
        await defense_reaction(update, context, "shield", attack_id)
    elif data.startswith("defense_spy_"):
        attack_id = int(data.split("_")[2])
        await defense_reaction(update, context, "spy", attack_id)
    elif data.startswith("defense_counter_"):
        attack_id = int(data.split("_")[2])
        await defense_reaction(update, context, "counter", attack_id)
    elif data.startswith("defense_wait_"):
        attack_id = int(data.split("_")[2])
        await defense_reaction(update, context, "wait", attack_id)
    elif data == "nuke_attack":
        await nuke_attack(update, context)
    elif data.startswith("nuke_") and data[len("nuke_"):].isdigit():
        target_id = int(data[len("nuke_"):])
        await execute_nuke(update, context, target_id)
    elif data == "free_money":
        await free_money(update, context)
    elif data == "companies":
        await companies(update, context)
    elif data == "company_collect":
        await company_collect(update, context)
    elif data == "oil_energy":
        await oil_energy(update, context)
    elif data.startswith("sell_oil_"):
        amount = int(data.split("_")[2])
        await sell_oil(update, context, amount)
    elif data == "trade":
        await trade(update, context)
    elif data.startswith("trade_sell_"):
        amount = int(data.split("_")[2])
        await trade_action(update, context, "sell", amount)
    elif data.startswith("trade_buy_"):
        amount = int(data.split("_")[2])
        await trade_action(update, context, "buy", amount)
    elif data == "bank_menu":
        await bank_menu(update, context)
    elif data == "bank_deposit":
        await bank_deposit(update, context)
    elif data == "bank_withdraw":
        await bank_withdraw(update, context)
    elif data == "bank_interest":
        await bank_interest(update, context)
    elif data == "spy":
        await spy(update, context)
    elif data.startswith("spy_"):
        target_id = int(data.split("_")[1])
        await execute_spy(update, context, target_id)
    elif data == "alliance":
        await alliance(update, context)
    elif data.startswith("ally_"):
        npc_id = int(data.split("_")[1])
        await create_alliance(update, context, npc_id)
    elif data == "cancel_alliance":
        await cancel_alliance(update, context)
    elif data == "national_projects":
        await national_projects(update, context)
    elif data == "project_economy":
        await execute_project(update, context, "economy", 500)
    elif data == "project_tech":
        await execute_project(update, context, "tech", 500)
    elif data == "project_population":
        await execute_project(update, context, "population", 300)
    elif data == "project_nuke":
        await execute_project(update, context, "nuke", 5000)
    elif data == "project_shelter":
        await execute_project(update, context, "shelter", 1000)
    elif data == "project_army":
        await execute_project(update, context, "army", 400)
    elif data == "buy_vip":
        await buy_vip(update, context)
    elif data == "vip_panel":
        await vip_panel(update, context)
    elif data == "vip_hospital":
        await build_vip_building(update, context, "hospital", 5000, "بیمارستان")
    elif data == "vip_factory":
        await build_vip_building(update, context, "factory", 10000, "کارخانه اسلحه‌سازی")
    elif data == "vip_refinery":
        await build_vip_building(update, context, "refinery", 7500, "پالایشگاه نفت")
    elif data == "vip_university":
        await build_vip_building(update, context, "university", 5000, "دانشگاه")
    elif data == "vip_airport":
        await build_vip_building(update, context, "airport", 15000, "فرودگاه")
    elif data == "vip_shelter_adv":
        await build_vip_building(update, context, "shelter_advanced", 12000, "پناهگاه پیشرفته")
    elif data == "vip_buy_drugs":
        await drugs_trade(update, context, "buy")
    elif data == "vip_sell_drugs":
        await drugs_trade(update, context, "sell")
    elif data == "vip_cyber_attack":
        await cyber_attack(update, context)
    elif data == "black_market":
        await black_market(update, context)
    elif data.startswith("black_"):
        if data == "black_missile":
            await black_market_buy(update, context, "missile", 5000)
        elif data == "black_drone":
            await black_market_buy(update, context, "drone", 3000)
        else:
            parts = data.split("_")
            if len(parts) >= 3:
                item = parts[1]
                price = int(parts[2])
                await black_market_buy(update, context, item, price)
    elif data == "war_map":
        await war_map(update, context)
    elif data == "rankings":
        await rankings(update, context)
    elif data == "betting":
        await betting(update, context)
    elif data == "bet_1" or data == "bet_2":
        context.user_data['bet_choice'] = data
        await query.answer()
        await query.edit_message_text("💰 مقدار طلای شرط را وارد کنید (حداقل ۱۰۰):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="betting")]]))
        context.user_data['waiting_for'] = 'bet_amount'
    elif data == "clans":
        await clans(update, context)
    elif data == "clan_create":
        await clan_create(update, context)
    elif data == "clan_list":
        await clan_list(update, context)
    elif data == "clan_members":
        await clan_members(update, context)
    elif data == "clan_leave":
        await clan_leave(update, context)
    elif data == "duel":
        await duel(update, context)
    elif data == "duel_request":
        await duel_request(update, context)
    elif data == "duel_stats":
        await duel_stats(update, context)
    elif data == "stock_market":
        await stock_market(update, context)
    elif data.startswith("stock_") and not data.startswith("stock_buy_") and not data.startswith("stock_sell_"):
        npc_id = int(data.split("_")[1])
        await stock_detail(update, context, npc_id)
    elif data.startswith("stock_buy_"):
        npc_id = int(data.split("_")[2])
        await stock_buy(update, context, npc_id)
    elif data.startswith("stock_sell_"):
        npc_id = int(data.split("_")[2])
        await stock_sell(update, context, npc_id)
    elif data == "daily_mission":
        await daily_mission(update, context)
    elif data == "daily_gift":
        await daily_gift(update, context)
    elif data == "group_contest":
        await group_contest(update, context)
    elif data == "contest_join":
        await contest_join(update, context)
    elif data == "contest_rules":
        await contest_rules(update, context)
    elif data == "lucky_wheel":
        await lucky_wheel(update, context)
    elif data == "mining":
        await mining(update, context)
    elif data == "treasure_hunt":
        await treasure_hunt(update, context)
    elif data == "achievements":
        await achievements(update, context)
    elif data == "referral":
        await referral(update, context)
    elif data == "newspaper":
        await newspaper(update, context)
    elif data == "tournament":
        await tournament(update, context)
    elif data == "shield_buy":
        await shield_buy(update, context)
    elif data == "peace_menu":
        await peace_menu(update, context)
    elif data == "peace_offer":
        await peace_offer(update, context)
    elif data == "peace_inbox":
        await peace_inbox(update, context)
    elif data == "peace_status":
        await peace_status(update, context)
    elif data.startswith("peace_accept_"):
        sender_id = int(data.split("_")[2])
        await peace_accept(update, context, sender_id)
    elif data.startswith("peace_reject_"):
        sender_id = int(data.split("_")[2])
        await peace_reject(update, context, sender_id)
    elif data == "diplomacy":
        await diplomacy(update, context)
    elif data == "official_statement":
        await official_statement(update, context)
    elif data == "country_opinions":
        await country_opinions(update, context)
    elif data == "war_laws":
        await war_laws(update, context)
    elif data == "world_events":
        await world_events(update, context)
    elif data == "secret_chat":
        await secret_chat(update, context)
    elif data == "nuke_scientists_menu":
        await nuke_scientists_menu(update, context)
    elif data == "hire_scientist":
        await hire_scientist(update, context)
    elif data == "collect_research":
        await collect_research(update, context)
    elif data == "nuke_factory_menu":
        await nuke_factory_menu(update, context)
    elif data == "upgrade_factory":
        await upgrade_factory(update, context)
    elif data == "security_terror":
        await security_terror(update, context)
    elif data == "increase_security":
        await increase_security(update, context)
    elif data == "assassination":
        await assassination(update, context)
    elif data == "nuclear_sabotage":
        await nuclear_sabotage(update, context)
    elif data == "sabotage_npc":
        await sabotage_npc_menu(update, context)
    elif data == "sabotage_user":
        await sabotage_user_menu(update, context)
    elif data.startswith("sabotage_target_npc_"):
        npc_id = int(data[len("sabotage_target_npc_"):])
        await execute_sabotage_npc(update, context, npc_id)
    elif data.startswith("sabotage_target_user_"):
        target_id = int(data[len("sabotage_target_user_"):])
        await execute_sabotage_user(update, context, target_id)
    elif data == "pending_attacks":
        await query.answer("⏳ حملات در راه در بخش نظامی نمایش داده می‌شوند!", show_alert=True)
    elif data == "admin":
        await admin_panel(update, context)
    elif data == "admin_stats":
        await admin_stats(update, context)
    elif data == "admin_users":
        await admin_users(update, context)
    elif data == "admin_npcs":
        await admin_npcs(update, context)
    elif data == "admin_logs":
        await admin_logs(update, context)
    elif data == "admin_add_gold":
        await admin_add_gold(update, context)
    elif data == "admin_add_oil":
        await admin_add_oil(update, context)
    elif data == "admin_vip":
        await admin_vip(update, context)
    elif data == "admin_ban":
        await admin_ban(update, context)
    elif data == "admin_add_country":
        await admin_add_country(update, context)
    elif data == "admin_getdb":
        await admin_getdb(update, context)
    elif data == "admin_upload_db":
        await admin_upload_db(update, context)
    elif data == "admin_channels":
        await admin_channels(update, context)
    elif data == "admin_add_channel":
        await admin_add_channel(update, context)
    elif data == "admin_remove_channel":
        await admin_remove_channel(update, context)
    elif data == "admin_coupons":
        await admin_coupons(update, context)
    elif data == "admin_create_coupon":
        await admin_create_coupon(update, context)
    elif data == "admin_global_gold":
        await admin_global_gold(update, context)
    elif data == "admin_global_oil":
        await admin_global_oil(update, context)
    elif data == "admin_add_admin":
        await admin_add_admin(update, context)
    elif data == "admin_broadcast":
        await admin_broadcast(update, context)
    elif data == "admin_list_admins":
        await admin_list_admins(update, context)
    elif data.startswith("admin_perm_toggle_"):
        rest = data[len("admin_perm_toggle_"):]
        target_str, perm_key = rest.split("_", 1)
        await admin_perm_toggle(update, context, int(target_str), perm_key)
    elif data.startswith("admin_perm_menu_"):
        target_id = int(data[len("admin_perm_menu_"):])
        await admin_perm_menu(update, context, target_id)
    elif data.startswith("admin_remove_admin_"):
        target_id = int(data[len("admin_remove_admin_"):])
        await admin_remove_admin_action(update, context, target_id)
    else:
        await query.edit_message_text("❌ این گزینه در حال توسعه است.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]]))

# ========== Text Handler ==========
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user_id = update.effective_user.id
    waiting = context.user_data.get('waiting_for')

    if not (waiting and str(waiting).startswith('admin_')):
        if not await enforce_channel_membership(update, context):
            return

    if waiting == 'transfer_amount':
        await receive_transfer_amount(update, context)
    elif waiting == 'bet_amount':
        await receive_bet_amount(update, context)
    elif waiting == 'clan_name':
        await receive_clan_name(update, context)
    elif waiting == 'duel_opponent':
        await receive_duel_opponent(update, context)
    elif waiting == 'coupon_code':
        code = update.message.text.strip()
        reply = await redeem_coupon(user_id, code)
        await update.message.reply_text(reply)
        context.user_data['waiting_for'] = None
    elif waiting == 'peace_offer':
        try:
            target_id = int(update.message.text)
            target = get_user(target_id)
            if not target:
                await update.message.reply_text("❌ کاربر یافت نشد!")
                return
            if has_peace_treaty(user_id, target_id):
                await update.message.reply_text("🕊️ قبلاً پیمان صلح دارید!")
                return
            offers = target.get("peace_offers", {})
            user_obj = get_user(user_id)
            offers[str(user_id)] = user_obj["country_name"]
            update_user(target_id, peace_offers=offers)
            await update.message.reply_text(f"🕊️ پیشنهاد صلح به {target['country_name']} ارسال شد!")
            try:
                await context.bot.send_message(target_id, f"🕊️ {user_obj['country_name']} برای شما پیشنهاد صلح فرستاد!\nدر بخش سیاسی → پیمان صلح → دریافت‌ها آن را ببینید.")
            except:
                pass
        except:
            await update.message.reply_text("❌ آیدی عددی معتبر وارد کنید!")
        context.user_data['waiting_for'] = None
    elif waiting == 'official_statement':
        text = update.message.text.strip()
        if len(text) > 500:
            await update.message.reply_text("❌ حداکثر ۵۰۰ کاراکتر!")
            return
        user = get_user(user_id)
        conn = db_connect()
        c = conn.cursor()
        c.execute('INSERT INTO statements (user_id, country_name, text, created_at) VALUES (?, ?, ?, ?)',
                  (user_id, user["country_name"], text, int(time.time())))
        conn.commit()
        conn.close()
        await update.message.reply_text("📢 بیانیه رسمی ثبت شد!")
        context.user_data['waiting_for'] = None
    elif waiting == 'secret_chat':
        try:
            parts = update.message.text.split("|")
            target_id = int(parts[0].strip())
            msg = parts[1].strip()
            target = get_user(target_id)
            if not target:
                await update.message.reply_text("❌ کاربر یافت نشد!")
                return
            conn = db_connect()
            c = conn.cursor()
            c.execute('INSERT INTO secret_messages (sender_id, receiver_id, text, created_at) VALUES (?, ?, ?, ?)',
                      (user_id, target_id, msg, int(time.time())))
            conn.commit()
            conn.close()
            await update.message.reply_text("🕊️ پیام محرمانه ارسال شد!")
            try:
                await context.bot.send_message(target_id, f"🕊️ پیام محرمانه جدید دارید!\n📨 {msg}\n\n🔒 فرستنده ناشناس است.")
            except:
                pass
        except:
            await update.message.reply_text("❌ فرمت اشتباه!\nمثال: 123456789 | پیام شما...")
        context.user_data['waiting_for'] = None
    elif waiting == 'assassination_target':
        try:
            target_id = int(update.message.text)
            target = get_user(target_id)
            if not target:
                await update.message.reply_text("❌ کاربر یافت نشد!")
                return
            user = get_user(user_id)
            cost = 50000
            if user["gold"] < cost:
                await update.message.reply_text("طلای کافی ندارید!")
                return
            if random.random() < (target.get("terror_resistance", 0) / 100):
                await update.message.reply_text(f"❌ ترور ناموفق! {target['country_name']} امنیت قوی دارد.")
            else:
                damage = int(target["gold"] * 0.2)
                update_user(user_id, gold=user["gold"] - cost)
                update_user(target_id, gold=max(0, target["gold"] - damage))
                await update.message.reply_text(f"🗡️ ترور موفق!\n💰 {damage:,} طلا به {target['country_name']} آسیب زدید.")
                try:
                    await context.bot.send_message(target_id, f"🗡️ ترور نافرجام!\n💰 {damage:,} طلا از دست دادید!")
                except:
                    pass
        except:
            await update.message.reply_text("❌ آیدی عددی معتبر وارد کنید!")
        context.user_data['waiting_for'] = None
    elif waiting == 'bank_deposit':
        try:
            amount = int(update.message.text)
            user = get_user(user_id)
            if amount <= 0 or amount > user["gold"]:
                await update.message.reply_text("❌ مقدار نامعتبر!")
                return
            update_user(user_id, gold=user["gold"] - amount, bank_gold=user.get("bank_gold", 0) + amount)
            await update.message.reply_text(f"✅ {amount:,} طلا به بانک منتقل شد!")
        except:
            await update.message.reply_text("❌ عدد معتبر وارد کنید!")
        context.user_data['waiting_for'] = None
    elif waiting == 'bank_withdraw':
        try:
            amount = int(update.message.text)
            user = get_user(user_id)
            if amount <= 0 or amount > user.get("bank_gold", 0):
                await update.message.reply_text("❌ مقدار نامعتبر!")
                return
            update_user(user_id, gold=user["gold"] + amount, bank_gold=user.get("bank_gold", 0) - amount)
            await update.message.reply_text(f"✅ {amount:,} طلا از بانک برداشت شد!")
        except:
            await update.message.reply_text("❌ عدد معتبر وارد کنید!")
        context.user_data['waiting_for'] = None
    elif waiting in ['admin_gold', 'admin_oil', 'admin_vip', 'admin_ban', 'admin_add_country',
                     'admin_add_channel', 'admin_remove_channel', 'admin_create_coupon',
                     'admin_global_gold', 'admin_global_oil', 'admin_add_admin', 'admin_broadcast']:
        await admin_text_handler(update, context)
    else:
        await update.message.reply_text("برای دیدن منو /start را بزنید.")

# ========== Admin Text Handler ==========
async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    waiting = context.user_data.get('waiting_for')
    if waiting == 'admin_gold':
        try:
            parts = update.message.text.split()
            target_id = int(parts[0])
            amount = int(parts[1])
        except:
            await update.message.reply_text("❌ فرمت اشتباه! مثال: 123456789 5000")
            return
        user = get_user(target_id)
        if not user:
            await update.message.reply_text("❌ کاربر یافت نشد!")
            return
        update_user(target_id, gold=user["gold"] + amount)
        await update.message.reply_text(f"✅ {amount:,} طلا به {user['country_name']} اضافه شد!")
        try:
            await context.bot.send_message(target_id, f"💰 {amount:,} طلا به شما اضافه شد!")
        except Exception:
            pass
        context.user_data['waiting_for'] = None
    elif waiting == 'admin_oil':
        try:
            parts = update.message.text.split()
            target_id = int(parts[0])
            amount = int(parts[1])
        except:
            await update.message.reply_text("❌ فرمت اشتباه! مثال: 123456789 500")
            return
        user = get_user(target_id)
        if not user:
            await update.message.reply_text("❌ کاربر یافت نشد!")
            return
        update_user(target_id, oil=user["oil"] + amount)
        await update.message.reply_text(f"✅ {amount} نفت به {user['country_name']} اضافه شد!")
        try:
            await context.bot.send_message(target_id, f"🛢️ {amount} نفت به شما اضافه شد!")
        except Exception:
            pass
        context.user_data['waiting_for'] = None
    elif waiting == 'admin_vip':
        try:
            target_id = int(update.message.text)
        except:
            await update.message.reply_text("❌ آیدی عددی معتبر وارد کنید!")
            return
        user = get_user(target_id)
        if not user:
            await update.message.reply_text("❌ کاربر یافت نشد!")
            return
        update_user(target_id, is_vip=True)
        await update.message.reply_text(f"✅ کاربر {user['country_name']} VIP شد!")
        try:
            await context.bot.send_message(target_id, "👑 تبریک! شما توسط ادمین VIP شدید!")
        except Exception:
            pass
        context.user_data['waiting_for'] = None
    elif waiting == 'admin_ban':
        try:
            target_id = int(update.message.text)
        except:
            await update.message.reply_text("❌ آیدی عددی معتبر وارد کنید!")
            return
        user = get_user(target_id)
        if not user:
            await update.message.reply_text("❌ کاربر یافت نشد!")
            return
        update_user(target_id, is_banned=True)
        await update.message.reply_text(f"🚫 کاربر {user['country_name']} بن شد!")
        context.user_data['waiting_for'] = None
    elif waiting == 'admin_add_country':
        try:
            parts = update.message.text.split('|')
            name = parts[0].strip()
            gold = int(parts[1].strip())
            oil = int(parts[2].strip())
            army = int(parts[3].strip())
        except:
            await update.message.reply_text("❌ فرمت اشتباه! مثال: 🇩🇪 آلمان | 5000 | 2000 | 10")
            return
        conn = db_connect()
        c = conn.cursor()
        c.execute('INSERT INTO npc_countries (name, gold, oil, army, equipment, defense_power, share_price) VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (name, gold, oil, army, json.dumps(DEFAULT_EQUIPMENT), 5, 100))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ کشور {name} اضافه شد!")
        context.user_data['waiting_for'] = None
    elif waiting == 'admin_add_channel':
        raw = update.message.text.strip()
        # هم فرمت ساده (فقط @channel) و هم فرمت قدیمی (آیدی | نام | لینک) پشتیبانی می‌شود
        parts = [p.strip() for p in raw.split('|')]
        channel_id = parts[0]
        if channel_id.startswith("https://t.me/") or channel_id.startswith("t.me/"):
            uname = channel_id.split("t.me/")[-1].strip("/")
            channel_id = f"@{uname}"
        elif not channel_id.startswith("@") and not channel_id.lstrip("-").isdigit():
            channel_id = f"@{channel_id}"

        # تلاش برای گرفتن خودکار اطلاعات کانال/گروه از تلگرام
        try:
            chat = await context.bot.get_chat(channel_id)
        except Exception as e:
            await update.message.reply_text(
                f"❌ ربات نتونست این کانال/گروه رو پیدا کنه.\n"
                f"مطمئن شو آیدی درسته و ربات قبلاً به عنوان ادمین به «{channel_id}» اضافه شده.\n\nخطا: {e}"
            )
            return

        # چک اینکه ربات واقعاً توی کانال ادمینه (برای اینکه بعداً بتونه عضویت کاربرها رو چک کنه)
        try:
            bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
            if bot_member.status not in ["administrator", "creator"]:
                await update.message.reply_text(
                    f"⚠️ ربات توی «{chat.title}» عضو هست ولی ادمین نیست، پس نمی‌تونه عضویت کاربرها رو چک کنه.\n"
                    f"لطفاً اول ربات رو ادمین کن، بعد دوباره امتحان کن."
                )
                return
        except Exception as e:
            await update.message.reply_text(f"❌ ربات به «{chat.title}» دسترسی نداره. اول ربات رو ادمین اون کانال/گروه کن.\n\nخطا: {e}")
            return

        channel_name = parts[1] if len(parts) > 1 and parts[1] else (chat.title or channel_id)
        if len(parts) > 2 and parts[2]:
            invite_link = parts[2]
        elif chat.username:
            invite_link = f"https://t.me/{chat.username}"
        else:
            try:
                invite_link = chat.invite_link or await context.bot.export_chat_invite_link(chat.id)
            except Exception:
                invite_link = ""

        add_required_channel(str(chat.id), channel_name, invite_link, user_id)
        await update.message.reply_text(f"✅ «{channel_name}» به لیست عضویت اجباری اضافه شد و همین الان فعال شد!")
        context.user_data['waiting_for'] = None
    elif waiting == 'admin_remove_channel':
        channel_id = update.message.text.strip()
        remove_required_channel(channel_id)
        await update.message.reply_text(f"✅ کانال {channel_id} حذف شد!")
        context.user_data['waiting_for'] = None
    elif waiting == 'admin_create_coupon':
        try:
            parts = update.message.text.split('|')
            code = parts[0].strip()
            ctype = parts[1].strip()
            amount = int(parts[2].strip())
            max_uses = int(parts[3].strip())
            expires_hours = int(parts[4].strip())
        except:
            await update.message.reply_text("❌ فرمت اشتباه! مثال: WELCOME | gold | 1000 | 100 | 24")
            return
        create_coupon(code, ctype, amount, max_uses, expires_hours, user_id)
        await update.message.reply_text(f"✅ کوپن {code} ساخته شد!")
        context.user_data['waiting_for'] = None
    elif waiting == 'admin_global_gold':
        try:
            amount = int(update.message.text)
        except:
            await update.message.reply_text("❌ عدد معتبر وارد کنید!")
            return
        conn = db_connect()
        c = conn.cursor()
        c.execute('UPDATE users SET gold = gold + ?', (amount,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ {amount:,} طلا به همه اضافه شد! در حال اطلاع‌رسانی به کاربران...")
        all_users = get_all_users()
        sent = 0
        for u in all_users:
            try:
                await context.bot.send_message(u["user_id"], f"🎁 {amount:,} طلای همگانی به همه اضافه شد!")
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                continue
        await update.message.reply_text(f"📨 پیام اطلاع‌رسانی به {sent} کاربر ارسال شد.")
        context.user_data['waiting_for'] = None
    elif waiting == 'admin_global_oil':
        try:
            amount = int(update.message.text)
        except:
            await update.message.reply_text("❌ عدد معتبر وارد کنید!")
            return
        conn = db_connect()
        c = conn.cursor()
        c.execute('UPDATE users SET oil = oil + ?', (amount,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ {amount} نفت به همه اضافه شد! در حال اطلاع‌رسانی به کاربران...")
        all_users = get_all_users()
        sent = 0
        for u in all_users:
            try:
                await context.bot.send_message(u["user_id"], f"🎁 {amount} نفت همگانی به همه اضافه شد!")
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                continue
        await update.message.reply_text(f"📨 پیام اطلاع‌رسانی به {sent} کاربر ارسال شد.")
        context.user_data['waiting_for'] = None
    elif waiting == 'admin_add_admin':
        try:
            target_id = int(update.message.text)
        except:
            await update.message.reply_text("❌ آیدی عددی معتبر وارد کنید!")
            return
        context.user_data['waiting_for'] = None
        try:
            add_admin(target_id, user_id)
            await update.message.reply_text(
                f"✅ کاربر {target_id} ادمین شد!\n"
                f"🔐 الان دسترسی‌های او را مشخص کنید (پیش‌فرض: هیچ دسترسی):",
                reply_markup=build_admin_permissions_keyboard(target_id)
            )
        except Exception as e:
            logger.exception("admin_add_admin failed")
            await update.message.reply_text(f"❌ خطا در ادمین کردن کاربر: {e}")
    elif waiting == 'admin_broadcast':
        context.user_data['waiting_for'] = None
        broadcast_text = update.message.text
        all_users = get_all_users()
        status_msg = await update.message.reply_text(f"📣 در حال ارسال به {len(all_users)} کاربر...")
        sent = 0
        for u in all_users:
            try:
                await context.bot.send_message(u["user_id"], broadcast_text)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                pass
        await status_msg.edit_text(f"✅ پیام به {sent} کاربر ربات ارسال شد!")

# ========== Admin Panel Functions ==========
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        if update.message:
            await update.message.reply_text("🚫 شما دسترسی ادمین ندارید!")
        else:
            await update.callback_query.answer("🚫 دسترسی ندارید!", show_alert=True)
        return
    users = get_all_users()
    npcs = get_npc_countries()
    channels = get_required_channels()
    keyboard = [
        [InlineKeyboardButton("📊 آمار کاربران", style="primary", callback_data="admin_stats"),
         InlineKeyboardButton("💰 افزودن طلا", style="success", callback_data="admin_add_gold")],
        [InlineKeyboardButton("🛢️ افزودن نفت", style="success", callback_data="admin_add_oil"),
         InlineKeyboardButton("👑 اعطای VIP", style="success", callback_data="admin_vip")],
        [InlineKeyboardButton("🚫 بن کاربر", style="danger", callback_data="admin_ban"),
         InlineKeyboardButton("📋 لیست کاربران", style="primary", callback_data="admin_users")],
        [InlineKeyboardButton("🌍 لیست NPC ها", style="primary", callback_data="admin_npcs"),
         InlineKeyboardButton("➕ اضافه کردن کشور", style="primary", callback_data="admin_add_country")],
        [InlineKeyboardButton("📊 گزارش حملات", style="primary", callback_data="admin_logs"),
         InlineKeyboardButton("📁 دریافت دیتابیس", style="success", callback_data="admin_getdb")],
        [InlineKeyboardButton("📤 افزودن دیتابیس", style="primary", callback_data="admin_upload_db")],
        [InlineKeyboardButton("📢 کانال اجباری", style="primary", callback_data="admin_channels"),
         InlineKeyboardButton("🎟️ مدیریت کوپن", style="primary", callback_data="admin_coupons")],
        [InlineKeyboardButton("💰 طلای همگانی", style="primary", callback_data="admin_global_gold"),
         InlineKeyboardButton("🛢️ نفت همگانی", style="primary", callback_data="admin_global_oil")],
        [InlineKeyboardButton("➕ افزودن ادمین", style="success", callback_data="admin_add_admin"),
         InlineKeyboardButton("📋 لیست ادمین‌ها", style="primary", callback_data="admin_list_admins")],
        [InlineKeyboardButton("📣 پیام همگانی", style="primary", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="menu")]
    ]
    text = (f"👑 پنل مدیریت\n━━━━━━━━━━━━━━━━━━━━\n👥 کاربران: {len(users)}\n🤖 NPC ها: {len(npcs)}\n📢 کانال‌ها: {len(channels)}\n━━━━━━━━━━━━━━━━━━━━\n📋 انتخاب کنید:")
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    total_users = c.fetchone()[0]
    c.execute('SELECT SUM(gold) FROM users')
    total_gold = c.fetchone()[0] or 0
    c.execute('SELECT COUNT(*) FROM users WHERE is_vip = 1')
    total_vip = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM attack_logs')
    total_attacks = c.fetchone()[0]
    conn.close()
    await query.edit_message_text(
        f"📊 آمار ربات\n━━━━━━━━━━━━━━━━━━━━\n👥 کل کاربران: {total_users}\n💰 کل طلا: {total_gold:,}\n👑 VIP ها: {total_vip}\n⚔️ کل حملات: {total_attacks}\n━━━━━━━━━━━━━━━━━━━━",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="admin")]])
    )

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    users = get_all_users()
    text = "🌍 لیست کاربران\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, user in enumerate(users[:20], 1):
        vip = " 👑" if user["is_vip"] else ""
        clan = f" [{user['clan']}]" if user['clan'] else ""
        text += f"{i}. {user['name']}{vip}{clan}\n💰 طلا: {user['gold']:,} | 🏆 برد: {user['wins']}\n━━━━━━━━━━━━━━━━━━━━\n"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="admin")]]))

async def admin_npcs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    npcs = get_npc_countries()
    text = "🤖 لیست NPC ها\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, npc in enumerate(npcs[:20], 1):
        text += f"{i}. {npc['name']}\n💰 طلا: {npc['gold']:,} | ⚔️ ارتش: {npc['army']}\n━━━━━━━━━━━━━━━━━━━━\n"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="admin")]]))

async def admin_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT attacker_name, defender_name, result, gold_stolen, timestamp FROM attack_logs ORDER BY timestamp DESC LIMIT 10')
    rows = c.fetchall()
    conn.close()
    text = "📊 آخرین گزارش‌های حمله\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for row in rows:
        time_str = datetime.fromtimestamp(row[4]).strftime("%H:%M")
        text += f"🕐 {time_str} - {row[0]} → {row[1]}\n📊 نتیجه: {row[2]} | 💰 غنیمت: {row[3]}\n━━━━━━━━━━━━━━━━━━━━\n"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="admin")]]))

async def admin_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    channels = get_required_channels()
    text = "📢 مدیریت کانال‌ها\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for ch in channels:
        text += f"• {ch['channel_name']} ({ch['channel_id']})\n"
    keyboard = [
        [InlineKeyboardButton("➕ افزودن کانال", style="primary", callback_data="admin_add_channel")],
        [InlineKeyboardButton("❌ حذف کانال", style="danger", callback_data="admin_remove_channel")],
        [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="admin")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📢 فقط آیدی کانال یا گروه رو با @ بفرست (یا لینک t.me یا آیدی عددی -100...).\n"
        "مثال: @mychannel\n\n"
        "⚠️ قبلش ربات رو ادمین همون کانال/گروه کن، وگرنه نمی‌تونه عضویت رو چک کنه.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="admin_channels")]]))
    context.user_data['waiting_for'] = 'admin_add_channel'

async def admin_remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ آیدی کانال را برای حذف وارد کنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="admin_channels")]]))
    context.user_data['waiting_for'] = 'admin_remove_channel'

async def admin_coupons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT code, type, amount, max_uses, used_count, expires_at FROM coupons ORDER BY created_at DESC LIMIT 10')
    rows = c.fetchall()
    conn.close()
    text = "🎟️ مدیریت کوپن‌ها\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for row in rows:
        now = int(time.time())
        expired = "❌ منقضی" if row[5] > 0 and row[5] < now else "✅ فعال"
        text += f"🎟️ {row[0]} | {row[1]} | {row[2]:,}\n📊 {row[4]}/{row[3]} استفاده | {expired}\n━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = [
        [InlineKeyboardButton("➕ ساخت کوپن", style="success", callback_data="admin_create_coupon")],
        [InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="admin")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_create_coupon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🎟️ فرمت: کد | نوع(gold/oil/vip) | مقدار | حداکثر استفاده | ساعت اعتبار\nمثال: WELCOME | gold | 1000 | 100 | 24",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="admin_coupons")]]))
    context.user_data['waiting_for'] = 'admin_create_coupon'

async def admin_global_gold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("💰 مقدار طلای همگانی را وارد کنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="admin")]]))
    context.user_data['waiting_for'] = 'admin_global_gold'

async def admin_global_oil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🛢️ مقدار نفت همگانی را وارد کنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="admin")]]))
    context.user_data['waiting_for'] = 'admin_global_oil'

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📣 متن پیام همگانی را وارد کنید:\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ این پیام برای همه‌ی کاربران ربات ارسال می‌شود.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="admin")]])
    )
    context.user_data['waiting_for'] = 'admin_broadcast'

async def admin_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("➕ آیدی عددی کاربر جدید برای ادمین شدن:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="admin")]]))
    context.user_data['waiting_for'] = 'admin_add_admin'

async def admin_list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _render_admin_list(query)

async def _render_admin_list(query):
    admins = get_admins()
    text = "📋 لیست ادمین‌ها\n━━━━━━━━━━━━━━━━━━━━\n"
    text += f"• ادمین اصلی: {ADMIN_IDS[0]} (دسترسی کامل)\n"
    conn = db_connect()
    c = conn.cursor()
    keyboard = []
    for admin_id in admins:
        if admin_id not in ADMIN_IDS:
            c.execute('SELECT added_at FROM admins WHERE user_id = ?', (admin_id,))
            row = c.fetchone()
            if row:
                date_str = datetime.fromtimestamp(row[0]).strftime("%Y-%m-%d")
                text += f"• {admin_id} (اضافه شده: {date_str})\n"
                keyboard.append([
                    InlineKeyboardButton(f"🔐 دسترسی‌های {admin_id}", style="primary", callback_data=f"admin_perm_menu_{admin_id}"),
                    InlineKeyboardButton("🗑 حذف کامل", style="danger", callback_data=f"admin_remove_admin_{admin_id}"),
                ])
    conn.close()
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", style="primary", callback_data="admin")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_perm_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, target_id):
    query = update.callback_query
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("🚫 فقط ادمین اصلی می‌تواند دسترسی‌ها را تغییر دهد!", show_alert=True)
        return
    await query.answer()
    try:
        await query.edit_message_text(
            f"🔐 دسترسی‌های ادمین {target_id}\n━━━━━━━━━━━━━━━━━━━━\nروی هر گزینه بزنید تا فعال (✅) یا غیرفعال (❌) شود:",
            reply_markup=build_admin_permissions_keyboard(target_id)
        )
    except Exception as e:
        logger.exception("admin_perm_menu failed")
        await context.bot.send_message(query.from_user.id, f"❌ خطا در باز کردن منوی دسترسی‌ها: {e}")

async def admin_perm_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, target_id, perm_key):
    query = update.callback_query
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("🚫 فقط ادمین اصلی می‌تواند دسترسی‌ها را تغییر دهد!", show_alert=True)
        return
    if perm_key not in ADMIN_PERMISSIONS:
        await query.answer("❌ دسترسی نامعتبر!", show_alert=True)
        return
    try:
        current = get_admin_permissions(target_id)
        enable = perm_key not in current
        set_admin_permission(target_id, perm_key, enable)
        await query.answer("✅ فعال شد" if enable else "❌ غیرفعال شد")
        await query.edit_message_text(
            f"🔐 دسترسی‌های ادمین {target_id}\n━━━━━━━━━━━━━━━━━━━━\nروی هر گزینه بزنید تا فعال (✅) یا غیرفعال (❌) شود:",
            reply_markup=build_admin_permissions_keyboard(target_id)
        )
    except Exception as e:
        logger.exception("admin_perm_toggle failed")
        try:
            await query.answer(f"❌ خطا: {e}", show_alert=True)
        except Exception:
            pass
        await context.bot.send_message(query.from_user.id, f"❌ خطا در تغییر دسترسی: {e}")

async def admin_remove_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE, target_id):
    """حذف کامل یک ادمین (قطع کلی دسترسی، نه فقط یک مجوز خاص).
    قبلاً remove_admin_db تعریف شده بود ولی به هیچ دکمه‌ای وصل نبود."""
    query = update.callback_query
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("🚫 فقط ادمین اصلی می‌تواند ادمین حذف کند!", show_alert=True)
        return
    if target_id in ADMIN_IDS:
        await query.answer("🚫 ادمین اصلی قابل حذف نیست!", show_alert=True)
        return
    try:
        remove_admin_db(target_id)
        conn = db_connect()
        c = conn.cursor()
        c.execute('DELETE FROM admin_permissions WHERE user_id = ?', (target_id,))
        conn.commit()
        conn.close()
        await query.answer("✅ ادمین حذف شد")
        await _render_admin_list(query)
    except Exception as e:
        logger.exception("admin_remove_admin_action failed")
        await query.answer(f"❌ خطا: {e}", show_alert=True)

async def admin_getdb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not os.path.exists(DB_NAME):
        await query.edit_message_text("❌ فایل دیتابیس یافت نشد!")
        return
    try:
        await context.bot.send_document(chat_id=query.from_user.id, document=open(DB_NAME, 'rb'),
            caption="📁 فایل دیتابیس game.db\n━━━━━━━━━━━━━━━━━━━━\n✅ این فایل را در سرور جدید قرار دهید.")
        await query.edit_message_text("✅ فایل دیتابیس ارسال شد!")
    except Exception as e:
        await query.edit_message_text(f"❌ خطا در ارسال: {e}")

async def admin_upload_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📤 فایل دیتابیس (.db) را همینجا در همین چت ارسال کنید.\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ این فایل جایگزین دیتابیس فعلی می‌شود!\n"
        "💾 یک نسخه پشتیبان از دیتابیس فعلی خودکار نگه‌داری می‌شود.\n"
        "🔄 پس از آپلود، برای اعمال کامل تغییرات، ربات را ری‌استارت کنید.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="admin")]])
    )
    context.user_data['waiting_for'] = 'admin_upload_db'

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user_id = update.effective_user.id
    waiting = context.user_data.get('waiting_for')
    if waiting != 'admin_upload_db':
        return
    if not is_admin(user_id):
        return
    if not has_admin_permission(user_id, "uploaddb"):
        await update.message.reply_text("🚫 شما به این بخش دسترسی ندارید!")
        return
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(('.db', '.sqlite', '.sqlite3')):
        await update.message.reply_text("❌ لطفاً یک فایل دیتابیس معتبر (.db) ارسال کنید.")
        return
    status_msg = await update.message.reply_text("⏳ در حال دریافت و بررسی فایل...")
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        temp_path = f"{DB_NAME}.uploading"
        await tg_file.download_to_drive(temp_path)

        # بررسی معتبر بودن فایل و تطابق ساختار جدول users با ساختار مورد انتظار ربات
        # (این کار در یک ترد جدا انجام می‌شود تا حلقه رویداد ربات در این مدت فریز نشود)
        def validate_and_check_schema():
            test_conn = sqlite3.connect(temp_path)
            try:
                test_conn.execute("SELECT name FROM sqlite_master LIMIT 1")
                cols = [r[1] for r in test_conn.execute("PRAGMA table_info(users)").fetchall()]
            finally:
                test_conn.close()
            return cols

        try:
            new_cols = await asyncio.to_thread(validate_and_check_schema)
        except Exception:
            os.remove(temp_path)
            await status_msg.edit_text("❌ فایل ارسالی یک دیتابیس SQLite معتبر نیست!")
            return

        expected_cols = None
        if os.path.exists(DB_NAME):
            def get_current_cols():
                c = sqlite3.connect(DB_NAME)
                try:
                    return [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
                finally:
                    c.close()
            expected_cols = await asyncio.to_thread(get_current_cols)

        if expected_cols and set(new_cols) != set(expected_cols):
            missing = set(expected_cols) - set(new_cols)
            extra = set(new_cols) - set(expected_cols)
            os.remove(temp_path)
            warn = "⚠️ ساختار جدول کاربران این دیتابیس با ربات فعلی یکی نیست و جایگزینی آن باعث خطا و قفل‌شدن مکرر دیتابیس (کند شدن کل ربات) می‌شود.\n"
            if missing:
                warn += f"ستون‌های کم: {', '.join(sorted(missing))}\n"
            if extra:
                warn += f"ستون‌های اضافه: {', '.join(sorted(extra))}\n"
            warn += "لطفاً یک بکاپ سازگار با نسخه فعلی ربات ارسال کنید."
            await status_msg.edit_text(warn)
            return

        # بکاپ‌گیری از دیتابیس فعلی (روی ترد جدا، تا event loop مسدود نشود)
        backup_name = None
        if os.path.exists(DB_NAME):
            backup_name = f"{DB_NAME}.backup_{int(time.time())}"
            await asyncio.to_thread(shutil.copy, DB_NAME, backup_name)

        os.replace(temp_path, DB_NAME)
        # نکته‌ی مهم: init_db() فقط یک‌بار موقع استارت ربات اجرا می‌شود. اگر دیتابیس
        # جایگزین‌شده جدول‌هایی مثل admins/admin_permissions را نداشته باشد (بکاپ قدیمی‌تر
        # از نسخه فعلی ربات)، همون لحظه دوباره init_db() را صدا می‌زنیم تا جدول‌های
        # کم را با CREATE TABLE IF NOT EXISTS بسازد؛ در غیر این صورت تا ری‌استارت بعدی
        # خطای "no such table" می‌داد بدون این‌که کاربر بفهمد چرا.
        init_db()
        context.user_data['waiting_for'] = None
        msg = "✅ دیتابیس با موفقیت جایگزین شد!\n"
        if backup_name:
            msg += f"💾 نسخه قبلی ذخیره شد: {os.path.basename(backup_name)}\n"
        msg += "🔄 جدول‌های جدید (در صورت نیاز) هم به‌روزرسانی شدند؛ نیازی به ری‌استارت نیست."
        await status_msg.edit_text(msg)
    except Exception as e:
        await status_msg.edit_text(f"❌ خطا در دریافت فایل: {e}")

async def getdb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 شما دسترسی ندارید!")
        return
    if not os.path.exists(DB_NAME):
        await update.message.reply_text("❌ فایل دیتابیس یافت نشد!")
        return
    try:
        await context.bot.send_document(chat_id=user_id, document=open(DB_NAME, 'rb'),
            caption="📁 فایل دیتابیس game.db")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}")

async def admin_add_gold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("💰 فرمت: آیدی عددی کاربر | مقدار طلا\nمثال: 123456789 5000", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="admin")]]))
    context.user_data['waiting_for'] = 'admin_gold'

async def admin_add_oil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🛢️ فرمت: آیدی عددی کاربر | مقدار نفت\nمثال: 123456789 500", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="admin")]]))
    context.user_data['waiting_for'] = 'admin_oil'

async def admin_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("👑 آیدی عددی کاربر را برای اعطای VIP وارد کنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="admin")]]))
    context.user_data['waiting_for'] = 'admin_vip'

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🚫 آیدی عددی کاربر را برای بن کردن وارد کنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="admin")]]))
    context.user_data['waiting_for'] = 'admin_ban'

async def admin_add_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("➕ فرمت: نام | طلا | نفت | ارتش\nمثال: 🇩🇪 آلمان | 5000 | 2000 | 10", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="admin")]]))
    context.user_data['waiting_for'] = 'admin_add_country'

# ========== Coupon & Referral ==========
async def redeem_coupon(user_id, code) -> str:
    """Validates and applies a coupon code for user_id. Returns the reply text."""
    user = get_user(user_id)
    if not user:
        return "ابتدا /start کنید!"
    coupon = get_coupon(code)
    if not coupon:
        return "❌ کد کوپن نامعتبر است!"
    now = int(time.time())
    if coupon["expires_at"] > 0 and coupon["expires_at"] < now:
        return "❌ این کوپن منقضی شده است!"
    if coupon["used_count"] >= coupon["max_uses"]:
        return "❌ ظرفیت استفاده تمام شده!"
    if has_used_coupon(coupon["id"], user_id):
        return "❌ شما قبلاً از این کوپن استفاده کرده‌اید!"

    use_coupon(coupon["id"], user_id)
    if coupon["type"] == "gold":
        update_user(user_id, gold=user["gold"] + coupon["amount"])
        return f"✅ کوپن با موفقیت استفاده شد!\n💰 {coupon['amount']:,} طلا دریافت کردید!"
    elif coupon["type"] == "oil":
        update_user(user_id, oil=user["oil"] + coupon["amount"])
        return f"✅ کوپن با موفقیت استفاده شد!\n🛢️ {coupon['amount']} نفت دریافت کردید!"
    elif coupon["type"] == "vip":
        update_user(user_id, is_vip=True)
        return "✅ کوپن با موفقیت استفاده شد!\n👑 شما VIP شدید!"
    return "✅ کوپن با موفقیت استفاده شد!"

async def coupon_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("ابتدا /start کنید!")
        return
    if not context.args:
        await update.message.reply_text("🎟️ لطفاً کد کوپن را وارد کنید:\nمثال: /coupon WELCOME")
        return
    code = context.args[0]
    reply = await redeem_coupon(user_id, code)
    await update.message.reply_text(reply)

async def enter_coupon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("ابتدا /start کنید")
        return
    await query.edit_message_text(
        "🎟️ کد کوپن خود را وارد کنید:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", style="primary", callback_data="economic_menu")]])
    )
    context.user_data['waiting_for'] = 'coupon_code'



async def start_with_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if args:
        try:
            referrer_id = int(args[0])
            if referrer_id != user_id and get_user(referrer_id):
                referrer = get_user(referrer_id)
                update_user(referrer_id, referrals=referrer.get("referrals", 0) + 1, gold=referrer["gold"] + 500, oil=referrer["oil"] + 200)
                equip = referrer["equipment"].copy()
                equip["soldiers"] = equip.get("soldiers", 0) + 2
                update_user(referrer_id, equipment=equip)
                update_user(user_id, referred_by=referrer_id, gold=1200)
                try:
                    await context.bot.send_message(referrer_id, f"🎉 {update.effective_user.first_name} با لینک شما عضو شد!\n💰 ۵۰۰ طلا | 🛢️ ۲۰۰ نفت | 🪖 ۲ سرباز")
                except:
                    pass
        except:
            pass
    return await start(update, context)

# ========== مدیریت خطاهای مخفی ==========
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """قبلاً هیچ error handler ای ثبت نشده بود، یعنی هر Exception داخل هندلرها
    (کلیک دکمه یا پیام متنی) کاملاً بی‌صدا قورت داده می‌شد: کاربر هیچ پیامی نمی‌دید
    و به نظر می‌رسید "هیچ اتفاقی نمی‌افته". این تابع خطا را در لاگ چاپ می‌کند و
    برای ادمین اصلی می‌فرستد تا دیگر هیچ خطایی گم نشود."""
    tb = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    logger.error("Unhandled exception:\n%s", tb)
    short_tb = tb[-1500:]
    try:
        await context.bot.send_message(
            ADMIN_IDS[0],
            f"❌ خطای برنامه رخ داد:\n\n<code>{short_tb}</code>",
            parse_mode="HTML"
        )
    except Exception:
        pass
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("❌ خطایی رخ داد! ادمین از این موضوع مطلع شد.")
    except Exception:
        pass

# ========== MAIN ==========
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_error_handler(error_handler)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_with_referral)],
        states={COUNTRY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_country_name)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("attack", lambda u,c: u.message.reply_text("⚔️ از منوی نظامی استفاده کنید!")))
    app.add_handler(CommandHandler("profile", lambda u,c: u.message.reply_text("🏳️ از منوی کشور من استفاده کنید!")))
    app.add_handler(CommandHandler("rank", lambda u,c: u.message.reply_text("🏆 از منوی رتبه‌بندی استفاده کنید!")))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("getdb", getdb_command))
    app.add_handler(CommandHandler("coupon", coupon_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL & ~filters.ChatType.CHANNEL, document_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.ChatType.CHANNEL, text_handler))
    print("🤖 ربات جنگ جهانی ریات راه‌اندازی شد!")
    app.run_polling()

if __name__ == "__main__":
    main()
