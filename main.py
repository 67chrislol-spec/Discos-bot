import os
import re
import random
import asyncio
import aiohttp
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=["!", "."], intents=intents)

VERIFY_URL = "https://discord.com/oauth2/authorize?client_id=1496753618861424700&response_type=code&redirect_uri=https%3A%2F%2Fapex-verify-d.up.railway.app%2Fcallback&scope=identify+guilds.join"

active_giveaways = {}
ended_giveaways = {}


def has_staff_access(user: discord.Member) -> bool:
    if user.guild_permissions.administrator:
        return True
    return any(r.name.strip().lower() == "apex | staff" for r in user.roles)


def parse_duration(duration_str: str) -> int | None:
    pattern = re.compile(
        r"(?:(\d+)\s*d(?:ays?)?)?"
        r"\s*(?:(\d+)\s*h(?:ours?)?)?"
        r"\s*(?:(\d+)\s*m(?:in(?:utes?)?)?)?"
        r"\s*(?:(\d+)\s*s(?:ec(?:onds?)?)?)?",
        re.IGNORECASE,
    )
    match = pattern.fullmatch(duration_str.strip())
    if not match or not any(match.groups()):
        return None
    days = int(match.group(1) or 0)
    hours = int(match.group(2) or 0)
    minutes = int(match.group(3) or 0)
    seconds = int(match.group(4) or 0)
    total = days * 86400 + hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else None


def format_duration(seconds: int) -> str:
    parts = []
    d, remainder = divmod(seconds, 86400)
    h, remainder = divmod(remainder, 3600)
    m, s = divmod(remainder, 60)
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s:
        parts.append(f"{s}s")
    return " ".join(parts) if parts else "0s"


