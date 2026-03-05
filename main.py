import os
import json
import discord
import asyncio
from datetime import datetime, time, timedelta
from discord import ui, app_commands
from discord.ext import commands, tasks

T_FILE = "token.txt"
if not os.path.exists(T_FILE):
    with open(T_FILE, "w") as f: f.write('TOKEN="PASTE_HERE"')
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
GRAD_DATE = datetime(2030, 6, 14).date()

if not os.path.exists(ASSIGNMENT_FILE):
    with open(ASSIGNMENT_FILE, "w") as f: f.write("{}")

def load_data():
    try:
        with open(ASSIGNMENT_FILE, "r") as f: return json.load(f)
    except: return {} 

def save_data(data):
    with open(ASSIGNMENT_FILE, "w") as f: json.dump(data, f, indent=4)

def parse_date(d_str):
    for fmt in ("%Y-%m-%d", "%Y-%m-%j", "%Y-%n-%j", "%Y-%n-%d"):
        try: return datetime.strptime(d_str, fmt).date()
        except ValueError: continue
    return None

def get_rel_time(d_str):
    due = parse_date(d_str)
    if not due: return ""
    today = datetime.now().date()
    diff = (due - today).days
    if diff == 0: return " (**TODAY** 🚨)"
    if diff == 1: return " (Tomorrow)"
    if 1 < diff < 7: return f" ({diff} days left)"
    w, d = diff // 7, diff % 7
    if d == 0: return f" ({w} week{'s' if w > 1 else ''})"
    return f" ({w}w {d}d)"

class PrioritySelect(ui.Select):
    def __init__(self, t_data, gid):
        opts = [
            discord.SelectOption(label="High Priority", emoji="🔴", value="🔴 HIGH"),
            discord.SelectOption(label="Medium Priority", emoji="🟡", value="🟡 MED"),
            discord.SelectOption(label="Low Priority", emoji="🟢", value="🟢 LOW")
        ]
        super().__init__(placeholder="how cooked are we?...", options=opts)
        self.t_data, self.gid = t_data, gid
    async def callback(self, itx: discord.Interaction):
        data = itx.client.cached_data
        if self.gid not in data: data[self.gid] = {"tasks": [], "last_menu_id": None, "channel_id": None}
        self.t_data["priority"] = self.values[0]
        data[self.gid]["tasks"].append(self.t_data)
        save_data(data)
        await itx.response.edit_message(content=f"✅ added **{self.t_data['name']}** to the pile.", view=None)
        await itx.client.refresh_menu(self.gid, itx.channel)

#The modal stuff here

class AddTaskModal(ui.Modal):
    def __init__(self, sub):
        super().__init__(title=f"New {sub} Assignment")
        self.sub = sub
    name = ui.TextInput(label="What is it?", placeholder="eg. Quiz", required=True)
    date = ui.TextInput(label="Due date (YYYY-MM-DD)", placeholder="2030-04-20", min_length=10, max_length=10)
    info = ui.TextInput(label="Extra info", style=discord.TextStyle.paragraph, placeholder="sum details abt the assignment", required=False, max_length=200)
    async def on_submit(self, itx: discord.Interaction):
        clean = parse_date(self.date.value)
        if not clean: return await itx.response.send_message("that date is cursed. try YYYY-MM-DD.", ephemeral=True)
        t_data = {"subject": self.sub, "name": self.name.value, "due": str(clean), "info": self.info.value or "No details."}
        v = ui.View().add_item(PrioritySelect(t_data, str(itx.guild_id)))
        await itx.response.send_message("last step: priority?", view=v, ephemeral=True)

