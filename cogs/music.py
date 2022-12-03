import logging
import wavelink
import discord
import os
import asyncio
import random
import json
import datetime
from utils.functions import *
from math import floor
from asyncio import Task
from wavelink.ext import spotify
from discord import app_commands
from discord.ext import commands, tasks


MUSIC_CHANNEL_ID = 999002277186637854

tz = datetime.timezone(datetime.timedelta(hours=-3))
task_time = datetime.time(hour=00, minute=00, tzinfo=tz)


# noinspection PyTypeChecker
class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        filename = datetime.datetime.now().strftime('%d-%m')
        self.logger: logging.Logger = create_logger(filename)

        self.ready = False
        self.loop_flag = False

        self.display_view: DisplayView = None
        self.queue_view: QueueView = None

        self.vc: wavelink.Player = None
        self.queue: Queue = None
        self.playlist_loop: Task = None

        self._create_logger.start()
        bot.loop.create_task(self.connect_nodes())

    # Verifica se o comando foi executado corretamente
    def cog_check(self, ctx: commands.Context) -> bool:
        return bool(ctx.interaction)

    # Disparado ao node se conectar corretamente ao lavalink
    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, node: wavelink.Node):
        print(f'Node: <{node.identifier}> is ready!')

    # Disparado ao acabar uma música
    @commands.Cog.listener()
    async def on_wavelink_track_end(self, player: wavelink.Player, track: wavelink.Track, reason: str):
        if reason == 'REPLACED':
            return

        if self.loop_flag:
            await self.play_song(track)
            return

        self.queue.duration -= track.duration
        await self.play_song()

    # Disparado ao bot se conectar a api do discord
    @commands.Cog.listener()
    async def on_ready(self):
        if self.ready:
            return

        display_message, queue_message = await self.setup_views()

        self.display_view = await DisplayView.create_view(display_message, self)
        self.queue_view = await QueueView.create_view(queue_message, self)

        self.bot.add_view(self.display_view, message_id=display_message.id)
        self.bot.add_view(self.queue_view, message_id=queue_message.id)

        self.ready = True

    # Disparado ao enviar uma mensagem em um canal de texto
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # if message.interaction:
        #     return

        check = [not self.ready, message.channel.id != MUSIC_CHANNEL_ID, message.author.id == self.bot.user.id]

        # Verifica checks
        if any(check):
            return

        # Verifica se o conteúdo enviado é um link
        if is_url(message.content):
            ctx = await self.bot.get_context(message)
            await self.play(ctx, message.content)

        # Deleta toda e qualquer mensagem após isso
        await message.delete(delay=10)

    # Disparado ao ter uma alteração em algum canal de voz
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState,
                                    after: discord.VoiceState):
        if self.vc and len(self.vc.channel.members) == 1 or \
                (member.display_name == self.bot.user.name and not after.channel):
            await self.leave(True)

    # Prepara views dinâmicos e retorna as mensagens usadas como container
    async def setup_views(self):
        json_path = os.path.join(ROOT, 'config.json')
        channel = self.bot.get_channel(MUSIC_CHANNEL_ID)
        messages = []

        # Carrega ids armazenadas no arquivo json
        with open(json_path, 'r') as f:
            config: dict = json.load(f)

        ids = [value for value in config.values()]

        for message_id in ids:
            # Verifica se a id é valida
            try:
                message = await channel.fetch_message(message_id)
            # Caso não seja envia uma mensagem temporária
            except discord.NotFound:
                message = await channel.send('...')

            # Salva referência na memória
            messages.append(message)

        # Deleta qualquer mensagem que não seja parte dos views no canal do bot
        await channel.purge(check=lambda m: m not in messages)

        config = {
            'display_message_id': messages[0].id,
            'queue_message_id': messages[1].id,
        }

        # Salva as alterações no arquivo json
        with open(json_path, 'w') as f:
            f.write(json.dumps(config, indent=2))

        # Retorna a lista contendo a referência das mensagens
        return messages

    # Conecta node ao lavalink
    async def connect_nodes(self):
        await self.bot.wait_until_ready()

        # Obtém dados sensíveis armazenados como variáveis de ambiente
        client_id = os.getenv('SPOTIFY_ID')
        client_secret = os.getenv('SPOTIFY_SECRET')
        host = os.getenv('LAVALINK_HOST')
        password = os.getenv('LAVALINK_PASSWORD')

        # Cria objeto spotify_client
        spotify_client = spotify.SpotifyClient(client_id=client_id, client_secret=client_secret)

        # Cria node
        await wavelink.NodePool.create_node(bot=self.bot, host=host, port=443, password=password, https=True,
                                            identifier='main', spotify_client=spotify_client)

    # Cria um novo arquivo de log
    @tasks.loop(time=task_time)
    async def _create_logger(self):
        filename = datetime.datetime.now().strftime('%d-%m')
        self.logger = create_logger(filename)

    # Verifica se o bot está conectado
    async def bot_is_ready(self, ctx: commands.Context):
        if self.vc and self.vc.is_connected():
            return True

        await ctx.interaction.response.send_message('Não estou conectado a nenhum canal!', ephemeral=True,
                                                    delete_after=5)

    # Entra no canal do usuário caso esteja em um
    async def join(self, user: discord.Member):
        if not self.vc and user.voice:
            self.vc = await user.voice.channel.connect(cls=wavelink.Player)
            self.queue = Queue()
        elif self.vc and self.vc.channel != user.voice.channel:
            await self.vc.move_to(user.voice.channel)

        # Verifica se o bot conseguiu se conectar ao canal
        if self.vc:
            return True

    async def play(self, ctx: commands.Context, search: str):
        # Verifica se o bot se juntou ao canal
        if not await self.join(ctx.author):
            await ctx.reply('Entre na call primeiro, corno! :monkey_face::raised_back_of_hand:', ephemeral=True,
                            delete_after=5)
            return

        # Atrasa a resposta da interaction
        await ctx.defer()

        requester = ctx.author.nick
        decode = spotify.decode_url(search)
        waiting_time = self.get_waiting_time()

        # Verifica se a pesquisa é referente a uma playlist
        if is_playlist(search, decode):
            # Verifica se já existe uma pesquisa sendo feita
            if self.playlist_loop and not self.playlist_loop.done():
                await ctx.reply('Ainda estou processando a última playlist enviada! '
                                'Tente novamente em alguns segundos!', ephemeral=True, delete_after=5)
                return

            # Faz a pesquisa em segundo plano
            self.playlist_loop = self.bot.loop.create_task(self.playlist_lookup(search, requester, decode=decode))

            await ctx.reply('Playlist adicionada a fila! \n'
                            f'Tempo para execução: `{waiting_time}`', ephemeral=True, delete_after=5)
        # Do contrário considera como uma música apenas
        else:
            # Se decode for truthy a pesquisa é feita no Spotify
            if decode:
                track = await spotify.SpotifyTrack.search(query=search, return_first=True, type=decode['type'])
            # Do contrário faz a pesquisa no YouTube
            else:
                track = await wavelink.YouTubeTrack.search(query=search, return_first=True)

            # Cria um atributo para referenciar o solicitante do comando, usado para logar no arquivo de log mais tarde
            track.requester = requester

            # Adiciona música na fila e atualiza o queue_view
            await self.queue.put_wait(track)
            await self.queue_view.refresh()

            await ctx.reply(f'{track.title} adicionado a fila! \n'
                            f'Tempo para execução: `{waiting_time}`', ephemeral=True, delete_after=5)

        # Caso o bot não esteja tocando inicia a reprodução
        if not self.vc.is_playing() and not self.vc.is_paused():
            await self.play_song()

    # Faz a pesquisa de playlists
    async def playlist_lookup(self, search, requester, decode=None):
        if decode:
            async for track in spotify.SpotifyTrack.iterator(query=search, type=decode['type']):
                track.requester = requester

                await self.queue.put_wait(track)
                await self.queue_view.refresh()
        else:
            tracks = await wavelink.YouTubePlaylist.search(query=search)

            for track in tracks.tracks:
                track.requester = requester

                await self.queue.put_wait(track)
                await self.queue_view.refresh()

    # Desconecta o bot
    async def leave(self, leave: bool = True):
        print('leave')
        if self.playlist_loop and not self.playlist_loop.done():
            self.playlist_loop.cancel()

        if self.queue:
            self.queue.clear()

        if leave and self.vc.is_connected():
            await self.vc.disconnect()

        await self.display_view.reset()
        await self.queue_view.reset()

        self.vc = None
        self.queue = None
        self.playlist_loop = None

    async def play_song(self, track: wavelink.YouTubeTrack = None):
        if not track:
            if self.queue.is_empty:
                await self.display_view.reset()

            try:
                track = await asyncio.wait_for(self.queue.get_wait(), timeout=180)
            except asyncio.TimeoutError:
                await self.leave(True)

        await self.vc.play(track, pause=False)
        await self.display_view.refresh(track)
        await self.queue_view.refresh()

        requester = track.requester if hasattr(track, 'requester') else None
        self.logger.error(f'{track.title} requested by {requester}')

    async def pause(self, interaction: discord.Interaction):
        if not self.vc.is_paused():
            await self.vc.pause()
            message = 'Pediu pra parar parou!'
        else:
            message = 'Já estou pausado!'

        await interaction.response.send_message(message, ephemeral=True, delete_after=5)

    async def resume(self, interaction: discord.Interaction):
        if self.vc.is_paused():
            await self.vc.resume()
            message = 'Pediu pra voltar voltou!'
        else:
            message = 'Não estou pausado!'

        await interaction.response.send_message(message, ephemeral=True, delete_after=5)

    async def skip(self, interaction: discord.Interaction):
        await self.vc.stop()
        await interaction.response.send_message('Música skipada!', ephemeral=True, delete_after=5)

    async def stop(self, interaction: discord.Interaction, leave: bool):
        message = 'Saindo!' if leave else 'Parado!'
        await interaction.response.send_message(message, ephemeral=True, delete_after=5)
        await self.leave(leave)

    async def loop(self, interaction: discord.Interaction):
        status = 'Pausado' if self.vc.is_paused() else 'Tocando'
        embed = interaction.message.embeds[0]

        if self.loop_flag:
            self.loop_flag = False
            embed.set_footer(text=status)
            message = 'Loop desativado!'
        else:
            self.loop_flag = True
            embed.set_footer(text=f'{status} | Loop ativado')
            message = 'Música atual em loop!'

        await interaction.response.send_message(message, ephemeral=True, delete_after=5)
        await self.display_view.message.edit(embed=embed)

    async def shuffle(self, interaction: discord.Interaction):
        temp_queue = [track for track in self.queue]
        random.shuffle(temp_queue)

        self.queue.clear()

        for track in temp_queue:
            await self.queue.put_wait(track)

        await self.queue_view.refresh()
        await interaction.response.send_message('Fila embaralhada!', ephemeral=True, delete_after=5)

    # Retorna tempo de fila
    def get_waiting_time(self):
        seconds = self.vc.position - self.queue.duration
        return format_time(seconds)

    @commands.hybrid_command(name='play', description='Pesquisa por uma música e adiciona na fila')
    @app_commands.rename(search='pesquisa')
    @app_commands.describe(search='URL ou palavras chaves de busca')
    async def _play(self, ctx: commands.Context, search: str):
        await self.play(ctx, search)

    @commands.hybrid_command(name='pause', description='Pausa o bot')
    @commands.before_invoke(bot_is_ready)
    async def _pause(self, ctx: commands.Context):
        await self.pause(ctx.interaction)

    @commands.hybrid_command(name='resume', description='Despausa o bot')
    @commands.before_invoke(bot_is_ready)
    async def _resume(self, ctx: commands.Context):
        await self.resume(ctx.interaction)

    @commands.hybrid_command(name='skip', description='Pula a música atual')
    @commands.before_invoke(bot_is_ready)
    async def _skip(self, ctx: commands.Context):
        await self.skip(ctx.interaction)

    @commands.hybrid_command(name='stop', description='Para a execução e limpa a fila de músicas')
    @commands.before_invoke(bot_is_ready)
    @app_commands.rename(leave='sair')
    @app_commands.describe(leave='Desconectar bot do canal')
    async def _stop(self, ctx: commands.Context, leave: bool = False):
        await self.stop(ctx.interaction, leave)

    @commands.hybrid_command(name='shuffle', description='Embaralha a fila de músicas')
    @commands.before_invoke(bot_is_ready)
    async def _shuffle(self, ctx: commands.Context):
        await self.shuffle(ctx.interaction)

    @commands.hybrid_command(name='put-at', description='Coloca uma música na ordem desejada')
    @commands.before_invoke(bot_is_ready)
    @app_commands.rename(index='índice', new_index='novo_índice')
    @app_commands.describe(index='Índice atual', new_index='Novo índice')
    async def _put_at(self, ctx: commands.Context, index: int, new_index: int):
        interaction = ctx.interaction

        index -= 1
        new_index -= 1

        try:
            track = self.vc.queue[index]
        except IndexError:
            await interaction.response.send_message('Índice atual não existe!', ephemeral=True, delete_after=5)
            return

        if index > self.vc.queue.count:
            await interaction.response.send_message('Novo índice não existe!', ephemeral=True, delete_after=5)
        else:
            del self.vc.queue[index]

            self.vc.queue.put_at_index(new_index, track)
            await interaction.response.send_message(f'{track.title} mudado para a posição {new_index + 1} na fila!',
                                                    ephemeral=True, delete_after=5)

    @commands.hybrid_command(name='history', description='Histórico de músicas tocadas')
    async def history(self, ctx: commands.Context):
        interaction = ctx.interaction

        root = os.path.join(ROOT, 'logs')
        options = []

        for file in os.listdir(root):
            options.append(file)

        if len(options) == 0:
            interaction.response.send_message('Não há nenhum arquivo de log no sistema', delete_after=5)
            return

        # root = os.path.join(ROOT, 'logs')
        # select = discord.ui.Select(placeholder='Selecione a data de referência')
        #
        # for file in os.listdir(root):
        #     select.add_option(label=file)
        #
        # if len(select.options) == 0:
        #     interaction.response.send_message('Não há nenhum arquivo de log no sistema', delete_after=5)
        #     return
        #
        # async def callback(interaction: discord.Interaction):
        #     selection = select.values[0]
        #     fullname = os.path.join(root, selection)
        #
        #     with open(fullname, 'r') as f:
        #         content = f.read()
        #
        #     if not content:
        #         content = 'Não há logs nesse arquivo.'
        #
        #     content = f'```{content}```'
        #
        #     print(await interaction.original_response())
        #
        #     await interaction.response.send_message(content, delete_after=120)
        #
        # select.callback = callback
        #
        # view = discord.ui.View()
        # view.add_item(select)

        view = HistoryView(options)
        await interaction.response.send_message(view=view, delete_after=300)


