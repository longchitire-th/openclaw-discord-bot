import discord
import os
import threading
import gspread
import json
import re  # เพิ่ม regex สำหรับจัดการตัวอักษรพิเศษ
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
# 2. การตั้งค่า AI และฐานข้อมูล
# =========================
anthropic = Anthropic(api_key=ANTHROPIC_API_KEY)
line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)
app = Flask(__name__)

def get_tire_info(user_input):
    """ดึงข้อมูลราคายางและกรองตามขนาด โดยใช้หัวตารางตัวพิมพ์เล็กตาม Sheets"""
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file('service_account.json', scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        records = sheet.get_all_records()
        
        # ปรับค่าที่ลูกค้าพิมพ์ให้เหลือแต่ตัวเลข (เช่น 265/60r18 -> 2656018)
        clean_query = re.sub(r'[^0-9]', '', user_input)
        
        results = []
        for row in records:
            # ดึงค่าจากคอลัมน์ size_key (ต้องเป็นตัวพิมพ์เล็กตาม image_215065.png)
            db_size = re.sub(r'[^0-9]', '', str(row.get('size_key', '')))
            
            # ตรวจสอบว่าขนาดตรงกันหรือไม่
            if clean_query == db_size:
                results.append(row)
        
        # เรียงลำดับจากปีเก่าไปปีใหม่ (ใช้ 'year' ตัวพิมพ์เล็กตาม image_215065.png)
        sorted_results = sorted(results, key=lambda x: int(x.get('year', 0)))
        return sorted_results
    except Exception as e:
        print(f"Error reading sheet: {e}")
        return []

def create_flex_message(tire_list):
    """สร้าง Flex Message โดยดึงค่าจากหัวตารางตัวพิมพ์เล็ก"""
    brand_groups = {}
    for item in tire_list:
        # ใช้ 'brand', 'year', 'price' ตัวพิมพ์เล็กทั้งหมดตาม image_215065.png
        b = item.get('brand', 'ไม่ระบุแบรนด์')
        y = item.get('year', 'ไม่ระบุปี')
        p = item.get('price', '0')
        
        if b not in brand_groups:
            brand_groups[b] = []
        brand_groups[b].append(f"{y} (ราคา {p}.-)")

    contents = []
    for brand, details in brand_groups.items():
        contents.append({
            "type": "box",
            "layout": "vertical",
            "margin": "lg",
            "contents": [
                {"type": "text", "text": brand, "weight": "bold", "color": "#1DB446", "size": "sm"},
                {"type": "text", "text": ", ".join(details), "wrap": True, "color": "#444444", "size": "xs"}
            ]
        })
    
    # ... (ส่วนโครงสร้าง Flex อื่นๆ เหมือนเดิม)

def create_flex_message(tire_list):
    """สร้าง Flex Message บัลเบิ้ลที่มีโลโก้และจัดกลุ่มตามแบรนด์"""
    # จัดกลุ่มข้อมูลตามแบรนด์
    brand_groups = {}
    for item in tire_list:
        b = item.get('brand', 'ไม่ระบุแบรนด์')
        if b not in brand_groups: brand_groups[b] = []
        brand_groups[b].append(f"{item.get('year')} ({item.get('price')}.-)")

    contents = []
    for brand, details in brand_groups.items():
        contents.append({
            "type": "box",
            "layout": "vertical",
            "margin": "lg",
            "contents": [
                {"type": "text", "text": brand, "weight": "bold", "color": "#1DB446", "size": "sm"},
                {"type": "text", "text": ", ".join(details), "wrap": True, "color": "#444444", "size": "xs"}
            ]
        })

    flex_content = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "image",
                    "url": "https://lctyre.com/wp-content/uploads/2025/05/GYBL-2.png",
                    "size": "xxs", "aspectMode": "fit", "flex": 1
                },
                {
                    "type": "text", "text": "LONG CI GROUP", "weight": "bold", 
                    "color": "#111111", "size": "sm", "flex": 4, "gravity": "center"
                }
            ]
        },
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "📦 รายการยางแยกตามปีผลิต", "weight": "bold", "size": "md"},
                {"type": "separator", "margin": "md"},
                {"type": "box", "layout": "vertical", "contents": contents}
            ]
        }
    }
    return flex_content

# =========================
# 3. Webhook และการประมวลผล
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
    user_msg = event.message.text
    tire_results = get_tire_info(user_msg)
    
    if tire_results:
        flex_msg = create_flex_message(tire_results)
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text="ข้อมูลราคายาง หลงจื่อ กรุ๊ป", contents=flex_msg)
        )
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ขออภัยครับ ไม่พบข้อมูลขนาดยางที่ระบุ"))

# =========================
# 4. Discord Setup
# =========================
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_message(message):
    if message.author == client.user: return
    results = get_tire_info(message.content)
    if results:
        reply = "📦 รายการยาง หลงจื่อ กรุ๊ป (ปีเก่า -> ใหม่):\n"
        for item in results:
            reply += f"🔹 {item.get('brand')} ปี {item.get('year')} ราคา {item.get('price')}.-\n"
        await message.channel.send(reply)
    else:
        await message.channel.send("ไม่พบข้อมูลขนาดยางครับ")

# =========================
# 5. รันระบบ
# =========================
def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    client.run(TOKEN)
