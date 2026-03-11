"""
Class Assignment Tracker — Discord Bot
Ryan's Tracker
"""

import discord
from discord import app_commands
from discord.ui import View, Select, Button, Modal, TextInput
from discord.ext import tasks
import json
import os
import asyncio
import uuid
from datetime import datetime, date, time, timedelta

# ── Token Bootstrap ──────────────────────────────────────────────────────────
TOKEN_FILE = "Token File.txt"

if not os.path.exists(TOKEN_FILE):
    with open(TOKEN_FILE, "w") as f:
        f.write("TOKEN=RIGHT_HERE")
    print("=" * 50)
    print("Token File.txt has been created.")
    print("Open it and replace RIGHT_HERE with your bot token, then re-run.")
    print("=" * 50)
    exit(1)

with open(TOKEN_FILE, "r") as f:
    content = f.read().strip()

token_value = ""
for line in content.splitlines():
    if line.startswith("TOKEN="):
        token_value = line[6:].strip()

if not token_value or token_value == "RIGHT_HERE":
    print("=" * 50)
    print("Please open Token File.txt and replace RIGHT_HERE with your actual bot token, then re-run.")
    print("=" * 50)
    exit(1)

BOT_TOKEN = token_value

# ── Data ─────────────────────────────────────────────────────────────────────
DATA_FILE = "tracker_data.json"

def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_guild_data(data: dict, guild_id) -> dict:
    key = str(guild_id)
    if key not in data:
        data[key] = {"channel_id": None, "message_id": None, "assignments": []}
    return data[key]

# ── Helpers ───────────────────────────────────────────────────────────────────
PRIORITY_EMOJI  = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}
PRIORITY_LABEL  = {"Low": "🟢 LOW", "Medium": "🟡 MED", "High": "🔴 HIGH"}
CLASS_EMOJI     = {
    "English": "📚", "Math": "📐", "Science": "🧪",
    "Art": "🎨",    "Music": "🎸", "Other": "📝",
}
CLASSES = list(CLASS_EMOJI.keys())
BAR = "──────────────────"

def due_timestamp(due_str: str) -> int:
    return int(datetime.strptime(due_str, "%Y-%m-%d").timestamp())

def parse_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None

