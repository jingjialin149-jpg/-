import os
import discord
from google import genai

# ==================== 1. 設定區域 (支援多組 Key 備援替換) ====================
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")

# 讀取主要與備用的 Gemini Key
raw_keys = [
    os.getenv("GEMINI_API_KEY"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3")
]
# 過濾掉空白的 Key，保留有效清單
API_KEYS = [k.strip() for k in raw_keys if k and k.strip()]

if not API_KEYS:
    print("❌ 警告：未設定任何 GEMINI_API_KEY！")
else:
    print(f"✅ 成功載入 {len(API_KEYS)} 組 Gemini API Key！")

current_key_index = 0

def get_current_client():
    """取得當前可用的 Gemini Client"""
    global current_key_index
    return genai.Client(api_key=API_KEYS[current_key_index])

def switch_to_next_key():
    """當前 Key 額度用盡時，自動切換至下一把備用 Key"""
    global current_key_index
    if len(API_KEYS) > 1:
        current_key_index = (current_key_index + 1) % len(API_KEYS)
        print(f"⚠️ 偵測到額度限制或錯誤，已自動切換至第 {current_key_index + 1} 組 Key！")
    else:
        print("⚠️ 僅有一組 Key，無法切換備援。")

# ==================== 2. 初始化 Discord ====================
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
            success = False
            # 最多嘗試與擁有的 Key 數量相同的次數
            for _ in range(max(1, len(API_KEYS))):
                try:
                    ai_client = get_current_client()
                    response = ai_client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[
                            {"role": "system", "parts": [{"text": SYSTEM_PROMPT}]},
                            {"role": "user", "parts": [{"text": user_query}]}
                        ]
                    )
                    await message.reply(response.text)
                    success = True
                    break
                except Exception as e:
                    print(f"第 {current_key_index + 1} 組 Key 呼叫失敗: {e}")
                    switch_to_next_key() # 自動換下一把 Key 重試
            
            if not success:
                await message.reply("抱歉，目前所有 AI 額度均暫時滿載，請稍候片刻再試！")

bot.run(DISCORD_BOT_TOKEN)
