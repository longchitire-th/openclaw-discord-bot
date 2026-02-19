import os
import re
import json
import gspread
from flask import Flask, request, abort
from google.oauth2.service_account import Credentials
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage

# =========================
# 1. Config
# =========================
LINE_ACCESS_TOKEN  = os.environ.get("LINE_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
SHEET_ID   = os.environ.get("SHEET_ID", "1IhV_qpsPxW2VXp1KpvcLSgodKH-Ngk6yojrwK7Ysrdg")
SHEET_NAME = os.environ.get("SHEET_NAME", "ตาราง1")

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler      = WebhookHandler(LINE_CHANNEL_SECRET)
app          = Flask(__name__)

# =========================
# 2. Google Sheets
# =========================
def get_sheet():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        sa_info = json.loads(sa_json)
        creds = Credentials.from_service_account_info(sa_info, scopes=scope)
    else:
        creds = Credentials.from_service_account_file("service_account.json", scopes=scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

def search_tires(query):
    try:
        sheet   = get_sheet()
        records = sheet.get_all_records()
        q_digit = re.sub(r"[^0-9]", "", query)
        if not q_digit:
            return []
        matched = []
        for r in records:
            sk = re.sub(r"[^0-9]", "", str(r.get("size_key", "")))
            sz = re.sub(r"[^0-9]", "", str(r.get("ขนาด", "")))
            if q_digit == sk or q_digit == sz:
                matched.append(r)
        return sorted(matched, key=lambda x: str(x.get("year", "0")), reverse=True)
    except Exception as e:
        print(f"❌ Sheet Error: {e}")
        return []

# =========================
# 3. รูปโลโก้/ยางแต่ละแบรนด์
# =========================
BRAND_IMAGES = {
    "BRIDGESTONE": "https://upload.wikimedia.org/wikipedia/commons/thumb/6/60/Bridgestone_logo.svg/320px-Bridgestone_logo.svg.png",
    "DUNLOP":      "https://upload.wikimedia.org/wikipedia/commons/thumb/4/44/Dunlop_Logo.svg/320px-Dunlop_Logo.svg.png",
    "MICHELIN":    "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9e/Michelin_Logo.svg/320px-Michelin_Logo.svg.png",
    "YOKOHAMA":    "https://upload.wikimedia.org/wikipedia/commons/thumb/5/5d/Yokohama_Rubber_Company_logo.svg/320px-Yokohama_Rubber_Company_logo.svg.png",
    "PIRELLI":     "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e5/Pirelli_logo.svg/320px-Pirelli_logo.svg.png",
    "CONTINENTAL": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/40/Continental_AG_logo.svg/320px-Continental_AG_logo.svg.png",
    "GOODYEAR":    "https://upload.wikimedia.org/wikipedia/commons/thumb/6/68/Goodyear-Logo.svg/320px-Goodyear-Logo.svg.png",
    "MAXXIS":      "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6a/Maxxis_logo.svg/320px-Maxxis_logo.svg.png",
    "TOYO":        "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9c/Toyo_Tires_logo.svg/320px-Toyo_Tires_logo.svg.png",
    "FALKEN":      "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6b/Falken_Tyre_logo.svg/320px-Falken_Tyre_logo.svg.png",
}

def get_brand_image(brand):
    key = brand.upper().strip()
    return BRAND_IMAGES.get(key, f"https://placehold.co/200x200/eeeeee/333?text={brand}")

# =========================
# 4. Flex Message — หน้าตาตามรูป
#    header สีเหลือง "รหัส XXX"
#    body: ซ้าย=ข้อมูล, ขวา=รูปยาง
#    footer: ชื่อร้าน
# =========================
def build_bubble(tire):
    brand = str(tire.get("brand", "")).upper()
    model = str(tire.get("model", "-"))
    size  = str(tire.get("ขนาด", "-"))
    stock = str(tire.get("stock", ""))      # คงเหลือ (ถ้ามีคอลัมน์นี้ใน Sheet)
    dot   = str(tire.get("year", "-"))      # ปีผลิต/DOT
    price = tire.get("price", 0)

    price_text = f"฿{int(price):,}.-" if price else "ติดต่อฝ่ายขาย บาท"
    stock_text = f"{stock} เส้น" if stock and stock not in ["-", ""] else "-"

    img_url = get_brand_image(brand)

    return {
        "type": "bubble",
        "size": "kilo",
        # ---- HEADER สีเหลือง ----
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#F5C518",
            "paddingAll": "14px",
            "contents": [
                {
                    "type": "text",
                    "text": f"รหัส {size}",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#1a1a1a"
                }
            ]
        },
        # ---- BODY: ซ้าย=ข้อมูล, ขวา=รูป ----
        "body": {
            "type": "box",
            "layout": "horizontal",
            "paddingAll": "14px",
            "spacing": "md",
            "contents": [
                # ซ้าย — ข้อมูล
                {
                    "type": "box",
                    "layout": "vertical",
                    "flex": 3,
                    "spacing": "xs",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"{brand} - {model}",
                            "weight": "bold",
                            "size": "sm",
                            "color": "#111111",
                            "wrap": True
                        },
                        {
                            "type": "text",
                            "text": f"รหัส: {size}",
                            "size": "xs",
                            "color": "#555555"
                        },
                        {
                            "type": "text",
                            "text": f"คงเหลือ: {stock_text}",
                            "size": "xs",
                            "color": "#555555"
                        },
                        {
                            "type": "text",
                            "text": f"DOT: {dot}",
                            "size": "xs",
                            "color": "#555555"
                        },
                        {
                            "type": "text",
                            "text": f"ราคา: {price_text}",
                            "size": "xs",
                            "color": "#555555",
                            "wrap": True
                        }
                    ]
                },
                # ขวา — รูป
                {
                    "type": "image",
                    "url": img_url,
                    "flex": 2,
                    "size": "full",
                    "aspectMode": "fit",
                    "aspectRatio": "1:1"
                }
            ]
        },
        # ---- FOOTER ----
        "footer": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "8px",
            "backgroundColor": "#f9f9f9",
            "contents": [
                {
                    "type": "text",
                    "text": "หลงจื่อ กรุ๊ป",
                    "size": "xxs",
                    "color": "#aaaaaa",
                    "align": "end"
                }
            ]
        }
    }

