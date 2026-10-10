"""
Telegram Bot - Main File
Run: python main.py
"""
import sys
import types
import logging
import asyncio
import signal
from datetime import datetime

# ========== LOGGING ==========
logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("BomberBot")

# ========== CGI PATCH (for old PTB) ==========
if "cgi" not in sys.modules:
    class _CGI:
        def parse_multipart(self, *a, **k):
            return {}
        class FieldStorage:
            def __init__(self, *a, **k):
                self.value = None
            def __getattr__(self, name):
                return None
    _cgi = types.ModuleType("cgi")
    _cgi.parse_multipart = _CGI().parse_multipart
    _cgi.FieldStorage = _CGI.FieldStorage
    sys.modules["cgi"] = _cgi

# ========== IMPORTS ==========
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)
from aiohttp import web

from config import (
    BOT_TOKEN,
    OWNER_ID,
    ADMIN_IDS,
    WELCOME_IMAGE,
    PORT,
    WEBHOOK_URL,
    USE_WEBHOOK,
    PLANS,
    DATABASE_URL,
    SQLITE_DB_PATH,
)
from database import DatabaseStorage
from attack import AttackManager
from apis import ALL_APIS


# ============================================================
# GLOBAL OBJECTS
# ============================================================
db: DatabaseStorage = None
manager: AttackManager = None


def is_admin(uid):
    return uid == OWNER_ID or uid in ADMIN_IDS


# ============================================================
# KEYBOARDS
# ============================================================
def main_kb(user_id):
    kb = [
        [KeyboardButton("🚀 /mix"), KeyboardButton("📊 /status")],
        [KeyboardButton("👤 /account"), KeyboardButton("💳 /plan")],
        [KeyboardButton("🛡 /protect"), KeyboardButton("🔓 /unprotect")],
        [KeyboardButton("🔑 /redeem"), KeyboardButton("📩 /contact")],
        [KeyboardButton("❓ /help")],
    ]
    if is_admin(user_id):
        kb.append([KeyboardButton("👑 Admin")])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


async def multi_target_kb(user_id):
    max_t = await db.get_concurrent_limit(user_id)
    max_t = min(max_t, 10)
    btns = [
        [InlineKeyboardButton(f"🎯 {i} Target(s)", callback_data=f"targets_{i}")]
        for i in range(1, max_t + 1)
    ]
    btns.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_attack")])
    return InlineKeyboardMarkup(btns)


async def duration_kb(user_id):
    max_d = await db.get_max_duration(user_id)
    con = await db.get_concurrent_limit(user_id)
    btns = []
    row = []
    for m in [1, 5, 15, 30, 60, 120, 180, 300, 360, 480, 720]:
        if m <= max_d:
            label = f"{m}m" if m < 60 else f"{m // 60}h"
            row.append(InlineKeyboardButton(label, callback_data=f"dur_{m}"))
            if len(row) == 3:
                btns.append(row)
                row = []
    if row:
        btns.append(row)
    btns.append([InlineKeyboardButton(f"⚡ {con}x Concurrent", callback_data="info")])
    btns.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_attack")])
    return InlineKeyboardMarkup(btns)


# ============================================================
# CHANNEL CHECK
# ============================================================
async def check_channel_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_admin(uid):
        return True
    channel = await db.get_channel()
    if not channel:
        return True
    c = channel.strip()
    for pfx in ["https://", "http://", "t.me/"]:
        if c.startswith(pfx):
            c = c.replace(pfx, "", 1)
    c = c.lstrip("@").split("?")[0].split("/")[0].strip()
    if not c:
        return True
    try:
        m = await context.bot.get_chat_member(c, uid)
        if m.status in ("member", "administrator", "creator"):
            return True
    except Exception:
        pass

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{c}")]])
    msg = f"⛔ ACCESS DENIED\n\nJoin the channel first:\n👉 t.me/{c}\n\nThen click /start again."
    try:
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(msg, reply_markup=kb)
        else:
            await update.message.reply_text(msg, reply_markup=kb)
    except Exception:
        pass
    return False


