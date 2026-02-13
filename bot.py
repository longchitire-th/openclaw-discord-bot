import discord
import os
from anthropic import Anthropic

TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

client = discord.Client(intents=discord.Intents.default())
anthropic = Anthropic(api_key=ANTHROPIC_API_KEY)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    user_input = message.content

    response = anthropic.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=300,
        messages=[{"role": "user", "content": user_input}]
    )

    await message.channel.send(response.content[0].text)

client.run(TOKEN)