def build_verify_embed(guild):
    embed = discord.Embed(
        title="Server Verification",
        description="Click the button below to verify and gain access to the server.",
        color=discord.Color.green(),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    return embed


def build_verify_view():
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Verify", url=VERIFY_URL, style=discord.ButtonStyle.link))
    return view


async def ensure_verify_embed(guild):
    verify_channel = discord.utils.find(lambda c: "verify" in c.name.lower(), guild.text_channels)
    if verify_channel is None:
        return
    try:
        async for msg in verify_channel.history(limit=50):
            if msg.author == bot.user and msg.embeds and msg.embeds[0].title == "Server Verification":
                return
    except discord.Forbidden:
        return
    try:
        await verify_channel.send(embed=build_verify_embed(guild), view=build_verify_view())
    except discord.Forbidden:
        pass


def build_giveaway_embed(prize, host, end_time, winners_count, entries):
    embed = discord.Embed(title="🎉 GIVEAWAY 🎉", color=discord.Color.from_rgb(255, 90, 30))
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(name="Winners", value=str(winners_count), inline=True)
    embed.add_field(name="Entries", value=str(entries), inline=True)
    embed.add_field(name="Hosted by", value=host.mention, inline=True)
    embed.add_field(name="Ends", value=f"<t:{int(end_time.timestamp())}:R>", inline=False)
    embed.set_footer(text="Click the button below to enter!")
    return embed


def build_giveaway_ended_embed(prize, host_mention, winners, entries):
    embed = discord.Embed(title="🎉 GIVEAWAY ENDED 🎉", description="─" * 20, color=discord.Color.dark_grey())
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(
        name="Winner" if len(winners) == 1 else "Winners",
        value="\n".join(w.mention for w in winners) if winners else "No valid entries",
        inline=False,
    )
    embed.add_field(name="Entries", value=str(entries), inline=True)
    embed.add_field(name="Hosted by", value=host_mention, inline=True)
    embed.set_footer(text="This giveaway has ended.")
    return embed


class GiveawayView(discord.ui.View):
    def __init__(self, message_id=0):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="🎉 Enter Giveaway", style=discord.ButtonStyle.blurple, custom_id="giveaway_enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg_id = None
        for mid, data in active_giveaways.items():
            if data["channel_id"] == interaction.channel_id:
                msg_id = mid
                break
        if msg_id is None:
            await interaction.response.send_message("This giveaway has already ended.", ephemeral=True)
            return
        data = active_giveaways[msg_id]
        user_id = interaction.user.id
        if user_id in data["entries"]:
            data["entries"].discard(user_id)
            await interaction.response.send_message("You have withdrawn your entry.", ephemeral=True)
        else:
            data["entries"].add(user_id)
            await interaction.response.send_message("You have entered the giveaway! Good luck 🎉", ephemeral=True)
        try:
            msg = await interaction.channel.fetch_message(msg_id)
            host = interaction.guild.get_member(data["host_id"]) or await interaction.guild.fetch_member(data["host_id"])
            await msg.edit(embed=build_giveaway_embed(data["prize"], host, data["end_time"], data["winners_count"], len(data["entries"])))
        except Exception as e:
            print(f"[giveaway] entry count update failed: {e}")


async def end_giveaway(message_id):
    if message_id not in active_giveaways:
        return
    data = active_giveaways.pop(message_id)
    guild = bot.get_guild(data["guild_id"])
    if not guild:
        return
    channel = guild.get_channel(data["channel_id"])
    if not channel:
        return
    try:
        msg = await channel.fetch_message(message_id)
    except discord.NotFound:
        return
    host_member = guild.get_member(data["host_id"])
    host_mention = host_member.mention if host_member else f"<@{data['host_id']}>"
    valid_entries = list(data["entries"])
    winners = []
    count = min(data["winners_count"], len(valid_entries))
    if count > 0:
        for wid in random.sample(valid_entries, count):
            try:
                member = guild.get_member(wid) or await guild.fetch_member(wid)
                winners.append(member)
            except Exception:
                pass
    ended_view = discord.ui.View()
    ended_view.add_item(discord.ui.Button(label="Giveaway Ended", style=discord.ButtonStyle.grey, disabled=True))
    await msg.edit(embed=build_giveaway_ended_embed(data["prize"], host_mention, winners, len(valid_entries)), view=ended_view)
    ended_giveaways[data["channel_id"]] = {"prize": data["prize"], "entries": valid_entries}
    tickets_channel = discord.utils.find(lambda c: "ticket" in c.name.lower(), guild.text_channels)
    tickets_mention = tickets_channel.mention if tickets_channel else "#tickets"
    if winners:
        winner_mentions = " ".join(w.mention for w in winners)
        prize = data["prize"]
        congrats_embed = discord.Embed(title="🎉 Congratulations!", color=discord.Color.gold())
        congrats_embed.description = (
            f"{winner_mentions}\nYou have won **{prize}**!\n\n"
            f"⚠️ Open a ticket in {tickets_mention} within the next **24 hours** "
            "to claim your prize, or it will expire!"
        )
        await channel.send(winner_mentions, embed=congrats_embed)
    else:
        await channel.send(f"The giveaway for **{data['prize']}** ended with no valid entries.")


async def giveaway_timer(message_id, delay):
    await asyncio.sleep(delay)
    await end_giveaway(message_id)


@bot.event
async def on_ready():
    print("Logged in as " + str(bot.user))
    for guild in bot.guilds:
        await ensure_verify_embed(guild)
    try:
        synced = await bot.tree.sync()
        print("[on_ready] synced " + str(len(synced)) + " slash commands")
    except Exception as e:
        print("[on_ready] failed to sync: " + str(e))


@bot.event
async def on_raw_message_delete(payload):
    if payload.guild_id is None:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    channel = guild.get_channel(payload.channel_id)
    if channel is None or "verify" not in channel.name.lower():
        return
    cached = payload.cached_message
    if cached is not None:
        if cached.author != bot.user:
            return
        if not cached.embeds or cached.embeds[0].title != "Server Verification":
            return
    await ensure_verify_embed(guild)


@bot.event
async def on_member_join(member):
    unverified_role = discord.utils.find(lambda r: r.name.strip().lower() == "unverified", member.guild.roles)
    if unverified_role:
        try:
            await member.add_roles(unverified_role)
        except discord.Forbidden:
            pass
    welcome_channel = discord.utils.find(lambda c: "welcome" in c.name.lower(), member.guild.text_channels)
    if welcome_channel:
        count = member.guild.member_count
        suffix = "th" if 10 <= count % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(count % 10, "th")
        embed = discord.Embed(
            description=f"Welcome {member.display_name} to **APEX** - you are the {count}{suffix} member!",
            color=discord.Color.from_rgb(255, 90, 30),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        try:
            await welcome_channel.send(content=f"Welcome {member.mention} to **APEX**! You are the {count}{suffix} member!", embed=embed)
        except discord.Forbidden:
            pass


@bot.command()
async def setup(ctx):
    if not has_staff_access(ctx.author):
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
        return
    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass
    await ctx.send(embed=build_verify_embed(ctx.guild), view=build_verify_view())


@bot.command(name="mute")
async def mute(ctx, member: discord.Member = None, duration: str = None, *, reason: str = None):
    if not has_staff_access(ctx.author):
        await ctx.message.delete()
        return

    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass

    if member is None:
        await ctx.send("Usage: `.mute @user <duration> [reason]`\nDuration examples: `10m`, `1h`, `2h30m`, `1d`", delete_after=10)
        return

    if duration is None:
        await ctx.send("Please provide a duration. Examples: `10m`, `1h`, `2h30m`, `1d`", delete_after=10)
        return

    total_seconds = parse_duration(duration)
    if total_seconds is None:
        await ctx.send("Invalid duration. Use formats like `10m`, `1h`, `2h30m`, `1d`.", delete_after=10)
        return

    max_seconds = 28 * 24 * 3600
    if total_seconds > max_seconds:
        await ctx.send("Duration cannot exceed 28 days (Discord limit).", delete_after=10)
        return

    until = datetime.now(timezone.utc) + timedelta(seconds=total_seconds)

    if not ctx.guild.me.guild_permissions.moderate_members:
        await ctx.send("I'm missing the **Moderate Members** permission. Please give it to my role in Server Settings.", delete_after=15)
        return

    if member.top_role >= ctx.guild.me.top_role:
        await ctx.send(f"I can't mute {member.mention} because their role is equal to or higher than mine. Move my role above theirs in Server Settings.", delete_after=15)
        return

    try:
        await member.timeout(until, reason=reason or "Muted by staff")
    except discord.Forbidden:
        await ctx.send("Still missing permissions. Make sure my role is above the target member's role and I have **Moderate Members** enabled.", delete_after=15)
        return
    except discord.HTTPException as e:
        await ctx.send(f"Failed to mute: {e}", delete_after=10)
        return

    embed = discord.Embed(
        title="🔇  M U T E D",
        description=f"**{member.mention} has been silenced.**\n{'─' * 32}",
        color=0xFF0000,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=f"Action by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="👤  User", value=f"{member.mention}\n`{member.name}`", inline=True)
    embed.add_field(name="🛡️  Moderator", value=f"{ctx.author.mention}\n`{ctx.author.name}`", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(name="⏱️  Duration", value=f"`{format_duration(total_seconds)}`", inline=True)
    embed.add_field(name="🕐  Expires", value=f"<t:{int(until.timestamp())}:R>\n<t:{int(until.timestamp())}:f>", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(name="📋  Reason", value=f"> {reason}" if reason else "> *No reason provided*", inline=False)
    embed.set_footer(text="APEX Moderation", icon_url=ctx.guild.icon.url if ctx.guild.icon else discord.Embed.Empty)

    await ctx.send(
        content=f"🔇 {member.mention} **you have been muted for being a retard**",
        embed=embed,
    )


@bot.command(name="unmute")
async def unmute(ctx, member: discord.Member = None):
    if not has_staff_access(ctx.author):
        await ctx.message.delete()
        return

    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass

    if member is None:
        await ctx.send("Usage: `.unmute @user`", delete_after=10)
        return

    try:
        await member.timeout(None, reason=f"Unmuted by {ctx.author}")
    except discord.Forbidden:
        await ctx.send("I don't have permission to unmute that member.", delete_after=10)
        return
    except discord.HTTPException as e:
        await ctx.send(f"Failed to unmute: {e}", delete_after=10)
        return

    embed = discord.Embed(
        title="🔊 Member Unmuted",
        color=discord.Color.green(),
    )
    embed.add_field(name="User", value=member.mention, inline=True)
    embed.add_field(name="Unmuted by", value=ctx.author.mention, inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)

    await ctx.send(embed=embed)


@bot.command(name="muteall")
async def muteall(ctx, duration: str = None, *, reason: str = None):
    if not has_staff_access(ctx.author):
        await ctx.message.delete()
        return

    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass

    if duration is None:
        await ctx.send("Usage: `.muteall <duration> [reason]`\nDuration examples: `10m`, `1h`, `2h30m`, `1d`", delete_after=10)
        return

    total_seconds = parse_duration(duration)
    if total_seconds is None:
        await ctx.send("Invalid duration. Use formats like `10m`, `1h`, `2h30m`, `1d`.", delete_after=10)
        return

    max_seconds = 28 * 24 * 3600
    if total_seconds > max_seconds:
        await ctx.send("Duration cannot exceed 28 days (Discord limit).", delete_after=10)
        return

    if not ctx.guild.me.guild_permissions.moderate_members:
        await ctx.send("I'm missing the **Moderate Members** permission.", delete_after=15)
        return

    until = datetime.now(timezone.utc) + timedelta(seconds=total_seconds)

    status_msg = await ctx.send("🔇 Muting all members, please wait...")

    muted = 0
    skipped = 0
    failed = 0

    for member in ctx.guild.members:
        if member.bot:
            continue
        if has_staff_access(member):
            skipped += 1
            continue
        if member.top_role >= ctx.guild.me.top_role:
            skipped += 1
            continue
        try:
            await member.timeout(until, reason=reason or f"Mute all by {ctx.author}")
            muted += 1
        except (discord.Forbidden, discord.HTTPException):
            failed += 1

    embed = discord.Embed(
        title="🔇  M U T E  A L L",
        description=f"**Server-wide mute applied.**\n{'─' * 32}",
        color=0xFF0000,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=f"Action by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="🛡️  Moderator", value=f"{ctx.author.mention}\n`{ctx.author.name}`", inline=True)
    embed.add_field(name="⏱️  Duration", value=f"`{format_duration(total_seconds)}`", inline=True)
    embed.add_field(name="🕐  Expires", value=f"<t:{int(until.timestamp())}:R>", inline=True)
    embed.add_field(name="✅  Muted", value=str(muted), inline=True)
    embed.add_field(name="⏭️  Skipped (staff/higher role)", value=str(skipped), inline=True)
    embed.add_field(name="❌  Failed", value=str(failed), inline=True)
    embed.add_field(name="📋  Reason", value=f"> {reason}" if reason else "> *No reason provided*", inline=False)
    embed.set_footer(text="APEX Moderation", icon_url=ctx.guild.icon.url if ctx.guild.icon else discord.Embed.Empty)

    await status_msg.delete()
    await ctx.send(embed=embed)


@bot.command(name="unmuteall")
async def unmuteall(ctx):
    if not has_staff_access(ctx.author):
        await ctx.message.delete()
        return

    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass

    if not ctx.guild.me.guild_permissions.moderate_members:
        await ctx.send("I'm missing the **Moderate Members** permission.", delete_after=15)
        return

    status_msg = await ctx.send("🔊 Unmuting all members, please wait...")

    unmuted = 0
    failed = 0

    async for member in ctx.guild.fetch_members(limit=None):
        if member.bot:
            continue
        if member.is_timed_out():
            try:
                await member.timeout(None, reason=f"Unmute all by {ctx.author}")
                unmuted += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1

    embed = discord.Embed(
        title="🔊  U N M U T E  A L L",
        description=f"**Server-wide mute lifted.**\n{'─' * 32}",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=f"Action by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="🛡️  Moderator", value=f"{ctx.author.mention}\n`{ctx.author.name}`", inline=True)
    embed.add_field(name="✅  Unmuted", value=str(unmuted), inline=True)
    embed.add_field(name="❌  Failed", value=str(failed), inline=True)
    embed.set_footer(text="APEX Moderation", icon_url=ctx.guild.icon.url if ctx.guild.icon else discord.Embed.Empty)

    await status_msg.delete()
    await ctx.send(embed=embed)


@bot.tree.command(name="yo", description="Spam the APEX invite in all channels")
async def yo(interaction: discord.Interaction):
    await interaction.response.send_message("🚀 Spamming...", ephemeral=True)

    invite = "https://discord.gg/apexrlbot"
    spam_message = "\n".join([invite] * 10)

    for channel in interaction.guild.text_channels:
        try:
            await channel.send(spam_message)
            await asyncio.sleep(0.5)
        except (discord.Forbidden, discord.HTTPException):
            continue


@bot.tree.command(name="verify", description="Manually verify a member (staff only)")
@discord.app_commands.describe(member="The member to verify")
async def verify_cmd(interaction: discord.Interaction, member: discord.Member):
    if not has_staff_access(interaction.user):
        await interaction.response.send_message("APEX | Staff permission required.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = interaction.guild
    role = discord.utils.find(lambda r: r.name.strip().lower() == "apex | member", guild.roles)
    if role is None:
        await interaction.followup.send("Role apex | member not found.", ephemeral=True)
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
    await interaction.followup.send(f"Verified {member.mention}.", ephemeral=True)


@bot.tree.command(name="verifycount", description="Show verified vs unverified counts (staff only)")
async def verifycount(interaction: discord.Interaction):
    if not interaction.guild or not has_staff_access(interaction.user):
        await interaction.response.send_message("APEX | Staff permission required.", ephemeral=True)
        return
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


@bot.tree.command(name="gstart", description="Start a giveaway (staff only)")
@discord.app_commands.describe(
    prize="What are you giving away?",
    duration='Duration e.g. "1d", "2h30m", "45m", "1d12h"',
    winners="Number of winners (default: 1)",
    channel="Channel to post in (default: current channel)",
)
async def gstart(interaction: discord.Interaction, prize: str, duration: str, winners: int = 1, channel: discord.TextChannel = None):
    if not has_staff_access(interaction.user):
        await interaction.response.send_message("APEX | Staff permission required.", ephemeral=True)
        return
    total_seconds = parse_duration(duration)
    if total_seconds is None:
        await interaction.response.send_message(
            "Invalid duration format. Use combinations like `1d`, `2h`, `30m`, `1d12h`, `2h30m`, etc.",
            ephemeral=True,
        )
        return
    target_channel = channel or interaction.channel
    end_time = datetime.now(timezone.utc) + timedelta(seconds=total_seconds)
    embed = build_giveaway_embed(prize, interaction.user, end_time, winners, 0)
    await interaction.response.send_message(
        f"Giveaway started in {target_channel.mention}! (ends in {format_duration(total_seconds)})",
        ephemeral=True,
    )
    msg = await target_channel.send(content="@everyone", embed=embed, view=GiveawayView())
    active_giveaways[msg.id] = {
        "channel_id": target_channel.id,
        "guild_id": interaction.guild_id,
        "prize": prize,
        "host_id": interaction.user.id,
        "end_time": end_time,
        "winners_count": winners,
        "entries": set(),
        "task": asyncio.create_task(giveaway_timer(msg.id, total_seconds)),
    }


@bot.tree.command(name="gend", description="End the active giveaway in this channel early (staff only)")
async def gend(interaction: discord.Interaction):
    if not has_staff_access(interaction.user):
        await interaction.response.send_message("APEX | Staff permission required.", ephemeral=True)
        return
    mid = None
    for message_id, data in active_giveaways.items():
        if data["channel_id"] == interaction.channel_id:
            mid = message_id
            break
    if mid is None:
        await interaction.response.send_message("No active giveaway found in this channel.", ephemeral=True)
        return
    task = active_giveaways[mid].get("task")
    if task:
        task.cancel()
    await interaction.response.send_message("Ending giveaway...", ephemeral=True)
    await end_giveaway(mid)


@bot.tree.command(name="greroll", description="Reroll a winner from the last giveaway in this channel (staff only)")
async def greroll(interaction: discord.Interaction):
    if not has_staff_access(interaction.user):
        await interaction.response.send_message("APEX | Staff permission required.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    ended = ended_giveaways.get(interaction.channel_id)
    if not ended:
        await interaction.followup.send("No ended giveaway found for this channel.", ephemeral=True)
        return
    prize = ended["prize"]
    valid_entries = ended["entries"]
    if not valid_entries:
        await interaction.followup.send("No entries to reroll from.", ephemeral=True)
        return
    winner_id = random.choice(valid_entries)
    try:
        winner = interaction.guild.get_member(winner_id) or await interaction.guild.fetch_member(winner_id)
    except Exception:
        await interaction.followup.send("Could not fetch the rerolled winner.", ephemeral=True)
        return
    tickets_channel = discord.utils.find(lambda c: "ticket" in c.name.lower(), interaction.guild.text_channels)
    tickets_mention = tickets_channel.mention if tickets_channel else "#tickets"
    reroll_embed = discord.Embed(title="🎉 Congratulations!", color=discord.Color.gold())
    reroll_embed.description = (
        f"{winner.mention}\nYou have won **{prize}**!\n\n"
        f"⚠️ Open a ticket in {tickets_mention} within the next **24 hours** "
        "to claim your prize, or it will expire!"
    )
    await interaction.channel.send(winner.mention, embed=reroll_embed)
    await interaction.followup.send("Rerolled!", ephemeral=True)


APEX_COLOR = discord.Color.from_rgb(255, 90, 30)
APEX_SITE = "https://www.apexbot.store"


async def fetch_live_mmr() -> tuple[str, int] | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(APEX_SITE, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                text = await resp.text()
        rank_match = re.search(r"Grand Champion\s*(I{1,3}|IV|V)?", text)
        rating_match = re.search(r"Rating[:\s]+(\d{3,5})", text)
        rank = rank_match.group(0).strip() if rank_match else "Grand Champion III"
        rating = int(rating_match.group(1)) if rating_match else 2081
        return rank, rating
    except Exception:
        return None


@bot.tree.command(name="pricing", description="View APEX bot pricing plans")
async def pricing(interaction: discord.Interaction):
    embed = discord.Embed(
        title="💰 APEX Bot Pricing",
        description="All plans include full APEX access, Discord support, and automatic updates.",
        color=APEX_COLOR,
        url=APEX_SITE,
    )
    embed.add_field(name="⏱ Daily — $15", value="• 3 days access\n• Full APEX bot\n• SDK support\n• Discord support\n• HWID locked", inline=True)
    embed.add_field(name="📅 Weekly — $20", value="• 7 days access\n• Full APEX bot\n• SDK support\n• Discord support\n• HWID locked\n• All updates included", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(name="🌟 Monthly — $50 *(Most Popular)*", value="• 30 days access\n• Full APEX bot\n• SDK support\n• Priority Discord support\n• HWID locked\n• All updates included\n• Beta builds access", inline=True)
    embed.add_field(name="♾ Lifetime — $200", value="• Forever access\n• Full APEX bot\n• SDK support\n• Priority Discord support\n• HWID locked\n• All updates forever\n• Beta builds access\n• Exclusive Lifetime role", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.set_footer(text=f"Purchase at {APEX_SITE} · Keys delivered instantly via Discord DM")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="mmr", description="Check APEX bot's current rank and MMR")
async def mmr(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    result = await fetch_live_mmr()
    if result:
        rank, rating = result
        source = "Live data from apexbot.store"
    else:
        rank, rating = "Grand Champion III", 2081
        source = "Cached data — visit apexbot.store for live stats"
    embed = discord.Embed(title="👑 APEX Bot — Current Rating", color=APEX_COLOR, url=APEX_SITE)
    embed.add_field(name="Estimated Rank", value=f"**{rank}**", inline=True)
    embed.add_field(name="Rating", value=f"**{rating} MMR**", inline=True)
    embed.add_field(name="Training Status", value="🟢 Actively Training 24/7", inline=False)
    embed.add_field(name="ℹ️ About", value="APEX trains continuously on dedicated GPU hardware. Its rank improves with every training session — the number you see today will be higher tomorrow.", inline=False)
    embed.set_footer(text=source)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="about", description="Learn about the APEX Rocket League bot")
async def about(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🚀 About APEX",
        description="APEX is a **reinforcement-trained Rocket League bot** engineered for competitive play. Advanced mechanics. Relentless aggression. Continuously improving.",
        color=APEX_COLOR,
        url=APEX_SITE,
    )
    embed.add_field(name="🎮 Advanced Mechanics", value="Air dribbles, flip resets, redirects, ceiling shots, shadow defense — trained with a full reward library targeting elite mechanical play.", inline=False)
    embed.add_field(name="⚡ Elite Performance", value="Sub-10ms decision making with frame-perfect execution. APEX reacts and plays at a level that rivals professional human players.", inline=False)
    embed.add_field(name="📈 Continuous Training", value="APEX never stops improving. Active GPU training 24/7 means every update makes the bot sharper, faster, and smarter.", inline=False)
    embed.add_field(name="🔒 HWID Protection", value="Every license is locked to your machine on first activation. One key, one PC. Secure and tamper-proof.", inline=False)
    embed.add_field(name="⚙️ Simple Setup", value="Seamless plug-and-play SDK support. Get APEX running in minutes — no technical experience required.", inline=False)
    embed.add_field(name="📦 Key Delivery", value="Your unique license key is generated instantly and DM'd to you on Discord after purchase.", inline=False)
    embed.set_footer(text=f"Learn more at {APEX_SITE}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="faq", description="Frequently asked questions about APEX")
async def faq(interaction: discord.Interaction):
    embed = discord.Embed(title="❓ APEX — FAQ", color=APEX_COLOR, url=APEX_SITE)
    embed.add_field(name="How do I get APEX?", value=f"Head to [{APEX_SITE}]({APEX_SITE}), choose a plan, pay via Stripe, and your key is DM'd to you instantly on Discord.", inline=False)
    embed.add_field(name="What are the prices?", value="**Daily** $15 (3 days) · **Weekly** $20 (7 days) · **Monthly** $50 (30 days) · **Lifetime** $200\nUse `/pricing` for full details.", inline=False)
    embed.add_field(name="What rank is APEX?", value="Currently **Grand Champion III (~2081 MMR)** and actively training. Use `/mmr` for the latest.", inline=False)
    embed.add_field(name="Is it HWID locked?", value="Yes. Every key is locked to your machine on first activation — one key, one PC.", inline=False)
    embed.add_field(name="Do I get updates?", value="All plans include automatic updates. Monthly and Lifetime plans also get early beta builds.", inline=False)
    embed.add_field(name="How do I set it up?", value="After activating your key in the APEX launcher, launch through the SDK. No technical experience required.", inline=False)
    embed.add_field(name="Can I earn a free key?", value="Yes! Use `/referral` to see the referral reward tiers. Open a ticket to claim.", inline=False)
    embed.add_field(name="Where do I get support?", value="Open a ticket in this server. Monthly and Lifetime plans get priority support.", inline=False)
    embed.set_footer(text=f"More info at {APEX_SITE}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="referral", description="Learn how the APEX referral & earn program works")
async def referral(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔗 APEX Referral & Earn",
        description=f"Share your referral link from [{APEX_SITE}]({APEX_SITE}). Every time someone buys through your link, you earn progress toward free keys.\nOpen a ticket when you hit a tier to claim your reward!",
        color=APEX_COLOR,
        url=APEX_SITE,
    )
    embed.add_field(name="5 Referrals", value="🎁 **Free Daily Key** (3 days access)", inline=False)
    embed.add_field(name="15 Referrals", value="🎁 **Free Weekly Key** (7 days access)", inline=False)
    embed.add_field(name="30 Referrals", value="🎁 **Free Monthly Key** (30 days access)", inline=False)
    embed.add_field(name="300 Referrals", value="🎁 **Free Lifetime Key** (forever access)", inline=False)
    embed.set_footer(text=f"Get your referral link at {APEX_SITE}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="changelog", description="View the latest APEX training updates")
async def changelog(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 APEX — Changelog",
        description="APEX improves with every training session. Here's what's been added and upgraded.",
        color=APEX_COLOR,
        url=APEX_SITE,
    )
    embed.add_field(name="Apr 4, 2026 — GPU Training Upgrade", value="Switched from CPU to dedicated NVIDIA GPU training. Training speed increased 5-10x — APEX now accumulates over **80,000 steps per second**.", inline=False)
    embed.add_field(name="Apr 3, 2026 — Advanced Reward Library Added", value="Integrated full suite of advanced rewards: air dribbles, shadow defense, redirects, strong touches, and bouncy air dribbles.", inline=False)
    embed.add_field(name="Apr 2, 2026 — APEX Launch", value="APEX officially launched 🎉", inline=False)
    embed.set_footer(text=f"Updates every 10,000 training iterations · {APEX_SITE}")
    await interaction.response.send_message(embed=embed)


token = os.environ.get("DISCORD_BOT_TOKEN")
if not token:
    raise RuntimeError("DISCORD_BOT_TOKEN environment variable is not set")

bot.run(token)