# ============================================================
# BASIC HANDLERS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await check_channel_join(update, context):
        return

    if await db.is_banned(uid):
        await update.message.reply_text("🚫 You have been banned.")
        return

    await db.add_user(uid)
    caption = (
        f"🔥 Welcome to Premium Multi-Target Bomber\n\n"
        f"📡 Total APIs: {len(ALL_APIS)}\n"
        f"🎯 SMS + Call + WhatsApp\n\n"
        f"Use /help to see commands."
    )
    try:
        await update.message.reply_photo(
            WELCOME_IMAGE, caption=caption, reply_markup=main_kb(uid)
        )
    except Exception:
        await update.message.reply_text(caption, reply_markup=main_kb(uid))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_channel_join(update, context):
        return
    uid = update.effective_user.id
    msg = f"""ℹ️ HELP

🚀 User Commands
• /start – Main menu
• /mix – Start attack
• /status – Attack status
• /account – Your account
• /plan – View plans
• /redeem – Activate code
• /protect – Protect a number
• /unprotect – Remove protection
• /contact – Message admin
• /cancel – Cancel any action

📡 Total APIs: {len(ALL_APIS)}"""

    if is_admin(uid):
        msg += """

👑 ADMIN COMMANDS
• /giveplan <uid> <plan> <days>
• /removeplan <uid>
• /users [page] – List users
• /userinfo <uid>
• /genkey <days> <plan>
• /broadcast – Broadcast message
• /stats – Bot statistics
• /setchannel <@channel>
• /removechannel
• /ban <uid> [reason]
• /unban <uid>
• /banned
• /inbox
• /reply <uid> <msg>
• /checkapis
• /logs
"""

    await update.message.reply_text(msg, reply_markup=main_kb(uid))


# ============================================================
# USER COMMANDS
# ============================================================
async def mix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await check_channel_join(update, context):
        return
    if await db.is_banned(uid):
        await update.message.reply_text("🚫 You are banned.")
        return
    if not await db.is_premium(uid):
        await update.message.reply_text("⛔ Premium required. Use /plan or /redeem.")
        return
    if manager.is_attacking(uid):
        await update.message.reply_text("⚠️ Attack already running. Use /status.")
        return

    max_t = await db.get_concurrent_limit(uid)
    await update.message.reply_text(
        f"📞 Select number of targets (Max: {min(max_t, 10)}):",
        reply_markup=await multi_target_kb(uid),
    )
    context.user_data["waiting_for_target_count"] = True


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await check_channel_join(update, context):
        return

    info = manager.get_attack_info(uid)
    if info:
        left = max(0, int((info["end_time"] - datetime.now().timestamp()) / 60))
        await update.message.reply_text(
            f"🔥 ATTACK RUNNING\n\n"
            f"🎯 Targets: {', '.join(info['targets'])}\n"
            f"📊 Count: {len(info['targets'])}\n"
            f"⏳ Time left: {left} min",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🛑 STOP", callback_data="stop")]]
            ),
        )
    else:
        await update.message.reply_text("💤 No active attacks.")


async def account_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await check_channel_join(update, context):
        return
    plan = await db.get_plan_name(uid)
    exp = await db.get_expiry(uid)
    con = await db.get_concurrent_limit(uid)
    md = await db.get_max_duration(uid)
    await update.message.reply_text(
        f"👤 ACCOUNT\n\n"
        f"🆔 ID: {uid}\n"
        f"📋 Plan: {plan}\n"
        f"📅 Expiry: {exp}\n"
        f"⚡ Concurrent: {con}\n"
        f"⏰ Max duration: {md} min"
    )


async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_channel_join(update, context):
        return
    msg = "💳 AVAILABLE PLANS\n\n"
    for _, p in PLANS.items():
        msg += (
            f"🔹 {p['name']} — ₹{p['price']}\n"
            f"   • {p['days']} days\n"
            f"   • {p['concurrent']} concurrent\n"
            f"   • {p['max_duration']} min max\n\n"
        )
    msg += "💡 Use /redeem or /contact to buy"
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📩 Contact Admin", callback_data="contact_admin")]]
    )
    await update.message.reply_text(msg, reply_markup=kb)


async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_channel_join(update, context):
        return
    await update.message.reply_text("🔑 Send your code (Format: PREMIUM-XXXXXXXX):")
    context.user_data["waiting_for_redeem"] = True


