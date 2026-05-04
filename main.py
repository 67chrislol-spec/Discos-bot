import os
import re
import random
import asyncio
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

DISCORD_INVITE_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord\.(?:gg|io|me|li)|discordapp\.com/invite|discord\.com/invite)/[a-zA-Z0-9\-]+",
    re.IGNORECASE,
)

AUTO_MUTE_DURATION = 3 * 3600
SPAM_MUTE_DURATION = 1 * 3600
SPAM_THRESHOLD = 10

spam_tracker: dict[int, dict[str, int]] = {}


def has_staff_access(user: discord.Member) -> bool:
    if user.guild_permissions.administrator:
        return True
    return any(r.name.strip().lower() == "apex | staff" for r in user.roles)


def has_link_permission(user: discord.Member) -> bool:
    if has_staff_access(user):
        return True
    return any(r.name.strip().lower() == "apex | partner" for r in user.roles)


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


async def dm_invite_mute(member: discord.Member, guild: discord.Guild, until: datetime):
    embed = discord.Embed(
        title="🔇  Message Deleted — Auto Mute",
        description=(
            "Your message in **APEX** was deleted because it contained a **Discord invite link**.\n"
            "Sharing invite links for other servers is not permitted.\n\n"
            f"{'─' * 36}"
        ),
        color=0xFF4500,
        timestamp=datetime.now(timezone.utc),
    )
    if guild.icon:
        embed.set_author(name="APEX Moderation", icon_url=guild.icon.url)
    else:
        embed.set_author(name="APEX Moderation")
    embed.add_field(name="⏱️  Mute Duration", value="`3 hours`", inline=True)
    embed.add_field(
        name="🕐  You will be unmuted",
        value=f"<t:{int(until.timestamp())}:R>\n<t:{int(until.timestamp())}:f>",
        inline=True,
    )
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(
        name="📋  Why was I muted?",
        value=(
            "> Posting Discord server invite links is against our rules.\n"
            "> Please read the server rules to avoid further action."
        ),
        inline=False,
    )
    embed.set_footer(text="APEX Auto-Moderation  •  If you believe this was a mistake, contact staff.")
    try:
        await member.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass


async def dm_spam_mute(member: discord.Member, guild: discord.Guild, until: datetime):
    embed = discord.Embed(
        title="🔇  Auto Mute — Spam Detected",
        description=(
            "Your messages in **APEX** were removed because you sent the **same message more than 10 times**.\n"
            "Spamming is not permitted in this server.\n\n"
            f"{'─' * 36}"
        ),
        color=0xFF4500,
        timestamp=datetime.now(timezone.utc),
    )
    if guild.icon:
        embed.set_author(name="APEX Moderation", icon_url=guild.icon.url)
    else:
        embed.set_author(name="APEX Moderation")
    embed.add_field(name="⏱️  Mute Duration", value="`1 hour`", inline=True)
    embed.add_field(
        name="🕐  You will be unmuted",
        value=f"<t:{int(until.timestamp())}:R>\n<t:{int(until.timestamp())}:f>",
        inline=True,
    )
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(
        name="📋  Why was I muted?",
        value=(
            "> Sending the same message repeatedly is considered spam.\n"
            "> Please read the server rules to avoid further action."
        ),
        inline=False,
    )
    embed.set_footer(text="APEX Auto-Moderation  •  If you believe this was a mistake, contact staff.")
    try:
        await member.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass


