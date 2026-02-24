import discord
from discord import ui, app_commands
from discord.ext import commands, tasks
from datetime import datetime, time
import json
import asyncio

# ================= CONFIGURATION =================
BOT_TOKEN = 'BOT_TOKEN' 
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

class DeleteTaskSelect(ui.Select):
    def __init__(self, tasks, guild_id):
        options = [
            discord.SelectOption(
                label=f"{t['subject']}: {t['name']}", 
                description=f"Due: {t['due']}", 
                value=str(i)
            ) for i, t in enumerate(tasks)
        ][:25] # Discord limits select menus to 25 items
        super().__init__(placeholder="Select a task to remove...", options=options)
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        data = interaction.client.cached_data
        index = int(self.values[0])
        
        removed = data[self.guild_id]["tasks"].pop(index)
        save_data(data)
        
        await interaction.response.send_message(f"🗑️ Removed: **{removed['name']}**", ephemeral=True)
        # Refresh the main menu to show it's gone
        await interaction.client.refresh_menu(self.guild_id, interaction.channel)

class ManageView(ui.View):
    def __init__(self, tasks, guild_id):
        super().__init__(timeout=60)
        self.add_item(DeleteTaskSelect(tasks, guild_id))

class AddTaskModal(ui.Modal):
    def __init__(self, subject):
        super().__init__(title=f"New {subject} Task")
        self.subject = subject

    name = ui.TextInput(label="Assignment Name", placeholder="e.g. Chapter 4 Quiz", required=True)
    date = ui.TextInput(label="Due Date (YYYY-MM-DD)", placeholder="2026-2-5", min_length=8, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        clean_date = parse_date(self.date.value)
        if not clean_date:
            return await interaction.response.send_message("❌ Invalid date format!", ephemeral=True)

        guild_id = str(interaction.guild_id)
        data = interaction.client.cached_data
        
        if guild_id not in data:
            data[guild_id] = {"channel_id": interaction.channel_id, "tasks": [], "last_menu_id": None}

        data[guild_id]["tasks"].append({"subject": self.subject, "name": self.name.value, "due": str(clean_date)})
        save_data(data)
        
        await interaction.response.send_message(f"✅ Added! Due {clean_date}", ephemeral=True)
        # Refresh the main dashboard
        await interaction.client.refresh_menu(guild_id, interaction.channel)

class SubjectView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    @ui.select(
        placeholder="Select a class to add a deadline...",
        options=[
            discord.SelectOption(label="English", emoji="📚"),
            discord.SelectOption(label="Math", emoji="📐"),
            discord.SelectOption(label="Art", emoji="🎨"),
            discord.SelectOption(label="Music", emoji="🎸"),
            discord.SelectOption(label="Other", emoji="📝")
        ]
    )
    async def select_subject(self, interaction: discord.Interaction, select: ui.Select):
        await interaction.response.send_modal(AddTaskModal(select.values[0]))

    @ui.button(label="🗑️ Manage / Delete Tasks", style=discord.ButtonStyle.danger)
    async def manage_tasks(self, interaction: discord.Interaction, button: ui.Button):
        guild_id = str(interaction.guild_id)
        tasks = interaction.client.cached_data.get(guild_id, {}).get("tasks", [])
        
        if not tasks:
            return await interaction.response.send_message("No tasks to delete! 🥳", ephemeral=True)
        
        # Send the private "Secret Menu" for deletion
        await interaction.response.send_message("Which task would you like to remove?", view=ManageView(tasks, guild_id), ephemeral=True)

# --- THE BOT ---

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.cached_data = load_data()

    async def setup_hook(self):
        await self.tree.sync()
        self.daily_check.start()
        print(f"🚀 Turbo Bot Ready.")

    async def refresh_menu(self, guild_id, channel):
        """The TDS-Style 'Bottom Lock' logic"""
        data = self.cached_data.get(guild_id, {"tasks": []})
        
        # Build the task list display
        task_display = ""
        if not data["tasks"]:
            task_display = "No upcoming deadlines! Chill vibes only. 😎"
        else:
            for t in sorted(data["tasks"], key=lambda x: x['due']):
                task_display += f"• **{t['due']}**: {t['subject']} - {t['name']}\n"

        embed = discord.Embed(
            title="📅 Class Assignment Tracker", 
            description=f"Current Deadlines:\n{task_display}",
            color=discord.Color.blue()
        ).set_footer(text="Developed by Ryan | v2.2.0")

        # 1. SEND NEW FIRST (Instant satisfaction)
        new_msg = await channel.send(embed=embed, view=SubjectView())
        
        # 2. DELETE OLD SECOND (Background cleanup)
        old_id = self.cached_data.get(guild_id, {}).get("last_menu_id")
        self.cached_data[guild_id]["last_menu_id"] = new_msg.id
        save_data(self.cached_data)

        if old_id:
            try:
                old_msg = await channel.fetch_message(old_id)
                await old_msg.delete()
            except: pass

    @tasks.loop(time=time(hour=18, minute=0)) 
    async def daily_check(self):
        now = datetime.now().date()
        for guild_id, info in self.cached_data.items():
            channel = self.get_channel(info["channel_id"])
            if not channel: continue
            
            pings_sent = False
            updated_tasks = []
            for task in info["tasks"]:
                due_date = datetime.strptime(task['due'], "%Y-%m-%d").date()
                days_left = (due_date - now).days
                
                if 0 < days_left <= 3:
                    colors = {3: discord.Color.green(), 2: discord.Color.gold(), 1: discord.Color.red()}
                    titles = {3: "🟢 3 DAYS LEFT", 2: "🟡 2 DAYS LEFT", 1: "🔴 FINAL WARNING"}
                    
                    embed = discord.Embed(title=titles[days_left], description=f"**{task['subject']}**: {task['name']}", color=colors[days_left])
                    await channel.send(content="@everyone", embed=embed)
                    pings_sent = True
                
                if days_left >= 0: # Keep tasks until the day they are due
                    updated_tasks.append(task)
            
            self.cached_data[guild_id]["tasks"] = updated_tasks
            save_data(self.cached_data)
            if pings_sent:
                await self.refresh_menu(guild_id, channel)

bot = MyBot()

@bot.tree.command(name="setup_tracker", description="Initializes the tracker in this channel")
@app_commands.checks.has_permissions(administrator=True)
async def setup_tracker(interaction: discord.Interaction):
    await interaction.response.send_message("Initializing Dashboard...", ephemeral=True)
    guild_id = str(interaction.guild_id)
    if guild_id not in bot.cached_data:
        bot.cached_data[guild_id] = {"tasks": [], "channel_id": interaction.channel_id, "last_menu_id": None}
    else:
        bot.cached_data[guild_id]["channel_id"] = interaction.channel_id
    
    await bot.refresh_menu(guild_id, interaction.channel)

bot.run(BOT_TOKEN)