class HistoryView(discord.ui.View):
    def __init__(self, options):
        super().__init__(timeout=300)

        self.root = os.path.join(ROOT, 'logs')
        self.response: discord.InteractionMessage = None

        for option in options:
            self.select_history.add_option(label=option)

    async def on_timeout(self):
        if self.response:
            await self.response.delete()

    # REVISAR
    @discord.ui.select(cls=discord.ui.Select, placeholder='Selecione a data de referência')
    async def select_history(self, interaction: discord.Interaction, select: discord.ui.Select):
        selection = select.values[0]
        fullname = os.path.join(self.root, selection)

        with open(fullname, 'r') as f:
            content = f.read()

        if not content:
            content = 'Não há logs nesse arquivo.'

        content = f'```{content}```'

        if self.response:
            await interaction.response.defer()
            await self.response.edit(content=content)
        else:
            await interaction.response.send_message(content)
            self.response = await interaction.original_response()


# noinspection PyTypeChecker
class QueueView(discord.ui.View):
    def __init__(self, message: discord.Message, music_cog: Music):
        super().__init__(timeout=None)

        self.message = message
        self.music_cog = music_cog

        self.page = 0
        self.max_page = 0
        self.previous.disabled = True
        self.next.disabled = True

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user in self.music_cog.vc.channel.members:
            return True

        await interaction.response.send_message('Entre no canal primeiro!', delete_after=5)

    @classmethod
    async def create_view(cls, message, music_cog):
        self = cls(message, music_cog)
        await self.reset()
        return self

    @discord.ui.button(emoji='◀', style=discord.ButtonStyle.blurple, custom_id='queue:previous')
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self.next.disabled = False

        if self.page == 0:
            button.disabled = True

        await interaction.response.defer()
        await self.refresh()

    @discord.ui.button(emoji='▶', style=discord.ButtonStyle.blurple, custom_id='queue:next')
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self.previous.disabled = False

        if self.page == self.max_page:
            button.disabled = True

        await interaction.response.defer()
        await self.refresh()

    async def refresh(self):
        if self.music_cog.queue.count == 0:
            await self.reset()
            return

        self.max_page = floor(self.music_cog.queue.count / 25) if self.music_cog.queue.count else 0
        self.previous.disabled = True if self.page == 0 else False
        self.next.disabled = True if self.max_page == 0 else False

        if self.page < 0 or self.page > self.max_page:
            return

        index = 0 if self.page == 0 else self.page * 25
        embed = discord.Embed(title=f'{self.music_cog.queue.count} música(s) na fila', colour=discord.Colour.gold())

        if not self.music_cog.queue.is_empty:
            count = 0

            while count < 25:
                try:
                    track: wavelink.YouTubeTrack = self.music_cog.queue[index]

                    embed.add_field(name=index + 1, value=track.title, inline=False)
                    count += 1
                except IndexError:
                    break

                index += 1

        await self.message.edit(content=None, embed=embed, view=self)

    async def reset(self):
        embed = discord.Embed(title=f'Não há músicas na fila', colour=discord.Colour.dark_gold())

        self.page = 0
        self.previous.disabled = True
        self.next.disabled = True

        await self.message.edit(content=None, embed=embed, view=None)


