import discord
from discord import ui, app_commands
from discord.ext import commands, tasks
from datetime import datetime, time, timedelta
import json
import asyncio

# ================= CONFIGURATION =================
BOT_TOKEN = 'huh' 
ASSIGNMENT_FILE = "grade_tasks.json"
GRAD_DATE = datetime(2030, 6, 14).date() # Your Graduation Date
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

def get_relative_time(due_date_str):
    due_date = parse_date(due_date_str)
    if not due_date: return ""
    today = datetime.now().date()
    delta = (due_date - today).days
    if delta == 0: return " (**TODAY!** 🚨)"
    if delta == 1: return " (Tomorrow)"
    if 1 < delta < 7: return f" (In {delta} days)"
    weeks = delta // 7
    days = delta % 7
    if days == 0: return f" (In {weeks} week{'s' if weeks > 1 else ''})"
    return f" (In {weeks}w {days}d)"

# --- UI COMPONENTS ---

class PrioritySelect(ui.Select):
    def __init__(self, task_data, guild_id):
        options = [
            discord.SelectOption(label="High Priority", emoji="🔴", value="🔴 HIGH"),
            discord.SelectOption(label="Medium Priority", emoji="🟡", value="🟡 MED"),
            discord.SelectOption(label="Low Priority", emoji="🟢", value="🟢 LOW")
        ]
        super().__init__(placeholder="Choose priority level...", options=options)
        self.task_data = task_data
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        data = interaction.client.cached_data
        if self.guild_id not in data: 
            data[self.guild_id] = {"tasks": [], "last_menu_id": None, "channel_id": None}
        self.task_data["priority"] = self.values[0]
        data[self.guild_id]["tasks"].append(self.task_data)
        save_data(data)
        await interaction.response.edit_message(content=f"✅ Task Added: **{self.task_data['name']}**!", view=None)
        await interaction.client.refresh_menu(self.guild_id, interaction.channel)

class AddTaskModal(ui.Modal):
    def __init__(self, subject):
        super().__init__(title=f"New {subject} Task")
        self.subject = subject
    name = ui.TextInput(label="Assignment Name", placeholder="e.g. Lab Report", required=True)
    date = ui.TextInput(label="Due Date (YYYY-MM-DD)", placeholder="2026-03-05", min_length=10, max_length=10)
    info = ui.TextInput(label="Task Details", style=discord.TextStyle.paragraph, placeholder="Instructions...", required=False, max_length=200)

    async def on_submit(self, interaction: discord.Interaction):
        clean_date = parse_date(self.date.value)
        if not clean_date: return await interaction.response.send_message("❌ Invalid date", ephemeral=True)
        task_data = {"subject": self.subject, "name": self.name.value, "due": str(clean_date), "info": self.info.value or "No details."}
        view = ui.View().add_item(PrioritySelect(task_data, str(interaction.guild_id)))
        await interaction.response.send_message("Last step: Select Priority", view=view, ephemeral=True)

