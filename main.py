import os
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=”!”, intents=intents)

VERIFY_URL = “https://discord.com/oauth2/authorize?client_id=1496753618861424700&response_type=code&redirect_uri=http%3A%2F%2Flocalhost%3A5000%2Fcallback&scope=identify+guilds.join”

# ── Build the verify embed + button ───────────────────────────────────────────

def build_verify_embed(guild: discord.Guild) -> discord.Embed:
embed = discord.Embed(
title=“Server Verification”,
description=“Click the button below to verify and gain access to the server.”,
color=discord.Color.green(),
)
if guild.icon:
embed.set_thumbnail(url=guild.icon.url)
return embed

def build_verify_view() -> discord.ui.View:
view = discord.ui.View(timeout=None)
view.add_item(
discord.ui.Button(
label=“Verify”,
url=VERIFY_URL,
style=discord.ButtonStyle.link,
)
)
return view

# ── Post embed in verify channel if not already there ─────────────────────────

async def ensure_verify_embed(guild: discord.Guild):
verify_channel = discord.utils.find(
lambda c: “verify” in c.name.lower(), guild.text_channels
)
if verify_channel is None:
return

```
try:
    async for msg in verify_channel.history(limit=50):
        if (
            msg.author == bot.user
            and msg.embeds
            and msg.embeds[0].title == "Server Verification"
        ):
            return  # already posted
except discord.Forbidden:
    return

try:
    await verify_channel.send(embed=build_verify_embed(guild), view=build_verify_view())
    print(f"[ensure_verify_embed] posted in #{verify_channel.name}")
except discord.Forbidden:
    print(f"[ensure_verify_embed] FORBIDDEN in #{verify_channel.name}")
```

# ── on_ready ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
print(f”Logged in as {bot.user}”)
for guild in bot.guilds:
await ensure_verify_embed(guild)
try:
synced = await bot.tree.sync()
print(f”[on_ready] synced {len(synced)} slash commands”)
except Exception as e:
print(f”[on_ready] failed to sync: {e}”)

# ── Repost embed if it gets deleted ───────────────────────────────────────────

@bot.event
async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent):
if payload.guild_id is None:
return
guild = bot.get_guild(payload.guild_id)
if guild is None:
return
channel = guild.get_channel(payload.channel_id)
if channel is None or “verify” not in channel.name.lower():
return

```
cached = payload.cached_message
if cached is not None:
    if cached.author != bot.user:
        return
    if not cached.embeds or cached.embeds[0].title != "Server Verification":
        return

await ensure_verify_embed(guild)
```

# ── Give unverified role on join + welcome message ────────────────────────────

@bot.event
async def on_member_join(member: discord.Member):
print(f”[on_member_join] {member} joined {member.guild.name}”)

```
unverified_role = discord.utils.find(
    lambda r: r.name.strip().lower() == "unverified", member.guild.roles
)
if unverified_role:
    try:
        await member.add_roles(unverified_role)
    except discord.Forbidden:
        print(f"[on_member_join] FORBIDDEN to add unverified role")

welcome_channel = discord.utils.find(
    lambda c: "welcome" in c.name.lower(), member.guild.text_channels
)
if welcome_channel:
    count = member.guild.member_count
    suffix = (
        "th" if 10 <= count % 100 <= 20
        else {1: "st", 2: "nd", 3: "rd"}.get(count % 10, "th")
    )
    embed = discord.Embed(
        description=f"Welcome {member.display_name} to **APEX** — you are the {count}{suffix} member!",
        color=discord.Color.from_rgb(255, 90, 30),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    try:
        await welcome_channel.send(
            content=f"Welcome {member.mention} to **APEX**! You are the {count}{suffix} member!",
            embed=embed,
        )
    except discord.Forbidden:
        pass
```

# ── !setup — (re)post the verify embed manually ───────────────────────────────

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

# ── /verify — manual admin verify ─────────────────────────────────────────────

@bot.tree.command(name=“verify”, description=“Manually verify a member (admin only)”)
@discord.app_commands.describe(member=“The member to verify”)
async def verify_cmd(interaction: discord.Interaction, member: discord.Member):
if not interaction.user.guild_permissions.administrator:
await interaction.response.send_message(“Administrator permission required.”, ephemeral=True)
return

```
await interaction.response.defer(ephemeral=True, thinking=True)
guild = interaction.guild

role = discord.utils.find(lambda r: r.name.strip().lower() == "apex | member", guild.roles)
if role is None:
    await interaction.followup.send("Role `apex | member` not found.", ephemeral=True)
    return
if role in member.roles:
    await interaction.followup.send(f"{member.mention} is already verified.", ephemeral=True)
    return

try:
    await member.add_roles(role, reason=f"Manually verified by {interaction.user}")
except discord.Forbidden:
    await interaction.followup.send("Missing permissions to assign that role.", ephemeral=True)
    return

unverified_role = discord.utils.find(lambda r: r.name.strip().lower() == "unverified", guild.roles)
if unverified_role and unverified_role in member.roles:
    try:
        await member.remove_roles(unverified_role)
    except discord.Forbidden:
        pass

await interaction.followup.send(f"✅ Verified {member.mention}.", ephemeral=True)
```

# ── /verifycount ───────────────────────────────────────────────────────────────

@bot.tree.command(name=“verifycount”, description=“Show verified vs unverified counts (admin only)”)
async def verifycount(interaction: discord.Interaction):
if not interaction.guild or not interaction.user.guild_permissions.administrator:
await interaction.response.send_message(“Administrator permission required.”, ephemeral=True)
return

```
guild = interaction.guild
member_role = discord.utils.find(lambda r: r.name.strip().lower() == "apex | member", guild.roles)
unverified_role = discord.utils.find(lambda r: r.name.strip().lower() == "unverified", guild.roles)

embed = discord.Embed(title="Verification Stats", color=discord.Color.from_rgb(255, 90, 30))
embed.add_field(name="Verified", value=str(len(member_role.members) if member_role else 0), inline=True)
embed.add_field(name="Unverified", value=str(len(unverified_role.members) if unverified_role else 0), inline=True)
embed.add_field(name="Total Members", value=str(guild.member_count), inline=True)
if guild.icon:
    embed.set_thumbnail(url=guild.icon.url)
await interaction.response.send_message(embed=embed, ephemeral=True)
```

# ── Run ────────────────────────────────────────────────────────────────────────

token = os.environ.get(“DISCORD_BOT_TOKEN”)
if not token:
raise RuntimeError(“DISCORD_BOT_TOKEN environment variable is not set”)

bot.run(token)