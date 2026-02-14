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
# 2. Database & AI Logic
# =========================

def get_tire_inventory(query=""):
    """ดึงข้อมูลสต็อกทั้งหมดหรือกรองตามขนาดเพื่อส่งให้ AI"""
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file('service_account.json', scopes=scope)
        gs_client = gspread.authorize(creds)
        sheet = gs_client.open_by_key(SHEET_ID).sheet1
        records = sheet.get_all_records()

        if not query:
            return records[:20] # ส่งตัวอย่างสต็อกให้ AI ดู

        clean_query = re.sub(r'[^0-9]', '', query)
        matches = []
        for r in records:
            db_size_key = re.sub(r'[^0-9]', '', str(r.get('size_key', '')))
            if clean_query == db_size_key:
                matches.append(r)
        
        # เรียงปีใหม่ไปเก่า
        return sorted(matches, key=lambda x: str(x.get('year', '0')), reverse=True)
    except Exception as e:
        print(f"❌ Error: {e}")
        return []

def ask_ai_salesman(user_input):
    """ให้ AI ทำหน้าที่เป็นพนักงานขาย วิเคราะห์คำถามและเสนอ Data จากสต็อก"""
    # ดึงข้อมูลสต็อกที่เกี่ยวข้องมาเตรียมไว้
    stock_results = get_tire_inventory(user_input)
    stock_context = json.dumps(stock_results, ensure_ascii=False) if stock_results else "ไม่มีในสต็อก"

    system_prompt = f"""คุณคือ 'น้องหลงจื่อ' AI พนักงานขายยางรถยนต์ของร้าน หลงจื่อ กรุ๊ป (Long Ci Group) 
    ที่มีความเชี่ยวชาญเรื่องยางและสเป็ครถยนต์
    
    นี่คือข้อมูลสต็อกปัจจุบันที่เกี่ยวข้อง: {stock_context}
    
    หน้าที่ของคุณ:
    1. ถ้าลูกค้าถามขนาดยาง ให้สรุปรายการจากสต็อก (แบรนด์, ปี, ราคา) ให้ชัดเจน
    2. ถ้าลูกค้าถามเรื่องการใช้งานรถ ให้แนะนำขนาดยางที่เหมาะสมและแจ้งสต็อกที่มี
    3. ตอบด้วยความสุภาพ มืออาชีพ และปิดการขายให้ได้โดยไม่ระบุชื่อตนเอง"""

    try:
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_input}]
        )
        return response.content[0].text
    except Exception as e:
        return f"ขออภัยครับ ติดขัดการประมวลผล: {e}"

# =========================
# 3. Webhook & Event Handlers
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
    # ให้ AI เป็นคนตอบโดยใช้ข้อมูลจาก Data (Google Sheets)
    ai_reply = ask_ai_salesman(msg)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=ai_reply))

# Discord Setup
discord_intents = discord.Intents.default()
discord_intents.message_content = True
discord_client = discord.Client(intents=discord_intents)

@discord_client.event
async def on_message(message):
    if message.author == discord_client.user: return
    ai_reply = ask_ai_salesman(message.content)
    await message.channel.send(ai_reply)

# =========================
# 4. Execution
# =========================
def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    discord_client.run(TOKEN)