class DisplayView(discord.ui.View):
    def __init__(self, message: discord.Message, music_cog: Music):
        super().__init__(timeout=None)

        self.message = message
        self.music_cog = music_cog

        self.no_music_image = os.path.join(ROOT, 'assets', 'monki.jpg')

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user in self.music_cog.vc.channel.members:
            return True

        await interaction.response.send_message('Entre no canal primeiro!', delete_after=5)

    @classmethod
    async def create_view(cls, message, music_cog):
        self = cls(message, music_cog)
        await self.reset()
        return self

    @discord.ui.button(label='Pausar', emoji='⏸', style=discord.ButtonStyle.gray, custom_id='display:play_pause')
    async def play_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]

        if self.music_cog.vc.is_paused():
            embed.set_footer(text='Tocando')
            embed.colour = discord.Colour.green()

            await self.music_cog.resume(interaction)

            button.label = 'Pausar'
            button.emoji = '▶'
        else:
            embed.set_footer(text='Pausado')
            embed.colour = discord.Colour.orange()

            await self.music_cog.pause(interaction)

            button.label = 'Tocar'
            button.emoji = '⏸'

        await self.message.edit(content=None, embed=embed, view=self, attachments=[])

    @discord.ui.button(label='Próximo', emoji='⏭', style=discord.ButtonStyle.gray, custom_id='display:next')
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.music_cog.skip(interaction)

    @discord.ui.button(label='Parar', emoji='⏹', style=discord.ButtonStyle.gray, custom_id='display:stop')
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.music_cog.stop(interaction, leave=False)

    @discord.ui.button(label='Loop', emoji='🔁', style=discord.ButtonStyle.gray, custom_id='display:loop',)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.music_cog.loop(interaction)

    @discord.ui.button(label='Aleatório', emoji='🔀', style=discord.ButtonStyle.gray, custom_id='display:shuffle',)
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.music_cog.shuffle(interaction)

    async def refresh(self, track: wavelink.YouTubeTrack):
        embed = discord.Embed(title=track.title, colour=discord.Colour.green())
        embed.add_field(name='Artista', value=track.author)
        embed.add_field(name='Duração', value=format_time(track.duration))
        embed.add_field(name='URL', value=track.uri)
        embed.set_image(url=track.thumb)
        embed.set_footer(text='Tocando')

        for button in self.children:
            button.disabled = False

        await self.message.edit(content=None, embed=embed, view=self, attachments=[])

    async def reset(self):
        embed = discord.Embed(title='Não há músicas em reprodução',
                              description='Use /Play [Pesquisa] ou envie um link nesse canal',
                              colour=discord.Color.dark_green())
        embed.set_image(url='attachment://no_music.jpg')
        file = discord.File(self.no_music_image, filename='no_music.jpg')

        for button in self.children:
            button.disabled = True

        await self.message.edit(content=None, embed=embed, view=self, attachments=[file])


class SeekView(QueueView):
    def __init__(self, message: discord.Message, music_cog: Music):
        super().__init__(message, music_cog)


class Queue(wavelink.WaitQueue):
    def __init__(self):
        super().__init__()

        self._duration = 0

    @property
    def duration(self):
        return self._duration

    @duration.setter
    def duration(self, value):
        self._duration = value

    async def put_wait(self, item):
        await super().put_wait(item)
        self._duration += item.duration

    def clear(self):
        super().clear()
        self._duration = 0


class Track(wavelink.Track):
    pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
