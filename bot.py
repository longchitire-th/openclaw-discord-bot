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
# 2. Logic การจัดการข้อมูล (ปรับปรุงใหม่)
# =========================

def clean_tire_size(text):
    """แปลงทุกอย่างให้เหลือแค่ตัวเลข เช่น '265/60R18' -> '2656018'"""
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
        print(f"❌ Error: {e}")
        return cached_stock if cached_stock else []

def get_tire_data(user_input):
    records = fetch_all_records()
    query = clean_tire_size(user_input)
    if len(query) < 4: return [] 

    matches = []
    for r in records:
        # ดึงค่าจาก Google Sheets มาลบอักขระพิเศษเพื่อเทียบเลขเพียวๆ
        db_size_key = clean_tire_size(r.get('size_key', ''))
        db_size_name = clean_tire_size(r.get('ขนาด', ''))
        
        # ค้นหาแบบกว้าง (Broad Match)
        if query in db_size_key or query in db_size_name:
            matches.append(r)
    
    # เรียงปีใหม่สุดไว้บนสุด
    return sorted(matches, key=lambda x: str(x.get('year', '0')), reverse=True)

# =========================
# 3. AI Salesman Instruction
# =========================

def ask_ai_with_stock(user_msg):
    stock = get_tire_data(user_msg)
    stock_context = "ขณะนี้ไม่มีขนาดที่ระบุในคลัง"
    if stock:
        stock_context = "สต็อกที่พบจริง:\n" + "\n".join([f"- {s.get('brand')} {s.get('model')} ปี {s.get('year')} ราคา {s.get('price')}.-" for s in stock[:5]])

    prompt = f"""คุณคือ 'หลงจื่อบอท' พนักงานขายมืออาชีพประจำ หลงจื่อ กรุ๊ป
ข้อมูลจริงในสต็อก: {stock_context}

หน้าที่ของคุณ:
1. ถ้ามีสินค้า: สรุปสเปกและราคา (ใส่คอมม่าที่ราคาด้วย) แล้วถามว่าสนใจรับกี่เส้นดีครับ?
2. ถ้าไม่มีสินค้า: ห้ามคำนวณขนาดทดแทนเองเด็ดขาด! ให้แจ้งว่า 'ขออภัยครับ ขนาดนี้ไม่มีในสต็อกชั่วคราว เดี๋ยวผมให้แอดมินเช็คคลังสำรองให้นะครับ'
3. ห้ามมโนแบรนด์หรือราคาที่ไม่มีอยู่ในข้อมูลสต็อกที่ให้ไปด้านบนนี้"""

    try:
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        return f"ขออภัยครับ ระบบขัดข้องชั่วคราว: {str(e)}"

# =========================
# 4. Message Handler
# =========================

@handler.add(MessageEvent, message=TextMessage)
def handle_line_message(event):
    msg = event.message.text.strip()
    clean_msg = clean_tire_size(msg)
    
    # ถ้าพิมพ์เลขขนาดยาง (เช่น 2656018) ให้ส่ง Flex Message ทันที
    if len(clean_msg) >= 6:
        stock = get_tire_data(msg)
        if stock:
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="พบสต็อกยาง", contents=create_flex_carousel(stock)))
            return
            
    # กรณีถามคำถามทั่วไป หรือไม่พบสต็อก ให้ AI ตอบ
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=ask_ai_with_stock(msg)))

@discord_client.event
async def on_message(message):
    if message.author == discord_client.user: return
    content = message.content.strip()
    if len(clean_tire_size(content)) >= 6:
        stock = get_tire_data(content)
        if stock:
            res = "📦 **สต็อก หลงจื่อ กรุ๊ป:**\n" + "\n".join([f"🔹 {s['brand']} {s.get('model','')} ({s['year']}) - {format(int(s['price']), ',') if str(s['price']).isdigit() else s['price']}.-" for s in stock[:5]])
            await message.channel.send(res)
            return
    await message.channel.send(ask_ai_with_stock(content))

# ... (ฟังก์ชัน run_flask และ main เหมือนเดิม) ...

if __name__ == "__main__":
    # เริ่ม Flask ใน Thread แยก
    threading.Thread(target=run_flask, daemon=True).start()
    # เริ่ม Discord Client (Blocking call)
    discord_client.run(TOKEN)
