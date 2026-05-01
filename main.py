import os
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=”!”, intents=intents)

VERIFY_URL = “https://discord.com/oauth2/authorize?client_id=1496753618861424700&response_type=code&redirect_uri=https%3A%2F%2Fapex-verify-d.up.railway.app%2Fcallback&scope=identify+guilds.join”

active_giveaways = {}

def build_verify_embed(guild):
embed = discord.Embed(
title=“Server Verification”,
description=“Click the button below to verify and gain access to the server.”,
color=discord.Color.green(),
)
if guild.icon:
embed.set_thumbnail(url=guild.icon.url)
return embed

def build_verify_view():
view = discord.ui.View(timeout=None)
view.add_item(
discord.ui.Button(
label=“Verify”,
url=VERIFY_URL,
style=discord.ButtonStyle.link,
)
)
return view

async def ensure_verify_embed(guild):
verify_channel = discord.utils.find(
lambda c: “verify” in c.name.lower(), guild.text_channels
)
if verify_channel is None:
return
try:
async for msg in verify_channel.history(limit=50):
if msg.author == bot.user and msg.embeds and msg.embeds[0].title == “Server Verification”:
return
except discord.Forbidden:
return
try:
await verify_channel.send(embed=build_verify_embed(guild), view=build_verify_view())
print(”[ensure_verify_embed] posted in #” + verify_channel.name)
except discord.Forbidden:
print(”[ensure_verify_embed] FORBIDDEN in #” + verify_channel.name)

def build_giveaway_embed(prize, winners, host_id, end_time, entries=0, ended=False, winner_ids=None):
if ended and winner_ids:
winner_mentions = “, “.join(”<@” + str(w) + “>” for w in winner_ids)
embed = discord.Embed(title=“GIVEAWAY ENDED”, color=discord.Color.orange())
embed.add_field(name=“Prize”, value=prize, inline=False)
embed.add_field(name=“Winner” + (“s” if len(winner_ids) > 1 else “”), value=winner_mentions, inline=False)
embed.add_field(name=“Entries”, value=str(entries), inline=True)
embed.add_field(name=“Hosted by”, value=”<@” + str(host_id) + “>”, inline=True)
embed.set_footer(text=“This giveaway has ended.”)
else:
ts = int(end_time.timestamp())
embed = discord.Embed(title=“GIVEAWAY”, color=discord.Color.from_rgb(255, 90, 30))
embed.add_field(name=“Prize”, value=prize, inline=False)
embed.add_field(name=“Winners”, value=str(winners), inline=True)
embed.add_field(name=“Entries”, value=str(entries), inline=True)
embed.add_field(name=“Ends”, value=”<t:” + str(ts) + “:R>”, inline=True)
embed.add_field(name=“Hosted by”, value=”<@” + str(host_id) + “>”, inline=False)
embed.set_footer(text=“Click the button below to enter!”)
return embed

class GiveawayView(discord.ui.View):
def **init**(self, giveaway_id):
super().**init**(timeout=None)
self.giveaway_id = giveaway_id

```
@discord.ui.button(label="Enter Giveaway", style=discord.ButtonStyle.green, custom_id="giveaway_enter", emoji="")
async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
    gw = active_giveaways.get(self.giveaway_id)
    if not gw:
        await interaction.response.send_message("This giveaway is no longer active.", ephemeral=True)
        return
    user_id = interaction.user.id
    if user_id in gw["entries"]:
        gw["entries"].discard(user_id)
        await interaction.response.send_message("You have left the giveaway.", ephemeral=True)
    else:
        gw["entries"].add(user_id)
        await interaction.response.send_message("You have entered the giveaway! Good luck!", ephemeral=True)
    channel = interaction.guild.get_channel(gw["channel_id"])
    if channel:
        try:
            msg = await channel.fetch_message(gw["message_id"])
            await msg.edit(embed=build_giveaway_embed(gw["prize"], gw["winners"], gw["host_id"], gw["end_time"], len(gw["entries"])))
        except Exception:
            pass
```

class GiveawayEndedView(discord.ui.View):
def **init**(self):
super().**init**(timeout=None)
self.add_item(discord.ui.Button(label=“Giveaway Ended”, style=discord.ButtonStyle.secondary, disabled=True, emoji=””))

async def end_giveaway(giveaway_id):
gw = active_giveaways.pop(giveaway_id, None)
if not gw:
return
guild = bot.get_guild(1488422873415811092)
if not guild:
return
channel = guild.get_channel(gw[“channel_id”])
if not channel:
return
entries = list(gw[“entries”])
num_winners = min(gw[“winners”], len(entries))
if num_winners == 0:
winner_ids = []
else:
winner_ids = random.sample(entries, num_winners)
try:
msg = await channel.fetch_message(gw[“message_id”])
await msg.edit(
embed=build_giveaway_embed(gw[“prize”], gw[“winners”], gw[“host_id”], gw[“end_time”], len(entries), ended=True, winner_ids=winner_ids),
view=GiveawayEndedView()
)
except Exception:
pass
if winner_ids:
winner_text = “, “.join(”<@” + str(w) + “>” for w in winner_ids)
announce_embed = discord.Embed(title=“GIVEAWAY ENDED”, color=discord.Color.orange())
announce_embed.add_field(name=“Prize”, value=gw[“prize”], inline=False)
announce_embed.add_field(name=“Winner” + (“s” if len(winner_ids) > 1 else “”), value=winner_text, inline=False)
announce_embed.add_field(name=“Entries”, value=str(len(entries)), inline=True)
announce_embed.add_field(name=“Hosted by”, value=”<@” + str(gw[“host_id”]) + “>”, inline=True)
announce_embed.set_footer(text=“This giveaway has ended.”)
await channel.send(content=”@everyone”, embed=announce_embed, view=GiveawayEndedView())
for winner_id in winner_ids:
member = guild.get_member(winner_id)
if member:
try:
win_embed = discord.Embed(
title=“Congratulations!”,
description=“You have won **” + gw[“prize”] + “**!\n\nOpen a ticket within the next **24 hours** to claim your prize, or it will expire!”,
color=discord.Color.green(),
)
await member.send(embed=win_embed)
except discord.Forbidden:
pass
else:
await channel.send(“Giveaway ended with no winners.”)

@tasks.loop(seconds=10)
async def check_giveaways():
now = datetime.utcnow()
ended = [gid for gid, gw in list(active_giveaways.items()) if gw[“end_time”] <= now]
for gid in ended:
await end_giveaway(gid)

@bot.command()
@commands.has_permissions(administrator=True)
async def giveaway(ctx, duration: str, winners: int, *, prize: str):
try:
await ctx.message.delete()
except discord.HTTPException:
pass
unit = duration[-1].lower()
amount = int(duration[:-1])
if unit == “s”:
delta = timedelta(seconds=amount)
elif unit == “m”:
delta = timedelta(minutes=amount)
elif unit == “h”:
delta = timedelta(hours=amount)
elif unit == “d”:
delta = timedelta(days=amount)
else:
await ctx.send(“Invalid duration. Use s/m/h/d e.g. 10m, 2h, 1d”, delete_after=5)
return
end_time = datetime.utcnow() + delta
giveaway_id = str(ctx.message.id) + str(ctx.author.id)
view = GiveawayView(giveaway_id)
embed = build_giveaway_embed(prize, winners, ctx.author.id, end_time)
msg = await ctx.send(embed=embed, view=view)
active_giveaways[giveaway_id] = {
“message_id”: msg.id,
“channel_id”: ctx.channel.id,
“prize”: prize,
“winners”: winners,
“host_id”: ctx.author.id,
“end_time”: end_time,
“entries”: set(),
}

@giveaway.error
async def giveaway_error(ctx, error):
if isinstance(error, commands.MissingPermissions):
await ctx.send(“You need Administrator permission.”, delete_after=5)
elif isinstance(error, commands.MissingRequiredArgument):
await ctx.send(“Usage: !giveaway <duration> <winners> <prize>\nExample: !giveaway 1h 1 Nitro”, delete_after=10)

@bot.event
async def on_ready():
print(“Logged in as “ + str(bot.user))
for guild in bot.guilds:
await ensure_verify_embed(guild)
check_giveaways.start()
try:
synced = await bot.tree.sync()
print(”[on_ready] synced “ + str(len(synced)) + “ slash commands”)
except Exception as e:
print(”[on_ready] failed to sync: “ + str(e))

@bot.event
async def on_raw_message_delete(payload):
if payload.guild_id is None:
return
guild = bot.get_guild(payload.guild_id)
if guild is None:
return
channel = guild.get_channel(payload.channel_id)
if channel is None or “verify” not in channel.name.lower():
return
cached = payload.cached_message
if cached is not None:
if cached.author != bot.user:
return
if not cached.embeds or cached.embeds[0].title != “Server Verification”:
return
await ensure_verify_embed(guild)

@bot.event
async def on_member_join(member):
print(”[on_member_join] “ + str(member) + “ joined “ + member.guild.name)
unverified_role = discord.utils.find(
lambda r: r.name.strip().lower() == “unverified”, member.guild.roles
)
if unverified_role:
try:
await member.add_roles(unverified_role)
except discord.Forbidden:
print(”[on_member_join] FORBIDDEN to add unverified role”)
welcome_channel = discord.utils.find(
lambda c: “welcome” in c.name.lower(), member.guild.text_channels
)
if welcome_channel:
count = member.guild.member_count
suffix = (
“th” if 10 <= count % 100 <= 20
else {1: “st”, 2: “nd”, 3: “rd”}.get(count % 10, “th”)
)
embed = discord.Embed(
description=“Welcome “ + member.display_name + “ to **APEX** - you are the “ + str(count) + suffix + “ member!”,
color=discord.Color.from_rgb(255, 90, 30),
)
embed.set_thumbnail(url=member.display_avatar.url)
try:
await welcome_channel.send(
content=“Welcome “ + member.mention + “ to **APEX**! You are the “ + str(count) + suffix + “ member!”,
embed=embed,
)
except discord.Forbidden:
pass

@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
try:
await ctx.message.delete()
except discord.HTTPException:
pass
await ctx.send(embed=build_verify_embed(ctx.guild), view=build_verify_view())

@setup.error
async def setup_error(ctx, error):
if isinstance(error, commands.MissingPermissions):
try:
await ctx.message.delete()
except discord.HTTPException:
pass

@bot.tree.command(name=“verify”, description=“Manually verify a member (admin only)”)
@discord.app_commands.describe(member=“The member to verify”)
async def verify_cmd(interaction, member: discord.Member):
if not interaction.user.guild_permissions.administrator:
await interaction.response.send_message(“Administrator permission required.”, ephemeral=True)
return
await interaction.response.defer(ephemeral=True, thinking=True)
guild = interaction.guild
role = discord.utils.find(lambda r: r.name.strip().lower() == “apex | member”, guild.roles)
if role is None:
await interaction.followup.send(“Role apex | member not found.”, ephemeral=True)
return
if role in member.roles:
await interaction.followup.send(str(member.mention) + “ is already verified.”, ephemeral=True)
return
try:
await member.add_roles(role, reason=“Manually verified by “ + str(interaction.user))
except discord.Forbidden:
await interaction.followup.send(“Missing permissions to assign that role.”, ephemeral=True)
return
unverified_role = discord.utils.find(lambda r: r.name.strip().lower() == “unverified”, guild.roles)
if unverified_role and unverified_role in member.roles:
try:
await member.remove_roles(unverified_role)
except discord.Forbidden:
pass
await interaction.followup.send(“Verified “ + str(member.mention) + “.”, ephemeral=True)

@bot.tree.command(name=“verifycount”, description=“Show verified vs unverified counts (admin only)”)
async def verifycount(interaction):
if not interaction.guild or not interaction.user.guild_permissions.administrator:
await interaction.response.send_message(“Administrator permission required.”, ephemeral=True)
return
guild = interaction.guild
member_role = discord.utils.find(lambda r: r.name.strip().lower() == “apex | member”, guild.roles)
unverified_role = discord.utils.find(lambda r: r.name.strip().lower() == “unverified”, guild.roles)
embed = discord.Embed(title=“Verification Stats”, color=discord.Color.from_rgb(255, 90, 30))
embed.add_field(name=“Verified”, value=str(len(member_role.members) if member_role else 0), inline=True)
embed.add_field(name=“Unverified”, value=str(len(unverified_role.members) if unverified_role else 0), inline=True)
embed.add_field(name=“Total Members”, value=str(guild.member_count), inline=True)
if guild.icon:
embed.set_thumbnail(url=guild.icon.url)
await interaction.response.send_message(embed=embed, ephemeral=True)

token = os.environ.get(“DISCORD_BOT_TOKEN”)
if not token:
raise RuntimeError(“DISCORD_BOT_TOKEN environment variable is not set”)

bot.run(token)