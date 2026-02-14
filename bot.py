import discord
import os
import threading
import gspread
import re
import time
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from google.oauth2.service_account import Credentials

# =========================
# 1. การตั้งค่าระบบ
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_CHANNEL_SECRET")
SHEET_ID = os.getenv("SPREADSHEET_ID")

cached_stock = []
last_update = 0
CACHE_TTL = 300 

line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)
app = Flask(__name__)

intents = discord.Intents.default()
intents.message_content = True
discord_client = discord.Client(intents=intents)

# =========================
# 2. ระบบดึงข้อมูลและค้นหา
# =========================

def clean_tire_size(text):
    """ทำให้พิมพ์ 2656018 หรือ 265/60R18 ก็ค้นหาเจอ"""
    if not text: return ""
    return re.sub(r'[^0-9xX]', '', str(text)).lower()

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
        print("✅ ข้อมูลสต็อกอัปเดตเรียบร้อย")
        return cached_stock
    except Exception as e:
        print(f"❌ Sheet Error: {e}")
        return cached_stock if cached_stock else []

def get_tire_data(user_input):
    records = fetch_all_records()
    query = clean_tire_size(user_input)
    if len(query) < 4: return [] 

    matches = []
    for r in records:
        size_key = clean_tire_size(r.get('size_key', ''))
        size_name = clean_tire_size(r.get('ขนาด', ''))
        if query in size_key or query in size_name:
            matches.append(r)
    return matches

# =========================
# 3. ส่วนการตอบกลับ (เน้นแจ้งราคา)
# =========================

def format_stock_response(matches):
    if not matches:
        return "ขออภัยครับ ไม่พบขนาดสินค้าที่ท่านค้นหาในสต็อกขณะนี้"
    
    response = "📦 รายการสินค้าที่พร้อมส่ง:\n"
    for item in matches[:5]:
        brand = item.get('brand', '-')
        year = item.get('year', '-')
        price = item.get('price', 'สอบถาม')
        size = item.get('ขนาด', '-')
        response += f"🔹 {brand} ({size}) ปี {year} \n   💰 ราคา {price}.- \n\n"
    response += "สนใจรับรายการไหน หรือสอบถามเพิ่มเติมแจ้งได้เลยครับ"
    return response

# =========================
# 4. Webhook & Flask
# =========================

def run_flask():
    """เพิ่มฟังก์ชันนี้เพื่อป้องกันระบบ NameError ล่ม"""
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

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
    if len(clean_tire_size(msg)) >= 5:
        stock = get_tire_data(msg)
        reply_text = format_stock_response(stock)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

@discord_client.event
async def on_message(message):
    if message.author == discord_client.user: return
    content = message.content.strip()
    if len(clean_tire_size(content)) >= 5:
        stock = get_tire_data(content)
        await message.channel.send(format_stock_response(stock))

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    discord_client.run(TOKEN)
