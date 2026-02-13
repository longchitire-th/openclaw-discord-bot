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

# =========================
# Ready Event
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
            max_tokens=300,
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
