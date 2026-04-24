import os
import discord
from discord.ext import commands
from datetime import datetime, timezone, timedelta

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ================= VERIFY BUTTON =================
class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify ✅", style=discord.ButtonStyle.green, custom_id="verify_button")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)

        role = discord.utils.find(
            lambda r: r.name.strip().lower() == "apex | member",
            interaction.guild.roles,
        )

        if role is None:
            await interaction.followup.send("Role `apex | member` not found.", ephemeral=True)
            return

        if role in interaction.user.roles:
            await interaction.followup.send("Already verified ✅", ephemeral=True)
            return

        await interaction.user.add_roles(role)

        # Remove unverified
        unverified = discord.utils.find(
            lambda r: r.name.strip().lower() == "unverified",
            interaction.guild.roles,
        )
        if unverified and unverified in interaction.user.roles:
            await interaction.user.remove_roles(unverified)

        await interaction.followup.send("✅ You are now verified!", ephemeral=True)


# ================= VERIFY EMBED =================
def build_verify_embed(guild):
    embed = discord.Embed(
        title="Server Verification",
        description="Click the button below to verify and gain access.",
        color=discord.Color.green(),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    return embed


async def ensure_verify_embed(guild):
    verify_channel = discord.utils.find(lambda c: "verify" in c.name.lower(), guild.text_channels)
    if not verify_channel:
        return

    async for msg in verify_channel.history(limit=50):
        if msg.author == bot.user and msg.embeds:
            if msg.embeds[0].title == "Server Verification":
                return

    await verify_channel.send(embed=build_verify_embed(guild), view=VerifyView())


# ================= BOT READY =================
@bot.event
async def on_ready():
    bot.add_view(VerifyView())
    print(f"Logged in as {bot.user}")

    for guild in bot.guilds:
        await ensure_verify_embed(guild)

    await bot.tree.sync()


# ================= MEMBER JOIN =================
@bot.event
async def on_member_join(member):
    unverified = discord.utils.find(
        lambda r: r.name.strip().lower() == "unverified",
        member.guild.roles,
    )
    if unverified:
        await member.add_roles(unverified)


# ================= SETUP COMMAND =================
@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    await ctx.send(embed=build_verify_embed(ctx.guild), view=VerifyView())


# ================= RISK SYSTEM =================
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
        flags.append("Default avatar")

    if member.public_flags.value == 0 and account_age < timedelta(days=30):
        flags.append("No badges + new account")

    if server_age < timedelta(minutes=5) and account_age < timedelta(days=14):
        flags.append("Joined very recently")

    if account_age < timedelta(days=3):
        risk = "HIGH"
    elif account_age < timedelta(days=30) and member.avatar is None:
        risk = "MEDIUM"
    elif flags:
        risk = "LOW"
    else:
        risk = "NONE"

    return account_age, server_age, flags, risk


def fmt_age(delta):
    days = delta.days
    if days >= 365:
        return f"{days // 365}y"
    if days >= 1:
        return f"{days}d"
    hours = delta.seconds // 3600
    if hours >= 1:
        return f"{hours}h"
    return f"{delta.seconds // 60}m"


# ================= /CHECKUSER =================
@bot.tree.command(name="checkuser", description="Check if a user is suspicious")
async def checkuser(interaction: discord.Interaction, member: discord.Member):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return

    account_age, server_age, flags, risk = account_risk_report(member)

    color = {
        "HIGH": discord.Color.red(),
        "MEDIUM": discord.Color.orange(),
        "LOW": discord.Color.yellow(),
        "NONE": discord.Color.green(),
    }[risk]

    embed = discord.Embed(
        title=f"User Check — {member}",
        color=color
    )

    embed.set_thumbnail(url=member.display_avatar.url)

    embed.add_field(name="Risk", value=risk, inline=True)
    embed.add_field(name="Account Age", value=fmt_age(account_age), inline=True)
    embed.add_field(name="Server Time", value=fmt_age(server_age), inline=True)

    embed.add_field(
        name="Flags",
        value="\n".join(f"• {f}" for f in flags) if flags else "None",
        inline=False
    )

    embed.add_field(
        name="Created",
        value=f"<t:{int(member.created_at.timestamp())}:F>",
        inline=False
    )

    if member.joined_at:
        embed.add_field(
            name="Joined",
            value=f"<t:{int(member.joined_at.timestamp())}:F>",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ================= RUN =================
token = os.environ.get("DISCORD_BOT_TOKEN")
if not token:
    raise RuntimeError("DISCORD_BOT_TOKEN not set")

bot.run(token)