async def send_modlog_spam_mute(guild: discord.Guild, member: discord.Member, channel: discord.TextChannel, repeated_content: str, until: datetime):
    log_channel = discord.utils.find(
        lambda c: "moderation-log" in c.name.lower() or c.name.lower() == "moderation-logs",
        guild.text_channels,
    )
    if log_channel is None:
        return

    account_age = datetime.now(timezone.utc) - member.created_at
    account_age_str = f"{account_age.days}d {account_age.seconds // 3600}h"
    joined_age = datetime.now(timezone.utc) - member.joined_at if member.joined_at else None
    joined_age_str = f"{joined_age.days}d {joined_age.seconds // 3600}h" if joined_age else "Unknown"
    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    roles_str = " ".join(roles) if roles else "*None*"

    embed = discord.Embed(
        title="🔁  S P A M  D E T E C T E D",
        description=f"**{member.mention} was automatically muted for spamming the same message {SPAM_THRESHOLD}+ times.**\n{'─' * 36}",
        color=0xFFA500,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=f"{member.display_name} ({member.name})", icon_url=member.display_avatar.url)
    embed.set_thumbnail(url=member.display_avatar.url)

    embed.add_field(name="👤  User", value=f"{member.mention}\n`{member.name}`\n`ID: {member.id}`", inline=True)
    embed.add_field(name="📺  Channel", value=channel.mention, inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    embed.add_field(name="⏱️  Mute Duration", value="`1 hour`", inline=True)
    embed.add_field(name="🕐  Unmuted", value=f"<t:{int(until.timestamp())}:R>\n<t:{int(until.timestamp())}:f>", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    embed.add_field(name="🗓️  Account Created", value=f"<t:{int(member.created_at.timestamp())}:D>\n`{account_age_str} ago`", inline=True)
    embed.add_field(name="📥  Joined Server", value=f"<t:{int(member.joined_at.timestamp())}:D>\n`{joined_age_str} ago`" if member.joined_at else "Unknown", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    embed.add_field(name="🏷️  Roles", value=roles_str[:1024], inline=False)

    snipped = repeated_content if len(repeated_content) <= 512 else repeated_content[:509] + "..."
    embed.add_field(name="🔁  Repeated Message", value=f"```{snipped}```", inline=False)

    embed.set_footer(
        text="APEX Auto-Moderation  •  Spam Filter",
        icon_url=guild.icon.url if guild.icon else discord.Embed.Empty,
    )
    try:
        await log_channel.send(embed=embed)
    except discord.Forbidden:
        pass


async def send_modlog_invite_mute(guild: discord.Guild, member: discord.Member, channel: discord.TextChannel, message_content: str, until: datetime):
    log_channel = discord.utils.find(
        lambda c: "moderation-log" in c.name.lower() or c.name.lower() == "moderation-logs",
        guild.text_channels,
    )
    if log_channel is None:
        return

    account_age = datetime.now(timezone.utc) - member.created_at
    account_age_str = f"{account_age.days}d {account_age.seconds // 3600}h"

    joined_age = datetime.now(timezone.utc) - member.joined_at if member.joined_at else None
    joined_age_str = f"{joined_age.days}d {joined_age.seconds // 3600}h" if joined_age else "Unknown"

    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    roles_str = " ".join(roles) if roles else "*None*"

    embed = discord.Embed(
        title="🔗  D I S C O R D  L I N K  D E T E C T E D",
        description=f"**{member.mention} was automatically muted for posting a Discord invite.**\n{'─' * 36}",
        color=0xFF4500,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(
        name=f"{member.display_name} ({member.name})",
        icon_url=member.display_avatar.url,
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    embed.add_field(name="👤  User", value=f"{member.mention}\n`{member.name}`\n`ID: {member.id}`", inline=True)
    embed.add_field(name="📺  Channel", value=channel.mention, inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    embed.add_field(name="⏱️  Mute Duration", value="`3 hours`", inline=True)
    embed.add_field(name="🕐  Unmuted", value=f"<t:{int(until.timestamp())}:R>\n<t:{int(until.timestamp())}:f>", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    embed.add_field(name="🗓️  Account Created", value=f"<t:{int(member.created_at.timestamp())}:D>\n`{account_age_str} ago`", inline=True)
    embed.add_field(name="📥  Joined Server", value=f"<t:{int(member.joined_at.timestamp())}:D>\n`{joined_age_str} ago`" if member.joined_at else "Unknown", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    embed.add_field(name="🏷️  Roles", value=roles_str[:1024], inline=False)

    snipped = message_content if len(message_content) <= 512 else message_content[:509] + "..."
    embed.add_field(name="💬  Deleted Message", value=f"```{snipped}```", inline=False)

    embed.set_footer(
        text="APEX Auto-Moderation  •  Discord Invite Filter",
        icon_url=guild.icon.url if guild.icon else discord.Embed.Empty,
    )

    try:
        await log_channel.send(embed=embed)
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
async def on_message(message: discord.Message):
    if message.author.bot:
        await bot.process_commands(message)
        return

    if message.guild is None:
        await bot.process_commands(message)
        return

    member = message.guild.get_member(message.author.id)
    if member is None:
        await bot.process_commands(message)
        return

    if has_link_permission(member):
        await bot.process_commands(message)
        return

    if DISCORD_INVITE_PATTERN.search(message.content):
        original_content = message.content

        try:
            await message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

        until = datetime.now(timezone.utc) + timedelta(seconds=AUTO_MUTE_DURATION)

        muted = False
        if message.guild.me.guild_permissions.moderate_members:
            if member.top_role < message.guild.me.top_role:
                try:
                    await member.timeout(until, reason="Auto-mute: posted a Discord invite link")
                    muted = True
                except (discord.Forbidden, discord.HTTPException):
                    pass

        await send_modlog_invite_mute(
            guild=message.guild,
            member=member,
            channel=message.channel,
            message_content=original_content,
            until=until,
        )

        if muted:
            await dm_invite_mute(member, message.guild, until)
            try:
                warn_embed = discord.Embed(
                    title="🔇  Message Removed",
                    description=(
                        f"{member.mention}, your message was removed because it contained a **Discord invite link**.\n"
                        f"You have been muted for **3 hours**. Check your DMs for more info."
                    ),
                    color=0xFF4500,
                    timestamp=datetime.now(timezone.utc),
                )
                warn_embed.set_footer(
                    text="APEX Auto-Moderation",
                    icon_url=message.guild.icon.url if message.guild.icon else discord.Embed.Empty,
                )
                await message.channel.send(embed=warn_embed, delete_after=15)
            except (discord.Forbidden, discord.HTTPException):
                pass

        spam_tracker.pop(member.id, None)
        return

    content_key = message.content.strip().lower()
    if content_key:
        user_spam = spam_tracker.setdefault(member.id, {})
        user_spam[content_key] = user_spam.get(content_key, 0) + 1

        if user_spam[content_key] >= SPAM_THRESHOLD:
            spam_tracker.pop(member.id, None)

            try:
                await message.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass

            until = datetime.now(timezone.utc) + timedelta(seconds=SPAM_MUTE_DURATION)

            muted = False
            if message.guild.me.guild_permissions.moderate_members:
                if member.top_role < message.guild.me.top_role:
                    try:
                        await member.timeout(until, reason="Auto-mute: spam (repeated message)")
                        muted = True
                    except (discord.Forbidden, discord.HTTPException):
                        pass

            await send_modlog_spam_mute(
                guild=message.guild,
                member=member,
                channel=message.channel,
                repeated_content=content_key,
                until=until,
            )

            if muted:
                await dm_spam_mute(member, message.guild, until)
                try:
                    warn_embed = discord.Embed(
                        title="🔇  Spam Detected",
                        description=(
                            f"{member.mention}, you have been muted for **1 hour** for sending the same message repeatedly.\n"
                            f"Check your DMs for more info."
                        ),
                        color=0xFFA500,
                        timestamp=datetime.now(timezone.utc),
                    )
                    warn_embed.set_footer(
                        text="APEX Auto-Moderation",
                        icon_url=message.guild.icon.url if message.guild.icon else discord.Embed.Empty,
                    )
                    await message.channel.send(embed=warn_embed, delete_after=15)
                except (discord.Forbidden, discord.HTTPException):
                    pass

            return

    await bot.process_commands(message)


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


token = os.environ.get("DISCORD_BOT_TOKEN")
if not token:
    raise RuntimeError("DISCORD_BOT_TOKEN environment variable is not set")

bot.run(token)