def build_embed(assignments: list) -> discord.Embed:
    embed = discord.Embed(
        title="📅 Class Assignment Tracker",
        description="*Current active deadlines:*",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Ryan's Tracker")

    if not assignments:
        embed.description = "No homework due that usually doesnt happen"
        return embed

    sorted_assignments = sorted(assignments, key=lambda x: x["due"])
    for i, a in enumerate(sorted_assignments):
        prio    = a.get("priority", "Low")
        p_label = PRIORITY_LABEL.get(prio, "🟢 LOW")
        emoji   = CLASS_EMOJI.get(a["class"], "📝")
        raw     = a.get("details") or "No details."
        # Truncate to 60 chars max to keep the embed tidy
        details = raw if len(raw) <= 60 else raw[:57] + "..."
        ts      = due_timestamp(a["due"])
        # Only add BAR + tip on the last entry to eliminate the blank-field gap
        is_last = (i == len(sorted_assignments) - 1)
        suffix  = f"\n{BAR}\nTip: use `/what` for help" if is_last else f"\n{BAR}"
        embed.add_field(
            name  = f"📌 {emoji} {a['class'].upper()}: {a['name']} [{p_label}]",
            value = f"📅 **Due:** <t:{ts}:R>\n📝 {details}{suffix}",
            inline=False
        )
    return embed

def build_urgent_embed(assignments: list, day_range: int = 7):
    today  = date.today()
    urgent = []
    for a in assignments:
        d = parse_date(a["due"])
        if d is None:
            continue
        delta = (d - today).days
        if 0 <= delta <= day_range:
            urgent.append((delta, a))
    if not urgent:
        return None
    urgent.sort(key=lambda x: x[0])
    embed = discord.Embed(title="⚠️ ASSIGNMENTS DUE SOON", color=discord.Color.red())
    embed.set_footer(text="Ryan's Tracker")
    for days, a in urgent:
        time_str = "DUE TODAY! 🚨" if days == 0 else f"{days} day(s) left"
        p_label  = PRIORITY_LABEL.get(a.get("priority", "Low"), "🟢 LOW")
        embed.add_field(
            name  = f"🛑 {a['name']} [{p_label}]",
            value = f"**Time:** {time_str}\n**Date:** {a['due']}\n{BAR}",
            inline=False
        )
    return embed

def build_medium_list_embed(assignments: list) -> discord.Embed:
    """Fallback embed listing all medium priority assignments when nothing is urgent."""
    mediums = [a for a in assignments if a.get("priority") == "Medium"]
    embed = discord.Embed(title="📋 No urgent deadlines — here's your mediums", color=discord.Color.yellow())
    embed.set_footer(text="Ryan's Tracker")
    for a in sorted(mediums, key=lambda x: x["due"]):
        ts = due_timestamp(a["due"])
        embed.add_field(
            name  = f"🟡 {a['class']}: {a['name']}",
            value = f"📅 **Due:** <t:{ts}:R>\n{BAR}",
            inline=False
        )
    return embed

# ── Per-guild locks ───────────────────────────────────────────────────────────
guild_locks: dict = {}

def get_lock(guild_id) -> asyncio.Lock:
    key = str(guild_id)
    if key not in guild_locks:
        guild_locks[key] = asyncio.Lock()
    return guild_locks[key]

# ── Bot ───────────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

bot  = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# ── Dashboard refresh ─────────────────────────────────────────────────────────
async def refresh_dashboard(guild: discord.Guild):
    async with get_lock(guild.id):
        data = load_data()
        gd   = get_guild_data(data, guild.id)

        channel_id = gd.get("channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return

        old_msg_id = gd.get("message_id")

        # Send new first → instant appearance
        new_msg = await channel.send(embed=build_embed(gd["assignments"]), view=DashboardView())

        # Delete old in background → non-blocking
        if old_msg_id:
            asyncio.create_task(_delete_safe(channel, old_msg_id))

        gd["message_id"] = new_msg.id
        save_data(data)

async def _delete_safe(channel, msg_id):
    try:
        await channel.get_partial_message(msg_id).delete()
    except Exception:
        pass

# ── Views ─────────────────────────────────────────────────────────────────────
class AddAssignmentModal(Modal):
    def __init__(self, class_name: str, prefill: dict = None):
        super().__init__(title=f"New {class_name} Assignment")
        self.class_name = class_name
        self.edit_id    = None

        self.assignment_name = TextInput(
            label="Assignment Name", placeholder="e.g. Lab Report",
            max_length=100, default=prefill.get("name", "") if prefill else ""
        )
        self.due_date = TextInput(
            label="Due Date (YYYY-MM-DD)", placeholder="2030-04-7",
            min_length=10, max_length=10, default=prefill.get("due", "") if prefill else ""
        )
        self.details = TextInput(
            label="Details (optional)", style=discord.TextStyle.paragraph,
            placeholder="Instructions & Important stuff", max_length=300, required=False,
            default=prefill.get("details", "") if prefill else ""
        )
        self.add_item(self.assignment_name)
        self.add_item(self.due_date)
        self.add_item(self.details)

    async def on_submit(self, interaction: discord.Interaction):
        name    = self.assignment_name.value.strip()
        due     = self.due_date.value.strip()
        details = self.details.value.strip() if self.details.value else ""

        parsed = parse_date(due)
        if not parsed:
            await interaction.response.send_message("❌ Invalid date! Use YYYY-MM-DD.", ephemeral=True)
            return
        if parsed < date.today():
            await interaction.response.send_message("Wrong date bud", ephemeral=True)
            return
        if details and len(details.split()) > 50:
            await interaction.response.send_message(
                "Too long! Keep it under 50 words and try paraphrasing.", ephemeral=True)
            return

        await interaction.response.send_message(
            "Last step: Select Priority level",
            view=PrioritySelectView(self.class_name, name, due, details, self.edit_id),
            ephemeral=True
        )


class PrioritySelectView(View):
    def __init__(self, class_name, name, due, details, edit_id=None):
        super().__init__(timeout=120)
        self.add_item(PrioritySelect(class_name, name, due, details, edit_id))


class PrioritySelect(Select):
    def __init__(self, class_name, name, due, details, edit_id=None):
        self.class_name        = class_name
        self.assignment_name   = name
        self.due               = due
        self.details           = details
        self.edit_id           = edit_id
        super().__init__(
            placeholder="Choose priority level...",
            options=[
                discord.SelectOption(label="High Priority", emoji="🔴", value="High"),
                discord.SelectOption(label="Medium Priority", emoji="🟡", value="Medium"),
                discord.SelectOption(label="Low Priority",  emoji="🟢", value="Low"),
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        priority = self.values[0]
        data = load_data()
        gd   = get_guild_data(data, interaction.guild_id)

        if self.edit_id:
            for a in gd["assignments"]:
                if a["id"] == self.edit_id:
                    a.update(name=self.assignment_name, **{"class": self.class_name},
                             due=self.due, details=self.details, priority=priority)
                    break
        else:
            gd["assignments"].append({
                "id": str(uuid.uuid4()), "class": self.class_name,
                "name": self.assignment_name, "due": self.due,
                "details": self.details, "priority": priority
            })

        save_data(data)
        await interaction.response.edit_message(
            content=f"✅ Task Added: **{self.assignment_name}**!", view=None)
        await refresh_dashboard(interaction.guild)


class ClassDropdown(Select):
    def __init__(self):
        super().__init__(
            placeholder="Add a deadline...",
            options=[discord.SelectOption(label=cls, emoji=em) for cls, em in CLASS_EMOJI.items()],
            custom_id="class_dropdown"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddAssignmentModal(class_name=self.values[0]))


class DeleteSelect(Select):
    def __init__(self, assignments: list):
        super().__init__(
            placeholder="Select to remove...",
            options=[
                discord.SelectOption(label=f"{a['class']}: {a['name'][:50]}", value=a["id"])
                for a in assignments[:25]
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        data = load_data()
        gd   = get_guild_data(data, interaction.guild_id)
        gd["assignments"] = [a for a in gd["assignments"] if a["id"] != self.values[0]]
        save_data(data)
        await interaction.response.edit_message(content="✅ Removed.", view=None)
        await asyncio.sleep(3)
        try:
            await interaction.delete_original_response()
        except Exception:
            pass
        await refresh_dashboard(interaction.guild)


class DashboardView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ClassDropdown())
        self.add_item(CleanUpButton())


class CleanUpButton(Button):
    def __init__(self):
        super().__init__(label="✨ Clean Up List", style=discord.ButtonStyle.secondary,
                         custom_id="cleanup_btn")

    async def callback(self, interaction: discord.Interaction):
        data = load_data()
        gd   = get_guild_data(data, interaction.guild_id)
        if not gd["assignments"]:
            await interaction.response.send_message("Nothing to clean!", ephemeral=True)
            return
        view = View(timeout=60)
        view.add_item(DeleteSelect(gd["assignments"]))
        await interaction.response.send_message("Delete a task:", view=view, ephemeral=True)

# ── Daily task: auto-clean + reminder pings ───────────────────────────────────
@tasks.loop(time=time(hour=16, minute=0))
async def daily_check():
    data     = load_data()
    today    = date.today()
    tomorrow = today + timedelta(days=1)

    for guild_id, gd in data.items():
        # Auto-upgrade LOW → MEDIUM if due tomorrow
        for a in gd["assignments"]:
            if a.get("priority") == "Low" and parse_date(a["due"]) == tomorrow:
                a["priority"] = "Medium"

        # Strip past assignments
        gd["assignments"] = [
            a for a in gd["assignments"]
            if parse_date(a["due"]) is not None and parse_date(a["due"]) >= today
        ]
        save_data(data)

        chan_id = gd.get("channel_id")
        if not chan_id:
            continue
        channel = bot.get_channel(int(chan_id))
        if not channel:
            continue

        # @everyone for HIGH due tomorrow
        hp = [a for a in gd["assignments"]
              if parse_date(a["due"]) == tomorrow and a.get("priority") == "High"]
        if hp:
            names = ", ".join(f"**{a['name']}**" for a in hp)
            await channel.send(
                f"🚨 @everyone **URGENT:** {names} {'is' if len(hp) == 1 else 'are'} due TOMORROW! 🚨")

        # 7-day warning embed — if nothing urgent, fall back to medium list
        remind = build_urgent_embed(gd["assignments"], day_range=7)
        if remind:
            await channel.send(embed=remind)
        else:
            mediums = [a for a in gd["assignments"] if a.get("priority") == "Medium"]
            if mediums:
                await channel.send(embed=build_medium_list_embed(gd["assignments"]))

        await refresh_dashboard(channel.guild)

# ── Events ────────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    bot.add_view(DashboardView())
    await tree.sync()
    daily_check.start()
    print(f"✅ Logged in as {bot.user} — commands synced.")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    data = load_data()
    gd   = get_guild_data(data, message.guild.id)
    if gd.get("channel_id") == message.channel.id:
        await refresh_dashboard(message.guild)

@bot.event
async def on_message_delete(message: discord.Message):
    if not message.guild:
        return
    data = load_data()
    gd   = get_guild_data(data, message.guild.id)
    if gd.get("message_id") == message.id:
        gd["message_id"] = None
        save_data(data)
        await refresh_dashboard(message.guild)

# ── Slash Commands ────────────────────────────────────────────────────────────
@tree.command(name="setup_tracker", description="Admin: set up the assignment tracker channel.")
async def setup_tracker(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Imagine not having admin 🙉", ephemeral=True)
        return

    data = load_data()
    gd   = get_guild_data(data, interaction.guild_id)

    if gd.get("channel_id"):
        ch      = interaction.guild.get_channel(gd["channel_id"])
        mention = ch.mention if ch else f"<deleted channel {gd['channel_id']}>"
        await interaction.response.send_message(
            f"There's already a tracker in {mention}. Use `/reset_tracker` first.", ephemeral=True)
        async def _del():
            await asyncio.sleep(5)
            try: await interaction.delete_original_response()
            except: pass
        asyncio.create_task(_del())
        return

    channels = interaction.guild.text_channels[:25]
    options  = [discord.SelectOption(label=f"#{c.name}", value=str(c.id)) for c in channels]

    class ChannelSelect(Select):
        def __init__(self):
            super().__init__(placeholder="Pick a channel...", options=options)

        async def callback(self2, inter: discord.Interaction):
            d2  = load_data()
            gd2 = get_guild_data(d2, inter.guild_id)
            gd2["channel_id"] = int(self2.values[0])
            gd2["message_id"] = None
            save_data(d2)

            async def _confirm():
                await inter.response.send_message("✅ Tracker set up!", ephemeral=True)
                await asyncio.sleep(3)
                try: await inter.delete_original_response()
                except: pass

            await asyncio.gather(_confirm(), refresh_dashboard(inter.guild))

    v = View(timeout=60)
    v.add_item(ChannelSelect())
    await interaction.response.send_message("Select the tracker channel:", view=v, ephemeral=True)


@tree.command(name="reset_tracker", description="Admin: reset tracker setup. Assignments are preserved.")
async def reset_tracker(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Imagine not having admin.", ephemeral=True)
        return
    data = load_data()
    gd   = get_guild_data(data, interaction.guild_id)
    gd["channel_id"] = None
    gd["message_id"] = None
    save_data(data)
    await interaction.response.send_message(
        "🔄 Tracker reset (dw nth was deleted) Run `/setup_tracker` again.", ephemeral=True)


@tree.command(name="edit_assignment", description="Edit an existing assignment.")
async def edit_assignment(interaction: discord.Interaction):
    data = load_data()
    gd   = get_guild_data(data, interaction.guild_id)
    if not gd["assignments"]:
        await interaction.response.send_message("like are you slow. Theres nothing to edit like I have to write these by hand", ephemeral=True)
        return

    options = [
        discord.SelectOption(
            label=f"{a['class']}: {a['name'][:50]}",
            emoji=CLASS_EMOJI.get(a["class"], "📝"),
            value=a["id"]
        ) for a in gd["assignments"][:25]
    ]

    class EditSelect(Select):
        def __init__(self):
            super().__init__(placeholder="Select assignment to edit...", options=options)

        async def callback(self2, inter: discord.Interaction):
            d2     = load_data()
            gd2    = get_guild_data(d2, inter.guild_id)
            target = next((a for a in gd2["assignments"] if a["id"] == self2.values[0]), None)
            if not target:
                await inter.response.send_message("Assignment not found.", ephemeral=True)
                return
            modal         = AddAssignmentModal(class_name=target["class"], prefill=target)
            modal.edit_id = target["id"]
            await inter.response.send_modal(modal)

    v = View(timeout=60)
    v.add_item(EditSelect())
    await interaction.response.send_message("Select assignment to edit:", view=v, ephemeral=True)


@tree.command(name="what", description="Quick guide for the bot.")
async def what(interaction: discord.Interaction):
    embed = discord.Embed(title="📘 Ryan's Bot: Quick Guide", color=0x57F287)
    embed.add_field(name="The Logic", value=(
        "• **Blue Dashboard:** Stays at the bottom — auto-refreshes on every message.\n"
        "• **Daily 2:30 PM Check:** Cleans past assignments + posts 7-day warning embed.\n"
        "• **🚨 High Priority:** Pings @everyone the day before a HIGH assignment is due."
    ), inline=False)
    embed.add_field(name="Commands", value=(
        "• `/setup_tracker` — Admin: pick a channel for the dashboard.\n"
        "• `/reset_tracker` — Admin: reset setup if stuck (assignments stay).\n"
        "• `/edit_assignment` — Edit any assignment.\n"
        "• `/remind_now` — Private 3-day check.\n"
        "• `/what` just a guid"
    ), inline=False)
    embed.add_field(name="Adding Assignments", value=(
        "Use **Add a deadline...** on the dashboard → fill the modal → pick priority."
    ), inline=False)
    embed.add_field(name="Deleting Assignments", value=(
        "Hit **✨ Clean Up List** on the dashboard → pick what to remove."
    ), inline=False)
    embed.set_footer(text="Ryan's Tracker")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="remind_now", description="Private 3-day deadline check.")
async def remind_now(interaction: discord.Interaction):
    data   = load_data()
    gd     = get_guild_data(data, interaction.guild_id)
    remind = build_urgent_embed(gd["assignments"], day_range=3)
    if remind:
        await interaction.response.send_message(embed=remind, ephemeral=True)
    else:
        await interaction.response.send_message("Nothing due in 3 days!", ephemeral=True)

# ── Run ───────────────────────────────────────────────────────────────────────
bot.run(BOT_TOKEN)
