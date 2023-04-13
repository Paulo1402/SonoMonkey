import os
import asyncio

import dotenv
from discord import Intents
from discord.ext import commands


GUILD_ID = 742892816937779201


# Classe principal
class SonoMonkey(commands.Bot):
    def __init__(self):
        # Habilita permissões para o bot
        intents = Intents.default()
        intents.message_content = True
        intents.members = True

        # Cria o bot
        super().__init__(command_prefix='$', intents=intents, help_command=None)

        # Carrega variáveis do ambiente
        dotenv.load_dotenv()

    # Retorna o token armazenado no arquivo .env
    @property
    def token(self):
        return os.getenv('TOKEN')

    # Disparado ao iniciar o bot
    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user})")


async def main():
    bot = SonoMonkey()

    async with bot:
        await bot.load_extension('cogs.music')
        await bot.load_extension('cogs.adm')
        await bot.start(bot.token)


if __name__ == '__main__':
    asyncio.run(main())

