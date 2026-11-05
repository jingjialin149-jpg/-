import os
import asyncio
import logging
import re
from aiohttp import web
import discord
from dotenv import load_dotenv
from google import genai
from google.genai import types

# ==================== 0. 載入本地 .env 環境變數 ====================
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ==================== 1. 取得環境變數設定 ====================
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()

raw_channel_id = os.getenv("ALERT_CHANNEL_ID", "")
digits_only = re.sub(r"\D", "", raw_channel_id)
ALERT_CHANNEL_ID = int(digits_only) if digits_only else None

PORT = int(os.getenv("PORT", 8080))

gemini_keys = []
primary_key = os.getenv("GEMINI_API_KEY", "")
if primary_key:
    gemini_keys.extend([k.strip() for k in primary_key.split(",") if k.strip()])

idx = 2
while True:
    k = os.getenv(f"GEMINI_API_KEY_{idx}")
    if k:
        k_clean = k.strip()
        if k_clean and k_clean not in gemini_keys:
            gemini_keys.append(k_clean)
        idx += 1
    else:
        break

if not gemini_keys:
    logging.warning("⚠️ 未讀取到任何 GEMINI_API_KEY，AI 急救建議將自動使用靜態備援清單。")
else:
    logging.info(f"🔑 目前共成功載入 {len(gemini_keys)} 組 Gemini API Key 備援")

current_key_index = 0

def get_current_client():
    if not gemini_keys:
        return None
    return genai.Client(api_key=gemini_keys[current_key_index])

def switch_to_next_key():
    global current_key_index
    if not gemini_keys:
        return
    old_idx = current_key_index
    current_key_index = (current_key_index + 1) % len(gemini_keys)
    logging.warning(f"🔄 Gemini API 觸發輪替：由第 {old_idx + 1} 組切換至第 {current_key_index + 1} 組 Key")

# ==================== 2. 安全邊界提示詞 (對齊夏普 GP2Y0A21YK0F 架構) ====================
SYSTEM_PROMPT = """
你現在是運行在 Discord 伺服器中的『浴室安全小幫手』。
專題定位：搭配 ESP32 微控制器與 6 組夏普 (Sharp) GP2Y0A21YK0F 紅外線測距感測器（分為上層站立偵測與下層地面防跌陣列），專門針對長輩進行無攝影機、高隱私的浴室防跌即時通報與照護輔助。

==================== 【核心醫療安全與防護邊界 (Guardrails)】 ====================
為確保長者生命安全與避免法律責任，你必須嚴格遵守以下防護邊界：
1. 【嚴禁藥物與偏方】：絕對不可推薦任何處方藥、非處方藥、外用藥膏或民間偏方。
2. 【嚴禁病理診斷】：長輩倒地原因多樣，切勿隔空猜測或診斷病因（如猜測是否為中風、心肌梗塞或特定骨折）。
3. 【強制 119 就醫通報】：長輩若有「意識不清/昏迷」、「呼吸急促或微弱」、「頭部撞擊出血」、「嚴重劇痛無法動彈」任一狀況，必須強制將「立即撥打 119 送醫」列為第一優先項目！
4. 【非醫療替代聲明】：你扮演的是「現場黃金時間確認清單 (Checklist) 與情緒安撫者」，絕非取代專業醫護人員。

==================== 【跌倒通報現場應變指引守則 (SOP)】 ====================
當收到 ESP32 的跌倒警報或家屬通報跌倒時，請以沉穩、冷靜且條理分明的格式提供以下確認步驟：
1. 保持冷靜與切勿硬拉：強烈提醒家屬進入現場切勿慌張，絕對不可馬上用力將長輩拉起或扶起，避免髖關節、脊椎或頸椎受到致命二次傷害。
2. 評估意識與呼吸：指示家屬輕喚長輩，確認神智是否清楚、呼吸是否平穩順暢。
3. 檢查疼痛與四肢：詢問長輩有無劇烈疼痛部位，觀察頸部與四肢關節是否有異常角度變形。
4. 現場保暖與側臥防嗆：若無頸椎疑慮且意識清楚，可用乾毛巾保暖浴室地面防止失溫；若有嘔吐或意識漸漸模糊，保持側臥以防呼吸道阻塞。
5. 評估就醫需求：若狀況不對勁，立刻撥打 119，並指引現場人員解鎖大門、清除救護動線。

==================== 【日常對話與衛教諮詢】 ====================
平時若家屬在頻道中詢問系統原理或浴室防滑、安全扶手等日常防護問題：
- 系統原理說明：採用 6 組夏普 GP2Y0A21YK0F 紅外線距離感測器（量測範圍 10~80cm），當下層地面感測器持續偵測到人體遮擋距離、且上層感測器無站立反應時，即觸發蜂鳴器、警示紅燈與 Discord 通報，兼顧 100% 隱私與防跌安全。
- 全程使用標準繁體中文（台灣），語氣溫和、沉穩、具同理心，條列說明且切中要點。
"""

