import os
import secrets
import asyncio
import threading
import discord
from discord.ext import commands
from flask import Flask, request, jsonify
from flask_cors import CORS

# ── Flask app ──────────────────────────────────────────────────────────────────

flask_app = Flask(**name**)
CORS(flask_app)  # allow your verify site to call this

# token → discord user id + guild id

pending_verifications: dict[str, dict] = {}

# ── Discord bot ────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=”!”, intents=intents)

VERIFY_SITE_URL = os.environ.get(“VERIFY_SITE_URL”, “http://localhost:3000”)  # your hosted site

# ── Helper ─────────────────────────────────────────────────────────────────────

async def grant_verified_role(guild: discord.Guild, member: discord.Member):
target = “apex | member”
role = discord.utils.find(lambda r: r.name.strip().lower() == target, guild.roles)
if role is None:
return False, “Role not found”
if role in member.roles:
return False, “already_verified”

```
await member.add_roles(role)

unverified_role = discord.utils.find(
    lambda r: r.name.strip().lower() == "unverified", guild.roles
)
if unverified_role and unverified_role in member.roles:
    await member.remove_roles(unverified_role)

verify_channel = discord.utils.find(
    lambda c: "verify" in c.name.lower(), guild.text_channels
)
if verify_channel:
    try:
        await verify_channel.set_permissions(
            member,
            view_channel=False,
            send_messages=False,
            read_message_history=False,
            reason="Web-verified",
        )
    except discord.Forbidden:
        pass

print(f"[web-verify] granted role to {member}")
return True, "ok"
```

# ── Flask endpoint called by the verify website ────────────────────────────────

@flask_app.route(”/verify”, methods=[“POST”])
def verify_endpoint():
data = request.get_json(force=True)
token = data.get(“token”, “”).strip()

```
if not token or token not in pending_verifications:
    return jsonify({"success": False, "error": "Invalid or expired token"}), 400

info = pending_verifications.pop(token)
guild_id = info["guild_id"]
user_id = info["user_id"]

guild = bot.get_guild(guild_id)
if guild is None:
    return jsonify({"success": False, "error": "Guild not found"}), 500

member = guild.get_member(user_id)
if member is None:
    return jsonify({"success": False, "error": "Member not found in guild"}), 400

# Run the async grant in the bot's event loop
future = asyncio.run_coroutine_threadsafe(
    grant_verified_role(guild, member), bot.loop
)
try:
    success, msg = future.result(timeout=10)
except Exception as e:
    return jsonify({"success": False, "error": str(e)}), 500

if msg == "already_verified":
    return jsonify({"success": True, "message": "Already verified!"})

if not success:
    return jsonify({"success": False, "error": msg}), 500

return jsonify({"success": True, "message": f"Welcome to {guild.name}!"})
```

@flask_app.route(”/health”, methods=[“GET”])
def health():
return jsonify({“status”: “ok”})

# ── Send DM with verify link when member joins ─────────────────────────────────

@bot.event
async def on_member_join(member: discord.Member):
print(f”[on_member_join] {member} joined {member.guild.name}”)

```
# Assign unverified role
unverified_role = discord.utils.find(
    lambda r: r.name.strip().lower() == "unverified", member.guild.roles
)
if unverified_role:
    try:
        await member.add_roles(unverified_role)
    except discord.Forbidden:
        print(f"[on_member_join] FORBIDDEN to add unverified role")

# Generate a single-use token and send DM
token = secrets.token_urlsafe(32)
pending_verifications[token] = {
    "guild_id": member.guild.id,
    "user_id": member.id,
}
verify_url = f"{VERIFY_SITE_URL}?token={token}"

try:
    dm_embed = discord.Embed(
        title=f"Verify your membership in {member.guild.name}",
        description=(
            f"Click the button below to complete verification and unlock the server.\n\n"
            f"[**Verify Now →**]({verify_url})\n\n"
            "_This link is single-use and tied to your account._"
        ),
        color=discord.Color.from_rgb(255, 90, 30),
    )
    if member.guild.icon:
        dm_embed.set_thumbnail(url=member.guild.icon.url)
    await member.send(embed=dm_embed)
    print(f"[on_member_join] sent verify DM to {member}")
except discord.Forbidden:
    print(f"[on_member_join] cannot DM {member} — falling back to verify channel mention")
    verify_channel = discord.utils.find(
        lambda c: "verify" in c.name.lower(), member.guild.text_channels
    )
    if verify_channel:
        try:
            await verify_channel.send(
                f"{member.mention} — please verify: {verify_url}",
                delete_after=300,
            )
        except discord.Forbidden:
            pass

# Welcome message
welcome_channel = discord.utils.find(
    lambda c: "welcome" in c.name.lower(), member.guild.text_channels
)
if welcome_channel:
    count = member.guild.member_count
    suffix = (
        "th"
        if 10 <= count % 100 <= 20
        else {1: "st", 2: "nd", 3: "rd"}.get(count % 10, "th")
    )
    embed = discord.Embed(
        description=(
            f"Welcome {member.display_name} to **APEX** — "
            f"you are the {count}{suffix} member!"
        ),
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

# ── /verify slash command (admin manual verify — unchanged) ────────────────────

@bot.tree.command(name=“verify”, description=“Manually verify a member (admin only)”)
@discord.app_commands.describe(member=“The member to verify”)
async def verify_cmd(interaction: discord.Interaction, member: discord.Member):
if not interaction.user.guild_permissions.administrator:
await interaction.response.send_message(“Administrator permission required.”, ephemeral=True)
return

```
await interaction.response.defer(ephemeral=True, thinking=True)
guild = interaction.guild
success, msg = await grant_verified_role(guild, member)

if msg == "already_verified":
    await interaction.followup.send(f"{member.mention} is already verified.", ephemeral=True)
elif not success:
    await interaction.followup.send(f"Error: {msg}", ephemeral=True)
else:
    await interaction.followup.send(f"✅ Verified {member.mention}.", ephemeral=True)
```

# ── /verifycount (unchanged) ───────────────────────────────────────────────────

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

# ── on_ready ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
print(f”Logged in as {bot.user}”)
try:
synced = await bot.tree.sync()
print(f”[on_ready] synced {len(synced)} slash commands”)
except Exception as e:
print(f”[on_ready] failed to sync: {e}”)

# ── Start Flask in a background thread, then run the bot ──────────────────────

def run_flask():
port = int(os.environ.get(“PORT”, 8080))
flask_app.run(host=“0.0.0.0”, port=port)

if **name** == “**main**”:
token = os.environ.get(“DISCORD_BOT_TOKEN”)
if not token:
raise RuntimeError(“DISCORD_BOT_TOKEN environment variable is not set”)

```
t = threading.Thread(target=run_flask, daemon=True)
t.start()
print("[startup] Flask running")

bot.run(token)
```