async def protect_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await check_channel_join(update, context):
        return
    if not await db.is_premium(uid):
        await update.message.reply_text("⛔ Premium required!")
        return
    await update.message.reply_text("🛡 Send 10-digit number to protect:")
    context.user_data["waiting_for_protect"] = True


async def unprotect_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await check_channel_join(update, context):
        return
    await db.unprotect(uid)
    await update.message.reply_text("🔓 Number unprotected.")


async def contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await check_channel_join(update, context):
        return
    if await db.is_contact_blocked(uid):
        await update.message.reply_text("🚫 You are blocked.")
        return
    await update.message.reply_text("📩 Send your message. /cancel to abort.")
    context.user_data["waiting_for_contact_msg"] = True


# ============================================================
# ADMIN COMMANDS
# ============================================================
async def giveplan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "Usage: /giveplan <user_id> <plan> <days>\n\n"
            "Plans: standard, premium, ultimate\n"
            "Example: /giveplan 123456789 premium 30"
        )
        return
    try:
        tid = int(args[0])
        plan_type = args[1].lower()
        days = int(args[2])
    except ValueError:
        await update.message.reply_text("❌ Invalid numbers.")
        return

    if plan_type not in PLANS:
        await update.message.reply_text("❌ Plan must be: standard, premium, ultimate")
        return
    if not (1 <= days <= 3650):
        await update.message.reply_text("❌ Days must be 1–3650.")
        return

    await db.add_user(tid)
    exp = await db.add_premium(tid, days, plan_type)
    p = PLANS[plan_type]

    await update.message.reply_text(
        f"✅ PLAN ACTIVATED\n\n"
        f"👤 User: {tid}\n"
        f"📋 Plan: {p['name']}\n"
        f"📅 Days: {days}\n"
        f"📆 Expiry: {exp[:10]}"
    )
    try:
        await context.bot.send_message(
            tid,
            f"🎉 PREMIUM ACTIVATED!\n\n"
            f"📋 Plan: {p['name']}\n"
            f"📅 Days: {days}\n"
            f"📆 Expiry: {exp[:10]}\n\n"
            f"🚀 Use /mix to start!",
        )
    except Exception:
        pass


async def removeplan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /removeplan <user_id>")
        return
    tid = int(args[0])
    await db.remove_premium(tid)
    await update.message.reply_text(f"✅ Plan removed for {tid}.")


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    users = await db.get_all_users_with_plan()
    if not users:
        await update.message.reply_text("📭 No users yet.")
        return

    page = 1
    if context.args and context.args[0].isdigit():
        page = max(1, int(context.args[0]))

    per_page = 20
    total = len(users)
    total_p = (total + per_page - 1) // per_page
    start = (page - 1) * per_page
    page_users = users[start : start + per_page]

    msg = f"📋 USERS (page {page}/{total_p})\n👥 Total: {total}\n\n"
    now = datetime.now()
    for u in page_users:
        plan = "Free"
        exp_s = "N/A"
        if u.get("premium_expiry"):
            try:
                e = datetime.fromisoformat(u["premium_expiry"])
                if e > now:
                    plan = (u.get("premium_plan") or "standard").upper()
                    exp_s = f"{(e - now).days}d"
                else:
                    plan = "Expired"
            except Exception:
                pass
        msg += f"• {u['user_id']} — {plan} ({exp_s})\n"

    if total_p > 1 and page < total_p:
        msg += f"\nNext: /users {page + 1}"

    await update.message.reply_text(msg)


async def userinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /userinfo <user_id>")
        return
    tid = int(args[0])
    user = await db.get_user(tid)
    if not user:
        await update.message.reply_text(f"❌ User {tid} not found.")
        return
    plan = await db.get_plan_name(tid)
    exp = await db.get_expiry(tid)
    con = await db.get_concurrent_limit(tid)
    md = await db.get_max_duration(tid)
    prot = user.get("protected_number") or "None"
    banned = await db.is_banned(tid)
    await update.message.reply_text(
        f"👤 USER INFO\n\n"
        f"🆔 {tid}\n"
        f"📋 Plan: {plan}\n"
        f"📅 Expiry: {exp}\n"
        f"⚡ Concurrent: {con}\n"
        f"⏰ Max: {md} min\n"
        f"🛡 Protected: {prot}\n"
        f"🚫 Banned: {'yes' if banned else 'no'}\n"
        f"📆 Joined: {(user.get('created_at') or 'N/A')[:10]}"
    )


