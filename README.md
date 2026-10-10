# 🔥 Premium Multi-Target Bomber Bot

Telegram bot for sending OTP/call/WhatsApp bombs to target numbers.

## Features

- 🎯 Multi-target support (2–10 targets simultaneously based on plan)
- 📡 1400+ APIs (SMS + Call + WhatsApp + ClassX)
- 💾 PostgreSQL + SQLite support
- 🛡 Number protection system
- 🔑 Redeem codes
- 👑 Full admin panel
- 🚫 Ban system
- 📩 Contact / inbox / reply
- 📊 Stats
- 📢 Broadcast

## Plans

| Plan       | Price  | Days | Concurrent | Max Duration |
|------------|--------|------|------------|--------------|
| Standard   | ₹149   | 30   | 2          | 300 min      |
| Premium    | ₹249   | 30   | 5          | 720 min      |
| Ultimate   | ₹349   | 30   | 10         | 720 min      |

## Setup on VPS (Ubuntu 22.04)

```bash
# 1. Install dependencies
sudo apt update
sudo apt install -y python3-pip python3-venv git

# 2. Clone / upload files
mkdir bomber-bot && cd bomber-bot
# upload all .py files here

# 3. Create virtual env
python3 -m venv venv
source venv/bin/activate

# 4. Install requirements
pip install -r requirements.txt

# 5. Create .env
cp .env.example .env
nano .env
# put your BOT_TOKEN and OWNER_ID

# 6. Run
python main.py
```

## Run as systemd service

Create `/etc/systemd/system/bomber.service`:

```ini
[Unit]
Description=Bomber Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/bomber-bot
ExecStart=/root/bomber-bot/venv/bin/python /root/bomber-bot/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable bomber
sudo systemctl start bomber
sudo systemctl status bomber
```

## GitHub Upload

Files are small enough for GitHub. Just push:

```bash
git init
git add .
git commit -m "initial"
git branch -M main
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git push -u origin main
```

**Note:** `.env` is gitignored — never commit secrets.
