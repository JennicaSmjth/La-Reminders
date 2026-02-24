import discord
from discord import ui, app_commands
from discord.ext import commands, tasks
from datetime import datetime, time
import json

# ================= CONFIGURATION =================
BOT_TOKEN = 'PASTE_YOUR_TOKEN_HERE' 
# =================================================

ASSIGNMENT_FILE = "grade_tasks.json"

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

class AddTaskModal(ui.Modal):
    def __init__(self, subject):
        super().__init__(title=f"New {subject} Task")
        self.subject = subject

    name = ui.TextInput(label="Assignment Name", placeholder="e.g. Chapter 4 Quiz", required=True)
    date = ui.TextInput(label="Due Date (YYYY-MM-DD)", placeholder="2026-2-5", min_length=8, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        clean_date = parse_date(self.date.value)
        if not clean_date:
            return await interaction.response.send_message("❌ Invalid date!", ephemeral=True)

        guild_id = str(interaction.guild_id)
        # Use the bot's memory instead of reading the file
        data = interaction.client.cached_data
        
        if guild_id not in data:
            data[guild_id] = {"channel_id": interaction.channel_id, "tasks": [], "last_menu_id": None}

        data[guild_id]["tasks"].append({"subject": self.subject, "name": self.name.value, "due": str(clean_date)})
        save_data(data) # Save to file in background
        
        await interaction.response.send_message(f"✅ Added! Due {clean_date}", ephemeral=True)

class SubjectView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    @ui.select(
        placeholder="Which class is this for?",
        options=[
            discord.SelectOption(label="English (Mr Andy)", emoji="📚"),
            discord.SelectOption(label="Math (Ms Schumie)", emoji="📐"),
            discord.SelectOption(label="Art (Ms Leah)", emoji="🎨"),
            discord.SelectOption(label="Music (Mr Gonzales)", emoji="🎸"),
            discord.SelectOption(label="Other/General", emoji="📝")
        ]
    )
    async def select_subject(self, interaction: discord.Interaction, select: ui.Select):
        await interaction.response.send_modal(AddTaskModal(select.values[0]))

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        # BRAIN POWER: Load data once into RAM
        self.cached_data = load_data()

    async def setup_hook(self):
        await self.tree.sync()
        self.daily_check.start()
        print(f"✅ Turbo Bot is online.")

    async def refresh_menu(self, guild_id, channel):
        """The 'Sleight of Hand' Refresh"""
        # 1. SEND NEW MENU IMMEDIATELY
        embed = discord.Embed(
            title="📅 Grade Assignment Tracker", 
            description="Select a class to add a deadline. Pings @everyone at 6:00 PM.",
            color=discord.Color.blue()
        ).set_footer(text="Managed by Ryan")
        
        new_msg = await channel.send(embed=embed, view=SubjectView())
        
        # 2. CAPTURE OLD ID
        old_id = self.cached_data.get(guild_id, {}).get("last_menu_id")
        
        # 3. UPDATE MEMORY & FILE
        if guild_id not in self.cached_data:
            self.cached_data[guild_id] = {"tasks": [], "channel_id": channel.id}
        self.cached_data[guild_id]["last_menu_id"] = new_msg.id
        save_data(self.cached_data)

        # 4. DELETE OLD MENU LAST (Background cleanup)
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
                
                embed = None
                if days_left == 3:
                    embed = discord.Embed(title="🟢 3 DAYS LEFT", description=f"**{task['subject']}**: {task['name']}", color=discord.Color.green())
                elif days_left == 2:
                    embed = discord.Embed(title="🟡 2 DAYS LEFT", description=f"**{task['subject']}**: {task['name']}", color=discord.Color.gold())
                elif days_left == 1:
                    embed = discord.Embed(title="🔴 ITS OVER IF YOU HAVN'T STARTED", description=f"**{task['subject']}**: {task['name']}", color=discord.Color.red())

                if embed:
                    await channel.send(content="@everyone", embed=embed.set_footer(text="Managed by Ryan"))
                    pings_sent = True
                if days_left > 0: updated_tasks.append(task)
            
            self.cached_data[guild_id]["tasks"] = updated_tasks
            save_data(self.cached_data)
            if pings_sent:
                await self.refresh_menu(guild_id, channel)

bot = MyBot()

@bot.tree.command(name="setup_tracker")
@app_commands.checks.has_permissions(administrator=True)
async def setup_tracker(interaction: discord.Interaction):
    await interaction.response.send_message("Initializing Turbo Tracker...", ephemeral=True)
    await bot.refresh_menu(str(interaction.guild_id), interaction.channel)

@bot.tree.command(name="test_embed")
async def test_embed(interaction: discord.Interaction):
    test_embed = discord.Embed(title="🔍 DIAGNOSTIC", description="Testing layout...", color=discord.Color.blue()).set_footer(text="Managed by Ryan")
    await interaction.response.send_message("Running...", ephemeral=True)
    await interaction.channel.send(content="@everyone", embed=test_embed)
    await bot.refresh_menu(str(interaction.guild_id), interaction.channel)

bot.run(BOT_TOKEN)
