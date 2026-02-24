import discord
from discord import ui, app_commands
from discord.ext import commands, tasks
from datetime import datetime, time
import json
import os

# ================= CONFIGURATION =================
BOT_TOKEN = 'PASTE_YOUR_TOKEN_HERE' 
# =================================================

ASSIGNMENT_FILE = "grade_tasks.json"

# --- DATA HELPERS ---
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
class AddTaskModal(ui.Modal):
    def __init__(self, subject):
        super().__init__(title=f"New {subject} Task")
        self.subject = subject

    name = ui.TextInput(label="Assignment Name", placeholder="e.g. Chapter 4 Quiz", required=True)
    date = ui.TextInput(label="Due Date (YYYY-MM-DD)", placeholder="2026-2-5", min_length=8, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        clean_date = parse_date(self.date.value)
        if not clean_date:
            return await interaction.response.send_message("❌ Invalid date! Use YYYY-MM-DD (e.g., 2026-3-25)", ephemeral=True)

        guild_id = str(interaction.guild_id)
        data = load_data()
        
        if guild_id not in data:
            data[guild_id] = {"channel_id": interaction.channel_id, "tasks": [], "last_menu_id": None}

        data[guild_id]["tasks"].append({"subject": self.subject, "name": self.name.value, "due": str(clean_date)})
        save_data(data)
        
        now = datetime.now().date()
        days_left = (clean_date - now).days
        
        await interaction.response.send_message(f"✅ Added! Due in {days_left} days.", ephemeral=True)

        # Immediate ping if it's due tomorrow
        if days_left == 1:
            await interaction.channel.send(content="@everyone", embed=discord.Embed(
                title="🔴 ITS OVER IF YOU HAVN'T STARTED",
                description=f"**LATE ENTRY**: {self.subject} - {self.name.value} is due tomorrow!",
                color=discord.Color.red()
            ).set_footer(text="Managed by Ryan"))
            await interaction.client.refresh_menu(guild_id, interaction.channel)

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

# --- THE BOT CORE ---
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        self.daily_check.start()
        print(f"✅ Bot is live. Daily alerts at 6:00 PM.")

    async def refresh_menu(self, guild_id, channel):
        data = load_data()
        # Delete old menu if it exists
        if data.get(guild_id, {}).get("last_menu_id"):
            try:
                old_msg = await channel.fetch_message(data[guild_id]["last_menu_id"])
                await old_msg.delete()
            except: pass

        embed = discord.Embed(
            title="📅 Grade Assignment Tracker", 
            description="Select a class to add a deadline. The bot will ping @everyone here at 6:00 PM daily.",
            color=discord.Color.blue()
        )
        embed.set_footer(text="Managed by Ryan")
        new_msg = await channel.send(embed=embed, view=SubjectView())
        
        data[guild_id]["last_menu_id"] = new_msg.id
        save_data(data)

    @tasks.loop(time=time(hour=18, minute=0)) 
    async def daily_check(self):
        data = load_data()
        now = datetime.now().date()

        for guild_id, info in data.items():
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
                    embed.set_footer(text="Managed by Ryan")
                    await channel.send(content="@everyone", embed=embed)
                    pings_sent = True
                
                if days_left > 0: updated_tasks.append(task)
            
            data[guild_id]["tasks"] = updated_tasks
            save_data(data)
            if pings_sent:
                await self.refresh_menu(guild_id, channel)

bot = MyBot()

@bot.tree.command(name="setup_tracker", description="Admins: Initialize the tracker in this channel")
@app_commands.checks.has_permissions(administrator=True)
async def setup_tracker(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    data = load_data()
    if guild_id not in data:
        data[guild_id] = {"tasks": [], "last_menu_id": None}
    data[guild_id]["channel_id"] = interaction.channel_id
    save_data(data)
    await interaction.response.send_message("Initializing...", ephemeral=True)
    await bot.refresh_menu(guild_id, interaction.channel)

@bot.tree.command(name="test_embed", description="Verify layout and move menu to bottom")
async def test_embed(interaction: discord.Interaction):
    test_embed = discord.Embed(
        title="🔍 DIAGNOSTIC TEST",
        description="Testing layout. Subject: TEST | Task: TEST TEST TEST",
        color=discord.Color.blue()
    )
    test_embed.add_field(name="Current Status", value="🔴 ITS OVER IF YOU HAVN'T STARTED")
    test_embed.set_footer(text="Managed by Ryan")
    
    await interaction.response.send_message("Diagnostic running...", ephemeral=True)
    await interaction.channel.send(content="@everyone", embed=test_embed)
    await bot.refresh_menu(str(interaction.guild_id), interaction.channel)

bot.run(BOT_TOKEN)