async def genkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text("Usage: /genkey <days> <plan>")
        return
    try:
        days = int(args[0])
        plan = args[1].lower()
    except ValueError:
        await update.message.reply_text("❌ Invalid arguments.")
        return
    if plan not in PLANS:
        await update.message.reply_text("❌ Invalid plan.")
        return
    code = await db.generate_code(days, plan)
    await update.message.reply_text(f"✅ KEY GENERATED\n\n🔑 {code}\n📅 {days} days\n📋 {plan.upper()}")


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    await update.message.reply_text("📢 Send broadcast message. /cancel to abort.")
    context.user_data["waiting_for_broadcast"] = True


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    u, p, c, pend = await db.get_stats()
    await update.message.reply_text(
        f"📊 STATS\n\n"
        f"👥 Users: {u}\n"
        f"⭐ Premium: {p}\n"
        f"🔑 Codes: {c}\n"
        f"📩 Pending messages: {pend}\n"
        f"💎 Owner: {OWNER_ID}\n"
        f"📡 APIs: {len(ALL_APIS)}"
    )


async def setchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /setchannel @yourchannel")
        return
    c = args[0].strip().strip("@")
    if "t.me/" in c:
        c = c.split("t.me/")[-1]
    c = c.split("?")[0].split("/")[0]
    await db.set_channel(c)
    await update.message.reply_text(f"✅ Channel set: @{c}")


async def removechannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    await db.remove_channel()
    await update.message.reply_text("🗑 Channel removed.")


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /ban <user_id> [reason]")
        return
    tid = int(args[0])
    reason = " ".join(args[1:]) if len(args) > 1 else ""
    await db.ban_user(tid, reason)
    await update.message.reply_text(f"🚫 User {tid} banned.")


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    tid = int(args[0])
    await db.unban_user(tid)
    await update.message.reply_text(f"✅ User {tid} unbanned.")


async def banned_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    banned = await db.get_banned_users()
    if not banned:
        await update.message.reply_text("📭 No banned users.")
        return
    msg = "🚫 BANNED USERS\n\n"
    for b in banned[:50]:
        msg += f"• {b['user_id']} — {b.get('reason') or 'no reason'}\n"
    await update.message.reply_text(msg)


async def inbox_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    pending = await db.get_pending_contacts()
    if not pending:
        await update.message.reply_text("📭 No pending messages.")
        return
    for m in pending[:5]:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Mark replied", callback_data=f"mark_replied_{m['id']}")],
            [InlineKeyboardButton("🚫 Block user", callback_data=f"block_user_{m['user_id']}")],
        ])
        await update.message.reply_text(
            f"📩 MSG #{m['id']}\n👤 {m['user_id']}\n💬 {m['message']}",
            reply_markup=kb,
        )


async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    args = context.args
    if not args or len(args) < 2 or not args[0].isdigit():
        await update.message.reply_text("Usage: /reply <user_id> <message>")
        return
    tid = int(args[0])
    msg = " ".join(args[1:])
    try:
        await context.bot.send_message(tid, f"📬 Admin reply:\n\n{msg}")
        await update.message.reply_text(f"✅ Sent to {tid}")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")


async def checkapis_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    msg = await update.message.reply_text("🔍 Testing APIs... please wait.")
    try:
        working, failed = await manager.check_apis(max_check=200)
        await msg.edit_text(
            f"📊 API CHECK COMPLETE\n\n"
            f"✅ Working: {len(working)}\n"
            f"❌ Failed: {len(failed)}\n\n"
            f"Top working:\n" + "\n".join(f"• {w}" for w in working[:20])
        )
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")


async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    active = len(manager.active_attacks)
    await update.message.reply_text(f"📊 Active attacks: {active}")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    for k in [
        "waiting_for_target_count",
        "waiting_for_numbers",
        "waiting_for_redeem",
        "waiting_for_protect",
        "waiting_for_broadcast",
        "expected_targets",
        "waiting_for_contact_msg",
    ]:
        context.user_data.pop(k, None)
    db.clear_attack_data(uid)
    await update.message.reply_text("❌ Cancelled.", reply_markup=main_kb(uid))


