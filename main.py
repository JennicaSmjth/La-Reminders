import discord
from discord import ui, app_commands
from discord.ext import commands, tasks
from datetime import datetime, time
import json

# ================= CONFIGURATION =================
BOT_TOKEN = 'smth' 
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
        
        # Add the priority to the task and save
        self.task_data["priority"] = self.values[0]
        data[self.guild_id]["tasks"].append(self.task_data)
        save_data(data)
        
        await interaction.response.edit_message(content=f"✅ Task Added: **{self.task_data['name']}** with {self.values[0]} priority!", view=None)
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
        
        # Prepare the task data but don't save yet
        task_data = {
            "subject": self.subject,
            "name": self.name.value,
            "due": str(clean_date),
            "info": self.info.value or "No details."
        }
        
        # Send the Priority Dropdown (Step 2)
        view = ui.View().add_item(PrioritySelect(task_data, str(interaction.guild_id)))
        await interaction.response.send_message("Select the priority for this assignment:", view=view, ephemeral=True)

class ConfirmDeleteView(ui.View):
    def __init__(self, task_index, guild_id):
        super().__init__(timeout=30)
        self.task_index = task_index
        self.guild_id = guild_id

    @ui.button(label="Confirm Cleanup", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        data = interaction.client.cached_data
        if self.guild_id in data and len(data[self.guild_id]["tasks"]) > self.task_index:
            removed = data[self.guild_id]["tasks"].pop(self.task_index)
            save_data(data)
            await interaction.response.edit_message(content=f"✅ Removed: **{removed['name']}**", view=None)
            await interaction.client.refresh_menu(self.guild_id, interaction.channel)

class DeleteTaskSelect(ui.Select):
    def __init__(self, tasks, guild_id):
        options = [discord.SelectOption(label=f"{t['name']}", description=f"Due: {t['due']}", value=str(i)) for i, t in enumerate(tasks)][:25]
        super().__init__(placeholder="Select a task to remove...", options=options)
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        index = int(self.values[0])
        await interaction.response.send_message(content="⚠️ Remove this?", view=ConfirmDeleteView(index, self.guild_id), ephemeral=True)

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
        await interaction.response.send_message("Select to remove:", view=ui.View().add_item(DeleteTaskSelect(tasks, guild_id)), ephemeral=True)

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
                bar = "──────────────────"
                p_label = t.get("priority", "🟡 MED")
                embed.add_field(
                    name=f"📌 {t['subject'].upper()}: {t['name']} [{p_label}]", 
                    value=f"{bar}\n📅 **Due:** {t['due']}\n📝 {t['info']}\n{bar}", 
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
        urgent_tasks = []
        for t in info["tasks"]:
            due_date = parse_date(t['due'])
            if due_date:
                diff = (due_date - today).days
                if 0 <= diff <= day_range:
                    urgent_tasks.append((t, diff))

        if not urgent_tasks: return None

        embed = discord.Embed(title="⚠️ ASSIGNMENTS DUE SOON", color=discord.Color.red())
        embed.set_footer(text="Managed by Ryan")
        for t, days in urgent_tasks:
            time_str = "DUE TODAY! 🚨" if days == 0 else f"{days} day(s) left"
            p_label = t.get("priority", "🟡 MED")
            embed.add_field(
                name=f"🛑 {t['subject']}: {t['name']} [{p_label}]",
                value=f"**Time Left:** {time_str}\n**Date:** {t['due']}",
                inline=False
            )
        return embed

    @tasks.loop(time=time(hour=14, minute=30)) 
    async def daily_check(self):
        today = datetime.now().date()
        for guild_id in list(self.cached_data.keys()):
            self.cached_data[guild_id]["tasks"] = [t for t in self.cached_data[guild_id]["tasks"] if parse_date(t["due"]) >= today]
            save_data(self.cached_data)
            
            chan = self.get_channel(int(self.cached_data[guild_id]["channel_id"]))
            if chan:
                remind_embed = self.get_urgent_embed(guild_id, 7)
                if remind_embed: await chan.send(embed=remind_embed)
                await self.refresh_menu(guild_id, chan)

bot = MyBot()

@bot.tree.command(name="remind_now", description="Private 3-day check")
async def remind_now(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    remind_embed = bot.get_urgent_embed(guild_id, 3)
    if remind_embed:
        await interaction.response.send_message(embed=remind_embed, ephemeral=True)
    else:
        await interaction.response.send_message("Nothing due in 3 days!", ephemeral=True)

@bot.tree.command(name="setup_tracker", description="Launch dashboard (Admin Only)")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    old_data = bot.cached_data.get(guild_id, {})
    
    old_id = old_data.get("last_menu_id")
    if old_id:
        try:
            m = await interaction.channel.fetch_message(old_id)
            await m.delete()
        except: pass

    bot.cached_data[guild_id] = {
        "channel_id": interaction.channel_id, 
        "tasks": old_data.get("tasks", []), 
        "last_menu_id": None 
    }
    save_data(bot.cached_data)
    await interaction.response.send_message("Setup complete!", ephemeral=True)
    await bot.refresh_menu(guild_id, interaction.channel)

bot.run(BOT_TOKEN)
