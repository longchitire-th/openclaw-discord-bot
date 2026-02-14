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
# 1. Configuration
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_CHANNEL_SECRET")
SHEET_ID = os.getenv("SPREADSHEET_ID")

# Global Cache สำหรับเก็บข้อมูลสต็อก (ลดการดึง Sheet บ่อยเกินไป)
cached_stock = []
last_update = 0
CACHE_TTL = 300  # อัปเดตทุก 5 นาที (300 วินาที)

anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)
app = Flask(__name__)

intents = discord.Intents.default()
intents.message_content = True
discord_client = discord.Client(intents=intents)

# =========================
# 2. Data Logic
# =========================

def fetch_all_records():
    """ดึงข้อมูลจาก Google Sheets พร้อมระบบ Cache"""
    global cached_stock, last_update
    now = time.time()
    
    if now - last_update < CACHE_TTL and cached_stock:
        return cached_stock

    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        # แนะนำให้ใช้ Path แบบแปรผันหรือเก็บใน Env หากทำได้
        creds = Credentials.from_service_account_file('service_account.json', scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        cached_stock = sheet.get_all_records()
        last_update = now
        print("✅ Stock Data Updated from Google Sheets")
        return cached_stock
    except Exception as e:
        print(f"❌ Sheet Error: {e}")
        return cached_stock if cached_stock else []

def get_tire_data(user_input):
    records = fetch_all_records()
    # ทำความสะอาด Input: เหลือแค่ตัวเลขและตัวอักษร r
    clean_query = re.sub(r'[^0-9rR]', '', user_input).lower()
    
    if not clean_query: return []

    matches = []
    for r in records:
        # ดึงค่า size_key มาทำความสะอาดเพื่อเปรียบเทียบ
        raw_size = str(r.get('size_key', r.get('ขนาด', '')))
        db_size = re.sub(r'[^0-9rR]', '', raw_size).lower()
        
        if clean_query in db_size or db_size in clean_query:
            matches.append(r)
    
    # เรียงลำดับปี (Handle กรณีปีไม่ใช่ตัวเลขด้วย)
    def sort_year(x):
        try: return int(x.get('year', 0))
        except: return 0

    return sorted(matches, key=sort_year, reverse=True)

# =========================
# 3. Messaging Logic
# =========================

def create_flex_carousel(tire_list):
    bubbles = []
    for item in tire_list[:10]:
        brand = item.get('brand', 'ไม่ระบุยี่ห้อ')
        model = item.get('model', '')
        size = item.get('ขนาด', item.get('size_key', '-'))
        year = item.get('year', '-')
        price = item.get('price', 'สอบถามราคา')
        
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
                        {"type": "text", "text": f"ราคา: {format(price, ',') if isinstance(price, int) else price}.-", "size": "xl", "weight": "bold", "color": "#ff0000", "margin": "md"}
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
    if stock:
        stock_text = "\n".join([f"- {s.get('brand')} {s.get('model')} ปี {s.get('year')} ราคา {s.get('price')}.-" for s in stock[:5]])
    else:
        stock_text = "ไม่มีสินค้าขนาดนี้ในสต็อกขณะนี้"
    
    prompt = f"คุณคือพนักงานขายยางรถยนต์มืออาชีพของ 'หลงจื่อ กรุ๊ป'\nคำถามลูกค้า: '{user_msg}'\nข้อมูลสต็อกจริง: {stock_text}\n\nคำแนะนำ: ตอบคำถามอย่างสุภาพและแม่นยำ หากมีสินค้าให้เชียร์ขาย หากไม่มีให้แนะนำให้สอบถามแอดมินเพื่อเช็คของจากคลังอื่น"
    
    try:
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        return f"ขออภัยครับ ระบบประมวลผลขัดข้องชั่วคราว (Error: {str(e)})"

# =========================
# 4. Webhook & Execution
# =========================

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_line_message(event):
    msg = event.message.text.strip()
    # ตรวจสอบว่าเป็นรหัสยางหรือไม่ (เช่น 265/60R18)
    is_size_query = re.match(r'^[\d/x.R ]+$', msg)
    
    if is_size_query:
        stock = get_tire_data(msg)
        if stock:
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="เช็คสต็อกยาง", contents=create_flex_carousel(stock)))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ขออภัยครับ ไม่พบขนาดนี้ในสต็อกในขณะนี้ ท่านต้องการให้เจ้าหน้าที่ช่วยเช็คจากคลังอื่นให้ไหมครับ?"))
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=ask_ai_with_stock(msg)))

@discord_client.event
async def on_message(message):
    if message.author == discord_client.user: return
    
    content = message.content.strip()
    if re.match(r'^[\d/x.R ]+$', content):
        stock = get_tire_data(content)
        if stock:
            res = "📦 **รายการสต็อกที่พบ:**\n" + "\n".join([f"🔹 {s['brand']} {s.get('model','')} ({s['year']}) - {s['price']}.-" for s in stock[:10]])
            await message.channel.send(res)
        else:
            await message.channel.send("❌ ไม่พบสินค้าขนาดนี้ในสต็อก")
    else:
        await message.channel.send(ask_ai_with_stock(content))

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # เริ่ม Flask ใน Thread แยก
    threading.Thread(target=run_flask, daemon=True).start()
    # เริ่ม Discord Client (Blocking call)
    discord_client.run(TOKEN)
