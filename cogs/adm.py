import discord
import typing
from discord.ext import commands


class Adm(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name='ping')
    @commands.is_owner()
    async def ping(self, ctx: commands.Context):
        await ctx.reply('pong!')

    @commands.command(name='sync')
    @commands.is_owner()
    async def sync(self, ctx: commands.Context, guilds: commands.Greedy[discord.Object],
                   spec: typing.Optional[typing.Literal["~", "*", "^"]] = None):
        """
        !sync -> global sync
        !sync ~ -> sync current guild
        !sync * -> copies all global app commands to current guild and syncs
        !sync ^ -> clears all commands from the current guild target and syncs (removes guild commands)
        !sync id_1 id_2 -> syncs guilds with id 1 and 2
        """
        if not guilds:
            if spec == "~":
                synced = await self.bot.tree.sync(guild=ctx.guild)
            elif spec == "*":
                self.bot.tree.copy_global_to(guild=ctx.guild)
                synced = await self.bot.tree.sync(guild=ctx.guild)
            elif spec == "^":
                self.bot.tree.clear_commands(guild=ctx.guild)
                await self.bot.tree.sync(guild=ctx.guild)
                synced = []
            else:
                synced = await self.bot.tree.sync()

            await ctx.send(f"{len(synced)} comandos sincronizados "
                               f"{'globalmente' if spec is None else 'no server atual.'}")
            return

        count = 0

        for guild in guilds:
            try:
                await self.bot.tree.sync(guild=guild)
            except discord.HTTPException:
                pass
            else:
                count += 1

        await ctx.send(f"Synced the tree to {count}/{len(guilds)}.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Adm(bot))
