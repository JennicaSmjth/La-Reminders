import discord
from discord import ui, app_commands
from discord.ext import commands, tasks
from datetime import datetime, time
import json

# ================= CONFIGURATION =================
BOT_TOKEN = 'PASTE_YOUR_TOKEN_HERE' 
# =================================================

ASSIGNMENT_FILE = "grade_tasks.json"

def load_tasks():
    try:
        with open(ASSIGNMENT_FILE, "r") as f: return json.load(f)
    except: return {"channel_id": None, "tasks": []}

def save_tasks(data):
    with open(ASSIGNMENT_FILE, "w") as f: json.dump(data, f)

class AddTaskModal(ui.Modal):
    def __init__(self, subject):
        super().__init__(title=f"New {subject} Task")
        self.subject = subject

    name = ui.TextInput(label="Assignment Name", placeholder="e.g. History Essay", required=True)
    date = ui.TextInput(label="Due Date (YYYY-MM-DD)", placeholder="2026-03-05", min_length=10, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        data = load_tasks()
        data["tasks"].append({"subject": self.subject, "name": self.name.value, "due": self.date.value})
        save_tasks(data)
        
        embed = discord.Embed(title="✅ Task Logged", color=discord.Color.green())
        embed.add_field(name="Class", value=self.subject)
        embed.add_field(name="Task", value=self.name.value)
        embed.set_footer(text="Managed by Ryan")
        
        await interaction.response.send_message(f"Logged! I'll ping everyone here 3 days before **{self.date.value}**.", embed=embed, ephemeral=True)

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

    async def setup_hook(self):
        await self.tree.sync()
        self.daily_check.start()
        print(f"✅ {self.user} is online and managed by Ryan.")

    @tasks.loop(time=time(hour=7, minute=0)) 
    async def daily_check(self):
        data = load_tasks()
        if not data["channel_id"] or not data["tasks"]: return
        
        channel = self.get_channel(data["channel_id"])
        if not channel: return
        
        now = datetime.now().date()
        updated_tasks = []

        for task in data["tasks"]:
            due_date = datetime.strptime(task['due'], "%Y-%m-%d").date()
            days_left = (due_date - now).days

            if days_left == 3:
                await channel.send(f"⏰ @everyone **DUE SOON**: **{task['subject']} - {task['name']}** is in 3 days!")
            elif days_left == 2:
                await channel.send(f"🚧 @everyone **SHOULD START**: **{task['subject']} - {task['name']}** is in 2 days!")
            elif days_left == 1:
                await channel.send(f"💀 @everyone **YOU ARE COOKED**: **{task['subject']} - {task['name']}** is DUE TOMORROW!")
            
            if days_left > 0: updated_tasks.append(task)
            
        data["tasks"] = updated_tasks
        save_tasks(data)

bot = MyBot()

@bot.tree.command(name="setup_tracker", description="Admins only: Set the channel for reminders")
@app_commands.checks.has_permissions(administrator=True)
async def setup_tracker(interaction: discord.Interaction):
    data = load_tasks()
    data["channel_id"] = interaction.channel_id
    save_tasks(data)

    embed = discord.Embed(
        title="📅 Grade Assignment Tracker", 
        description="Select a class below to add a deadline. The bot will ping @everyone here at 7:00 AM when the deadline is close.",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Managed by Ryan")
    await interaction.response.send_message(embed=embed, view=SubjectView())

bot.run(BOT_TOKEN)
