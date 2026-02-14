import discord
import os
import threading
import gspread
import json
import re
from flask import Flask, request, abort
from anthropic import Anthropic
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
from google.oauth2.service_account import Credentials

# =========================
# 1. การตั้งค่าตัวแปร
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_CHANNEL_SECRET")
SHEET_ID = os.getenv("SPREADSHEET_ID")

# =========================
# 2. การตั้งค่าระบบ
# =========================
anthropic = Anthropic(api_key=ANTHROPIC_API_KEY)
line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)
app = Flask(__name__)

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
        
        # 1. ตรวจสอบว่าเป็นคำถามทั่วไป (Consultation) หรือการค้นหา (Search)
        # ถ้าไม่มีตัวเลขที่ดูเหมือนขนาดยาง ให้ส่งไปให้ AI ตอบ
        if not re.search(r'\d', user_input):
            return None, "consult"

        # 2. ค้นหาในฐานข้อมูล (Search Mode)
        matches = []
        for r in records:
            db_size = clean_text(r.get('size_key', ''))
            # ค้นหาแบบกว้าง (Partial Match) เพื่อรองรับ 19514 หรือ 33125015
            if user_clean in db_size or db_size in user_clean:
                matches.append(r)
        
        if not matches:
            return None, "consult" # ถ้าหาไม่เจอ ให้ AI ช่วยแนะนำแทน

        # จัดกลุ่มและหาปีล่าสุด
        latest_by_brand = {}
        for r in matches:
            brand = r.get('brand', 'Unknown')
            year = int(r.get('year', 0))
            if brand not in latest_by_brand or year > int(latest_by_brand[brand].get('year', 0)):
                latest_by_brand[brand] = r
                
        return list(latest_by_brand.values()), "summary"

    except Exception as e:
        print(f"Error: {e}")
        return [], "error"

def ask_ai_expert(user_input):
    """AI พนักงานขายมือโปร ตอบคำถามเรื่องสเป็ครถ ล้อ และยาง"""
    try:
        # ดึงข้อมูลจาก Sheets ไปให้ AI ใช้เป็นฐานความรู้ (ถ้ามี)
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file('service_account.json', scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        tire_data = str(sheet.get_all_records()[:20]) # ส่งตัวอย่างข้อมูลให้ AI

        system_prompt = f"""คุณคือพนักงานขายอัจฉริยะของร้าน 'หลงจื่อ กรุ๊ป' (Long Ci Group) 
        ที่มีความเชี่ยวชาญเรื่องยางรถยนต์ (รวมถึงยาง Off-road, กระบะบรรทุก) สเป็คล้อแม็ก และการแต่งรถ
        นี่คือข้อมูลสต็อกบางส่วน: {tire_data}
        
        หน้าที่ของคุณ:
        1. แนะนำขนาดยางที่เหมาะสมกับรถรุ่นที่ลูกค้าถาม
        2. ตอบคำถามเรื่องสเป็คล้อ เช่น Offset, PCD หรือความกว้างล้อ
        3. ถ้าลูกค้าถามขนาดยางที่ไม่มีในสต็อก ให้แนะนำขนาดใกล้เคียงหรือรุ่นที่เหมาะสม
        4. ตอบด้วยความสุภาพ มืออาชีพ และปิดการขายให้ได้"""

        response = anthropic.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=800,
            system=system_prompt,
            messages=[{"role": "user", "content": user_input}]
        )
        return response.content[0].text
    except Exception as e:
        return f"ขออภัยครับพี่อิทธิพล ติดปัญหาที่ AI: {e}"

def create_flex_carousel(tire_list):
    """สร้างบัลเบิ้ลสไลด์ข้าง พร้อมโลโก้และปุ่ม Action"""
    bubbles = []
    for item in tire_list:
        brand = item.get('brand', 'ไม่ระบุ')
        year = item.get('year', 'ไม่ระบุ')
        price = item.get('price', '0')
        model = item.get('model', '-')
        size_display = item.get('ขนาด', '-')

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
                    {"type": "button", "action": {"type": "message", "label": "สนใจรุ่นนี้", "text": f"ต้องการสั่งซื้อ {brand} {size_display} ปี {year}"}, "style": "primary", "color": "#1DB446"}
                ]
            }
        }
        bubbles.append(bubble)
    return {"type": "carousel", "contents": bubbles[:10]}

# =========================
# 3. Webhook (LINE & Discord)
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
    results, mode = get_tire_data(user_msg)
    
    if mode == "summary" and results:
        carousel = create_flex_carousel(results)
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="ข้อมูลยาง หลงจื่อ กรุ๊ป", contents=carousel))
    else:
        # ถ้าหาไม่เจอ หรือเป็นคำถามทั่วไป ให้ AI ตอบ
        ai_reply = ask_ai_expert(user_msg)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=ai_reply))

# (ส่วน Discord และการรัน Threading เหมือนเดิม)
def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    client.run(TOKEN)
