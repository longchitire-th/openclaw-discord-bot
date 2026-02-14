import discord
import os
import threading
import gspread
import json
from flask import Flask, request, abort
from anthropic import Anthropic
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, FlexSendMessage
from google.oauth2.service_account import Credentials

# =========================
# 1. การตั้งค่าตัวแปร (ดึงจาก Railway)
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_CHANNEL_SECRET")
SHEET_ID = os.getenv("SPREADSHEET_ID")

# =========================
# 2. การตั้งค่า AI และฐานข้อมูล
# =========================
anthropic = Anthropic(api_key=ANTHROPIC_API_KEY)
line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)
app = Flask(__name__)

def get_formatted_tire_data():
    """ดึงข้อมูลและจัดเรียง ปีเก่า -> ใหม่ แยกตามแบรนด์"""
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file('service_account.json', scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        records = sheet.get_all_records()
        
        # กรองข้อมูลและเรียงลำดับ (Brand แล้วตามด้วย Year)
        # ตรวจสอบชื่อหัวตารางใน Sheets ของพี่ด้วยนะครับว่าสะกด 'Brand' และ 'Year' หรือไม่
        sorted_data = sorted(records, key=lambda x: (str(x.get('Brand', '')), str(x.get('Year', '0'))))
        
        brand_summary = {}
        for item in sorted_data:
            b = item.get('Brand', 'ไม่ระบุแบรนด์')
            y = str(item.get('Year', 'ไม่ระบุปี'))
            p = str(item.get('Price', '0'))
            if b not in brand_summary:
                brand_summary[b] = []
            brand_summary[b].append(f"{y} (ราคา {p}.-)")
        
        return brand_summary
    except Exception as e:
        print(f"Error: {e}")
        return None

def create_flex_message(brand_data):
    """สร้างบัลเบิ้ล Flex Message ที่มีโลโก้บริษัท"""
    contents = []
    for brand, details in brand_data.items():
        contents.append({
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": brand, "weight": "bold", "color": "#111111", "flex": 2},
                {"type": "text", "text": ", ".join(details), "wrap": True, "color": "#666666", "size": "sm", "flex": 3, "align": "end"}
            ],
            "margin": "md"
        })

    # โครงสร้าง Flex Message
    flex_content = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "image",
                    "url": "https://www.lctyre.com/wp-content/uploads/2024/01/logo-lctyre.png", # ใส่ URL โลโก้จริงของพี่
                    "size": "xxs",
                    "aspectMode": "fit",
                    "flex": 1
                },
                {
                    "type": "text",
                    "text": "LONG CI GROUP",
                    "weight": "bold",
                    "color": "#1DB446",
                    "size": "sm",
                    "flex": 4,
                    "gravity": "center"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "รายการยางแยกตามปีผลิต", "weight": "bold", "size": "md"},
                {"type": "separator", "margin": "md"},
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "md",
                    "contents": contents
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "หลงจื่อ กรุ๊ป ยินดีให้บริการครับ", "size": "xs", "color": "#aaaaaa", "align": "center"}
            ]
        }
    }
    return flex_content

# =========================
# 3. ส่วนของ LINE Webhook
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
    data = get_formatted_tire_data()
    if data:
        flex_msg = create_flex_message(data)
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text="ข้อมูลราคายาง หลงจื่อ กรุ๊ป", contents=flex_msg)
        )
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ขออภัยครับ ไม่สามารถดึงข้อมูลได้ในขณะนี้"))

# =========================
# 4. ส่วนของ Discord Setup (ตอบเป็นข้อความปกติ)
# =========================
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"✅ Discord Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author == client.user: return
    data = get_formatted_tire_data()
    if data:
        reply = "📦 รายการยาง หลงจื่อ กรุ๊ป (ปีเก่า -> ใหม่):\n"
        for brand, details in data.items():
            reply += f"🔹 {brand}: {', '.join(details)}\n"
        await message.channel.send(reply)

# =========================
# 5. การรันระบบ
# =========================
def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    client.run(TOKEN)
