import discord
from discord import ui, app_commands
from discord.ext import commands, tasks
from datetime import datetime, time
import json

# ================= CONFIGURATION =================
# 1. Paste your new Bot Token here:
BOT_TOKEN = 'PASTE_YOUR_TOKEN_HERE' 
ASSIGNMENT_FILE = "grade_tasks.json"
# =================================================

def load_data():
    try:
        with open(ASSIGNMENT_FILE, "r") as f: return json.load(f)
    except: return {}

def save_data(data):
    with open(ASSIGNMENT_FILE, "w") as f: json.dump(data, f, indent=4)

def parse_date(date_str):
    for fmt in ("%Y-%m-%d", "%Y-%m-%j", "%Y-%n-%j", "%Y-%n-%d"):
        try: return datetime.strptime(date_str, fmt).date()
        except ValueError: continue
    return None

# --- UI COMPONENTS ---

class ConfirmDeleteView(ui.View):
    def __init__(self, task_index, guild_id):
        super().__init__(timeout=30)
        self.task_index = task_index
        self.guild_id = guild_id

    @ui.button(label="Confirm Cleanup", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        data = interaction.client.cached_data
        if len(data[self.guild_id]["tasks"]) > self.task_index:
            removed = data[self.guild_id]["tasks"].pop(self.task_index)
            save_data(data)
            await interaction.response.edit_message(content=f"✅ Removed: **{removed['name']}**", view=None)
            await interaction.client.refresh_menu(self.guild_id, interaction.channel)
        else:
            await interaction.response.edit_message(content="❌ Task not found.", view=None)

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content="Cancelled.", view=None)

class DeleteTaskSelect(ui.Select):
    def __init__(self, tasks, guild_id):
        options = [
            discord.SelectOption(label=f"{t['name']}", description=f"Due: {t['due']}", value=str(i))
            for i, t in enumerate(tasks)
        ][:25]
        super().__init__(placeholder="Select a task to remove...", options=options)
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        index = int(self.values[0])
        await interaction.response.send_message(
            content="⚠️ Remove this assignment from the list?",
            view=ConfirmDeleteView(index, self.guild_id),
            ephemeral=True
        )

class AddTaskModal(ui.Modal):
    def __init__(self, subject):
        super().__init__(title=f"New {subject} Task")
        self.subject = subject

    name = ui.TextInput(label="Assignment Name", placeholder="e.g. Lab Report", required=True)
    date = ui.TextInput(label="Due Date (YYYY-MM-DD)", placeholder="2026-02-26", min_length=10, max_length=10)
    info = ui.TextInput(
        label="Task Details", 
        style=discord.TextStyle.paragraph, 
        placeholder="Instructions, links, or page numbers...",
        required=False,
        max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        clean_date = parse_date(self.date.value)
        if not clean_date:
            return await interaction.response.send_message("❌ Invalid date! Use YYYY-MM-DD", ephemeral=True)
        
        if clean_date < datetime.now().date():
            return await interaction.response.send_message("Nah why you trying to put old assignments", ephemeral=True)

        guild_id = str(interaction.guild_id)
        data = interaction.client.cached_data
        
        if guild_id not in data:
            data[guild_id] = {"channel_id": interaction.channel_id, "tasks": [], "last_menu_id": None}

        data[guild_id]["tasks"].append({
            "subject": self.subject, 
            "name": self.name.value, 
            "due": str(clean_date),
            "info": self.info.value or "No extra details provided."
        })
        save_data(data)
        
        await interaction.response.send_message(f"✅ Added {self.name.value}!", ephemeral=True)
        await interaction.client.refresh_menu(guild_id, interaction.channel)

class SubjectView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    @ui.select(
        placeholder="Select a class to add a deadline...",
        options=[
            discord.SelectOption(label="English", emoji="📚"),
            discord.SelectOption(label="Math", emoji="📐"),
            discord.SelectOption(label="Science", emoji="🧪"),
            discord.SelectOption(label="Art", emoji="🎨"),
            discord.SelectOption(label="Music", emoji="🎸"),
            discord.SelectOption(label="Other", emoji="📝")
        ]
    )
    async def select_subject(self, interaction: discord.Interaction, select: ui.Select):
        await interaction.response.send_modal(AddTaskModal(select.values[0]))

    @ui.button(label="✨ Clean up List", style=discord.ButtonStyle.secondary)
    async def manage_tasks(self, interaction: discord.Interaction, button: ui.Button):
        guild_id = str(interaction.guild_id)
        tasks = interaction.client.cached_data.get(guild_id, {}).get("tasks", [])
        if not tasks:
            return await interaction.response.send_message("Nothing to clean!", ephemeral=True)
        await interaction.response.send_message("Select a task to remove:", view=ui.View().add_item(DeleteTaskSelect(tasks, guild_id)), ephemeral=True)

# --- THE BOT CORE ---

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.cached_data = load_data()

    async def setup_hook(self):
        await self.tree.sync()
        self.daily_check.start()

    async def refresh_menu(self, guild_id, channel):
        data = self.cached_data.get(guild_id, {"tasks": [], "last_menu_id": None})
        
        embed = discord.Embed(
            title="📅 Class Assignment Tracker", 
            description="*Current active deadlines for the class:*",
            color=discord.Color.blue()
        )
        
        if not data["tasks"]:
            embed.description = "No upcoming deadlines! Chill vibes only. 😎"
        else:
            sorted_tasks = sorted(data["tasks"], key=lambda x: x['due'])
            for t in sorted_tasks:
                # The "Card" Design with double bars
                bar = "──────────────────"
                field_name = f"📌 {t['subject'].upper()}: {t['name']}"
                field_val = f"{bar}\n📅 **Due:** {t['due']}\n📝 {t['info']}\n{bar}"
                embed.add_field(name=field_name, value=field_val, inline=False)

        # Bottom-Lock: Clean up old menu
        old_id = data.get("last_menu_id")
        if old_id:
            try:
                msg = await channel.fetch_message(old_id)
                await msg.delete()
            except: pass

        new_msg = await channel.send(embed=embed, view=SubjectView())
        self.cached_data[guild_id]["last_menu_id"] = new_msg.id
        save_data(self.cached_data)

    @tasks.loop(time=time(hour=8, minute=0))
    async def daily_check(self):
        """Auto-Clear and Reminders"""
        today = datetime.now().date()
        for guild_id, info in self.cached_data.items():
            # Clear yesterday's tasks
            info["tasks"] = [t for t in info["tasks"] if parse_date(t["due"]) >= today]
            save_data(self.cached_data)

            # Check for things due Today/Tomorrow
            urgent = [t for t in info["tasks"] if (parse_date(t["due"]) - today).days <= 1]
            channel = self.get_channel(info["channel_id"])
            if channel:
                if urgent:
                    await channel.send(f"⚠️ **Urgent:** You have {len(urgent)} tasks due soon!")
                await self.refresh_menu(guild_id, channel)

bot = MyBot()

@bot.tree.command(name="setup_tracker")
async def setup(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    bot.cached_data[guild_id] = {"channel_id": interaction.channel_id, "tasks": [], "last_menu_id": None}
    save_data(bot.cached_data)
    await interaction.response.send_message("Tracker Setup Complete!", ephemeral=True)
    await bot.refresh_menu(guild_id, interaction.channel)

bot.run(BOT_TOKEN)
