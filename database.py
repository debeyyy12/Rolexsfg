"""
Database Storage - Supports PostgreSQL (asyncpg) + SQLite (aiosqlite)
"""
import os
import time
import random
import string
import sqlite3
import logging
from datetime import datetime, timedelta

from config import DATABASE_URL, SQLITE_DB_PATH, PLANS, OWNER_ID

logger = logging.getLogger(__name__)

try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

try:
    import aiosqlite
    HAS_SQLITE = True
except ImportError:
    HAS_SQLITE = False


class DatabaseStorage:
    def __init__(self, database_url=None, sqlite_path=None):
        self.database_url = database_url
        self.sqlite_path = sqlite_path
        self.use_postgres = False
        self._pool = None
        self._conn = None
        self.temp_attack_data = {}

        if database_url and HAS_ASYNCPG:
            self.use_postgres = True
        elif sqlite_path and HAS_SQLITE:
            self.use_postgres = False
            d = os.path.dirname(os.path.abspath(sqlite_path))
            if d and not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
        else:
            raise RuntimeError("No database backend available!")

    # ---------- Connection ----------
    async def _get_pool(self):
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self.database_url, min_size=1, max_size=10, command_timeout=30
            )
        return self._pool

    async def _get_sqlite_conn(self):
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.sqlite_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    @staticmethod
    def _convert_placeholders(sql):
        parts = sql.split("?")
        if len(parts) == 1:
            return sql
        result = parts[0]
        for i, part in enumerate(parts[1:], 1):
            result += f"${i}" + part
        return result

    async def _exec(self, sql, *params):
        if self.use_postgres:
            sql_pg = self._convert_placeholders(sql)
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                return await conn.execute(sql_pg, *params)
        else:
            conn = await self._get_sqlite_conn()
            cur = await conn.execute(sql, params)
            await conn.commit()
            return cur

    async def _fetchone(self, sql, *params):
        if self.use_postgres:
            sql_pg = self._convert_placeholders(sql)
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(sql_pg, *params)
                return dict(row) if row else None
        else:
            conn = await self._get_sqlite_conn()
            cur = await conn.execute(sql, params)
            row = await cur.fetchone()
            await cur.close()
            return dict(row) if row else None

    async def _fetchall(self, sql, *params):
        if self.use_postgres:
            sql_pg = self._convert_placeholders(sql)
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql_pg, *params)
                return [dict(r) for r in rows]
        else:
            conn = await self._get_sqlite_conn()
            cur = await conn.execute(sql, params)
            rows = await cur.fetchall()
            await cur.close()
            return [dict(r) for r in rows]

    # ---------- Schema ----------
    async def ensure_indexes(self):
        if self.use_postgres:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        premium_expiry TEXT,
                        premium_plan TEXT DEFAULT 'standard',
                        protected_number TEXT,
                        created_at TEXT
                    )
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS redeem_codes (
                        code TEXT PRIMARY KEY,
                        days INTEGER,
                        plan_type TEXT,
                        is_used INTEGER DEFAULT 0,
                        created_at TEXT
                    )
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS contact_messages (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        message TEXT,
                        status TEXT DEFAULT 'pending',
                        created_at TEXT,
                        replied_at TEXT,
                        reply_text TEXT
                    )
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS contact_blocked (
                        user_id BIGINT PRIMARY KEY,
                        blocked_at TEXT
                    )
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS banned_users (
                        user_id BIGINT PRIMARY KEY,
                        banned_at TEXT,
                        reason TEXT
                    )
                """)
        else:
            conn = await self._get_sqlite_conn()
            await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, premium_expiry TEXT, premium_plan TEXT DEFAULT 'standard', protected_number TEXT, created_at TEXT)")
            await conn.execute("CREATE TABLE IF NOT EXISTS redeem_codes (code TEXT PRIMARY KEY, days INTEGER, plan_type TEXT, is_used INTEGER DEFAULT 0, created_at TEXT)")
            await conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            await conn.execute("CREATE TABLE IF NOT EXISTS contact_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message TEXT, status TEXT DEFAULT 'pending', created_at TEXT, replied_at TEXT, reply_text TEXT)")
            await conn.execute("CREATE TABLE IF NOT EXISTS contact_blocked (user_id INTEGER PRIMARY KEY, blocked_at TEXT)")
            await conn.execute("CREATE TABLE IF NOT EXISTS banned_users (user_id INTEGER PRIMARY KEY, banned_at TEXT, reason TEXT)")
            await conn.commit()
        logger.info("✅ Database schema ready")

    # ---------- Users ----------
    async def get_user(self, user_id):
        return await self._fetchone("SELECT * FROM users WHERE user_id = ?", int(user_id))

    async def add_user(self, user_id):
        if not await self.get_user(user_id):
            try:
                await self._exec(
                    "INSERT INTO users (user_id, premium_expiry, premium_plan, protected_number, created_at) VALUES (?,?,?,?,?)",
                    int(user_id), None, "standard", None, datetime.now().isoformat(),
                )
            except Exception:
                pass
        return True

    async def is_premium(self, user_id):
        if user_id == OWNER_ID:
            return True
        user = await self.get_user(user_id)
        if user and user.get("premium_expiry"):
            try:
                return datetime.now() < datetime.fromisoformat(user["premium_expiry"])
            except Exception:
                return False
        return False

    async def get_concurrent_limit(self, user_id):
        if user_id == OWNER_ID:
            return 10
        user = await self.get_user(user_id)
        if user and user.get("premium_expiry"):
            try:
                if datetime.now() < datetime.fromisoformat(user["premium_expiry"]):
                    return PLANS.get(user.get("premium_plan", "standard"), PLANS["standard"])["concurrent"]
            except Exception:
                pass
        return 0

    async def get_max_duration(self, user_id):
        if user_id == OWNER_ID:
            return 720
        user = await self.get_user(user_id)
        if user and user.get("premium_expiry"):
            try:
                if datetime.now() < datetime.fromisoformat(user["premium_expiry"]):
                    return PLANS.get(user.get("premium_plan", "standard"), PLANS["standard"])["max_duration"]
            except Exception:
                pass
        return 0

    async def get_plan_name(self, user_id):
        if user_id == OWNER_ID:
            return "Ultimate"
        user = await self.get_user(user_id)
        if user and user.get("premium_expiry"):
            try:
                if datetime.now() < datetime.fromisoformat(user["premium_expiry"]):
                    return PLANS.get(user.get("premium_plan", "standard"), PLANS["standard"])["name"]
            except Exception:
                pass
        return "Free"

    async def get_expiry(self, user_id):
        user = await self.get_user(user_id)
        if user and user.get("premium_expiry"):
            try:
                exp = datetime.fromisoformat(user["premium_expiry"])
                if datetime.now() < exp:
                    return user["premium_expiry"]
            except Exception:
                pass
        return "Not Active"

    async def add_premium(self, user_id, days, plan_type="standard"):
        current = datetime.now()
        user = await self.get_user(user_id)
        if user and user.get("premium_expiry"):
            try:
                stored = datetime.fromisoformat(user["premium_expiry"])
                if stored > current:
                    current = stored
            except Exception:
                pass
        new_exp = current + timedelta(days=days)
        str_exp = new_exp.isoformat()

        if self.use_postgres:
            await self._exec(
                """INSERT INTO users (user_id, premium_expiry, premium_plan, protected_number, created_at)
                   VALUES (?, ?, ?, NULL, ?)
                   ON CONFLICT(user_id) DO UPDATE
                   SET premium_expiry = EXCLUDED.premium_expiry,
                       premium_plan = EXCLUDED.premium_plan""",
                int(user_id), str_exp, plan_type, datetime.now().isoformat(),
            )
        else:
            await self._exec(
                "INSERT INTO users (user_id, premium_expiry, premium_plan, protected_number, created_at) VALUES (?, ?, ?, NULL, ?)"
                " ON CONFLICT(user_id) DO UPDATE SET premium_expiry=excluded.premium_expiry, premium_plan=excluded.premium_plan",
                int(user_id), str_exp, plan_type, datetime.now().isoformat(),
            )
        return str_exp

    async def remove_premium(self, user_id):
        await self._exec("UPDATE users SET premium_expiry = NULL, premium_plan = NULL WHERE user_id = ?", int(user_id))
        return True

    async def get_all_users_with_plan(self):
        return await self._fetchall(
            "SELECT user_id, premium_expiry, premium_plan, protected_number, created_at FROM users ORDER BY created_at DESC"
        )

    # ---------- Redeem ----------
    async def generate_code(self, days, plan_type="standard"):
        code = "PREMIUM-" + "".join(
            random.choice(string.ascii_uppercase + string.digits) for _ in range(8)
        )
        existing = await self._fetchone("SELECT code FROM redeem_codes WHERE code = ?", code)
        if existing:
            return await self.generate_code(days, plan_type)
        await self._exec(
            "INSERT INTO redeem_codes (code, days, plan_type, is_used, created_at) VALUES (?,?,?,?,?)",
            code, days, plan_type, 0, datetime.now().isoformat(),
        )
        return code

    async def redeem(self, user_id, code):
        row = await self._fetchone("SELECT * FROM redeem_codes WHERE code = ?", code)
        if not row or row["is_used"] == 1:
            return False, 0, None, None
        days = row["days"] or 0
        plan_type = row["plan_type"] or "standard"
        await self._exec("UPDATE redeem_codes SET is_used = 1 WHERE code = ?", code)
        exp_date = await self.add_premium(user_id, days, plan_type)
        return True, days, plan_type, exp_date

    # ---------- Protected ----------
    async def protect(self, user_id, number):
        await self._exec("UPDATE users SET protected_number = ? WHERE user_id = ?", number, int(user_id))

    async def unprotect(self, user_id):
        await self._exec("UPDATE users SET protected_number = NULL WHERE user_id = ?", int(user_id))

    async def is_protected(self, number):
        return (await self._fetchone("SELECT user_id FROM users WHERE protected_number = ?", number)) is not None

    # ---------- Settings ----------
    async def set_channel(self, channel_id):
        if self.use_postgres:
            await self._exec(
                "INSERT INTO settings (key, value) VALUES ('channel_id', ?) ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value",
                str(channel_id),
            )
        else:
            await self._exec(
                "INSERT INTO settings (key, value) VALUES ('channel_id', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                str(channel_id),
            )

    async def get_channel(self):
        row = await self._fetchone("SELECT value FROM settings WHERE key = 'channel_id'")
        return str(row["value"]) if row and row["value"] else None

    async def remove_channel(self):
        await self._exec("DELETE FROM settings WHERE key = 'channel_id'")

    async def get_all_users(self):
        rows = await self._fetchall("SELECT user_id FROM users")
        return [r["user_id"] for r in rows]

    async def get_stats(self):
        row = await self._fetchone("SELECT COUNT(*) AS c FROM users")
        total = row["c"] if row else 0
        now = datetime.now().isoformat()
        row = await self._fetchone("SELECT COUNT(*) AS c FROM users WHERE premium_expiry > ?", now)
        premium = row["c"] if row else 0
        row = await self._fetchone("SELECT COUNT(*) AS c FROM redeem_codes")
        codes = row["c"] if row else 0
        row = await self._fetchone("SELECT COUNT(*) AS c FROM contact_messages WHERE status = 'pending'")
        pending = row["c"] if row else 0
        return total, premium, codes, pending

    # ---------- Contact ----------
    async def add_contact_message(self, user_id, message):
        if self.use_postgres:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "INSERT INTO contact_messages (user_id, message, status, created_at) VALUES ($1,$2,$3,$4) RETURNING id",
                    int(user_id), message, "pending", datetime.now().isoformat(),
                )
                return row["id"] if row else None
        else:
            conn = await self._get_sqlite_conn()
            cur = await conn.execute(
                "INSERT INTO contact_messages (user_id, message, status, created_at) VALUES (?,?,?,?)",
                (int(user_id), message, "pending", datetime.now().isoformat()),
            )
            await conn.commit()
            return cur.lastrowid

    async def get_pending_contacts(self):
        return await self._fetchall(
            "SELECT * FROM contact_messages WHERE status = 'pending' ORDER BY created_at ASC"
        )

    async def reply_contact_message(self, msg_id, reply_text):
        await self._exec(
            "UPDATE contact_messages SET status = 'replied', reply_text = ?, replied_at = ? WHERE id = ?",
            reply_text, datetime.now().isoformat(), msg_id,
        )

    async def block_contact(self, user_id):
        if self.use_postgres:
            await self._exec(
                "INSERT INTO contact_blocked (user_id, blocked_at) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET blocked_at = EXCLUDED.blocked_at",
                int(user_id), datetime.now().isoformat(),
            )
        else:
            await self._exec(
                "INSERT OR REPLACE INTO contact_blocked (user_id, blocked_at) VALUES (?,?)",
                int(user_id), datetime.now().isoformat(),
            )

    async def unblock_contact(self, user_id):
        await self._exec("DELETE FROM contact_blocked WHERE user_id = ?", int(user_id))

    async def is_contact_blocked(self, user_id):
        return (await self._fetchone("SELECT user_id FROM contact_blocked WHERE user_id = ?", int(user_id))) is not None

    async def get_blocked_users(self):
        rows = await self._fetchall("SELECT user_id FROM contact_blocked")
        return [r["user_id"] for r in rows]

    # ---------- Ban system ----------
    async def ban_user(self, user_id, reason=""):
        if self.use_postgres:
            await self._exec(
                "INSERT INTO banned_users (user_id, banned_at, reason) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET banned_at = EXCLUDED.banned_at, reason = EXCLUDED.reason",
                int(user_id), datetime.now().isoformat(), reason,
            )
        else:
            await self._exec(
                "INSERT OR REPLACE INTO banned_users (user_id, banned_at, reason) VALUES (?,?,?)",
                int(user_id), datetime.now().isoformat(), reason,
            )

    async def unban_user(self, user_id):
        await self._exec("DELETE FROM banned_users WHERE user_id = ?", int(user_id))

    async def is_banned(self, user_id):
        return (await self._fetchone("SELECT user_id FROM banned_users WHERE user_id = ?", int(user_id))) is not None

    async def get_banned_users(self):
        return await self._fetchall("SELECT * FROM banned_users ORDER BY banned_at DESC")

    # ---------- Temp attack data ----------
    def set_attack_data(self, user_id, targets):
        self.temp_attack_data[user_id] = {"targets": targets, "timestamp": time.time()}

    def get_attack_data(self, user_id):
        data = self.temp_attack_data.get(user_id)
        if data and time.time() - data["timestamp"] < 300:
            return data["targets"]
        if user_id in self.temp_attack_data:
            del self.temp_attack_data[user_id]
        return None

    def clear_attack_data(self, user_id):
        if user_id in self.temp_attack_data:
            del self.temp_attack_data[user_id]

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None
        if self._conn:
            await self._conn.close()
            self._conn = None
