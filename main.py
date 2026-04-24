import os
import discord
from discord.ext import commands
from datetime import datetime, timezone, timedelta  # <-- ADDED

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify ✅", style=discord.ButtonStyle.green, custom_id="verify_button")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)

        target = "apex | member"
        role = discord.utils.find(
            lambda r: r.name.strip().lower() == target,
            interaction.guild.roles,
        )

        if role is None:
            available = ", ".join(r.name for r in interaction.guild.roles if r.name != "@everyone")
            await interaction.followup.send(
                f"Role not found. Available roles: {available}",
                ephemeral=True,
            )
            return

        if role in interaction.user.roles:
            await interaction.followup.send("Already verified ✅", ephemeral=True)
            return

        await interaction.user.add_roles(role)

        unverified_role = discord.utils.find(
            lambda r: r.name.strip().lower() == "unverified",
            interaction.guild.roles,
        )
        if unverified_role and unverified_role in interaction.user.roles:
            await interaction.user.remove_roles(unverified_role)

        try:
            await interaction.channel.set_permissions(
                interaction.user,
                view_channel=False,
                send_messages=False,
                read_message_history=False,
                reason="Verified - removed from verify channel",
            )
            print(f"[verify] removed {interaction.user} from {interaction.channel}")
        except discord.Forbidden:
            print(f"[verify] FORBIDDEN to set channel perms for {interaction.user}")
        except Exception as e:
            print(f"[verify] error setting perms: {e}")

        general_channel = discord.utils.find(
            lambda c: "general" in c.name.lower(),
            interaction.guild.text_channels,
        )
        general_mention = general_channel.mention if general_channel else "#general"

        success_embed = discord.Embed(
            title="You're Verified",
            description=(
                f"Welcome to **{interaction.guild.name}**. "
                f"You now have full access to the server — head over to {general_mention} "
                "to introduce yourself and join the conversation."
            ),
            color=discord.Color.green(),
        )
        if interaction.guild.icon:
            success_embed.set_thumbnail(url=interaction.guild.icon.url)

        await interaction.followup.send(embed=success_embed, ephemeral=True)


