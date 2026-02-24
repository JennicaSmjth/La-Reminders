import discord
from discord import ui, app_commands
from discord.ext import commands, tasks
from datetime import datetime, time
import json
import os
from dotenv import load_dotenv

# --- INITIAL SETUP ---
load_dotenv()
# On your server, make a file named .env and put: DISCORD_TOKEN=your_actual_token
BOT_TOKEN = os.getenv('DISCORD_TOKEN') or 'TOKEN HERE' 

MY_USER_ID = 896389113576562749  
ASSIGNMENT_FILE = "grade_tasks.json"
ANNOUNCE_CHANNEL_ID = 123456789012345678 # CHANGE THIS to your channel ID

# --- DATA HELPERS ---
def load_tasks():
    try:
        with open(ASSIGNMENT_FILE, "r") as f: return json.load(f)
    except: return []

def save_tasks(data):
    with open(ASSIGNMENT_FILE, "w") as f: json.dump(data, f)

# --- THE UI (MODALS & DROPDOWNS) ---
class AddTaskModal(ui.Modal):
    def __init__(self, subject, owner_name):
        super().__init__(title=f"New {subject} Task")
        self.subject = subject
        self.owner_name = owner_name

    name = ui.TextInput(label="Assignment Name", placeholder="e.g. Chapter 5 Quiz", required=True)
    date = ui.TextInput(label="Due Date (YYYY-MM-DD)", placeholder="2026-03-05", min_length=10, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        data = load_tasks()
        data.append({"subject": self.subject, "name": self.name.value, "due": self.date.value})
        save_tasks(data)
        
        embed = discord.Embed(title="✅ Task Logged", color=discord.Color.green())
        embed.add_field(name="Class", value=self.subject)
        embed.add_field(name="Task", value=self.name.value)
        embed.add_field(name="Due Date", value=self.date.value)
        embed.set_footer(text=f"Managed by {self.owner_name}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

class SubjectView(ui.View):
    def __init__(self, owner_name):
        super().__init__(timeout=None)
        self.owner_name = owner_name
        
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
        await interaction.response.send_modal(AddTaskModal(select.values[0], self.owner_name))

# --- THE BOT CORE ---
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        self.daily_check.start()
        print(f"✅ Bot is online as {self.user}")

    # THE 7:00 AM ALERT LOOP
    @tasks.loop(time=time(hour=7, minute=0)) 
    async def daily_check(self):
        channel = self.get_channel(ANNOUNCE_CHANNEL_ID)
        if not channel: return
        
        data = load_tasks()
        if not data: return
        
        now = datetime.now().date()
        updated_data = []

        for task in data:
            due_date = datetime.strptime(task['due'], "%Y-%m-%d").date()
            days_left = (due_date - now).days

            # Urgency levels
            if days_left == 3:
                await channel.send(f"⏰ @everyone **DUE SOON**: **{task['subject']} - {task['name']}** is in 3 days!")
            elif days_left == 2:
                await channel.send(f"🚧 @everyone **SHOULD START**: **{task['subject']} - {task['name']}** is in 2 days!")
            elif days_left == 1:
                await channel.send(f"💀 @everyone **YOU ARE COOKED**: **{task['subject']} - {task['name']}** is DUE TOMORROW!")
            
            # Keep if not past due
            if days_left > 0:
                updated_data.append(task)
        save_tasks(updated_data)

bot = MyBot()

@bot.tree.command(name="setup_tracker", description="Launch the assignment menu")
async def setup_tracker(interaction: discord.Interaction):
    owner = await interaction.client.fetch_user(MY_USER_ID)
    embed = discord.Embed(
        title="📅 Grade Assignment Tracker", 
        description="Add assignments here. The bot will ping @everyone when deadlines are close.",
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Managed by {owner.name}")
    await interaction.response.send_message(embed=embed, view=SubjectView(owner.name))

bot.run(BOT_TOKEN)
