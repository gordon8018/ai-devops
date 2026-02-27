import json
import os
import time
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv

BASE_DIR = Path.home() / "ai-devops"
QUEUE_DIR = BASE_DIR / "orchestrator" / "queue"
QUEUE_DIR.mkdir(parents=True, exist_ok=True)

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")  # 推荐填，能更快同步命令；不填也能用但会慢
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL"))

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

def put_task(payload: dict) -> str:
    task_id = payload["id"]
    path = QUEUE_DIR / f"{task_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)

@client.event
async def on_ready():
    # 可选：加速 slash command 同步（限定某个 guild）
    if GUILD_ID:
        guild = discord.Object(id=int(GUILD_ID))
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
    else:
        await tree.sync()

    channel = client.get_channel(CHANNEL_ID)
    if channel:
        await channel.send("Zoe control plane online. Use /status or /task")
    print(f"Logged in as {client.user}")

@tree.command(name="status", description="Check orchestrator status")
async def status(interaction: discord.Interaction):
    await interaction.response.send_message("Zoe orchestrator alive ✅", ephemeral=True)

@tree.command(name="task", description="Create a coding task (spawns agent)")
@app_commands.describe(
    repo="Repo name (must exist in ~/ai-devops/repos/<repo>)",
    title="Short task title",
    description="What to build / change",
    agent="codex or claude",
    model="Codex model name, e.g. gpt-5.3-codex",
    effort="low/medium/high"
)
async def task(
    interaction: discord.Interaction,
    repo: str,
    title: str,
    description: str,
    agent: str = "codex",
    model: str = "gpt-5.3-codex",
    effort: str = "high",
):
    task_id = f"{int(time.time())}-{repo}".replace("/", "_")
    payload = {
        "id": task_id,
        "repo": repo,
        "title": title,
        "description": description,
        "agent": agent,
        "model": model,
        "effort": effort,
        "requested_by": str(interaction.user),
        "requested_at": int(time.time() * 1000),
        "discord": {
            "channel_id": CHANNEL_ID,
            "guild_id": int(GUILD_ID) if GUILD_ID else None,
        },
    }
    put_task(payload)
    await interaction.response.send_message(
        f"✅ Task queued: **{title}**\n- id: `{task_id}`\n- repo: `{repo}`\n- agent: `{agent}` `{model}` effort={effort}",
        ephemeral=False,
    )

client.run(TOKEN)
