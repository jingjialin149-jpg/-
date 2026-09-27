import os
import discord
from google import genai

# ==================== 1. 設定區域 (從環境變數讀取) ====================
# 優先讀取 Railway 的環境變數，若在本地電腦執行則 fallback 讀取備用值
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY")

# ==================== 2. 初始化 ====================
ai_client = genai.Client(api_key=GEMINI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

SYSTEM_PROMPT = """
你現在是安裝在 Discord 伺服器中的『浴室安全小幫手』專題 AI 守護衛士。
硬體架構：ESP32 搭配 6 顆 Sharp 紅外線測距感測器做 3x3 網格交叉偵測，不使用攝影機以維護隱私。
職責：回答使用者關於浴室防跌安全、長者照護與跌倒緊急應變步驟。語氣沉穩、條理分明、簡短清楚。
"""

@bot.event
async def on_ready():
    print(f"機器人已成功上線！名稱：{bot.user}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # 當有人 tag 機器人時觸發 AI 回覆
    if bot.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        user_query = message.clean_content.replace(f"@{bot.user.name}", "").strip()
        
        if not user_query:
            await message.channel.send("你好！我是浴室安全小幫手，請問有什麼浴室安全或照護問題想了解嗎？")
            return

        async with message.channel.typing():
            try:
                response = ai_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        {"role": "system", "parts": [{"text": SYSTEM_PROMPT}]},
                        {"role": "user", "parts": [{"text": user_query}]}
                    ]
                )
                await message.reply(response.text)
            except Exception as e:
                print(f"錯誤: {e}")
                await message.reply("目前連線忙碌中，請稍後再試一次！")

bot.run(DISCORD_BOT_TOKEN)