def build_verify_embed(guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(
        title="Server Verification",
        description="Click the button below to verify and gain access to the server.",
        color=discord.Color.green(),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    return embed


async def ensure_verify_embed(guild: discord.Guild):
    verify_channel = discord.utils.find(
        lambda c: "verify" in c.name.lower(),
        guild.text_channels,
    )
    if verify_channel is None:
        return

    try:
        async for msg in verify_channel.history(limit=50):
            if (
                msg.author == bot.user
                and msg.embeds
                and msg.embeds[0].title == "Server Verification"
            ):
                return
    except discord.Forbidden:
        return

    try:
        await verify_channel.send(embed=build_verify_embed(guild), view=VerifyView())
        print(f"[ensure_verify_embed] posted in {guild.name}#{verify_channel.name}")
    except discord.Forbidden:
        print(f"[ensure_verify_embed] FORBIDDEN in {guild.name}#{verify_channel.name}")


@bot.event
async def on_ready():
    bot.add_view(VerifyView())
    print(f"Logged in as {bot.user}")
    for guild in bot.guilds:
        await ensure_verify_embed(guild)
    try:
        synced = await bot.tree.sync()
        print(f"[on_ready] synced {len(synced)} slash commands")
    except Exception as e:
        print(f"[on_ready] failed to sync slash commands: {e}")


# ================= CHECKUSER SYSTEM (ADDED) =================

def account_risk_report(member: discord.Member):
    now = datetime.now(timezone.utc)
    account_age = now - member.created_at
    server_age = now - member.joined_at if member.joined_at else timedelta(0)

    flags = []

    if account_age < timedelta(days=1):
        flags.append("Account less than 24 hours old")
    elif account_age < timedelta(days=7):
        flags.append("Account less than 7 days old")

    if member.avatar is None:
        flags.append("Default avatar (never customized)")

    if member.public_flags.value == 0 and account_age < timedelta(days=30):
        flags.append("No badges + new account")

    if server_age < timedelta(minutes=5) and account_age < timedelta(days=14):
        flags.append("Joined very recently with new account")

    if account_age < timedelta(days=3):
        risk = "HIGH"
    elif account_age < timedelta(days=30) and member.avatar is None:
        risk = "MEDIUM"
    elif flags:
        risk = "LOW"
    else:
        risk = "NONE"

    return account_age, server_age, flags, risk


def fmt_age(delta: timedelta) -> str:
    days = delta.days
    if days >= 365:
        return f"{days // 365}y {days % 365}d"
    if days >= 1:
        return f"{days}d"
    hours = delta.seconds // 3600
    if hours >= 1:
        return f"{hours}h"
    return f"{delta.seconds // 60}m"


@bot.tree.command(name="checkuser", description="Check if a member looks fake or suspicious (admin only)")
@discord.app_commands.describe(member="The member to check")
async def checkuser(interaction: discord.Interaction, member: discord.Member):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "You need Administrator permission to use this command.",
            ephemeral=True,
        )
        return

    account_age, server_age, flags, risk = account_risk_report(member)

    color = {
        "HIGH": discord.Color.red(),
        "MEDIUM": discord.Color.orange(),
        "LOW": discord.Color.yellow(),
        "NONE": discord.Color.green(),
    }[risk]

    embed = discord.Embed(
        title=f"Account Check — {member.display_name}",
        color=color,
    )

    embed.set_thumbnail(url=member.display_avatar.url)

    embed.add_field(name="Username", value=str(member), inline=True)
    embed.add_field(name="Risk", value=risk, inline=True)
    embed.add_field(name="Account Age", value=fmt_age(account_age), inline=True)
    embed.add_field(name="In Server", value=fmt_age(server_age), inline=True)

    embed.add_field(
        name="Flags",
        value="\n".join(f"• {f}" for f in flags) if flags else "None",
        inline=False,
    )

    embed.add_field(
        name="Created",
        value=f"<t:{int(member.created_at.timestamp())}:F>",
        inline=False,
    )

    if member.joined_at:
        embed.add_field(
            name="Joined Server",
            value=f"<t:{int(member.joined_at.timestamp())}:F>",
            inline=False,
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ================= REST OF YOUR ORIGINAL CODE =================

@bot.tree.command(name="verify", description="Manually verify a member (admin only)")
@discord.app_commands.describe(member="The member to verify")
async def verify_cmd(interaction: discord.Interaction, member: discord.Member):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "You need Administrator permission to use this command.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    guild = interaction.guild
    role = discord.utils.find(
        lambda r: r.name.strip().lower() == "apex | member",
        guild.roles,
    )
    if role is None:
        await interaction.followup.send("Role `APEX | member` not found.", ephemeral=True)
        return

    if role in member.roles:
        await interaction.followup.send(f"{member.mention} is already verified.", ephemeral=True)
        return

    try:
        await member.add_roles(role, reason=f"Manually verified by {interaction.user}")
    except discord.Forbidden:
        await interaction.followup.send(
            "I don't have permission to assign that role. Make sure my role is above `APEX | member`.",
            ephemeral=True,
        )
        return

    unverified_role = discord.utils.find(
        lambda r: r.name.strip().lower() == "unverified",
        guild.roles,
    )
    if unverified_role and unverified_role in member.roles:
        try:
            await member.remove_roles(unverified_role, reason=f"Manually verified by {interaction.user}")
        except discord.Forbidden:
            pass

    verify_channel = discord.utils.find(
        lambda c: "verify" in c.name.lower(),
        guild.text_channels,
    )
    if verify_channel:
        try:
            await verify_channel.set_permissions(
                member,
                view_channel=False,
                send_messages=False,
                read_message_history=False,
                reason=f"Manually verified by {interaction.user}",
            )
        except discord.Forbidden:
            pass

    await interaction.followup.send(f"✅ Verified {member.mention}.", ephemeral=True)


# ================= RUN =================

token = os.environ.get("DISCORD_BOT_TOKEN")
if not token:
    raise RuntimeError("DISCORD_BOT_TOKEN environment variable is not set")

bot.run(token)