import os
import json
import discord
from discord import ui, app_commands
from discord.ext import commands, tasks
from datetime import datetime, time, timedelta

# --- SECURITY UPDATE: TOKEN HANDLING ---
T_FILE = "token.txt"

# If the file doesn't exist, create it with a template
if not os.path.exists(T_FILE):
    with open(T_FILE, "w") as f:
        f.write('TOKEN="PASTE_HERE"')
    print(f"--- Created {T_FILE}. Put your token inside the quotes and restart! ---")
    exit()

def get_token():
    with open(T_FILE, "r") as f:
        line = f.read()
        if 'PASTE_HERE' in line:
            print("Error: You haven't put your token in token.txt yet!")
            exit()
        # Extracts just the text inside the double quotes
        if '"' in line:
            return line.split('"')[1]
        return line.strip()

BOT_TOKEN = get_token()
# ----------------------------------------

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
            return await interaction.response.send_message("❌ Invalid date format.", ephemeral=True)

        task_data = {
            "subject": self.subject,
            "name": self.name.value,
            "due": str(clean_date),
            "info": self.info.value or "No details."
        }

        view = ui.View().add_item(PrioritySelect(task_data, str(interaction.guild_id)))
        await interaction.response.send_message("Last step: Select Priority level", view=view, ephemeral=True)

class SubjectView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

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
            return await interaction.response.send_message("Admins only.", ephemeral=True)

        guild_id = str(interaction.guild_id)
        tasks = interaction.client.cached_data.get(guild_id, {}).get("tasks", [])
        if not tasks: return await interaction.response.send_message("Nothing to clean!", ephemeral=True)

        options = [discord.SelectOption(label=f"{t['name']}", value=str(i)) for i, t in enumerate(tasks)][:25]
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

    async def setup_hook(self):
        await self.tree.sync()
        self.daily_check.start()

    async def refresh_menu(self, guild_id, channel):
        data = self.cached_data.get(guild_id, {"tasks": [], "last_menu_id": None})
        embed = discord.Embed(title="📅 Class Assignment Tracker", description="*Current active deadlines:*", color=discord.Color.blue())
        embed.set_footer(text="Managed by Ryan")

        if not data["tasks"]:
            embed.description = "No upcoming deadlines! Chill vibes only. 😎"
        else:
            for t in sorted(data["tasks"], key=lambda x: x['due']):
                p_label = t.get("priority", "🟡 MED")
                embed.add_field(
                    name=f"📌 {t['subject'].upper()}: {t['name']} [{p_label}]", 
                    value=f"📅 **Due:** {t['due']}\n📝 {t['info']}\n──────────────────", 
                    inline=False
                )

        old_id = data.get("last_menu_id")
        if old_id:
            try:
                msg = await channel.fetch_message(old_id)
                await msg.delete()
            except: pass

        new_msg = await channel.send(embed=embed, view=SubjectView())
        self.cached_data[guild_id]["last_menu_id"] = new_msg.id
        save_data(self.cached_data)

    def get_urgent_embed(self, guild_id, day_range):
        info = self.cached_data.get(guild_id)
        if not info: return None
        today = datetime.now().date()
        urgent = [(t, (parse_date(t['due']) - today).days) for t in info["tasks"] if 0 <= (parse_date(t['due']) - today).days <= day_range]
        if not urgent: return None

        embed = discord.Embed(title="⚠️ ASSIGNMENTS DUE SOON", color=discord.Color.red())
        embed.set_footer(text="Managed by Ryan")
        for t, days in urgent:
            time_str = "DUE TODAY! 🚨" if days == 0 else f"{days} day(s) left"
            embed.add_field(name=f"🛑 {t['name']} [{t.get('priority', '🟡 MED')}]", value=f"**Time:** {time_str}\n**Date:** {t['due']}", inline=False)
        return embed

    @tasks.loop(time=time(hour=14, minute=30)) 
    async def daily_check(self):
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        for guild_id in list(self.cached_data.keys()):
            self.cached_data[guild_id]["tasks"] = [t for t in self.cached_data[guild_id]["tasks"] if parse_date(t["due"]) >= today]
            save_data(self.cached_data)
            chan_id = self.cached_data[guild_id].get("channel_id")
            if chan_id:
                chan = self.get_channel(int(chan_id))
                if chan:
                    hp = [t for t in self.cached_data[guild_id]["tasks"] if parse_date(t["due"]) == tomorrow and "HIGH" in t.get("priority", "")]
                    if hp: await chan.send(f"🚨 @everyone **URGENT:** {', '.join([t['name'] for t in hp])} is due TOMORROW! 🚨")

                    remind_emb = self.get_urgent_embed(guild_id, 7)
                    if remind_emb: await chan.send(embed=remind_emb)
                    await self.refresh_menu(guild_id, chan)

bot = MyBot()

@bot.tree.command(name="what", description="Quick manual for the bot")
async def what(interaction: discord.Interaction):
    embed = discord.Embed(title="📘 Ryan's Bot: Quick Guide", color=discord.Color.blue())
    embed.add_field(name="The Logic", value="• **Blue List:** Permanent dashboard. Auto-cleans at 8am.\n• **Red Alert:** Daily 2:30pm check (7 days out).\n• **🚨 High Priority:** Pings @everyone 1 day before due.", inline=False)
    embed.add_field(name="Commands", value="• `/remind_now`: Private 3-day check.\n• `/setup_tracker`: Reset dashboard (Admin).", inline=False)
    embed.set_footer(text="Managed by Ryan")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="remind_now", description="Private 3-day check")
async def remind_now(interaction: discord.Interaction):
    remind_emb = bot.get_urgent_embed(str(interaction.guild_id), 3)
    await interaction.response.send_message(embed=remind_emb if remind_emb else None, content="Nothing due soon!" if not remind_emb else None, ephemeral=True)

@bot.tree.command(name="setup_tracker", description="Launch dashboard (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    old_id = bot.cached_data.get(guild_id, {}).get("last_menu_id")
    if old_id:
        try:
            m = await interaction.channel.fetch_message(old_id)
            await m.delete()
        except: pass
    bot.cached_data[guild_id] = {"channel_id": interaction.channel_id, "tasks": bot.cached_data.get(guild_id, {}).get("tasks", []), "last_menu_id": None}
    await interaction.response.send_message("Dashboard resetting...", ephemeral=True)
    await bot.refresh_menu(guild_id, interaction.channel)

bot.run(BOT_TOKEN)
