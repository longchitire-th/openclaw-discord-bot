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
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
from google.oauth2.service_account import Credentials

# =========================
# 1. Configuration & Caching
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
# 2. Advanced Search Logic (รองรับทุก Pattern)
# =========================

def clean_tire_size(text):
    """
    ทำให้พิมพ์ท่าไหนก็เจอ:
    265/60R18 -> 2656018
    33x12.5R15 -> 3312515
    195R14 -> 19514
    """
    if not text: return ""
    # เก็บแค่ตัวเลขและตัว x (สำหรับยางออฟโรด)
    clean = re.sub(r'[^0-9xX]', '', str(text)).lower()
    # จัดการกรณี 12.50 หรือ 12.5 ให้ตรงกัน
    clean = clean.replace('50', '5') if '12.5' in text or '12.50' in text else clean
    return clean

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
        print("✅ ข้อมูลสต็อกอัปเดตแล้ว")
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
        # ค้นหาแบบกว้างเพื่อให้ครอบคลุมทุกการพิมพ์
        if query in size_key or query in size_name or size_key in query:
            matches.append(r)
    return sorted(matches, key=lambda x: str(x.get('year', '0')), reverse=True)

# =========================
# 3. UI & AI Consultant Mode
# =========================

def create_flex_carousel(tire_list):
    bubbles = []
    for item in tire_list[:10]:
        brand = item.get('brand', 'ไม่ระบุยี่ห้อ')
        model = item.get('model', '-')
        size = item.get('ขนาด', '-')
        year = item.get('year', '-')
        price = item.get('price', 'สอบถาม')
        formatted_price = f"{price:,}" if isinstance(price, int) else str(price)

        bubble = {
            "type": "bubble", "size": "mega",
            "header": {
                "type": "box", "layout": "horizontal", "contents": [
                    {"type": "image", "url": "https://lctyre.com/wp-content/uploads/2025/05/GYBL-2.png", "size": "xxs", "aspectMode": "fit"},
                    {"type": "text", "text": "LONG CI GROUP", "weight": "bold", "color": "#1DB446", "size": "sm", "margin": "sm", "gravity": "center"}
                ]
            },
            "body": {
                "type": "box", "layout": "vertical", "contents": [
                    {"type": "text", "text": f"{brand} {model}", "weight": "bold", "size": "xl", "wrap": True},
                    {"type": "separator", "margin": "md"},
                    {"type": "box", "layout": "vertical", "margin": "md", "contents": [
                        {"type": "text", "text": f"ขนาด: {size}", "size": "sm", "color": "#666666"},
                        {"type": "text", "text": f"ปีผลิต: {year}", "size": "sm", "color": "#666666"},
                        {"type": "text", "text": f"ราคา: {formatted_price}.-", "size": "xl", "weight": "bold", "color": "#ff0000", "margin": "md"}
                    ]}
                ]
            },
            "footer": {
                "type": "box", "layout": "vertical", "contents": [
                    {"type": "button", "action": {"type": "message", "label": "สนใจสั่งซื้อ", "text": f"สนใจ {brand} {size} ปี {year}"}, "style": "primary", "color": "#1DB446"}
                ]
            }
        }
        bubbles.append(bubble)
    return {"type": "carousel", "contents": bubbles}

def ask_ai_with_stock(user_msg):
    stock = get_tire_data(user_msg)
    stock_text = "ไม่มีขนาดนี้ในสต็อก" if not stock else "สต็อกที่มีตอนนี้:\n" + "\n".join([f"- {s.get('brand')} {s.get('year')} {s.get('price')}.-" for s in stock[:5]])

    prompt = f"""คุณคือพนักงานขายและที่ปรึกษาเรื่องล้อ/ยางรถยนต์ของ 'หลงจื่อ กรุ๊ป'
คำถามลูกค้า: {user_msg}
ข้อมูลสต็อกจริง: {stock_text}

กฎการตอบ:
1. หากลูกค้าถามเรื่องรุ่นรถ (เช่น Vigo ใส่ยางอะไรดี) ให้แนะนำสเปกที่เหมาะสมและปลอดภัย
2. สามารถให้ความรู้เรื่องสเปกล้อ PCD/Offset และยางเบอร์ต่างๆ ได้อย่างผู้เชี่ยวชาญ
3. หากในสต็อกมีของที่ 'ใส่แทนกันได้' หรือ 'ตรงรุ่น' ให้เสนอขายทันที
4. ห้ามแนะนำขนาดยางที่อันตรายหรือไม่เป็นมาตรฐาน
5. หากไม่มีของจริงให้แจ้งว่าจะเช็คคลังอื่นให้ ห้ามมโนแบรนด์เอง"""

    try:
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        return f"ขออภัย ระบบปรึกษาขัดข้อง: {str(e)}"

# =========================
# 4. Webhook & Execution
# =========================

def run_flask():
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
    clean_msg = clean_tire_size(msg)
    # ถ้าพิมพ์ขนาดยางมา (มีตัวเลขเยอะ) ให้เช็คสต็อกก่อน
    if len(clean_msg) >= 5:
        stock = get_tire_data(msg)
        if stock:
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="เช็คสต็อกยาง", contents=create_flex_carousel(stock)))
            return
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=ask_ai_with_stock(msg)))

@discord_client.event
async def on_message(message):
    if message.author == discord_client.user: return
    content = message.content.strip()
    if len(clean_tire_size(content)) >= 5:
        stock = get_tire_data(content)
        if stock:
            res = "📦 **สต็อก หลงจื่อ กรุ๊ป:**\n" + "\n".join([f"🔹 {s['brand']} {s['year']} - {s['price']}.-" for s in stock[:5]])
            await message.channel.send(res)
            return
    await message.channel.send(ask_ai_with_stock(content))

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    discord_client.run(TOKEN)
