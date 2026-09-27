import os
import re
import asyncio
import urllib.request
import xml.etree.ElementTree as ET
import html
import json
import discord
from discord.ext import tasks
from datetime import datetime, timezone, timedelta
from google import genai
from google.genai import types

# ==================== 1. 環境變數讀取 (雙向支援逗號或多變數) ====================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("DISCORD_BOT_TOKEN")

# 讀取 GEMINI_API_KEY (支援逗號分隔)
primary_keys_raw = os.getenv("GEMINI_API_KEY", "")
keys_list = [k.strip() for k in primary_keys_raw.split(",") if k.strip()]

# 讀取 GEMINI_API_KEY_2, GEMINI_API_KEY_3...
for i in range(2, 6):
    k_val = os.getenv(f"GEMINI_API_KEY_{i}")
    if k_val and k_val.strip():
        keys_list.append(k_val.strip())

# 去除重複
API_KEYS = list(dict.fromkeys(keys_list))

current_key_index = 0

def get_current_client():
    global current_key_index
    if not API_KEYS:
        raise ValueError("未設定任何 GEMINI_API_KEY")
    return genai.Client(api_key=API_KEYS[current_key_index])

def switch_to_next_key():
    global current_key_index
    if len(API_KEYS) > 1:
        current_key_index = (current_key_index + 1) % len(API_KEYS)
        print(f"⚠️ 偵測到限制或錯誤，已自動切換至第 {current_key_index + 1} 組 Key！")
        return True
    return False

# 開啟 Discord 必要權限
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# 正確可用的模型名稱清單
MODELS_TO_TRY = ["gemini-2.5-flash", "gemini-1.5-flash"]

# ==================== 2. Twitter 監控設定 ====================
tracked_users = {}

def clean_html(raw_html: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw_html)
    return html.unescape(text).strip()

def extract_username(text: str) -> str:
    match = re.search(r"(?:twitter\.com|x\.com)/([A-Za-z0-9_]+)", text)
    if match:
        return match.group(1)
    clean = text.replace("@", "").strip()
    if re.match(r"^[A-Za-z0-9_]+$", clean):
        return clean
    return None

@tasks.loop(minutes=3)
async def check_all_twitter():
    if not tracked_users:
        return
    for username, info in list(tracked_users.items()):
        channel = client.get_channel(info["channel_id"])
        if not channel:
            continue
        rss_endpoints = [
            f"https://rsshub.app/twitter/user/{username}",
            f"https://nitter.privacydev.net/{username}/rss",
        ]
        for endpoint in rss_endpoints:
            try:
                req = urllib.request.Request(
                    endpoint,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                )
                with urllib.request.urlopen(req, timeout=10) as response:
                    xml_data = response.read()
                    tree = ET.fromstring(xml_data)
                    latest_item = tree.find(".//item")
                    if latest_item is None:
                        continue
                    tweet_link = latest_item.find("link").text.strip()
                    tweet_content = clean_html(latest_item.find("description").text or "")
                    
                    if info["last_tweet"] is None:
                        tracked_users[username]["last_tweet"] = tweet_link
                        break
                    if tweet_link != info["last_tweet"]:
                        tracked_users[username]["last_tweet"] = tweet_link
                        msg = (
                            f"🐦 **@{username} 發布了新推文！**\n\n"
                            f"{tweet_content}\n\n"
                            f"🔗 **推文連結**：<{tweet_link}>"
                        )
                        await channel.send(msg)
                        break
            except Exception:
                continue

# ==================== 3. 智慧定時提醒排程器 ====================
async def schedule_reminder(delay_seconds: int, channel_id: int, user_id: int, task_description: str):
    await asyncio.sleep(delay_seconds)
    channel = client.get_channel(channel_id)
    if channel:
        await channel.send(
            f"⏰ <@{user_id}> **叮咚！提醒時間到了：**\n> {task_description}"
        )

@client.event
async def on_ready():
    print(f"機器人已上線：{client.user}")
    print(f"目前共載入 {len(API_KEYS)} 把 API Key 備援")
    if not check_all_twitter.is_running():
        check_all_twitter.start()

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    raw_text = message.content.strip()
    clean_text = re.sub(r"^<@!?\d+>\s*", "", raw_text).strip()

    # 指令處理
    if clean_text.startswith("!follow"):
        parts = clean_text.split(" ", 1)
        if len(parts) < 2:
            await message.reply("⚠️ 請附上 Twitter 帳號，例如：`!follow 帳號`")
            return
        username = extract_username(parts[1])
        if not username:
            await message.reply("⚠️ 無法識別該帳號！")
            return
        tracked_users[username] = {"channel_id": message.channel.id, "last_tweet": None}
        await message.reply(f"✅ 成功將 **@{username}** 加入監控清單！每 3 分鐘檢查一次。")
        return

    if clean_text == "!following":
        if not tracked_users:
            await message.reply("📋 目前沒有追蹤任何 Twitter 帳號。")
            return
        msg = "**📋 目前追蹤中的 Twitter 帳號：**\n"
        for i, (u, data) in enumerate(tracked_users.items(), 1):
            msg += f"{i}. **@{u}**（頻道：<#{data['channel_id']}>）\n"
        await message.reply(msg)
        return

    if clean_text.startswith("!unfollow"):
        parts = clean_text.split(" ", 1)
        if len(parts) < 2:
            await message.reply("⚠️ 請輸入要取消追蹤的帳號，例如：`!unfollow 帳號`")
            return
        username = extract_username(parts[1])
        if username in tracked_users:
            del tracked_users[username]
            await message.reply(f"🗑️ 已停止追蹤 **@{username}**。")
        else:
            await message.reply(f"⚠️ 在追蹤名單中找不到 @{username}。")
        return

    # ==================== Gemini AI 對話 ====================
    if client.user in message.mentions or isinstance(message.channel, discord.DMChannel):
        if not clean_text:
            await message.reply("你好！我是浴室安全小幫手，請問有什麼我可以協助你的嗎？")
            return

        tz_tw = timezone(timedelta(hours=8))
        now_tw_str = datetime.now(tz_tw).strftime("%Y-%m-%d %H:%M:%S")

        async with message.channel.typing():
            reply_text = None
            
            # 輪替嘗試所有的 Key
            for _ in range(max(1, len(API_KEYS))):
                try:
                    ai_client = get_current_client()
                    
                    # 嘗試可用模型
                    for model_name in MODELS_TO_TRY:
                        try:
                            res = await ai_client.aio.models.generate_content(
                                model=model_name,
                                contents=clean_text,
                                config=types.GenerateContentConfig(
                                    system_instruction=f"你現在是安裝在 Discord 伺服器中的『浴室安全小幫手』。當前台灣時間為：{now_tw_str}。專門回答長輩照護、防跌安全與緊急急救步驟。請務必使用標準繁體中文（台灣）簡潔親切地回答。",
                                    max_output_tokens=600,
                                ),
                            )
                            reply_text = res.text
                            break
                        except Exception as me:
                            print(f"模型 {model_name} 錯誤: {me}")
                            continue

                    if reply_text:
                        break
                    else:
                        switch_to_next_key()
                except Exception as e:
                    print(f"Key 呼叫失敗: {e}")
                    switch_to_next_key()

            if reply_text:
                await message.reply(reply_text[:2000])
            else:
                await message.reply("抱歉，目前所有 AI 額度均暫時滿載，請稍候片刻再試！")

client.run(DISCORD_TOKEN)
