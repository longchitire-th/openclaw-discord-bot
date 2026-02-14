import discord
import os
import threading
import gspread
import re
import json
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

anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)
app = Flask(__name__)

# =========================
# 2. UI Helper (Flex Message Generator)
# =========================

def create_tire_carousel(tire_list):
    """สร้างบัลเบิ้ลสไลด์ข้างแบบมืออาชีพ"""
    bubbles = []
    for item in tire_list[:10]: # แสดงสูงสุด 10 รายการ
        brand = str(item.get('brand', 'ไม่ระบุ')).upper()
        model = str(item.get('model', '-'))
        year = str(item.get('year', '-'))
        price = str(item.get('price', '0'))
        size = str(item.get('ขนาด', '-'))

        bubble = {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box", "layout": "horizontal", "contents": [
                    {"type": "image", "url": "https://lctyre.com/wp-content/uploads/2025/05/GYBL-2.png", "size": "xxs", "aspectMode": "fit", "flex": 1},
                    {"type": "text", "text": "LONG CI GROUP", "weight": "bold", "color": "#1DB446", "size": "sm", "flex": 4, "gravity": "center"}
                ]
            },
            "body": {
                "type": "box", "layout": "vertical", "contents": [
                    {"type": "text", "text": f"{brand} {model}", "weight": "bold", "size": "xl", "wrap": True, "color": "#111111"},
                    {"type": "text", "text": f"ขนาด: {size}", "size": "sm", "color": "#666666", "margin": "sm"},
                    {"type": "separator", "margin": "md"},
                    {"type": "box", "layout": "vertical", "margin": "md", "spacing": "sm", "contents": [
                        {"type": "box", "layout": "horizontal", "contents": [
                            {"type": "text", "text": "ปีผลิต (DOT)", "size": "sm", "color": "#555555", "flex": 1},
                            {"type": "text", "text": year, "size": "sm", "color": "#111111", "align": "end", "weight": "bold", "flex": 1}
                        ]},
                        {"type": "box", "layout": "horizontal", "contents": [
                            {"type": "text", "text": "ราคาต่อเส้น", "size": "sm", "color": "#555555", "flex": 1},
                            {"type": "text", "text": f"฿{price}.-", "size": "lg", "color": "#ff0000", "weight": "bold", "align": "end", "flex": 1}
                        ]}
                    ]}
                ]
            },
            "footer": {
                "type": "box", "layout": "vertical", "contents": [
                    {"type": "button", "action": {"type": "message", "label": "🛒 สั่งซื้อ / สอบถาม", "text": f"สนใจสั่งซื้อ {brand} {size} ปี {year}"}, "style": "primary", "color": "#1DB446"}
                ]
            }
        }
        bubbles.append(bubble)
    return {"type": "carousel", "contents": bubbles}

# =========================
# 3. Database & AI Logic
# =========================

def get_tire_inventory(query=""):
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file('service_account.json', scopes=scope)
        gs_client = gspread.authorize(creds)
        sheet = gs_client.open_by_key(SHEET_ID).sheet1
        records = sheet.get_all_records()

        clean_query = re.sub(r'[^0-9]', '', query)
        if not clean_query: return []

        matches = []
        for r in records:
            db_size_key = re.sub(r'[^0-9]', '', str(r.get('size_key', '')))
            if clean_query == db_size_key:
                matches.append(r)
        
        # เรียงปีใหม่ไปเก่า
        return sorted(matches, key=lambda x: str(x.get('year', '0')), reverse=True)
    except Exception as e:
        print(f"❌ Database Error: {e}")
        return []

def ask_ai_salesman(user_input):
    """AI พนักงานขายที่สรุปข้อมูลจาก Data"""
    stock_results = get_tire_inventory(user_input)
    # ตัดข้อมูลให้ AI เฉพาะที่จำเป็นเพื่อความรวดเร็ว
    stock_summary = [{"brand": r.get('brand'), "year": r.get('year'), "price": r.get('price')} for r in stock_results]

    system_prompt = f"""คุณคือพนักงานขายของร้าน 'หลงจื่อ กรุ๊ป'
    นี่คือข้อมูลสต็อกปัจจุบัน: {json.dumps(stock_summary, ensure_ascii=False)}
    หากลูกค้าถามขนาดยาง ให้คุณตอบสั้นๆ ว่า 'นี่คือรายการยางในสต็อกครับ' 
    หากลูกค้าถามคำถามทั่วไป ให้แนะนำตามความเชี่ยวชาญ และปิดการขายด้วยความสุภาพ"""

    try:
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_input}]
        )
        return response.content[0].text, stock_results
    except Exception as e:
        return f"ขออภัยครับ ติดขัดการประมวลผล: {e}", []

# =========================
# 4. Webhook & Discord
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
    msg = event.message.text
    ai_text, stock_data = ask_ai_salesman(msg)
    
    # ส่งคำตอบ AI พร้อม Flex Carousel
    messages = [TextSendMessage(text=ai_text)]
    if stock_data:
        carousel = create_tire_carousel(stock_data)
        messages.append(FlexSendMessage(alt_text="เช็คราคายาง หลงจื่อ", contents=carousel))
    
    line_bot_api.reply_message(event.reply_token, messages)

# Discord Logic
discord_intents = discord.Intents.default()
discord_intents.message_content = True
discord_client = discord.Client(intents=discord_intents)

@discord_client.event
async def on_message(message):
    if message.author == discord_client.user: return
    ai_text, stock_data = ask_ai_salesman(message.content)
    reply = f"🤖 AI: {ai_text}\n"
    if stock_data:
        reply += "\n📦 **รายการในสต็อก:**\n"
        for s in stock_data[:10]:
            reply += f"🔹 {s.get('brand')} | ปี {s.get('year')} | ราคา {s.get('price')}.- (ขนาด {s.get('ขนาด')})\n"
    await message.channel.send(reply)

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    discord_client.run(TOKEN)
