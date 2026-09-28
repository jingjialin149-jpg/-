import os
import re
import asyncio
import discord
from aiohttp import web
from google import genai
from google.genai import types

# ==================== 1. 環境變數讀取 ====================
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))  # Railway 會自動分配 PORT

# 讀取 GEMINI_API_KEY (支援逗號或多變數)
raw_keys_str = os.getenv("GEMINI_API_KEY", "")
keys_list = [k.strip() for k in raw_keys_str.split(",") if k.strip()]
for i in range(2, 6):
    extra_key = os.getenv(f"GEMINI_API_KEY_{i}")
    if extra_key and extra_key.strip():
        keys_list.append(extra_key.strip())

API_KEYS = list(dict.fromkeys(keys_list))
current_key_index = 0

def get_current_client():
    global current_key_index
    if not API_KEYS:
        raise ValueError("未讀取到有效的 GEMINI_API_KEY！")
    return genai.Client(api_key=API_KEYS[current_key_index])

def switch_to_next_key():
    global current_key_index
    if len(API_KEYS) > 1:
        current_key_index = (current_key_index + 1) % len(API_KEYS)
        print(f"⚠️ 切換至第 {current_key_index + 1} 組 Key")
        return True
    return False

# ==================== 2. Discord 與 Gemini 設定 ====================
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

SYSTEM_PROMPT = """
你現在是安裝在 Discord 伺服器中的『浴室安全小幫手』。
專題特色：搭配 ESP32 進行浴室防跌偵測，不使用攝影機以維護使用者隱私。
職責：專門回答長輩照護、浴室防跌安全與緊急急救步驟。
請一律使用標準繁體中文（台灣），語氣沉穩、條理分明、親切且簡短扼要。
"""

MODELS_TO_TRY = ["gemini-3.8-flash", "gemini-3-flash-preview"]

async def call_gemini(prompt: str) -> str:
    """呼叫 Gemini 產生內容的共用函式"""
    for _ in range(max(1, len(API_KEYS))):
        try:
            ai_client = get_current_client()
            for model_name in MODELS_TO_TRY:
                try:
                    response = await asyncio.to_thread(
                        ai_client.models.generate_content,
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                            max_output_tokens=600,
                        ),
                    )
                    return response.text
                except Exception as model_err:
                    print(f"模型 {model_name} 錯誤: {model_err}")
                    continue
            switch_to_next_key()
        except Exception as key_err:
            print(f"Key 失敗: {key_err}")
            switch_to_next_key()
    return "⚠️ AI 分析連線異常，請家屬先直接前往現場確認長輩狀況！"

# ==================== 3. aiohttp Web API (接收 ESP32 訊號) ====================
async def handle_esp32_alert(request):
    try:
        data = await request.json()
    except Exception:
        data = {}

    sensor_msg = data.get("message", "偵測到浴室底層感測器異常停留，判定為疑似跌倒！")
    print(f"🚨 收到 ESP32 跌倒警報：{sensor_msg}")

    channel = bot.get_channel(ALERT_CHANNEL_ID)
    if not channel:
        print("❌ 找不到指定的 Discord 頻道，請確認 ALERT_CHANNEL_ID 設定！")
        return web.Response(text="Channel not found", status=500)

    # 1. 先在 Discord 頻道發送即時警報
    await channel.send(f"🚨 **【緊急跌倒通報】**\n硬體回傳狀態：`{sensor_msg}`\nAI 正在評估現場處置步驟，請稍候...")

    # 2. 自動呼叫 AI 產生急救指引
    ai_prompt = f"感測器發出通報：『{sensor_msg}』。請提供家屬當下進入浴室後最關鍵的 3 點急救與確認步驟（如不要慌張、確認意識與呼吸、切勿硬拉起身），條理分明且簡短。"
    ai_reply = await call_gemini(ai_prompt)

    # 3. 將 AI 指引推送到頻道
    await channel.send(f"📋 **【現場急救建議指引】**\n{ai_reply}")

    return web.json_response({"status": "success", "message": "Alert processed"})

async def run_web_server():
    app = web.Application()
    app.router.add_post("/alert", handle_esp32_alert)
    # 提供健康檢查端點
    app.router.add_get("/", lambda r: web.Response(text="Bot is running!"))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 HTTP 伺服器已在連接埠 {PORT} 啟動，等待 ESP32 訊號...")

# ==================== 4. Discord 事件處理 ====================
@bot.event
async def on_ready():
    print(f"✅ 機器人成功上線！名稱：{bot.user}")
    print(f"🔑 目前共成功載入 {len(API_KEYS)} 組 Gemini API Key 備援")
    # 機器人連上 Discord 後，啟動 Web 接收端
    await run_web_server()

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # 平常家屬在頻道 tag 機器人時的正常對話
    if bot.user in message.mentions or isinstance(message.channel, discord.DMChannel):
        clean_text = message.clean_content.replace(f"@{bot.user.name}", "").strip()
        clean_text = re.sub(r"^<@!?\d+>\s*", "", clean_text).strip()

        if not clean_text:
            await message.reply("你好！我是浴室安全小幫手，請問有什麼浴室安全或長者照護問題需要協助嗎？")
            return

        async with message.channel.typing():
            reply_text = await call_gemini(clean_text)
            await message.reply(reply_text[:2000])

# 啟動機器人
bot.run(DISCORD_TOKEN)
