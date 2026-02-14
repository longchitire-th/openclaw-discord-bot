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
# 2. Database Logic (Google Sheets)
# =========================

def get_tire_data(query=""):
    """ค้นหายางตามขนาดที่ลูกค้าพิมพ์มา"""
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file('service_account.json', scopes=scope)
        gs_client = gspread.authorize(creds)
        sheet = gs_client.open_by_key(SHEET_ID).sheet1
        records = sheet.get_all_records()

        # ทำความสะอาดคำค้นหา (เช่น 2656018 หรือ 265/60R18 ให้เหลือแต่เลข)
        clean_query = re.sub(r'[^0-9]', '', query)
        
        matches = []
        for r in records:
            # ดึงข้อมูลโดยไม่สนตัวพิมพ์เล็ก-ใหญ่ และรองรับชื่อ Column หลายแบบ
            brand = r.get('Brand', r.get('แบรนด์', 'ไม่ระบุ'))
            year = str(r.get('Year', r.get('ปี', '0')))
            price = str(r.get('Price', r.get('ราคา', '0')))
            size_key = re.sub(r'[^0-9]', '', str(r.get('size_key', r.get('ขนาด', ''))))

            if not clean_query or clean_query in size_key:
                matches.append({'brand': brand, 'year': year, 'price': price})

        # เรียงลำดับจากปีใหม่ไปเก่า (เพื่อปิดการขายของดีก่อน)
        return sorted(matches, key=lambda x: x['year'], reverse=True)
    except Exception as e:
        print(f"❌ Sheet Error: {e}")
        return None

# =========================
# 3. UI Logic (Flex Message)
# =========================

def create_flex_message(tire_list, query_text):
    if not tire_list:
        return {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "ไม่พบข้อมูลขนาดนี้ในสต็อกครับ"}]}}

    contents = []
    for item in tire_list[:10]: # แสดงสูงสุด 10 รายการป้องกัน Flex ยาวเกินไป
        contents.append({
            "type": "box", "layout": "horizontal", "contents": [
                {"type": "text", "text": item['brand'], "weight": "bold", "flex": 2},
                {"type": "text", "text": f"ปี {item['year']}", "size": "sm", "color": "#666666", "flex": 1},
                {"type": "text", "text": f"{item['price']}.-", "align": "end", "weight": "bold", "color": "#ff0000", "flex": 2}
            ], "margin": "md"
        })

    return {
        "type": "bubble",
        "header": {
            "type": "box", "layout": "horizontal", "contents": [
                {"type": "image", "url": "https://www.lctyre.com/wp-content/uploads/2024/01/logo-lctyre.png", "size": "xxs", "aspectMode": "fit", "flex": 1},
                {"type": "text", "text": "LONG CI GROUP", "weight": "bold", "color": "#1DB446", "flex": 4, "gravity": "center"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "contents": [
                {"type": "text", "text": f"ผลการค้นหา: {query_text}", "weight": "bold", "size": "md"},
                {"type": "separator", "margin": "md"},
                {"type": "box", "layout": "vertical", "margin": "md", "contents": contents}
            ]
        }
    }

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
    msg = event.message.text
    data = get_tire_data(msg)
    
    if data:
        flex = create_flex_message(data, msg)
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="เช็คสต็อกหลงจื่อ", contents=flex))
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ขออภัยครับ ไม่พบข้อมูลยางขนาดที่ระบุ"))

# Discord Setup
discord_intents = discord.Intents.default()
discord_intents.message_content = True
discord_client = discord.Client(intents=discord_intents)

@discord_client.event
async def on_message(message):
    if message.author == discord_client.user: return
    data = get_tire_data(message.content)
    if data:
        reply = f"📦 **สต็อก หลงจื่อ กรุ๊ป (ขนาด: {message.content})**\n"
        for item in data[:15]:
            reply += f"🔹 {item['brand']} ปี {item['year']} | ราคา {item['price']}.-\n"
        await message.channel.send(reply)
    else:
        await message.channel.send("❌ ไม่พบข้อมูลในสต็อกครับ")

# =========================
# 5. Execution
# =========================
def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    discord_client.run(TOKEN)
