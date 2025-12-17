import os
import sqlite3
import datetime
import discord
from discord.ext import commands, tasks
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

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sent_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_user_id INTEGER NOT NULL,
            notify_key TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            UNIQUE(discord_user_id, notify_key)
        );
        """
    )

    conn.commit()
    conn.close()
# DB初期化
init_db()

def mark_task_submitted(discord_user_id: int, task_id: int) -> bool:
    """指定IDのタスクを submitted=1 にする（本人のタスクのみ）。更新できたら True"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE tasks
        SET submitted = 1, updated_at = ?
        WHERE id = ? AND discord_user_id = ? AND submitted = 0;
        """,
        (datetime.datetime.now().isoformat(), task_id, discord_user_id),
    )
    updated = cur.rowcount
    conn.commit()
    conn.close()
    return updated > 0


def fetch_unsubmitted_tasks(discord_user_id: int):
    """未提出タスクを締切昇順で取得"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, subject, title, deadline
        FROM tasks
        WHERE discord_user_id = ? AND submitted = 0
        ORDER BY deadline ASC;
        """,
        (discord_user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows

def was_notified(discord_user_id: int, notify_key: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sent_notifications WHERE discord_user_id=? AND notify_key=? LIMIT 1;",
        (discord_user_id, notify_key),
    )
    hit = cur.fetchone() is not None
    conn.close()
    return hit


def mark_notified(discord_user_id: int, notify_key: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO sent_notifications (discord_user_id, notify_key, sent_at)
        VALUES (?, ?, ?);
        """,
        (discord_user_id, notify_key, datetime.datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def fetch_active_user_ids():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT discord_user_id FROM tasks;")
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]

def fetch_unsubmitted_tasks_all(discord_user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, subject, title, deadline
        FROM tasks
        WHERE discord_user_id = ? AND submitted = 0
        ORDER BY deadline ASC;
        """,
        (discord_user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


# ===== 自分のサーバー / チャンネルのIDを入れる =====
GUILD_ID = 912019792905535600  # サーバーID
CHANNEL_ID = 1448247532047040684  # 通知を送りたいテキストチャンネルID
# ===================================================

DAILY_NOTIFY_HOUR = 16
DAILY_NOTIFY_MINUTE = 43

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    guild_obj = discord.Object(id=GUILD_ID)
    try:
        synced = await bot.tree.sync(guild=guild_obj)
        print(f"Synced {len(synced)} command(s) to guild {GUILD_ID}")
    except Exception as e:
        print(f"Command sync error: {e}")
    if not deadline_notify_loop.is_running():
        deadline_notify_loop.start()

    if not daily_notify_loop.is_running():
        daily_notify_loop.start()

@tasks.loop(minutes=1)
async def deadline_notify_loop():
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        return

    now = datetime.datetime.now()

    user_ids = fetch_active_user_ids()
    for uid in user_ids:
        rows = fetch_unsubmitted_tasks_all(uid)

        # deadline(分単位)ごとにグルーピング
        groups = {}
        for task_id, subject, title, deadline_iso in rows:
            try:
                d = datetime.datetime.fromisoformat(deadline_iso)
            except Exception:
                continue
            key = d.replace(second=0, microsecond=0).isoformat()
            groups.setdefault(key, {"deadline": d.replace(second=0, microsecond=0), "items": []})
            groups[key]["items"].append((task_id, subject, title))

        # 各グループについて n時間前 を計算
        for g in groups.values():
            deadline_dt = g["deadline"]
            n = len(g["items"])
            notify_time = deadline_dt - datetime.timedelta(hours=n)

            # 「今」から±30秒以内なら通知対象
            if abs((now - notify_time).total_seconds()) <= 30:
                notify_key = f"deadline:{notify_time.isoformat()}:{deadline_dt.isoformat()}"
                if was_notified(uid, notify_key):
                    continue

                # メッセージ（同じ締切の課題が複数なら列挙）
                titles = " / ".join([f"{sub}:{ttl}(ID:{tid})" for (tid, sub, ttl) in g["items"]])
                msg = (
                    f"<@{uid}>\n"
                    f"{titles}\n"
                    f"締切は本日の {deadline_dt.strftime('%H:%M')} です。未提出の場合は急いでやりましょう。"
                )

                await channel.send(msg)
                mark_notified(uid, notify_key)

@tasks.loop(minutes=1)
async def daily_notify_loop():
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        return

    now = datetime.datetime.now()
    if not (now.hour == DAILY_NOTIFY_HOUR and now.minute == DAILY_NOTIFY_MINUTE):
        return

    today = now.date()
    notify_day_key = today.strftime("%Y-%m-%d")

    user_ids = fetch_active_user_ids()
    for uid in user_ids:
        notify_key = f"daily:{notify_day_key}"
        if was_notified(uid, notify_key):
            continue

        # 今日締切の未提出を抽出
        rows = fetch_unsubmitted_tasks_all(uid)
        today_items = []
        for task_id, subject, title, deadline_iso in rows:
            try:
                d = datetime.datetime.fromisoformat(deadline_iso)
            except Exception:
                continue
            if d.date() == today:
                today_items.append((task_id, subject, title, d))

        if not today_items:
            mark_notified(uid, notify_key)
            continue

        # 今日締切の一覧を作成（締切時刻を文に使う）
        lines = []
        for tid, sub, ttl, d in sorted(today_items, key=lambda x: x[3]):
            lines.append(f"{sub}:{ttl}(ID:{tid}) → {d.strftime('%H:%M')}")

        msg = (
            f"<@{uid}>\n"
            "本日締切の未提出課題があります。\n"
            + "\n".join(lines)
            + "\n未提出の場合は急いでやりましょう。"
        )

        await channel.send(msg)
        mark_notified(uid, notify_key)


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

# 未提出課題一覧表示（締切が近い順）
@bot.tree.command(
    name="task_list",
    description="未提出の課題一覧を締切が近い順に表示します",
    guild=discord.Object(id=GUILD_ID),
)
async def task_list(interaction: discord.Interaction):
    rows = fetch_unsubmitted_tasks(interaction.user.id)

    if not rows:
        await interaction.response.send_message("未提出の課題はありません。", ephemeral=True)
        return

    lines = []
    for task_id, subject, title, deadline_iso in rows:
        # deadline は ISO 文字列で保存している前提
        try:
            dt = datetime.datetime.fromisoformat(deadline_iso)
            deadline_str = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            deadline_str = deadline_iso  # 変換できない場合はそのまま表示

        lines.append(f"ID:{task_id} | {subject} | {title} | 締切:{deadline_str}")

    msg = "未提出の課題一覧（締切が近い順）\n" + "\n".join(lines)
    await interaction.response.send_message(msg, ephemeral=True)

# 課題提出済みにする（ID指定）
@bot.tree.command(
    name="task_done",
    description="課題を提出済みにします（ID指定）",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(task_id="提出済みにする課題のID（/task_list に表示されるID）")
async def task_done(interaction: discord.Interaction, task_id: int):
    ok = mark_task_submitted(interaction.user.id, task_id)

    if ok:
        await interaction.response.send_message(
            f"課題（ID:{task_id}）を提出済みにしました。",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            "指定IDの未提出課題が見つかりません。（ID違い / 既に提出済み / 他ユーザーの課題の可能性）",
            ephemeral=True,
        )

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
