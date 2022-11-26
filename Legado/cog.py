import os
import random
import json
from discord import Member, VoiceState, FFmpegPCMAudio
from discord.channel import VoiceChannel, TextChannel
from discord.voice_client import VoiceClient
from discord.errors import ClientException
from discord.ext import commands
from discord.utils import get
from asyncio import sleep
from _asyncio import Task


# Classe dos comandos
class Cog(commands.Cog, name='Comandos'):
    def __init__(self, bot: commands.Bot):
        # Instancia variáveis
        self.bot = bot

        self._run_loop: Task | None = None
        self._voice_client: VoiceClient | None = None
        self._text_channel: TextChannel | None = None

        self._auto_join: bool = False
        self._ban_event: bool = True

        # Abre o arquivo json para coletar informações sobre os canais padrões
        with open('../config.json') as file:
            config = json.load(file)

        self._default_text_channel_id: int = config['default_text_channel_id']
        self._ban_voice_channel_id: int = config['ban_voice_channel_id']

        # Tempo padrão do temporizador
        self._inicial_timer: int = 300
        self._final_timer: int = 500

    # Retorna o atual temporizador
    @property
    def timer(self):
        if self._inicial_timer == self._final_timer:
            message = f'{self.bot.user.name} configurado a cada {self._inicial_timer} segundos.'
        else:
            message = f'{self.bot.user.name} configurado entre {self._inicial_timer} e {self._final_timer} segundos.'

        return message

    # Disparado ao houver atualização em algum canal de voz
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: Member, before: VoiceState, after: VoiceState):
        if before:
            pass

        channel = after.channel

        # Caso o bot seja o último membro de um canal de voz ou alguém tiver removido ele, interrompe o loop
        if (self._voice_client and len(self._voice_client.channel.members) == 1) or \
                (member.display_name == self.bot.user.name and not channel):
            await self._leave()
            return

        # Caso auto_join estiver True e número de membros de um canal de voz ser maior que 1, bot entra automaticamente
        if channel and self._auto_join:
            # Ignora caso o bot já esteja em funcionamento em um canal
            if self._run_loop and not self._run_loop.done():
                return

            count = len([i_member for i_member in channel.members if not i_member.bot])

            if count > 1:
                # Como o bot entrou automaticamente não é setado nenhum canal padrão para enviar mensagens
                self._text_channel = None
                await self._play(channel)

    # Caso o bot seja disparado pelo comando, então seta o canal de texto utilizado como canal para enviar mensagens
    @commands.hybrid_command(name='play', help='Inicia o bot.')
    async def play(self, ctx: commands.Context):
        voice = ctx.message.author.voice

        if not voice:
            await ctx.send('Entre na call primeiro, corno!  :monkey_face::raised_back_of_hand: ')
            return

        self._text_channel = ctx.channel
        channel = voice.channel

        await self._play(channel)

    @commands.hybrid_command(name='leave', help=f'Remover bot.')
    async def leave(self, ctx: commands.Context):
        if ctx:
            pass

        await self._leave()

    # Seta o temporizador
    @commands.hybrid_command(name='set', help='Configurar temporizador em segundos.')
    async def set_timer(self, ctx: commands.Context, timer1: str, timer2: str = None):
        if not timer1:
            await ctx.send('Envie ao menos um valor, corno!  :monkey:')
            return

        if not timer1.isnumeric() or (timer2 and not timer2.isnumeric()):
            await ctx.send('Envie apenas valores numéricos, monkey!  :monkey:')
            return

        self._inicial_timer = int(timer1)
        self._final_timer = int(timer2) if timer2 else int(timer1)

        if self._inicial_timer == self._final_timer:
            message = f'{self.bot.user.name} configurado para funcionar a cada {timer1} segundos.'
        else:
            message = f'{self.bot.user.name} configurado para funcionar entre {timer1} e {timer2} segundos.'

        await ctx.send(f'Entendido, monkey!  :muscle:\n'
                       f'{message}')

    @commands.hybrid_command(name='timer', help='Retorna o atual temporizador.')
    async def current_timer(self, ctx: commands.Context):
        await ctx.send(self.timer)

    # Desativa ou ativa a opção de entrar automaticamente
    @commands.hybrid_command(name='auto-join', help='Quando True o bot entra sozinho ao perceber duas ou mais '
                                             'pessoas em um canal de voz.')
    async def auto_join(self, ctx: commands.Context, mode: bool):
        self._auto_join = mode
        await ctx.send(f'Bot auto join configurado para {mode}')

    # Desativa ou ativa o evento do efeito 'banido.mp3'
    @commands.hybrid_command(name='ban-event', help="Quando True o bot move aleatoriamente um usuário para um canal "
                                                    "alternativo.")
    async def ban(self, ctx: commands.Context, mode: bool):
        self._ban_event = mode
        await ctx.send(f'Bot ban event configurado para {mode}')

    # Caso o bot já esteja em um canal, move-o, do contrário, conecta-o no canal
    async def _join(self, voice_channel: VoiceChannel):
        try:
            await voice_channel.connect()

            guild = getattr(voice_channel, 'guild')
            self._voice_client = get(self.bot.voice_clients, guild=guild)
        except ClientException:
            if self._voice_client:
                await self._voice_client.move_to(voice_channel)

        if self._text_channel:
            await self._text_channel.send(f'{self.bot.user.name} está na área, derrubou é penalty!  :sunglasses:')

        print('join')

    # Inicia o loop e se junta ao canal
    async def _play(self, voice_channel: VoiceChannel):
        if self._run_loop and not self._run_loop.done():
            if self._text_channel:
                await self._text_channel.send('Já estou funcionando, monkey! :monkey:')

            return

        await self._join(voice_channel)

        if self._text_channel:
            await self._text_channel.send(f'Você que pediu.  :see_no_evil:\n{self.timer}')

        # Cria o loop
        self._run_loop = self.bot.loop.create_task(self._loop(voice_channel))
        print('play')

    # Encerra o loop e se desconecta do canal
    async def _leave(self):
        if self._run_loop and not self._run_loop.done():
            self._run_loop.cancel()

        if self._voice_client:
            await self._voice_client.disconnect()

            if self._text_channel:
                await self._text_channel.send('As vozes... elas não saem da minha cabeça.  :hear_no_evil:')

            self._text_channel = None
            self._voice_client = None

        print('leave')

    # Loop principal
    async def _loop(self, voice_channel: VoiceChannel):
        effects = []
        effect = ''

        for root, dirs, files in os.walk('../effects/'):
            for file in files:
                fullname = os.path.join(root, file)
                effects.append(fullname)

        print(f'{len(effects)} efeitos encontrados.')

        while True:
            while self._voice_client.is_playing():
                await sleep(1)

            if 'BANIDO' in effect and self._ban_event:
                await self._ban(voice_channel)

            timer = random.randint(self._inicial_timer, self._final_timer)
            await sleep(timer)

            effect = random.choice(effects)
            print(effect)

            try:
                self._voice_client.play(FFmpegPCMAudio(source=effect))
                self._voice_client.is_playing()
            except Exception as e:
                message = e.message if hasattr(e, 'message') else e
                self._text_channel = self.bot.get_channel(self._default_text_channel_id)

                await self._text_channel.send(f'Algo de errado não está certo, verifique por favor:  '
                                              f':monkey_face::thumbsdown:\n '
                                              f'{e.__class__.__name__} {e.__context__}: {message}')

                self._text_channel = None
                self._run_loop.cancel()
                print('error')

    # Evento BANIDO
    async def _ban(self, voice_channel: VoiceChannel):
        monkey_channel = self.bot.get_channel(self._ban_voice_channel_id)
        members = []

        for member in voice_channel.members:
            if not member.bot:
                members.append(member.id)

        user_id = random.choice(members)
        user = get(self.bot.get_all_members(), id=user_id)

        await user.move_to(monkey_channel)
        print(user)


# Função para adicionar cog ao bot
async def setup(bot: commands.Bot):
    await bot.add_cog(Cog(bot))
