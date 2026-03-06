import discord
from discord import ui, app_commands
from discord.ext import commands, tasks
from datetime import datetime, time, timedelta
import json
import asyncio
import os

# ================= TOKEN SECURITY LAYER =================
T_FILE = "token.txt"
if not os.path.exists(T_FILE):
    with open(T_FILE, "w") as f: 
        f.write('TOKEN="PASTE_HERE"')
    print(f"--- created {T_FILE}. put your token in and restart ---")
    exit()

def get_token():
    with open(T_FILE, "r") as f:
        line = f.read()
        if 'PASTE_HERE' in line:
            print("yo, token.txt is still empty. fix it.")
            exit()
        return line.split('"')[1] if '"' in line else line.strip()

BOT_TOKEN = get_token()
ASSIGNMENT_FILE = "grade_tasks.json"
# ========================================================

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
            data[self.guild_id] = {"channel_id": interaction.channel_id, "tasks": [], "last_menu_id": None}
        
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
        if not clean_date: 
            return await interaction.response.send_message("❌ Invalid date. Use YYYY-MM-DD", ephemeral=True)
        
        task_data = {
            "subject": self.subject, 
            "name": self.name.value, 
            "due": str(clean_date), 
            "info": self.info.value or "No details."
        }
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
        if not interaction.user.guild_permissions.administrator: 
            return await interaction.response.send_message("too bad u dont have admin", ephemeral=True)
        
        guild_id = str(interaction.guild_id)
        tasks_list = interaction.client.cached_data.get(guild_id, {}).get("tasks", [])
        
        if not tasks_list: 
            return await interaction.response.send_message("Nothing to clean!", ephemeral=True)
        
        options = [discord.SelectOption(label=f"{t['name']}", value=str(i)) for i, t in enumerate(tasks_list)][:25]
        del_select = ui.Select(placeholder="Select to remove...", options=options)
        
        async def del_callback(idx_interaction):
            idx = int(del_select.values[0])
            interaction.client.cached_data[guild_id]["tasks"].pop(idx)
            save_data(interaction.client.cached_data)
            await idx_interaction.response.send_message("✅ Removed.", ephemeral=True)
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
            data = self.cached_data.get(guild_id, {"tasks": [], "last_menu_id": None})
            old_id = data.get("last_menu_id")

            embed = discord.Embed(title="📅 Class Assignment Tracker", description="*Current active deadlines:*", color=discord.Color.blue())
            embed.set_footer(text="Managed by Ryan")
            
            if not data.get("tasks"):
                embed.description = "No upcoming deadlines! Chill vibes only. 😎"
            else:
                for t in sorted(data["tasks"], key=lambda x: x['due']):
                    p_label = t.get("priority", "🟡 MED")
                    embed.add_field(name=f"📌 {t['subject'].upper()}: {t['name']} [{p_label}]", 
                                    value=f"📅 **Due:** {t['due']}\n📝 {t['info']}\n──────────────────", inline=False)

            new_msg = await channel.send(embed=embed, view=SubjectView())
            
            if old_id:
                asyncio.create_task(self.delete_message_safe(channel, old_id))

            self.cached_data[guild_id]["last_menu_id"] = new_msg.id
            self.cached_data[guild_id]["channel_id"] = channel.id
            save_data(self.cached_data)

    async def delete_message_safe(self, channel, msg_id):
        try:
            m = channel.get_partial_message(msg_id)
            await m.delete()
        except: pass

    def get_urgent_embed(self, guild_id, day_range, high_only=False):
        info = self.cached_data.get(guild_id)
        if not info or "tasks" not in info: return None
        
        today = datetime.now().date()
        tasks_found = []
        
        for t in info["tasks"]:
            due_date = parse_date(t['due'])
            days_left = (due_date - today).days
            
            # Logic: If high_only is True, check if it's High Priority AND within range
            if 0 <= days_left <= day_range:
                if high_only and "🔴 HIGH" not in t.get("priority", ""):
                    continue
                tasks_found.append((t, days_left))

        if not tasks_found: return None
        
        embed = discord.Embed(title="⚠️ ASSIGNMENTS DUE SOON", color=discord.Color.red())
        for t, days in tasks_found:
            time_str = "DUE TODAY! 🚨" if days == 0 else f"{days} day(s) left"
            embed.add_field(name=f"🛑 {t['name']} [{t.get('priority', '🟡 MED')}]", 
                            value=f"**Time:** {time_str}\n**Date:** {t['due']}\n──────────────────", inline=False)
        return embed

    @tasks.loop(time=time(hour=14, minute=30)) 
    async def daily_check(self):
        today = datetime.now().date()
        for guild_id in list(self.cached_data.keys()):
            # Auto-remove expired tasks
            self.cached_data[guild_id]["tasks"] = [t for t in self.cached_data[guild_id]["tasks"] if parse_date(t["due"]) >= today]
            save_data(self.cached_data)
            
            chan_id = self.cached_data[guild_id].get("channel_id")
            if chan_id:
                chan = self.get_channel(int(chan_id))
                if chan:
                    # ONLY send an alert if there is a HIGH priority task due within 2 days
                    urgent_alert = self.get_urgent_embed(guild_id, 2, high_only=True)
                    if urgent_alert:
                        await chan.send(content="⚡ **High Priority Alert!**", embed=urgent_alert)
                    
                    # Refresh the main dashboard anyway to keep it clean
                    await self.refresh_menu(guild_id, chan)

bot = MyBot()

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    guild_id = str(message.guild.id)
    data = bot.cached_data.get(guild_id)
    
    if data and str(message.channel.id) == str(data.get("channel_id")):
        await bot.refresh_menu(guild_id, message.channel)
    
    await bot.process_commands(message)

@bot.tree.command(name="setup_tracker", description="Launch dashboard (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    if guild_id in bot.cached_data and bot.cached_data[guild_id].get("channel_id"):
        return await interaction.response.send_message("theres already one u bum", ephemeral=True)

    bot.cached_data[guild_id] = {"channel_id": interaction.channel_id, "tasks": [], "last_menu_id": None}
    await interaction.response.send_message("Setting up smooth dashboard...", ephemeral=True)
    await bot.refresh_menu(guild_id, interaction.channel)

@bot.tree.command(name="remind_now", description="Private 3-day check")
async def remind_now(interaction: discord.Interaction):
    remind = bot.get_urgent_embed(str(interaction.guild_id), 3)
    if remind: await interaction.response.send_message(embed=remind, ephemeral=True)
    else: await interaction.response.send_message("Chill vibes! Nothing due in 3 days. 😎", ephemeral=True)

bot.run(BOT_TOKEN)
