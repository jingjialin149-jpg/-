import os
import re
import asyncio
import discord
from aiohttp import web
from google import genai
from google.genai import types

# ==================== 1. 環境變數讀取 (雙向相容) ====================
# 同時支援 DISCORD_BOT_TOKEN 或 DISCORD_TOKEN
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))  # Railway 會自動注入 PORT

# 讀取 GEMINI_API_KEY (支援逗號分隔或多變數命名)
raw_keys_str = os.getenv("GEMINI_API_KEY", "")
keys_list = [k.strip() for k in raw_keys_str.split(",") if k.strip()]

for i in range(2, 6):
    extra_key = os.getenv(f"GEMINI_API_KEY_{i}")
    if extra_key and extra_key.strip():
        keys_list.append(extra_key.strip())

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

# ==================== 2. 模型與 Prompt 設定 ====================
SYSTEM_PROMPT = """
你現在是安裝在 Discord 伺服器中的『浴室安全小幫手』。
專題特色：搭配 ESP32 進行浴室防跌偵測，不使用攝影機以維護使用者隱私。
職責：專門回答長輩照護、浴室防跌安全與緊急急救步驟。
請一律使用標準繁體中文（台灣），語氣沉穩、條理分明、親切且簡短扼要。
"""

MODELS_TO_TRY = ["gemini-3.8-flash", "gemini-3-flash-preview"]

async def call_gemini(prompt: str) -> str:
    """呼叫 Gemini 產生內容的共用函式 (含 Key 輪替與模型備援)"""
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
                    if response.text:
                        return response.text.strip()
                except Exception as model_err:
                    print(f"模型 {model_name} 執行失敗: {model_err}")
                    continue
            switch_to_next_key()
        except Exception as key_err:
            print(f"第 {current_key_index + 1} 組 Key 失敗: {key_err}")
            switch_to_next_key()
            
    return "⚠️ 目前 AI 額度暫時滿載或連線異常，請稍候片刻再試！"

# ==================== 3. Discord Bot 初始化 ====================
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

# ==================== 4. aiohttp Web API (接收 ESP32 訊號) ====================
async def handle_esp32_alert(request):
    """接收 ESP32 發出的 HTTP POST 請求"""
    try:
        data = await request.json()
    except Exception:
        data = {}

    sensor_msg = data.get("message", "偵測到底層感測器異常停留，判定為長者跌倒！")
    print(f"🚨 收到 ESP32 跌倒警報：{sensor_msg}")

    channel = bot.get_channel(ALERT_CHANNEL_ID)
    if not channel:
        print(f"❌ 找不到頻道 ID {ALERT_CHANNEL_ID}，請檢查 ALERT_CHANNEL_ID 環境變數！")
        return web.Response(text="Channel not found", status=500)

    # 1. 第一時間在 Discord 頻道發送警報
    await channel.send(f"🚨 **【緊急跌倒通報】**\n感測狀態：`{sensor_msg}`\nAI 正在評估現場處置步驟，請稍候...")

    # 2. 自動呼叫 AI 產生急救指導
    ai_prompt = f"感測器發出通報：『{sensor_msg}』。請提供家屬當下進入浴室後最關鍵的 3 點急救與確認步驟（如不要慌張、確認意識與呼吸、切勿硬拉起身），條理分明且簡短。"
    ai_reply = await call_gemini(ai_prompt)

    # 3. 發送 AI 指引
    await channel.send(f"📋 **【現場急救建議指引】**\n{ai_reply}")

    return web.json_response({"status": "success", "message": "Alert sent to Discord"})

async def run_web_server():
    """啟動微型 Web 伺服器"""
    app = web.Application()
    app.router.add_post("/alert", handle_esp32_alert)
    app.router.add_get("/", lambda r: web.Response(text="浴室安全小幫手正在運行中！"))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 HTTP 伺服器已在連接埠 {PORT} 啟動，等待 ESP32 訊號...")

# ==================== 5. Discord 事件監聽 ====================
@bot.event
async def on_ready():
    print(f"✅ 機器人成功上線！名稱：{bot.user}")
    print(f"🔑 目前共成功載入 {len(API_KEYS)} 組 Gemini API Key 備援")
    await run_web_server()

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # 當有人 tag 機器人或傳送私訊時
    if bot.user in message.mentions or isinstance(message.channel, discord.DMChannel):
        clean_text = message.clean_content.replace(f"@{bot.user.name}", "").strip()
        clean_text = re.sub(r"^<@!?\d+>\s*", "", clean_text).strip()

        if not clean_text:
            await message.reply("你好！我是浴室安全小幫手，請問有什麼浴室安全或長者照護問題需要協助嗎？")
            return

        async with message.channel.typing():
            reply_text = await call_gemini(clean_text)
            await message.reply(reply_text[:2000])

# ==================== 6. 啟動程式 ====================
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise ValueError("❌ 未找到 DISCORD_TOKEN 或 DISCORD_BOT_TOKEN，請檢查 Railway 環境變數！")
    bot.run(DISCORD_TOKEN)
