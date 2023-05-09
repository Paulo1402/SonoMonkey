import os
import asyncio

import dotenv
from discord import Intents
from discord.ext import commands


class SonoMonkey(commands.Bot):
    """Classe principal."""

    def __init__(self):
        # Habilita permissões para o bot
        intents = Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True

        # Cria o bot
        super().__init__(command_prefix='$', intents=intents, help_command=None)

    @property
    def token(self):
        """Retorna o token armazenado no arquivo .env."""
        return os.getenv('TOKEN')

    async def on_ready(self):
        """Disparado ao bot se conectar a api do discord."""
        print(f"Logged in as {self.user} (ID: {self.user.id})")


async def main():
    # Instância do bot
    bot = SonoMonkey()

    # Adiciona cogs ao bot e inicia o loop
    async with bot:
        await bot.load_extension('cogs.music')
        await bot.load_extension('cogs.adm')
        await bot.start(bot.token)


if __name__ == '__main__':
    # Carrega variáveis do ambiente e executa entry point
    dotenv.load_dotenv()
    asyncio.run(main())

