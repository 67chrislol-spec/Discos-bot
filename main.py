import os
import discord
from discord.ext import commands

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

    print(f"[verify_cmd] {interaction.user} manually verified {member}")
    await interaction.followup.send(f"✅ Verified {member.mention}.", ephemeral=True)


@bot.tree.command(name="verifycount", description="Show how many members are verified vs unverified")
async def verifycount(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "You need Administrator permission to use this command.",
            ephemeral=True,
        )
        return

    member_role = discord.utils.find(
        lambda r: r.name.strip().lower() == "apex | member",
        guild.roles,
    )
    unverified_role = discord.utils.find(
        lambda r: r.name.strip().lower() == "unverified",
        guild.roles,
    )

    verified_count = len(member_role.members) if member_role else 0
    unverified_count = len(unverified_role.members) if unverified_role else 0

    embed = discord.Embed(
        title="Verification Stats",
        color=discord.Color.from_rgb(255, 90, 30),
    )
    embed.add_field(name="Verified", value=str(verified_count), inline=True)
    embed.add_field(name="Unverified", value=str(unverified_count), inline=True)
    embed.add_field(name="Total Members", value=str(guild.member_count), inline=True)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.event
async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent):
    if payload.guild_id is None:
        return
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
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

    print(f"[on_raw_message_delete] message in verify channel deleted, ensuring embed exists")
    await ensure_verify_embed(guild)


@bot.event
async def on_member_join(member: discord.Member):
    print(f"[on_member_join] {member} joined {member.guild.name}")

    unverified_role = discord.utils.find(
        lambda r: r.name.strip().lower() == "unverified",
        member.guild.roles,
    )
    if unverified_role:
        try:
            await member.add_roles(unverified_role)
            print(f"[on_member_join] gave unverified role to {member}")
        except discord.Forbidden:
            print(f"[on_member_join] FORBIDDEN to add unverified role")

    welcome_channel = discord.utils.find(
        lambda c: "welcome" in c.name.lower(),
        member.guild.text_channels,
    )
    print(f"[on_member_join] welcome_channel={welcome_channel}")

    if welcome_channel:
        count = member.guild.member_count
        if 10 <= count % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(count % 10, "th")

        embed = discord.Embed(
            description=(
                f"Welcome {member.display_name} to **APEX** "
                f"you are the {count}{suffix} member!"
            ),
            color=discord.Color.from_rgb(255, 90, 30),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        content = (
            f"Welcome {member.mention} to **APEX**!\n"
            f"You are the {count}{suffix} member!"
        )
        try:
            await welcome_channel.send(content=content, embed=embed)
            print(f"[on_member_join] sent welcome message")
        except discord.Forbidden:
            print(f"[on_member_join] FORBIDDEN to send in welcome channel")
    else:
        text_channels = ", ".join(c.name for c in member.guild.text_channels)
        print(f"[on_member_join] no welcome channel found. Available: {text_channels}")


@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass

    embed = discord.Embed(
        title="Server Verification",
        description="Click the button below to verify and gain access to the server.",
        color=discord.Color.green(),
    )
    if ctx.guild and ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)
    await ctx.send(embed=embed, view=VerifyView())


@setup.error
async def setup_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass


token = os.environ.get("DISCORD_BOT_TOKEN")
if not token:
    raise RuntimeError("DISCORD_BOT_TOKEN environment variable is not set")

bot.run(token)

@bot.command(name="checkuser")
@commands.has_permissions(administrator=True)
async def checkuser_cmd(ctx, member: discord.Member):
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
    embed.add_field(name="User ID", value=str(member.id), inline=True)
    embed.add_field(name="Risk", value=risk, inline=True)
    embed.add_field(name="Account Age", value=fmt_age(account_age), inline=True)
    embed.add_field(name="In Server", value=fmt_age(server_age), inline=True)
    embed.add_field(name="Custom Avatar", value="No" if member.avatar is None else "Yes", inline=True)
    embed.add_field(name="Created", value=f"<t:{int(member.created_at.timestamp())}:F>", inline=False)
    if member.joined_at:
        embed.add_field(name="Joined Server", value=f"<t:{int(member.joined_at.timestamp())}:F>", inline=False)
    embed.add_field(
        name="Flags",
        value="\n".join(f"• {f}" for f in flags) if flags else "None",
        inline=False,
    )

    await ctx.send(embed=embed)


@bot.command(name="scanfakes")
@commands.has_permissions(administrator=True)
async def scanfakes_cmd(ctx):
    suspicious = []
    for member in ctx.guild.members:
        if member.bot:
            continue
        _, _, flags, risk = account_risk_report(member)
        if risk in ("HIGH", "MEDIUM"):
            suspicious.append((member, risk, flags))

    if not suspicious:
        await ctx.send("No suspicious accounts found.")
        return

    suspicious.sort(key=lambda x: 0 if x[1] == "HIGH" else 1)
    lines = [
        f"**[{risk}]** {m.mention} — {', '.join(flags) if flags else 'Flagged'}"
        for m, risk, flags in suspicious[:25]
    ]
    embed = discord.Embed(
        title=f"Suspicious Accounts ({len(suspicious)} found)",
        description="\n".join(lines),
        color=discord.Color.red(),
    )
    if len(suspicious) > 25:
        embed.set_footer(text=f"Showing 25 of {len(suspicious)}")
    await ctx.send(embed=embed)


@bot.command(name="newaccounts")
@commands.has_permissions(administrator=True)
async def newaccounts_cmd(ctx, days: int = 7):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    matches = [m for m in ctx.guild.members if not m.bot and m.created_at > cutoff]
    matches.sort(key=lambda m: m.created_at)

    if not matches:
        await ctx.send(f"No accounts younger than {days} days.")
        return

    lines = [
        f"{m.mention} — created <t:{int(m.created_at.timestamp())}:R>"
        for m in matches[:25]
    ]
    embed = discord.Embed(
        title=f"Accounts Younger Than {days} Days ({len(matches)} found)",
        description="\n".join(lines),
        color=discord.Color.orange(),
    )
    if len(matches) > 25:
        embed.set_footer(text=f"Showing 25 of {len(matches)}")
    await ctx.send(embed=embed)