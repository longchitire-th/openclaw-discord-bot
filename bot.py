import discord
import os
import threading
import gspread
import re
from flask import Flask, request, abort
from anthropic import Anthropic
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
from google.oauth2.service_account import Credentials

# =========================
# 1. ตั้งค่าตัวแปร
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_CHANNEL_SECRET")
SHEET_ID = os.getenv("SPREADSHEET_ID")

# =========================
# 2. ตั้งค่าระบบ AI และฐานข้อมูล
# =========================
anthropic = Anthropic(api_key=ANTHROPIC_API_KEY)
line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)
app = Flask(__name__)

# ตั้งค่า Discord Intents (สร้างตัวแปร client ไว้ล่วงหน้ากัน Error)
intents = discord.Intents.default()
intents.message_content = True
discord_client = discord.Client(intents=intents)

def clean_text(text):
    """ลบอักขระพิเศษเพื่อให้ค้นหาได้ทุกรูปแบบ"""
    return re.sub(r'[^a-zA-Z0-9]', '', str(text)).lower()

def get_tire_data(user_input):
    """ระบบค้นหาอัจฉริยะ รองรับ 265/60R18, 33x12.5R15, 195R14"""
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file('service_account.json', scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        records = sheet.get_all_records()
        
        user_clean = clean_text(user_input)
        
        # ค้นหาในฐานข้อมูล
        matches = []
        for r in records:
            db_size = clean_text(r.get('size_key', ''))
            # ค้นหาแบบกว้างเพื่อรองรับทุกลักษณะการพิมพ์
            if user_clean == db_size or db_size in user_clean:
                matches.append(r)
        
        if not matches:
            return None

        # หาปีใหม่ที่สุดของแต่ละแบรนด์
        latest_by_brand = {}
        for r in matches:
            brand = r.get('brand', 'Unknown')
            year = int(r.get('year', 0))
            if brand not in latest_by_brand or year > int(latest_by_brand[brand].get('year', 0)):
                latest_by_brand[brand] = r
                
        return list(latest_by_brand.values())
    except Exception as e:
        print(f"Database Error: {e}")
        return None

def ask_ai_expert(user_input):
    """AI ตอบคำถามเรื่องสเป็ครถ ล้อ และการแนะนำยาง"""
    try:
        system_prompt = """คุณคือผู้เชี่ยวชาญด้านยางรถยนต์และล้อแม็ก 
        ตอบคำถามเรื่องการเลือกเบอร์ยางให้เหมาะกับรุ่นรถ สเป็คล้อ (Offset/PCD) 
        และคำแนะนำทั่วไปเกี่ยวกับการใช้รถ ตอบด้วยความสุภาพและเป็นมืออาชีพ"""

        response = anthropic.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=800,
            system=system_prompt,
            messages=[{"role": "user", "content": user_input}]
        )
        return response.content[0].text
    except Exception as e:
        return "ขออภัยครับ ติดขัดบางประการในการประมวลผลคำถามนี้"

def create_flex_carousel(tire_list):
    """สร้างบัลเบิ้ลสไลด์ข้าง พร้อมปุ่ม Action"""
    bubbles = []
    for item in tire_list:
        brand = item.get('brand', '-')
        year = item.get('year', '-')
        price = item.get('price', '0')
        model = item.get('model', '-')
        size_display = item.get('ขนาด', '-') # คอลัมน์ A

        bubble = {
            "type": "bubble",
            "header": {
                "type": "box", "layout": "horizontal",
                "contents": [
                    {"type": "image", "url": "https://lctyre.com/wp-content/uploads/2025/05/GYBL-2.png", "size": "xxs", "aspectMode": "fit"},
                    {"type": "text", "text": "LONG CI GROUP", "weight": "bold", "color": "#1DB446", "size": "sm", "margin": "sm"}
                ]
            },
            "body": {
                "type": "box", "layout": "vertical",
                "contents": [
                    {"type": "text", "text": brand, "weight": "bold", "size": "xl"},
                    {"type": "text", "text": f"รุ่น: {model}", "size": "sm", "color": "#666666"},
                    {"type": "separator", "margin": "md"},
                    {"type": "box", "layout": "vertical", "margin": "md", "contents": [
                        {"type": "text", "text": f"ขนาด: {size_display}", "size": "sm"},
                        {"type": "text", "text": f"ปีผลิต: {year}", "size": "sm"},
                        {"type": "text", "text": f"ราคา: {price}.-", "size": "lg", "weight": "bold", "color": "#ff0000"}
                    ]}
                ]
            },
            "footer": {
                "type": "box", "layout": "vertical",
                "contents": [
                    {"type": "button", "action": {"type": "message", "label": "สนใจรุ่นนี้", "text": f"สนใจ {brand} {size_display}"}, "style": "primary", "color": "#1DB446"}
                ]
            }
        }
        bubbles.append(bubble)
    return {"type": "carousel", "contents": bubbles[:10]}

# =========================
# 3. ส่วนเชื่อมต่อ (LINE & Discord)
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
    user_msg = event.message.text
    # ค้นหาในฐานข้อมูลก่อน
    tire_results = get_tire_data(user_msg)
    
    if tire_results:
        carousel = create_flex_carousel(tire_results)
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="ข้อมูลยาง", contents=carousel))
    else:
        # ถ้าหาไม่เจอ ให้ AI ตอบคำแนะนำทั่วไป
        ai_reply = ask_ai_expert(user_msg)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=ai_reply))

@discord_client.event
async def on_message(message):
    if message.author == discord_client.user: return
    tire_results = get_tire_data(message.content)
    if tire_results:
        reply = "📦 **รายการยางแนะนำ:**\n"
        for item in tire_results:
            reply += f"🔹 {item.get('brand')} ปี {item.get('year')} ราคา {item.get('price')}.-\n"
        await message.channel.send(reply)
    else:
        await message.channel.send(ask_ai_expert(message.content))

# =========================
# 4. เริ่มต้นระบบ
# =========================
def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    discord_client.run(TOKEN)
