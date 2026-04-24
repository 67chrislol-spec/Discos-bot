import os
import discord
from discord.ext import commands
import random
import string
from datetime import datetime, timedelta

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
        except:
            pass

        general_channel = discord.utils.find(
            lambda c: "general" in c.name.lower(),
            interaction.guild.text_channels,
        )
        general_mention = general_channel.mention if general_channel else "#general"

        success_embed = discord.Embed(
            title="You're Verified",
            description=f"Welcome to **{interaction.guild.name}**. Head to {general_mention}.",
            color=discord.Color.green(),
        )

        await interaction.followup.send(embed=success_embed, ephemeral=True)


# ✅ KEY GENERATOR ADDED HERE
def generate_key():
    parts = []
    for _ in range(5):
        part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        parts.append(part)
    return "APEX-" + "-".join(parts)


@bot.command()
async def key(ctx, action=None):
    if action != "gen":
        await ctx.send("Use `!key gen` to generate a key.")
        return

    key = generate_key()
    user = ctx.author.name
    expires = datetime.utcnow() + timedelta(days=1)

    embed = discord.Embed(
        title="APEX License Key Generated",
        color=discord.Color.dark_gray()
    )

    embed.add_field(name="Key", value=f"`{key}`", inline=False)
    embed.add_field(name="Type", value="Daily", inline=True)
    embed.add_field(name="User", value=user, inline=True)
    embed.add_field(name="Expires", value=expires.strftime("%Y-%m-%d %H:%M:%S"), inline=False)

    embed.set_footer(text="this is just a fake key gen lol get pranked 😭")

    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    embed = discord.Embed(
        title="Server Verification",
        description="Click the button below to verify.",
        color=discord.Color.green(),
    )
    await ctx.send(embed=embed, view=VerifyView())


token = os.environ.get("DISCORD_BOT_TOKEN")
if not token:
    raise RuntimeError("DISCORD_BOT_TOKEN environment variable is not set")

bot.run(token)