import os
import sqlite3
import datetime
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# .env からトークン読み込み
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

DB_PATH = "tasks.db"  # プロジェクト直下に作るSQLiteファイル

def init_db():
    """tasks テーブルがなければ作成する"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_user_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            title TEXT NOT NULL,
            deadline TEXT NOT NULL,
            submitted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()
# DB初期化
init_db()

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


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
    deadline="締切（例：2025-12-20 23:59 の形式で入力）",
)
async def task_add(
    interaction: discord.Interaction,
    subject: str,
    title: str,
    deadline: str,
):
    # 1. 締切文字列を日時に変換（フォーマットチェック）
    try:
        deadline_dt = datetime.datetime.strptime(deadline, "%Y-%m-%d %H:%M")
    except ValueError:
        await interaction.response.send_message(
            "締切は `YYYY-MM-DD HH:MM` 形式で入力してね。\n"
            "例: `2025-12-20 23:59`",
            ephemeral=True,
        )
        return

    now = datetime.datetime.now()

    # 2. DB に保存
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO tasks (
            discord_user_id,
            subject,
            title,
            deadline,
            submitted,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, 0, ?, ?);
        """,
        (
            interaction.user.id,
            subject,
            title,
            deadline_dt.isoformat(),  # 例: "2025-12-20T23:59:00"
            now.isoformat(),
            now.isoformat(),
        ),
    )
    task_id = cur.lastrowid
    conn.commit()
    conn.close()

    # 3. ユーザーに確認メッセージ
    msg = (
        f"課題を登録しました。（ID: {task_id}）\n"
        f"科目: {subject}\n"
        f"課題名: {title}\n"
        f"締切: {deadline_dt.strftime('%Y-%m-%d %H:%M')}\n"
        f"登録者: {interaction.user.display_name}"
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
