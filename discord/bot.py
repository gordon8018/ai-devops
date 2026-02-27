import json
import os
import time
from pathlib import Path
import re
import sys

import discord
from discord import app_commands
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

BASE_DIR = Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))
QUEUE_DIR = BASE_DIR / "orchestrator" / "queue"
REPOS_DIR = BASE_DIR / "repos"
QUEUE_DIR.mkdir(parents=True, exist_ok=True)

from orchestrator.bin.errors import PlannerError, PolicyViolation
from orchestrator.bin.zoe_tools import list_plans, plan_and_dispatch_task, task_status

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path, override=True)

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")  # 推荐填，能更快同步命令；不填也能用但会慢
CHANNEL_ID_RAW = os.getenv("DISCORD_CHANNEL")
CHANNEL_ID = int(CHANNEL_ID_RAW) if CHANNEL_ID_RAW else None
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

class PlannerInvocationError(Exception):
    pass


class PlannerPolicyViolation(PlannerInvocationError):
    pass


class PlannerExecutionError(PlannerInvocationError):
    pass


def put_task(payload: dict) -> str:
    task_id = payload["id"]
    path = QUEUE_DIR / f"{task_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def sanitize_identifier(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-_")
    return sanitized or "task"


def allowed_users() -> set[str]:
    return {
        item.strip() for item in os.getenv("DISCORD_ALLOWED_USERS", "").split(",") if item.strip()
    }