# ============================================================
# MESSAGE HANDLER
# ============================================================
async def process_numbers(update, context, text):
    uid = update.effective_user.id
    nums = [
        n.strip()
        for n in text.replace(",", " ").split()
        if n.strip().isdigit() and len(n.strip()) == 10
    ]
    expected = context.user_data.get("expected_targets", 0)
    if len(nums) != expected:
        await update.message.reply_text(f"❌ Send exactly {expected} valid 10-digit numbers.")
        return
    context.user_data["waiting_for_numbers"] = False
    db.set_attack_data(uid, nums)
    md = await db.get_max_duration(uid)
    await update.message.reply_text(
        f"📞 Targets: {', '.join(nums)}\n⏰ Choose duration (max {md} min):",
        reply_markup=await duration_kb(uid),
    )


async def broadcast_send(update, context, text):
    context.user_data["waiting_for_broadcast"] = False
    users = await db.get_all_users()
    ok, fail = 0, 0
    msg = await update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
    for u in users:
        try:
            await context.bot.send_message(u, f"📢 ANNOUNCEMENT\n\n{text}")
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await msg.edit_text(f"✅ Broadcast done.\n✅ {ok} OK\n❌ {fail} failed")


async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await check_channel_join(update, context):
        return
    if await db.is_banned(uid):
        await update.message.reply_text("🚫 You are banned.")
        return

    text = update.message.text or ""

    # Admin: broadcast
    if is_admin(uid) and context.user_data.get("waiting_for_broadcast"):
        await broadcast_send(update, context, text)
        return

    # Contact message
    if context.user_data.get("waiting_for_contact_msg"):
        context.user_data["waiting_for_contact_msg"] = False
        if await db.is_contact_blocked(uid):
            await update.message.reply_text("🚫 You are blocked.")
            return
        mid = await db.add_contact_message(uid, text)
        await update.message.reply_text(f"✅ Message sent. ID: #{mid}")
        try:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Mark replied", callback_data=f"mark_replied_{mid}")],
                [InlineKeyboardButton("🚫 Block user", callback_data=f"block_user_{uid}")],
            ])
            await context.bot.send_message(
                OWNER_ID,
                f"📩 NEW MESSAGE\n👤 {uid}\n💬 {text}\n\nReply: /reply {uid} <msg>",
                reply_markup=kb,
            )
        except Exception:
            pass
        return

    await db.add_user(uid)

    # Menu shortcuts
    if text in ("🚀 /mix", "/mix"):
        return await mix_command(update, context)
    if text in ("📊 /status", "/status"):
        return await status_command(update, context)
    if text in ("👤 /account", "/account"):
        return await account_command(update, context)
    if text in ("💳 /plan", "/plan"):
        return await plan_command(update, context)
    if text in ("🔑 /redeem", "/redeem"):
        return await redeem_command(update, context)
    if text in ("🛡 /protect", "/protect"):
        return await protect_command(update, context)
    if text in ("🔓 /unprotect", "/unprotect"):
        return await unprotect_command(update, context)
    if text in ("📩 /contact", "/contact"):
        return await contact_command(update, context)
    if text in ("❓ /help", "/help"):
        return await help_command(update, context)
    if text == "👑 Admin" and is_admin(uid):
        return await show_admin_panel(update, context)

    # Pending number input
    if context.user_data.get("waiting_for_numbers") and text.strip():
        return await process_numbers(update, context, text)

    # Redeem
    if context.user_data.get("waiting_for_redeem"):
        context.user_data["waiting_for_redeem"] = False
        ok, days, plan, exp = await db.redeem(uid, text.strip().upper())
        if ok:
            await update.message.reply_text(
                f"✅ Code activated!\n📋 {plan.upper()}\n📅 {exp[:10]}"
            )
        else:
            await update.message.reply_text("❌ Invalid or used code.")
        return

    # Protect
    if context.user_data.get("waiting_for_protect") and text.isdigit() and len(text) == 10:
        context.user_data["waiting_for_protect"] = False
        await db.protect(uid, text)
        await update.message.reply_text(f"🛡 Protected: {text}")
        return

    # /cancel
    if text == "/cancel":
        return await cancel_command(update, context)


