import discord
import os
import threading
import gspread
from flask import Flask, request, abort
from anthropic import Anthropic
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
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

def get_tire_info():
    """ดึงข้อมูลราคายางจาก Google Sheets"""
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        # ต้องอัปโหลดไฟล์ service_account.json ขึ้น GitHub ด้วยนะครับ
        creds = Credentials.from_service_account_file('service_account.json', scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        return str(sheet.get_all_records())
    except Exception as e:
        print(f"Error reading sheet: {e}")
        return "ไม่มีข้อมูลราคายางในขณะนี้"

def ask_claude(user_input):
    """ส่งคำถามให้ Claude AI ประมวลผล"""
    tire_data = get_tire_info()
    system_prompt = f"คุณคือพนักงานขายผู้เชี่ยวชาญเรื่องยางรถยนต์ รถยนต์ ของร้าน 'หลงจื่อ กรุ๊ป' (Long Ci Group) นี่คือข้อมูลราคายางในสต็อกปัจจุบัน: {tire_data} โดยให้แสดงรายการราคาตั้งแต่ปีเก่าสุด ไปถึงปีใหม่สุด แยกเป็นแบรนด์ พร้อมสร้างบับเบิ้ลให้สวยงาม ตอบลูกค้าด้วยความสุภาพเสมอ"
    
    response = anthropic.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=1000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_input}]
    )
    return response.content[0].text

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
    reply_text = ask_claude(event.message.text)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

# =========================
# 4. ส่วนของ Discord Setup
# =========================
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"✅ Discord Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    
    reply_text = ask_claude(message.content)
    await message.channel.send(reply_text)

# =========================
# 5. การรันระบบ (Threading)
# =========================
def run_flask():
    # Railway จะจ่าย Port ให้เราอัตโนมัติผ่าน os.environ.get("PORT")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

if __name__ == "__main__":
    # แยกสายงานให้ Flask (LINE) ทำงานคู่กับ Discord
    threading.Thread(target=run_flask).start()
    client.run(TOKEN)