class SubjectView(ui.View):
    def __init__(self): super().__init__(timeout=None)
    @ui.select(placeholder="Add something to the list...", options=[
        discord.SelectOption(label="English", emoji="📚"), discord.SelectOption(label="Math", emoji="📐"),
        discord.SelectOption(label="Science", emoji="🧪"), discord.SelectOption(label="Art", emoji="🎨"),
        discord.SelectOption(label="Music", emoji="🎸"), discord.SelectOption(label="Other", emoji="📝")
    ])
    async def select_sub(self, itx: discord.Interaction, select: ui.Select):
        await itx.response.send_modal(AddTaskModal(select.values[0]))

    @ui.button(label="✨ Clean up List", style=discord.ButtonStyle.secondary)
    async def manage(self, itx: discord.Interaction, btn: ui.Button):
        if not itx.user.guild_permissions.administrator: 
            return await itx.response.send_message("nice try lol. u need admin.", ephemeral=True)
        gid = str(itx.guild_id)
        tasks = itx.client.cached_data.get(gid, {}).get("tasks", [])
        if not tasks: return await itx.response.send_message("the list is empty. go outside.", ephemeral=True)
        opts = [discord.SelectOption(label=f"{t['name']}", description=f"due {t['due']}", value=str(i)) for i, t in enumerate(tasks)][:25]
        sel = ui.Select(placeholder="pick a task to kill...", options=opts)
        async def del_call(idx_itx: discord.Interaction):
            idx = int(sel.values[0])
            itx.client.cached_data[gid]["tasks"].pop(idx)
            save_data(itx.client.cached_data)
            await idx_itx.response.send_message("✅ removed. *don't delete real stuff u lazy b*...", ephemeral=True)
            await itx.client.refresh_menu(gid, itx.channel)
        sel.callback = del_call
        await itx.response.send_message("Delete a task:", view=ui.View().add_item(sel), ephemeral=True)

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
        self.cached_data = load_data()
        self.lock = asyncio.Lock() 

    async def setup_hook(self):
        self.daily_check.start()
        await self.tree.sync()

    async def refresh_menu(self, gid, chan):
        if self.lock.locked(): return 
        async with self.lock:
            d = self.cached_data.get(gid, {"tasks": [], "last_menu_id": None, "channel_id": None})
            old_id, old_cid = d.get("last_menu_id"), d.get("channel_id")
            emb = discord.Embed(title="📅 Class Assignment Tracker", description="*Current active deadlines:*", color=0x3498db)
            if not d.get("tasks"):
                emb.description = "No upcoming deadlines! Chill vibes only. 😎"
            else:
                for t in sorted(d["tasks"], key=lambda x: x['due']):
                    p = t.get("priority", "🟡 MED")
                    rel = get_rel_time(t['due'])
                    emb.add_field(name=f"📌 {t['subject'].upper()}: {t['name']} [{p}]", value=f"📅 **Due:** {t['due']}{rel}\n📝 {t['info']}\n──────────────────", inline=False)
            days = (GRAD_DATE - datetime.now().date()).days
            emb.set_footer(text=f"Ryan's Tracker | 🎓 {days} Days until our graduation!")
            msg = await chan.send(embed=emb, view=SubjectView())
            if old_id and old_cid:
                c = self.get_channel(int(old_cid))
                if c: asyncio.create_task(self.delete_msg(c, old_id))
            if gid not in self.cached_data: self.cached_data[gid] = {}
            self.cached_data[gid]["last_menu_id"], self.cached_data[gid]["channel_id"] = msg.id, chan.id 
            save_data(self.cached_data)

    async def delete_msg(self, c, mid):
        try: await c.get_partial_message(mid).delete()
        except: pass

    @tasks.loop(time=time(hour=14, minute=30)) 
    async def daily_check(self):
        now = datetime.now().date()
        for gid in list(self.cached_data.keys()):
            self.cached_data[gid]["tasks"] = [t for t in self.cached_data[gid]["tasks"] if parse_date(t["due"]) >= now]
            save_data(self.cached_data)
            cid = self.cached_data[gid].get("channel_id")
            if cid:
                c = self.get_channel(int(cid))
                if c: await self.refresh_menu(gid, c)

bot = MyBot()

@bot.event
async def on_message(msg):
    if msg.author == bot.user: return
    gid = str(msg.guild.id)
    d = bot.cached_data.get(gid)
    if d and d.get("channel_id") == msg.channel.id: await bot.refresh_menu(gid, msg.channel)
    await bot.process_commands(msg)

@bot.tree.command(name="setup_tracker")
async def setup(itx: discord.Interaction):
    if not itx.user.guild_permissions.administrator:
        return await itx.response.send_message("nice try lol. u need admin.", ephemeral=True)
    await itx.response.send_message("New Dashboard Made", ephemeral=True)
    await bot.refresh_menu(str(itx.guild_id), itx.channel)

@bot.tree.command(name="remind_now")
async def remind(itx: discord.Interaction):
    info = bot.cached_data.get(str(itx.guild_id))
    if not info or not info.get("tasks"): return await itx.response.send_message("Chill vibes! 😎", ephemeral=True)
    today = datetime.now().date()
    soon = [t for t in info["tasks"] if 0 <= (parse_date(t['due']) - today).days <= 3]
    if soon:
        emb = discord.Embed(title="⚠️ Soon™", color=0xff0000)
        for t in soon: emb.add_field(name=t['name'], value=f"due: {t['due']}", inline=False)
        await itx.response.send_message(embed=emb, ephemeral=True)
    else: await itx.response.send_message("Nothing due soon!", ephemeral=True)

bot.run(BOT_TOKEN)