def build_flex(tire_list):
    bubbles = [build_bubble(t) for t in tire_list[:10]]
    if len(bubbles) == 1:
        return bubbles[0]
    return {"type": "carousel", "contents": bubbles}

# =========================
# 5. Webhook
# =========================
@app.route("/callback", methods=["POST"])
def callback():
    sig  = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, sig)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg    = event.message.text.strip()
    digits = re.sub(r"[^0-9]", "", msg)

    if len(digits) < 6:
        # ข้อความทั่วไป
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text="👋 สวัสดีครับ! ระบบค้นหายาง\n\n"
                     "🔍 พิมพ์ขนาดยางได้เลยครับ เช่น:\n"
                     "• 265/60R18\n• 265/60/18\n• 2656018\n"
                     "• 195R14\n• 33x12.50R15"
            )
        )
        return

    results = search_tires(msg)

    if not results:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f"❌ ไม่พบยางขนาด \"{msg}\" ในสต็อก\n\n"
                     "💡 ลองพิมพ์ใหม่ เช่น:\n"
                     "• 265/60R18\n• 265/60/18\n• 2656018"
            )
        )
        return

    flex = build_flex(results)
    line_bot_api.reply_message(
        event.reply_token,
        [
            TextSendMessage(text=f"🔍 พบ {len(results)} รายการสำหรับ \"{msg}\""),
            FlexSendMessage(alt_text=f"ราคายาง {msg}", contents=flex)
        ]
    )

# =========================
# 6. Health Check
# =========================
@app.route("/", methods=["GET"])
def health():
    return {"status": "ok"}, 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
