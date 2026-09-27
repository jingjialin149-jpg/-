import os
import re
import discord
from google import genai
from google.genai import types

# ==================== 1. 環境變數讀取 (支援單變數逗號分隔或多變數命名) ====================
# 同時相容 DISCORD_BOT_TOKEN 或 DISCORD_TOKEN
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")

# 讀取 GEMINI_API_KEY (支援用逗號分開多把 Key)
raw_keys_str = os.getenv("GEMINI_API_KEY", "")
keys_list = [k.strip() for k in raw_keys_str.split(",") if k.strip()]

# 讀取 GEMINI_API_KEY_2, GEMINI_API_KEY_3, GEMINI_API_KEY_4, GEMINI_API_KEY_5
for i in range(2, 6):
    extra_key = os.getenv(f"GEMINI_API_KEY_{i}")
    if extra_key and extra_key.strip():
        keys_list.append(extra_key.strip())

# 去除重複項
API_KEYS = list(dict.fromkeys(keys_list))

current_key_index = 0

def get_current_client():
    """取得目前使用的 Gemini 客戶端"""
    global current_key_index
    if not API_KEYS:
        raise ValueError("未讀取到任何有效的 GEMINI_API_KEY，請檢查環境變數！")
    return genai.Client(api_key=API_KEYS[current_key_index])

def switch_to_next_key():
    """切換至下一組備援 Key"""
    global current_key_index
    if len(API_KEYS) > 1:
        current_key_index = (current_key_index + 1) % len(API_KEYS)
        print(f"⚠️ 偵測到限制或呼叫失敗，已自動切換至第 {current_key_index + 1} 組 Key")
        return True
    return False

# ==================== 2. 初始化 Discord 與系統 Prompt ====================
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

SYSTEM_PROMPT = """
你現在是安裝在 Discord 伺服器中的『浴室安全小幫手』。
專題特色：搭配 ESP32 進行浴室防跌偵測，不使用攝影機以維護使用者隱私。
職責：專門回答長輩照護、浴室防跌安全與緊急急救步驟。
請一律使用標準繁體中文（台灣），語氣沉穩、條理分明、親切且簡短扼要。
"""

# 依序嘗試的官方穩定模型
MODELS_TO_TRY = ["gemini-2.5-flash", "gemini-1.5-flash"]

@bot.event
async def on_ready():
    print(f"✅ 機器人成功上線！名稱：{bot.user}")
    print(f"🔑 目前共成功載入 {len(API_KEYS)} 組 Gemini API Key 備援")

@bot.event
async def on_message(message):
    # 忽略機器人自身發布的訊息
    if message.author == bot.user:
        return

    # 判斷是否為私訊，或是在頻道中被 tag
    if bot.user in message.mentions or isinstance(message.channel, discord.DMChannel):
        clean_text = message.clean_content.replace(f"@{bot.user.name}", "").strip()
        clean_text = re.sub(r"^<@!?\d+>\s*", "", clean_text).strip()

        if not clean_text:
            await message.reply("你好！我是浴室安全小幫手，請問有什麼浴室安全或長者照護問題需要協助嗎？")
            return

        async with message.channel.typing():
            reply_text = None

            # 針對擁有的 Key 數量進行輪替嘗試
            for _ in range(max(1, len(API_KEYS))):
                try:
                    ai_client = get_current_client()

                    # 嘗試可用模型
                    for model_name in MODELS_TO_TRY:
                        try:
                            response = await ai_client.aio.models.generate_content(
                                model=model_name,
                                contents=clean_text,
                                config=types.GenerateContentConfig(
                                    system_instruction=SYSTEM_PROMPT,
                                    max_output_tokens=600,
                                ),
                            )
                            reply_text = response.text
                            break
                        except Exception as model_err:
                            print(f"模型 {model_name} 執行失敗: {model_err}")
                            continue

                    if reply_text:
                        break
                    else:
                        switch_to_next_key()
                except Exception as key_err:
                    print(f"第 {current_key_index + 1} 組 Key 失敗: {key_err}")
                    switch_to_next_key()

            if reply_text:
                await message.reply(reply_text[:2000])
            else:
                await message.reply("抱歉，目前所有 AI 額度均暫時滿載或連線異常，請稍候片刻再試！")

# 啟動機器人
bot.run(DISCORD_TOKEN)
