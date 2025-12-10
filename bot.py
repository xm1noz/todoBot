import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# .env からトークン読み込み
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# ===== 自分のサーバー / チャンネルのIDを入れる =====
GUILD_ID = 912019792905535600  # サーバーID
CHANNEL_ID = 1448247532047040684  # 通知を送りたいテキストチャンネルID
# ===================================================

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    guild_obj = discord.Object(id=GUILD_ID)
    try:
        synced = await bot.tree.sync(guild=guild_obj)
        print(f"Synced {len(synced)} command(s) to guild {GUILD_ID}")
    except Exception as e:
        print(f"Command sync error: {e}")


# 課題追加（今は確認だけでDB保存はまだ）
@bot.tree.command(
    name="task_add",
    description="課題を登録します（科目・課題名・締切）",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    subject="科目名（例：情報処理）",
    title="課題名（例：レポート1）",
    deadline="締切（例：2025-12-20 23:59）",
)
async def task_add(
    interaction: discord.Interaction,
    subject: str,
    title: str,
    deadline: str,
):
    msg = (
        f"課題を登録しました。\n"
        f"科目: {subject}\n"
        f"課題名: {title}\n"
        f"締切: {deadline}"
    )
    await interaction.response.send_message(msg, ephemeral=True)


# 通知テスト（指定チャンネルに送れるかチェック）
@bot.tree.command(
    name="notify_test",
    description="通知チャンネルにテストメッセージを送信します",
    guild=discord.Object(id=GUILD_ID),
)
async def notify_test(interaction: discord.Interaction):
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        await interaction.response.send_message(
            "チャンネルが見つかりません。CHANNEL_ID を確認してね。",
            ephemeral=True,
        )
        return

    await channel.send("これは通知テストです。")
    await interaction.response.send_message(
        "通知チャンネルにテストメッセージを送信しました。",
        ephemeral=True,
    )


if __name__ == "__main__":
    bot.run(TOKEN)
