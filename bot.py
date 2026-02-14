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
# 1. ตั้งค่าตัวแปร (Railway)
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_CHANNEL_SECRET")
SHEET_ID = os.getenv("SPREADSHEET_ID")

# =========================
# 2. ตั้งค่าระบบ
# =========================
anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)
app = Flask(__name__)

# ตั้งค่า Discord (แก้ไขชื่อตัวแปรกัน Error)
intents = discord.Intents.default()
intents.message_content = True
discord_client = discord.Client(intents=intents)

def get_tire_data(user_input):
    """ระบบค้นหาสต็อกอัจฉริยะจาก Google Sheets (ขนาด, size_key, brand, model, year, price)"""
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file('service_account.json', scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        records = sheet.get_all_records()
        
        # ลบอักขระพิเศษเพื่อให้พิมพ์ 265/60R18 หรือ 2656018 ก็เจอ
        clean_query = re.sub(r'[^a-zA-Z0-9]', '', user_input).lower()
        
        matches = []
        for r in records:
            db_size = re.sub(r'[^a-zA-Z0-9]', '', str(r.get('size_key', ''))).lower()
            if clean_query == db_size or db_size in clean_query:
                matches.append(r)
        
        # เรียงปีผลิตใหม่ไปเก่า
        return sorted(matches, key=lambda x: int(x.get('year', 0)), reverse=True) if matches else []
    except Exception as e:
        print(f"Sheet Error: {e}")
        return []

def create_flex_carousel(tire_list):
    """สร้างบัลเบิ้ลรายการยางพร้อมโลโก้ หลงจื่อ กรุ๊ป"""
    bubbles = []
    for item in tire_list[:10]:
        brand, year, price, model, size = item.get('brand','-'), item.get('year','-'), item.get('price',0), item.get('model','-'), item.get('ขนาด','-')
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
                        {"type": "text", "text": f"ราคา: {price}.-", "size": "xl", "weight": "bold", "color": "#ff0000", "margin": "md"}
                    ]}
                ]
            },
            "footer": {
                "type": "box", "layout": "vertical", "contents": [
                    {"type": "button", "action": {"type": "message", "label": "สนใจสั่งซื้อ", "text": f"ต้องการ {brand} {size}"}, "style": "primary", "color": "#1DB446"}
                ]
            }
        }
        bubbles.append(bubble)
    return {"type": "carousel", "contents": bubbles}

def ask_ai_with_stock(user_msg):
    """AI พนักงานขาย: ตอบความรู้ + แจ้งสต็อก"""
    stock = get_tire_data(user_msg)
    stock_text = "\n".join([f"- {s['brand']} {s['year']} ราคา {s['price']}.-" for s in stock]) if stock else "ขณะนี้ขนาดนี้ไม่มีในสต็อก"
    
    prompt = f"ลูกค้าถามว่า: '{user_msg}'\nข้อมูลในสต็อกที่มี: {stock_text}\n\nตอบคำถามลูกค้าอย่างมืออาชีพและสรุปสต็อกที่มีให้ลูกค้าทราบด้วย"
    
    response = anthropic_client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text

# =========================
# 3. Webhook (LINE & Discord)
# =========================
@app.route("/callback", methods=['POST'])
def callback():
    signature, body = request.headers.get('X-Line-Signature'), request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_line_message(event):
    msg = event.message.text
    # กฎข้อที่ 1: ถ้าพิมพ์แค่เลขยาง (ไม่มีเว้นวรรคยาวๆ หรือคำถาม) ให้โชว์สต็อกทันที
    if re.match(r'^[\d/x.R ]+$', msg.strip()):
        stock = get_tire_data(msg)
        if stock:
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="เช็คสต็อกยาง", contents=create_flex_carousel(stock)))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ขออภัยครับ ไม่พบขนาดนี้ในสต็อก"))
    else:
        # กฎข้อที่ 2: ถามเชิงลึก ให้ AI ตอบพร้อมแทรกสต็อก
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=ask_ai_with_stock(msg)))

@discord_client.event
async def on_message(message):
    if message.author == discord_client.user: return
    # แก้ไขให้ Discord ทำงานได้เหมือน LINE
    if re.match(r'^[\d/x.R ]+$', message.content.strip()):
        stock = get_tire_data(message.content)
        if stock:
            reply = "📦 **รายการในสต็อก:**\n" + "\n".join([f"🔹 {s['brand']} ปี {s['year']} ราคา {s['price']}.-" for s in stock])
            await message.channel.send(reply)
        else:
            await message.channel.send("ไม่พบข้อมูลในสต็อกครับ")
    else:
        await message.channel.send(ask_ai_with_stock(message.content))

# =========================
# 4. Run System
# =========================
def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    discord_client.run(TOKEN)
