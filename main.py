import os
import random
import asyncio
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

VERIFY_URL = "https://discord.com/oauth2/authorize?client_id=1496753618861424700&response_type=code&redirect_uri=https%3A%2F%2Fapex-verify-d.up.railway.app%2Fcallback&scope=identify+guilds.join"

active_giveaways = {}
ended_giveaways = {}


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

    ended_giveaways[data["channel_id"]] = {
        "prize": data["prize"],
        "entries": valid_entries,
    }

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


@bot.tree.command(name="verify", description="Manually verify a member (admin only)")
@discord.app_commands.describe(member="The member to verify")
async def verify_cmd(interaction, member: discord.Member):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Administrator permission required.", ephemeral=True)
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


@bot.tree.command(name="verifycount", description="Show verified vs unverified counts (admin only)")
async def verifycount(interaction):
    if not interaction.guild or not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Administrator permission required.", ephemeral=True)
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


@bot.tree.command(name="gstart", description="Start a giveaway (admin only)")
@discord.app_commands.describe(
    prize="What are you giving away?",
    duration="Duration in minutes",
    winners="Number of winners (default: 1)",
    channel="Channel to post in (default: current channel)",
)
async def gstart(interaction: discord.Interaction, prize: str, duration: int, winners: int = 1, channel: discord.TextChannel = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Administrator permission required.", ephemeral=True)
        return
    target_channel = channel or interaction.channel
    end_time = datetime.now(timezone.utc) + timedelta(minutes=duration)
    embed = build_giveaway_embed(prize, interaction.user, end_time, winners, 0)
    await interaction.response.send_message(f"Giveaway started in {target_channel.mention}!", ephemeral=True)
    msg = await target_channel.send(content="@everyone", embed=embed, view=GiveawayView())
    active_giveaways[msg.id] = {
        "channel_id": target_channel.id,
        "guild_id": interaction.guild_id,
        "prize": prize,
        "host_id": interaction.user.id,
        "end_time": end_time,
        "winners_count": winners,
        "entries": set(),
        "task": asyncio.create_task(giveaway_timer(msg.id, duration * 60)),
    }


@bot.tree.command(name="gend", description="End the active giveaway in this channel early (admin only)")
async def gend(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Administrator permission required.", ephemeral=True)
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


@bot.tree.command(name="greroll", description="Reroll a winner from the last giveaway in this channel (admin only)")
async def greroll(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Administrator permission required.", ephemeral=True)
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
