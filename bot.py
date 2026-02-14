import discord
import os
from anthropic import Anthropic

# =========================
# ENV
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# =========================
# Discord Setup
# =========================
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


# =========================
# Claude Setup
# =========================
anthropic = Anthropic(api_key=ANTHROPIC_API_KEY)

# --- วางฟังก์ชันดึงราคายางตรงนี้ครับ ---
def get_tire_price(tire_name):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        # อย่าลืมอัปโหลดไฟล์ service_account.json ขึ้น GitHub ด้วยนะครับ
        creds = Credentials.from_service_account_file('service_account.json', scopes=scope)
        client = gspread.authorize(creds)
        
        # ดึง ID จาก Railway Shared Variables ที่คุณพี่ตั้งค่าไว้
        sheet = client.open_by_key(os.getenv("SPREADSHEET_ID")).sheet1
        records = sheet.get_all_records()
        
        for row in records:
            # แก้คำว่า 'Model' และ 'Price' ให้ตรงกับหัวตารางใน Google Sheets ของพี่นะครับ
            if tire_name.lower() in str(row.get('Model', '')).lower():
                return f"รุ่น {row.get('Model')} ราคา {row.get('Price')} บาท"
        return "ไม่พบข้อมูลรุ่นที่ระบุในฐานข้อมูลครับ"
    except Exception as e:
        return f"ระบบดึงข้อมูลขัดข้อง: {str(e)}"

# =========================
# Ready Event (โค้ดเดิมของพี่)
# =========================

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")

# =========================
# Message Event
# =========================
@client.event
async def on_message(message):

    if message.author == client.user:
        return

    user_input = message.content
    print(f"User: {user_input}")

    try:
        response = anthropic.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1000,
            # ย้าย system ออกมาวางตรงนี้ (ห้ามใส่ไว้ใน messages)
            system="คุณคือผู้เชี่ยวชาญด้านยางรถยนต์และพนักงานขายของร้าน 'หลงจื่อ กรุ๊ป' (Long Ci Group)",
            messages=[
                {"role": "user", "content": user_input}
            ]
        )


        reply = response.content[0].text
        await message.channel.send(reply)

    except Exception as e:
        await message.channel.send(f"Error: {str(e)}")

# =========================
# Run Bot
# =========================
client.run(TOKEN)