# ============================================================
# ADMIN PANEL
# ============================================================
async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Stats", callback_data="adm_stats"),
         InlineKeyboardButton("👥 Users", callback_data="adm_users")],
        [InlineKeyboardButton("🔑 Gen Standard", callback_data="adm_gen_standard"),
         InlineKeyboardButton("⭐ Gen Premium", callback_data="adm_gen_premium")],
        [InlineKeyboardButton("👑 Gen Ultimate", callback_data="adm_gen_ultimate"),
         InlineKeyboardButton("🔧 Custom Key", callback_data="adm_custom_key")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"),
         InlineKeyboardButton("🔍 Check APIs", callback_data="adm_check_apis")],
        [InlineKeyboardButton("📥 Inbox", callback_data="adm_inbox"),
         InlineKeyboardButton("🚫 Banned", callback_data="adm_banned")],
    ])
    await update.message.reply_text("👑 Admin Panel", reply_markup=kb)


# ============================================================
# BUTTON HANDLER
# ============================================================
async def btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not await check_channel_join(update, context):
        return
    data = q.data

    # ===== User =====
    if data.startswith("targets_"):
        cnt = int(data.split("_")[1])
        context.user_data["waiting_for_target_count"] = False
        context.user_data["waiting_for_numbers"] = True
        context.user_data["expected_targets"] = cnt
        await q.edit_message_text(
            f"📞 Send {cnt} valid 10-digit number(s), space-separated.\n\nExample: 9876543210 9123456780"
        )
        return

    if data.startswith("dur_"):
        targets = db.get_attack_data(uid)
        if not targets:
            await q.edit_message_text("❌ Session expired. Use /mix again.")
            return
        dur = int(data.split("_")[1])
        ok, msg = await manager.start_attack(uid, targets, dur)
        if ok:
            await q.edit_message_text(
                f"🚀 ATTACK STARTED\n\n"
                f"🎯 Targets: {', '.join(targets)}\n"
                f"📊 Count: {len(targets)}\n"
                f"⏰ Duration: {dur} min"
            )
        else:
            await q.edit_message_text(f"❌ {msg}")
        db.clear_attack_data(uid)
        return

    if data == "cancel_attack":
        db.clear_attack_data(uid)
        for k in ["waiting_for_target_count", "waiting_for_numbers", "expected_targets"]:
            context.user_data.pop(k, None)
        await q.edit_message_text("❌ Cancelled.")
        return

    if data == "stop":
        if await manager.stop_attack(uid):
            await q.edit_message_text("🛑 Attack stopped.")
        else:
            await q.answer("No active attack.", show_alert=True)
        return

    if data == "info":
        con = await db.get_concurrent_limit(uid)
        await q.answer(
            f"⚡ {con}x concurrent\n📡 Total APIs: {len(ALL_APIS)}",
            show_alert=True,
        )
        return

    if data == "contact_admin":
        await q.message.reply_text("📩 Send your message. /cancel to abort.")
        context.user_data["waiting_for_contact_msg"] = True
        return

    # ===== Admin =====
    if not is_admin(uid):
        return

    if data == "adm_stats":
        u, p, c, pend = await db.get_stats()
        await q.message.reply_text(
            f"📊 STATS\n\n"
            f"👥 Users: {u}\n"
            f"⭐ Premium: {p}\n"
            f"🔑 Codes: {c}\n"
            f"📩 Pending: {pend}\n"
            f"📡 APIs: {len(ALL_APIS)}"
        )
        return

    if data == "adm_users":
        users = await db.get_all_users_with_plan()
        msg = f"👥 Total users: {len(users)}\n\n"
        now = datetime.now()
        for u in users[:20]:
            plan = "Free"
            if u.get("premium_expiry"):
                try:
                    e = datetime.fromisoformat(u["premium_expiry"])
                    plan = (u.get("premium_plan") or "standard").upper() if e > now else "Expired"
                except Exception:
                    pass
            msg += f"• {u['user_id']} — {plan}\n"
        if len(users) > 20:
            msg += f"\n...and {len(users) - 20} more. Use /users <page>."
        await q.message.reply_text(msg)
        return

    if data in ("adm_gen_standard", "adm_gen_premium", "adm_gen_ultimate"):
        plan = data.replace("adm_gen_", "")
        code = await db.generate_code(30, plan)
        await q.message.reply_text(f"✅ {plan.upper()} KEY (30d)\n\n🔑 {code}")
        return

    if data == "adm_custom_key":
        await q.message.reply_text("Send: /genkey <days> <plan>")
        return

    if data == "adm_broadcast":
        await q.message.reply_text("Send broadcast message. /cancel to abort.")
        context.user_data["waiting_for_broadcast"] = True
        return

    if data == "adm_check_apis":
        msg = await q.message.reply_text("🔍 Testing APIs...")
        working, failed = await manager.check_apis(max_check=200)
        await msg.edit_text(
            f"📊 API CHECK\n\n"
            f"✅ Working: {len(working)}\n"
            f"❌ Failed: {len(failed)}"
        )
        return

    if data == "adm_inbox":
        pending = await db.get_pending_contacts()
        if not pending:
            await q.message.reply_text("📭 No pending messages.")
            return
        for m in pending[:5]:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Mark replied", callback_data=f"mark_replied_{m['id']}")],
                [InlineKeyboardButton("🚫 Block user", callback_data=f"block_user_{m['user_id']}")],
            ])
            await q.message.reply_text(
                f"📩 #{m['id']}\n👤 {m['user_id']}\n💬 {m['message']}",
                reply_markup=kb,
            )
        return

    if data == "adm_banned":
        banned = await db.get_banned_users()
        if not banned:
            await q.message.reply_text("📭 No banned users.")
            return
        msg = "🚫 Banned:\n\n"
        for b in banned[:30]:
            msg += f"• {b['user_id']}\n"
        await q.message.reply_text(msg)
        return

    if data.startswith("mark_replied_"):
        mid = int(data.split("_")[2])
        await db.reply_contact_message(mid, "Replied")
        await q.message.reply_text(f"✅ #{mid} marked replied.")
        return

    if data.startswith("block_user_"):
        tid = int(data.split("_")[2])
        await db.block_contact(tid)
        await q.message.reply_text(f"🚫 User {tid} blocked.")
        return


