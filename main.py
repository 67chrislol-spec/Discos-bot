import os
import discord
from discord.ext import commands

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


# 🔘 Button with LINK
class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(discord.ui.Button(
            label="Verify ✅",
            style=discord.ButtonStyle.link,
            url="PASTE_YOUR_LINK_HERE"  # 👈 YOUR OAUTH OR WEBSITE LINK
        ))


# 🧾 Embed
def verify_embed(guild):
    embed = discord.Embed(
        title="Server Verification",
        description="Click the button below to verify and gain access to the server.",
        color=discord.Color.green()
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    return embed


# 🚀 Command
@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    await ctx.send(embed=verify_embed(ctx.guild), view=VerifyView())


# 🔁 Keep button working
@bot.event
async def on_ready():
    bot.add_view(VerifyView())
    print(f"Logged in as {bot.user}")


bot.run(os.environ["DISCORD_BOT_TOKEN"])