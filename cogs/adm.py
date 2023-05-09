import typing

import discord
from discord.ext import commands


class Adm(commands.Cog):
    """Cog para comandos de teste e configuração."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name='purge')
    @commands.is_owner()
    async def purge(self, ctx: commands.Context, amount: int = 0):
        """
        Limpa mensagens no canal atual.

        :param ctx: Objeto de contexto
        :param amount: Quantidade de mensagens para apagar
        """
        await ctx.channel.purge(limit=amount or 100)

    @commands.command(name='ping')
    @commands.is_owner()
    async def ping(self, ctx: commands.Context):
        """
        Responde interação do usuário.

        :param ctx: Objeto de contexto
        """
        await ctx.reply('pong!', delete_after=5)

    @commands.command(name='sync')
    @commands.is_owner()
    async def sync(self, ctx: commands.Context, guilds: commands.Greedy[discord.Object],
                   spec: typing.Optional[typing.Literal["~", "*", "^"]] = None):
        """
        Sincroniza slash commands.

        $sync -> Sincroniza globalmente
        $sync ~ -> Sincroniza guild atual
        $sync * -> Copia todos os comandos globais para a guild atual e sincroniza
        $sync ^ -> Remove todos os comandos da guild atual e sincroniza
        $sync id_1 id_2 -> Sincroniza guilds com ids específicos

        :param ctx: Objeto de contexto
        :param guilds: Id da guild (Esse parâmetro pode ser enviado várias vezes)
        :param spec: Literal: "~", "*", "^" para alterar o comportamento do comando (Esse parâmetro é ignorado caso o
        parâmetro anterior seja enviado)
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

        await ctx.send(f"Árvore de comandos sincronizada para {count}/{len(guilds)} guilds.")


async def setup(bot: commands.Bot):
    """
    Função chamada internamente pelo framework discord.py para vincular a cog ao bot

    :param bot: Instância do bot
    """
    await bot.add_cog(Adm(bot))