# ============================================================
# WEB SERVER (for VPS health check)
# ============================================================
async def web_server():
    async def root(_):
        return web.Response(text="Bot alive")
    async def health(_):
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🌐 Web server started on port {PORT}")


async def post_init(app):
    await web_server()


# ============================================================
# MAIN
# ============================================================
def main():
    global db, manager

    # Database init
    if DATABASE_URL:
        logger.info("🗄 Using PostgreSQL")
        db = DatabaseStorage(database_url=DATABASE_URL)
    else:
        logger.info("🗄 Using SQLite")
        db = DatabaseStorage(sqlite_path=SQLITE_DB_PATH)

    asyncio.run(db.ensure_indexes())

    # Attack manager
    manager = AttackManager(db)

    # Build app
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .read_timeout(60)
        .write_timeout(60)
        .connect_timeout(60)
        .pool_timeout(60)
        .post_init(post_init)
        .build()
    )

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("mix", mix_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("account", account_command))
    app.add_handler(CommandHandler("plan", plan_command))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("protect", protect_command))
    app.add_handler(CommandHandler("unprotect", unprotect_command))
    app.add_handler(CommandHandler("contact", contact_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    # Admin
    app.add_handler(CommandHandler("giveplan", giveplan_command))
    app.add_handler(CommandHandler("removeplan", removeplan_command))
    app.add_handler(CommandHandler("users", users_command))
    app.add_handler(CommandHandler("userinfo", userinfo_command))
    app.add_handler(CommandHandler("genkey", genkey_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("setchannel", setchannel_command))
    app.add_handler(CommandHandler("removechannel", removechannel_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("banned", banned_command))
    app.add_handler(CommandHandler("inbox", inbox_command))
    app.add_handler(CommandHandler("reply", reply_command))
    app.add_handler(CommandHandler("checkapis", checkapis_command))
    app.add_handler(CommandHandler("logs", logs_command))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.add_handler(CallbackQueryHandler(btn_handler))

    logger.info("=" * 60)
    logger.info(f"🔥 PREMIUM BOMBER STARTED")
    logger.info(f"📡 Total APIs: {len(ALL_APIS)}")
    logger.info("=" * 60)

    # Run mode
    if USE_WEBHOOK and WEBHOOK_URL:
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
            drop_pending_updates=True,
        )
    else:
        import asyncio
asyncio.set_event_loop(asyncio.new_event_loop())
app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