STATIC_FALLBACK_GUIDE = (
    "📋 **【現場緊急應變防呆清單（衛福部標準指引）】**\n"
    "1. **切勿急拉扶起**：長輩倒地切勿立刻強行拉扯起身，避免造成骨折或脊椎二次傷害。\n"
    "2. **確認意識呼吸**：輕聲呼喚長輩並輕拍雙肩，觀察呼吸是否均勻、神智是否清楚。\n"
    "3. **評估劇痛部位**：詢問疼痛位置，注意保暖防失溫；若無嘔吐且呼吸正常，保持舒適側臥。\n"
    "4. **緊急就醫撥打 119**：若長輩**意識不清、劇烈疼痛無法動彈、頭部受撞擊或呼吸異常，請立刻撥打 119 送醫**！"
)

async def call_gemini(prompt: str) -> str:
    """呼叫 Gemini 3.8 Flash 生成指引，具備輪替與靜態備援機制"""
    if not gemini_keys:
        return STATIC_FALLBACK_GUIDE

    attempts = len(gemini_keys)
    for _ in range(attempts):
        client = get_current_client()
        if not client:
            break
        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model="gemini-3.8-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.2,
                    ),
                ),
            )
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            logging.error(f"Gemini API 呼叫失敗 ({e})，切換下一組 Key 備援...")
            switch_to_next_key()

    return STATIC_FALLBACK_GUIDE

# ==================== 3. Discord Bot 初始化 ====================
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

@bot.event
async def on_ready():
    logging.info(f"✅ Discord 機器人已成功上線！名稱：{bot.user}")

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    if bot.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        clean_content = message.clean_content.replace(f"@{bot.user.display_name}", "").strip()
        if not clean_content:
            await message.reply("您好！我是浴室安全小幫手，請問有什麼我可以協助的浴室防護或跌倒應變諮詢嗎？")
            return

        async with message.channel.typing():
            reply = await call_gemini(clean_content)
            await message.reply(reply)

# ==================== 4. 本地 Web 接收伺服器 (接收 ESP32 警報) ====================
async def handle_esp32_alert(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        data = {}

    sensor_status = data.get("status", "底層紅外線測距感測器持續遮擋 (上層無反應)")
    duration = data.get("duration", "持續超過 8 秒")

    logging.info(f"🚨 接收到 ESP32 警報訊號！狀態: {sensor_status}, 持續: {duration}")

    if ALERT_CHANNEL_ID:
        channel = bot.get_channel(ALERT_CHANNEL_ID)
        if channel:
            alert_embed = discord.Embed(
                title="🚨 【緊急通報】浴室偵測到長者跌倒！",
                description=f"感測器狀態：`{sensor_status}`\n持續時間：`{duration}`\n現場蜂鳴器與警示燈已同步啟動，請家屬立即前往確認！",
                color=discord.Color.red(),
            )
            await channel.send(embed=alert_embed)

            prompt = (
                f"現場浴室 ESP32 與夏普紅外線測距陣列偵測到疑似跌倒事件（{sensor_status}，{duration}）。"
                f"請以條列式給家屬 3 到 4 點最關鍵的現場確認步驟，重點強調切勿強行拉扯長輩造成二次傷害，"
                f"並提醒若有嚴重疼痛或意識模糊時第一優先撥打 119。"
            )
            guidance = await call_gemini(prompt)

            guide_embed = discord.Embed(
                title="📋 現場緊急應變防呆指引",
                description=guidance,
                color=discord.Color.orange(),
            )
            await channel.send(embed=guide_embed)
        else:
            logging.error(f"找不到指定的頻道 ID: {ALERT_CHANNEL_ID}")

    return web.json_response({"status": "success", "message": "Alert processed"})

async def handle_health_check(request: web.Request):
    return web.Response(text="Bathroom Safety Assistant Local Server is Running!")

async def start_web_server():
    app = web.Application()
    app.router.add_post("/alert", handle_esp32_alert)
    app.router.add_get("/", handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"🌐 本地 Web 伺服器已在 http://0.0.0.0:{PORT} 啟動，等待 ESP32 訊號...")

# ==================== 5. 主程式入口 ====================
async def main():
    if not DISCORD_BOT_TOKEN:
        logging.error("❌ 找不到 DISCORD_BOT_TOKEN，請檢查專案目錄下的 .env 檔案！")
        return

    await start_web_server()
    await bot.start(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("🛑 程式已被手動終止。")