class SubjectView(ui.View):
    def __init__(self): super().__init__(timeout=None)
    @ui.select(placeholder="Add a deadline...", options=[
        discord.SelectOption(label="English", emoji="📚"), discord.SelectOption(label="Math", emoji="📐"),
        discord.SelectOption(label="Science", emoji="🧪"), discord.SelectOption(label="Art", emoji="🎨"),
        discord.SelectOption(label="Music", emoji="🎸"), discord.SelectOption(label="Other", emoji="📝")
    ])
    async def select_subject(self, interaction: discord.Interaction, select: ui.Select):
        await interaction.response.send_modal(AddTaskModal(select.values[0]))

    @ui.button(label="✨ Clean up List", style=discord.ButtonStyle.secondary)
    async def manage_tasks(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.administrator: return await interaction.response.send_message("too bad u dont have admin", ephemeral=True)
        guild_id = str(interaction.guild_id)
        tasks = interaction.client.cached_data.get(guild_id, {}).get("tasks", [])
        if not tasks: return await interaction.response.send_message("Nothing to clean!", ephemeral=True)
        
        # FIXED: This now shows the name and the date in the dropdown
        options = [
            discord.SelectOption(label=f"{t['name']}", description=f"Due: {t['due']}", value=str(i)) 
            for i, t in enumerate(tasks)
        ][:25]
        
        del_select = ui.Select(placeholder="Select to remove...", options=options)
        
        async def del_callback(idx_interaction: discord.Interaction):
            idx = int(del_select.values[0])
            interaction.client.cached_data[guild_id]["tasks"].pop(idx)
            save_data(interaction.client.cached_data)
            
            await idx_interaction.response.send_message(
                "✅ Removed.\n\n*I swear to not wrongfully remove any real assignments, and only to remove duplicates. If you break this you're a bitch*", 
                ephemeral=True
            )
            await interaction.client.refresh_menu(guild_id, interaction.channel)
            
        del_select.callback = del_callback
        await interaction.response.send_message("Delete a task:", view=ui.View().add_item(del_select), ephemeral=True)

# --- THE BOT CORE ---

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.cached_data = load_data()
        self.lock = asyncio.Lock() 

    async def setup_hook(self):
        self.daily_check.start()
        await self.tree.sync()

    async def refresh_menu(self, guild_id, channel):
        if self.lock.locked(): return 
        async with self.lock:
            data = self.cached_data.get(guild_id, {"tasks": [], "last_menu_id": None, "channel_id": None})
            old_id = data.get("last_menu_id")
            old_channel_id = data.get("channel_id")

            embed = discord.Embed(title="📅 Class Assignment Tracker", description="*Current active deadlines:*", color=discord.Color.blue())
            
            if not data.get("tasks"):
                embed.description = "No upcoming deadlines! Chill vibes only. 😎"
            else:
                for t in sorted(data["tasks"], key=lambda x: x['due']):
                    p_label = t.get("priority", "🟡 MED")
                    relative_time = get_relative_time(t['due'])
                    embed.add_field(
                        name=f"📌 {t['subject'].upper()}: {t['name']} [{p_label}]", 
                        value=f"📅 **Due:** {t['due']}{relative_time}\n📝 {t['info']}\n──────────────────", 
                        inline=False
                    )

            # Help Prompt
            embed.add_field(name="❓ Need help?", value="Use the `/what` command to see how this bot works!", inline=False)
            
            # Graduation Countdown Footer
            days_left = (GRAD_DATE - datetime.now().date()).days
            embed.set_footer(text=f"Managed by Ryan | 🎓 {days_left} Days until Class of 2030 Graduation!")

            new_msg = await channel.send(embed=embed, view=SubjectView())
            
            if old_id and old_channel_id:
                old_chan = self.get_channel(int(old_channel_id))
                if old_chan:
                    asyncio.create_task(self.delete_message_safe(old_chan, old_id))

            if guild_id not in self.cached_data: self.cached_data[guild_id] = {}
            self.cached_data[guild_id]["last_menu_id"] = new_msg.id
            self.cached_data[guild_id]["channel_id"] = channel.id 
            save_data(self.cached_data)

    async def delete_message_safe(self, channel, msg_id):
        try:
            m = channel.get_partial_message(msg_id)
            await m.delete()
        except: pass

    def get_urgent_embed(self, guild_id, day_range):
        info = self.cached_data.get(guild_id)
        if not info or "tasks" not in info: return None
        today = datetime.now().date()
        urgent = [(t, (parse_date(t['due']) - today).days) for t in info["tasks"] if 0 <= (parse_date(t['due']) - today).days <= day_range]
        if not urgent: return None
        embed = discord.Embed(title="⚠️ ASSIGNMENTS DUE SOON", color=discord.Color.red())
        for t, days in urgent:
            time_str = "DUE TODAY! 🚨" if days == 0 else f"{days} day(s) left"
            embed.add_field(name=f"🛑 {t['name']} [{t.get('priority', '🟡 MED')}]", value=f"**Time:** {time_str}\n**Date:** {t['due']}\n──────────────────", inline=False)
        return embed

    @tasks.loop(time=time(hour=14, minute=30)) 
    async def daily_check(self):
        today = datetime.now().date()
        for guild_id in list(self.cached_data.keys()):
            self.cached_data[guild_id]["tasks"] = [t for t in self.cached_data[guild_id]["tasks"] if parse_date(t["due"]) >= today]
            save_data(self.cached_data)
            chan_id = self.cached_data[guild_id].get("channel_id")
            if chan_id:
                chan = self.get_channel(int(chan_id))
                if chan: await self.refresh_menu(guild_id, chan)

bot = MyBot()

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    guild_id = str(message.guild.id)
    data = bot.cached_data.get(guild_id)
    if data and data.get("channel_id") == message.channel.id:
        await bot.refresh_menu(guild_id, message.channel)
    await bot.process_commands(message)

@bot.tree.command(name="setup_tracker", description="Launch dashboard (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    await interaction.response.send_message("New Dashboard Made", ephemeral=True)
    await bot.refresh_menu(guild_id, interaction.channel)

@bot.tree.command(name="remind_now", description="Private 3-day check")
async def remind_now(interaction: discord.Interaction):
    remind = bot.get_urgent_embed(str(interaction.guild_id), 3)
    if remind: await interaction.response.send_message(embed=remind, ephemeral=True)
    else: await interaction.response.send_message("Chill vibes! Nothing due in 3 days. 😎", ephemeral=True)

@bot.tree.command(name="what", description="Quick manual for the bot")
async def what(interaction: discord.Interaction):
    embed = discord.Embed(title="📘 Ryan's Bot: Quick Guide", color=discord.Color.blue())
    embed.add_field(name="The Logic", value="• **Blue List:** Permanent dashboard. Auto-cleans at 8am.\n• **Red Alert:** Daily 2:30pm check (7 days out).\n• **🚨 High Priority:** Pings @everyone 1 day before due.", inline=False)
    embed.add_field(name="Commands", value="• `/remind_now`: Private 3-day check.\n• `/setup_tracker`: Reset dashboard (Admin).", inline=False)
    embed.set_footer(text="Managed by Ryan")
    await interaction.response.send_message(embed=embed, ephemeral=True)

bot.run(BOT_TOKEN)
