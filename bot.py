import discord
import os
import threading
import gspread
import re
import time
from flask import Flask, request, abort
from anthropic import Anthropic
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from google.oauth2.service_account import Credentials

# =========================
# 1. Configuration
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_CHANNEL_SECRET")
SHEET_ID = os.getenv("SPREADSHEET_ID")

cached_stock = []
last_update = 0
CACHE_TTL = 300 

anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)
app = Flask(__name__)

intents = discord.Intents.default()
intents.message_content = True
discord_client = discord.Client(intents=intents)

# =========================
# 2. Data & Search Logic
# =========================

def clean_tire_size(text):
    """แปลงทุกรูปแบบ (265/60R18, 2656018) ให้เหลือแค่ตัวเลขเพื่อความแม่นยำ"""
    if not text: return ""
    return re.sub(r'[^0-9]', '', str(text))

def fetch_all_records():
    global cached_stock, last_update
    now = time.time()
    if now - last_update < CACHE_TTL and cached_stock:
        return cached_stock
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file('service_account.json', scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        cached_stock = sheet.get_all_records()
        last_update = now
        return cached_stock
    except Exception as e:
        print(f"❌ Sheet Error: {e}")
        return cached_stock if cached_stock else []

def get_tire_data(user_input):
    records = fetch_all_records()
    query = clean_tire_size(user_input)
    if len(query) < 5: return [] 

    matches = []
    for r in records:
        # เทียบทั้งคอลัมน์ 'size_key' และ 'ขนาด'
        db_size_key = clean_tire_size(r.get('size_key', ''))
        db_size_name = clean_tire_size(r.get('ขนาด', ''))
        if query in db_size_key or query in db_size_name:
            matches.append(r)
    return sorted(matches, key=lambda x: str(x.get('year', '0')), reverse=True)

# =========================
# 3. AI & Web Server Logic
# =========================

def ask_ai_with_stock(user_msg):
    stock = get_tire_data(user_msg)
    stock_context = "ไม่มีในสต็อก" if not stock else "สต็อกที่มีตอนนี้:\n" + "\n".join([f"- {s.get('brand')} {s.get('year')} {s.get('price')}.-" for s in stock[:5]])

    prompt = f"คุณคือพนักงานขายของ หลงจื่อ กรุ๊ป\nคำถามลูกค้า: {user_msg}\nข้อมูลสต็อกจริง: {stock_context}\nห้ามมโนขนาดยางเองเด็ดขาด ถ้าไม่มีของให้บอกให้รอแอดมินเช็คคลังสำรอง"
    
    try:
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        return f"ขออภัย ระบบขัดข้อง: {str(e)}"

# ✅ เพิ่มฟังก์ชันที่หายไปเพื่อแก้ปัญหา NameError
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# =========================
# 4. Webhook & Event Handlers
# =========================

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_line_message(event):
    msg = event.message.text.strip()
    # ถ้าส่งแค่เบอร์ยาง ให้เช็คราคาก่อน ถ้าถามอย่างอื่นให้ AI ตอบ
    if len(clean_tire_size(msg)) >= 6:
        stock = get_tire_data(msg)
        if stock:
            res = "📦 รายการที่พบ:\n" + "\n".join([f"🔹 {s['brand']} {s['year']} - {s['price']}.-" for s in stock[:5]])
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=res))
            return
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=ask_ai_with_stock(msg)))

@discord_client.event
async def on_message(message):
    if message.author == discord_client.user: return
    content = message.content.strip()
    # ตรรกะเดียวกับ LINE
    if len(clean_tire_size(content)) >= 6:
        stock = get_tire_data(content)
        if stock:
            res = "📦 รายการในสต็อก:\n" + "\n".join([f"🔹 {s['brand']} {s['year']} - {s['price']}.-" for s in stock[:5]])
            await message.channel.send(res)
            return
    await message.channel.send(ask_ai_with_stock(content))

if __name__ == "__main__":
    # เริ่ม Flask ใน Thread แยก (แก้ปัญหา Crashed)
    threading.Thread(target=run_flask, daemon=True).start()
    discord_client.run(TOKEN)