def allowed_role_ids() -> set[int]:
    values: set[int] = set()
    for item in os.getenv("DISCORD_ALLOWED_ROLE_IDS", "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            values.add(int(item))
        except ValueError:
            continue
    return values


def is_allowed(interaction: discord.Interaction) -> bool:
    configured_users = allowed_users()
    configured_roles = allowed_role_ids()
    if not configured_users and not configured_roles:
        print(
            f"[ALLOWLIST] deny user_id={interaction.user.id} user={interaction.user} "
            "reason=no_allowlist_configured"
        )
        return False

    user_id = str(interaction.user.id)
    username = str(interaction.user)
    if user_id in configured_users or username in configured_users:
        print(
            f"[ALLOWLIST] allow user_id={interaction.user.id} user={interaction.user} "
            f"configured_users={sorted(configured_users)} configured_roles={sorted(configured_roles)}"
        )
        return True

    roles = getattr(interaction.user, "roles", [])
    role_ids = [getattr(role, "id", None) for role in roles]
    allowed = any(role_id in configured_roles for role_id in role_ids)
    print(
        f"[ALLOWLIST] {'allow' if allowed else 'deny'} user_id={interaction.user.id} user={interaction.user} "
        f"configured_users={sorted(configured_users)} configured_roles={sorted(configured_roles)} "
        f"user_roles={role_ids}"
    )
    return allowed


def repo_exists(repo: str) -> bool:
    return (REPOS_DIR / repo).exists()


def write_fallback_task(payload: dict) -> str:
    task_id = sanitize_identifier(f"{int(time.time() * 1000)}-{payload['repo']}")
    execution_task = {
        "id": task_id,
        "repo": payload["repo"],
        "title": payload["title"],
        "description": payload["description"],
        "agent": payload.get("agent", "codex"),
        "model": payload.get("model", "gpt-5.3-codex"),
        "effort": payload.get("effort", "high"),
        "requested_by": payload["requested_by"],
        "requested_at": payload["requested_at"],
        "metadata": {
            "plannedBy": "fallback",
            "fallbackReason": "planner_failed",
        },
    }
    return put_task(execution_task)


def invoke_planner(payload: dict) -> dict:
    try:
        return plan_and_dispatch_task(payload, base_dir=BASE_DIR).to_dict()
    except PolicyViolation as exc:
        raise PlannerPolicyViolation(str(exc)) from exc
    except PlannerError as exc:
        raise PlannerExecutionError(str(exc)) from exc

@client.event
async def on_ready():
    # 可选：加速 slash command 同步（限定某个 guild）
    if GUILD_ID:
        guild = discord.Object(id=int(GUILD_ID))
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
    else:
        await tree.sync()

    channel = client.get_channel(CHANNEL_ID) if CHANNEL_ID else None
    if channel:
        await channel.send("Zoe control adapter online. Use /status, /task, /plans, or /task_status")
    print(
        f"[BOOT] allowed_users={sorted(allowed_users())} allowed_roles={sorted(allowed_role_ids())}"
    )
    print(f"Logged in as {client.user}")

@tree.command(name="status", description="Check orchestrator status")
async def status(interaction: discord.Interaction):
    registry = task_status(base_dir=BASE_DIR)
    await interaction.response.send_message(
        f"Zoe tool layer alive. tracked tasks: {len(registry.get('tasks', []))}",
        ephemeral=True,
    )


@tree.command(name="plans", description="List recent archived Zoe plans")
@app_commands.describe(limit="How many recent plans to show")
async def plans(interaction: discord.Interaction, limit: int = 5):
    result = list_plans(base_dir=BASE_DIR, limit=max(1, min(limit, 20)))
    plans_payload = result.get("plans", [])
    if not plans_payload:
        await interaction.response.send_message("No archived plans found.", ephemeral=True)
        return

    lines = ["Recent plans:"]
    lines.extend(
        f"- `{item['planId']}` {item['title']} ({item['subtaskCount']} subtasks)"
        for item in plans_payload
    )
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@tree.command(name="task_status", description="Read task or plan status from the local registry")
@app_commands.describe(task_id="Execution task id", plan_id="Plan id")
async def task_status_command(
    interaction: discord.Interaction,
    task_id: str | None = None,
    plan_id: str | None = None,
):
    try:
        result = task_status(task_id=task_id, plan_id=plan_id, base_dir=BASE_DIR)
    except PlannerError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return

    if "task" in result:
        task_payload = result["task"]
        await interaction.response.send_message(
            f"task `{task_payload.get('id')}` status: `{task_payload.get('status')}`",
            ephemeral=True,
        )
        return

    tasks = result.get("tasks", [])
    if plan_id:
        if not tasks:
            await interaction.response.send_message(
                f"No registry tasks found yet for plan `{plan_id}`.",
                ephemeral=True,
            )
            return
        lines = [f"Plan `{plan_id}` tasks:"]
        lines.extend(f"- `{item.get('id')}` [{item.get('status')}]" for item in tasks[:10])
        await interaction.response.send_message("\n".join(lines), ephemeral=True)
        return

    await interaction.response.send_message(
        f"Tracked tasks: {len(tasks)}",
        ephemeral=True,
    )

@tree.command(name="task", description="Plan and queue a coding task")
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
    if not is_allowed(interaction):
        await interaction.response.send_message(
            f"Task creation is not allowed for this user. userId={interaction.user.id}",
            ephemeral=True,
        )
        return

    if not repo_exists(repo):
        await interaction.response.send_message(
            f"Repository not found: `{repo}`. Expected directory: `{REPOS_DIR / repo}`",
            ephemeral=True,
        )
        return

    payload = {
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
    try:
        result = invoke_planner(payload)
        plan = result["plan"]
        subtasks = plan.get("subtasks", [])
        lines = [
            f"Task planned: `{plan['planId']}`",
            f"repo: `{plan['repo']}`",
            f"subtasks: {len(subtasks)}",
        ]
        lines.extend(
            f"- `{subtask['id']}` {subtask['title']} [{subtask['agent']}]"
            for subtask in subtasks
        )
        await interaction.response.send_message("\n".join(lines), ephemeral=False)
    except PlannerPolicyViolation as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
    except PlannerInvocationError as exc:
        queue_path = write_fallback_task(payload)
        await interaction.response.send_message(
            "Planner failed, so the task was queued as a single fallback execution task.\n"
            f"repo: `{repo}`\n"
            f"title: `{title}`\n"
            f"queue: `{Path(queue_path).name}`\n"
            f"error: `{exc}`",
            ephemeral=False,
        )

client.run(TOKEN)
