import wavelink
import discord
import os
import asyncio
import random
import json
from utils.functions import format_time, is_url
from math import floor
from _asyncio import Task
from wavelink.ext import spotify
from discord import app_commands
from discord.ext import commands

MUSIC_CHANNEL_ID = 999002277186637854
ROOT = os.getcwd()


# noinspection PyTypeChecker
class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        client_id = os.getenv('SPOTIFY_ID')
        client_secret = os.getenv('SPOTIFY_SECRET')

        self.spotify_client = spotify.SpotifyClient(client_id=client_id, client_secret=client_secret)
        self.queue_duration = 0
        self.persistent_messages = []
        self.ready = False
        self.loop_flag = False

        self.display_view: DisplayView = None
        self.queue_view: QueueView = None
        self.vc: wavelink.Player = None
        self.spotify_loop: Task = None

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
    async def on_wavelink_track_end(self, player: wavelink.Player, track: wavelink.Track, reason):
        if self.loop_flag:
            await self.vc.play(track)
        else:
            self.queue_duration -= track.duration

            await self.play_song()
            await self.queue_view.refresh()

    # Disparado ao bot se conectar a api do discord
    @commands.Cog.listener()
    async def on_ready(self):
        if not self.ready:
            display_message, queue_message = await self.setup_views()

            self.display_view = await DisplayView.create_view(display_message, self)
            self.queue_view = await QueueView.create_view(queue_message)

            self.bot.add_view(self.display_view, message_id=display_message.id)
            self.bot.add_view(self.queue_view, message_id=queue_message.id)
            self.ready = True

    # Disparado ao enviar uma mensagem em um canal de texto
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        check = [not self.ready, message.channel.id != MUSIC_CHANNEL_ID, message.id in self.persistent_messages]

        # Verifica checks
        if any(check):
            return

        # Verifica se o conteúdo enviado é um link
        if is_url(message.content):
            ctx = await self.bot.get_context(message)
            await self.play(ctx, message.content)

        # Deleta toda e qualquer mensagem após isso
        await message.delete(delay=10)

    # Prepara views dinâmicos e retorna as mensagens usadas como container
    async def setup_views(self):
        json_path = os.path.join(ROOT, 'config.json')
        channel = self.bot.get_channel(MUSIC_CHANNEL_ID)
        messages = []

        with open(json_path, 'r') as f:
            config: dict = json.load(f)

        ids = [value for value in config.values()]

        for message_id in ids:
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                message = await channel.send('...')

            messages.append(message)
            self.persistent_messages.append(message.id)

        await channel.purge(check=lambda m: m.id not in self.persistent_messages)

        config = {
            'display_message_id': messages[0].id,
            'queue_message_id': messages[1].id,
        }

        with open(json_path, 'w') as f:
            f.write(json.dumps(config, indent=2))

        return messages

    # Conecta node ao lavalink
    async def connect_nodes(self):
        await self.bot.wait_until_ready()

        host = os.getenv('LAVALINK_HOST')
        password = os.getenv('LAVALINK_PASSWORD')

        await wavelink.NodePool.create_node(bot=self.bot, host=host, port=443, password=password, https=True,
                                            identifier='main', spotify_client=self.spotify_client)

    # Verifica se o bot está conectado
    async def bot_is_ready(self, ctx: commands.Context):
        if self.vc and self.vc.is_connected():
            return True

        await ctx.interaction.response.send_message('Não estou conectado a nenhum canal!', ephemeral=True)

    async def join(self, user: discord.Member):
        if not self.vc and user.voice:
            self.vc = await user.voice.channel.connect(cls=wavelink.Player)
            self.queue_view.queue = self.vc.queue
        elif self.vc and self.vc.channel != user.voice.channel:
            await self.vc.move_to(user.voice.channel)

        return True if self.vc else False

    async def play(self, ctx: commands.Context, search: str):
        if not await self.join(ctx.author):
            await ctx.reply('Entre na call primeiro, corno! :monkey_face::raised_back_of_hand:', ephemeral=True)
        else:
            decode = spotify.decode_url(search)
            playlist_duration = 0
            playlist = False

            await ctx.defer()
            waiting_time = self.get_waiting_time()

            # Se retornar qualquer coisa é spotify
            if decode:
                # Se for playlist ou album
                if decode['type'] in [spotify.SpotifySearchType.playlist, spotify.SpotifySearchType.album]:
                    print('Spotify Playlist / Album')

                    # Verifica se ainda há um processo em andamento
                    if self.spotify_loop and not self.spotify_loop.done():
                        await ctx.reply('Ainda estou processando a última playlist enviada! '
                                        'Tente novamente em alguns segundos!', ephemeral=True)
                        return

                    # Faz o loop pela playlist do spotify em segundo plano
                    self.spotify_loop = self.bot.loop.create_task(self.spotify_lookup(search, decode))
                    playlist = True

                    await ctx.reply('Playlist adicionada a fila! \n'
                                    f'Tempo para execução: `{waiting_time}`', ephemeral=True)
                    # Se for uma música
                else:
                    print('Spotify Song')
                    track = await spotify.SpotifyTrack.search(query=decode['id'], return_first=True,
                                                              type=decode['type'])
                    await self.vc.queue.put_wait(track)

                    await ctx.reply(f'{track.title} adicionado a fila! \n'
                                    f'Tempo para execução: `{waiting_time}`', ephemeral=True)
                    self.queue_duration += track.duration
            # Se retornar None é YT
            else:
                if 'https://youtube.com/playlist?list=' in search:
                    print('YouTube Playlist')
                    tracks = await wavelink.YouTubePlaylist.search(query=search)

                    for track in tracks.tracks:
                        await self.vc.queue.put_wait(track)
                        playlist_duration += track.duration

                    await ctx.reply(f'{tracks.name} adicionado a fila! \n'
                                    f'Tempo para execução: `{waiting_time}`', ephemeral=True)
                    self.queue_duration += playlist_duration
                else:
                    print('YouTube Song')
                    track = await wavelink.YouTubeTrack.search(query=search, return_first=True)
                    await self.vc.queue.put_wait(track)

                    await ctx.reply(f'{track.title} adicionado a fila! \n'
                                    f'Tempo para execução: `{waiting_time}`', ephemeral=True)
                    self.queue_duration += track.duration

            if not self.vc.is_playing() and not self.vc.is_paused():
                await self.play_song()
            elif not playlist:
                await self.queue_view.refresh()

    async def spotify_lookup(self, search, decode):
        async for track in spotify.SpotifyTrack.iterator(query=search, type=decode['type']):
            await self.vc.queue.put_wait(track)
            self.queue_duration += track.duration

        await self.queue_view.refresh()

    async def play_song(self):
        try:
            next_song = await asyncio.wait_for(self.vc.queue.get_wait(), timeout=180)
        except asyncio.TimeoutError:
            await self.vc.disconnect()
            await self.display_view.reset()
            await self.queue_view.reset()

            self.vc = None
        else:
            await self.vc.play(next_song)
            await self.display_view.refresh(next_song)
            await self.queue_view.refresh()

    async def pause(self, interaction: discord.Interaction):
        if not self.vc.is_paused():
            await self.vc.pause()
            await interaction.response.send_message('Pediu pra parar parou!', ephemeral=True)
        else:
            await interaction.response.send_message('Já estou pausado!', ephemeral=True)

    async def resume(self, interaction: discord.Interaction):
        if self.vc.is_paused():
            await self.vc.resume()
            await interaction.response.send_message('Pediu pra voltar voltou!', ephemeral=True)
        else:
            await interaction.response.send_message('Não estou pausado!', ephemeral=True)

    async def skip(self, interaction: discord.Interaction):
        await self.vc.stop()
        await self.vc.resume()
        await interaction.response.send_message('Música skipada!', ephemeral=True)

    async def previous(self, interaction: discord.Interaction):
        track = self.vc.queue.history[0]

        if track:
            await self.vc.play(track)
            await interaction.response.send_message('Música anterior selecionada!', ephemeral=True)
        else:
            await interaction.response.send_message('Não há nenhuma música anterior!', ephemeral=True)

    async def stop(self, interaction: discord.Interaction, leave: bool):
        self.vc.queue.clear()
        self.queue_duration = 0

        await self.vc.stop()
        await self.display_view.reset()
        await self.queue_view.reset()

        if leave:
            await self.vc.disconnect()
            self.vc = None

            await interaction.response.send_message('Saindo!', ephemeral=True)
        else:
            await interaction.response.send_message('Parado!', ephemeral=True)

    async def loop(self, interaction: discord.Interaction):
        if self.loop_flag:
            self.loop_flag = False
            await interaction.response.send_message('Loop desativado!', ephemeral=True)
        else:
            self.loop_flag = True
            await interaction.response.send_message('Música atual em loop!', ephemeral=True)

    async def shuffle(self, interaction: discord.Interaction):
        temp_queue = [track for track in self.vc.queue]
        random.shuffle(temp_queue)

        self.vc.queue.clear()

        for track in temp_queue:
            await self.vc.queue.put_wait(track)

        await self.queue_view.refresh()
        await interaction.response.send_message('Fila embaralhada!', ephemeral=True)

    # Retorna tempo de fila
    def get_waiting_time(self):
        seconds = self.vc.position + self.queue_duration
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
        interaction: discord.Interaction = ctx.interaction

        index -= 1
        new_index -= 1

        try:
            track = self.vc.queue[index]
        except IndexError:
            await interaction.response.send_message('Índice atual não existe!', ephemeral=True)
        else:
            if index > self.vc.queue.count:
                await interaction.response.send_message('Novo índice não existe!', ephemeral=True)
            else:
                del self.vc.queue[index]

                self.vc.queue.put_at_index(new_index, track)
                await interaction.response.send_message(f'{track.title} mudado para a posição {new_index + 1} na fila!',
                                                        ephemeral=True)


# noinspection PyTypeChecker
class QueueView(discord.ui.View):
    def __init__(self, message: discord.Message):
        super().__init__(timeout=None)

        self.message = message
        self.queue: wavelink.WaitQueue = None

        self.page = 0
        self.max_page = 0

        # self.previous_button: discord.Button = self.children[0]
        # self.next_button: discord.Button = self.children[1]
        #
        # self.previous_button.disabled = True
        # self.next_button.disabled = True
        self.previous.disabled = True
        self.next.disabled = True

    @classmethod
    async def create_view(cls, message):
        self = cls(message)
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
        if self.queue.count == 0:
            await self.reset()
            return

        self.max_page = floor(self.queue.count / 25) if self.queue.count else 0
        self.previous.disabled = True if self.page == 0 else False
        self.next.disabled = True if self.max_page == 0 else False

        if self.page < 0 or self.page > self.max_page:
            return

        index = 0 if self.page == 0 else self.page * 25
        embed = self.message.embeds[0]

        embed.title = f'{self.queue.count} música(s) na fila'
        embed.clear_fields()

        if not self.queue.is_empty:
            count = 0

            while count < 25:
                try:
                    track: wavelink.YouTubeTrack = self.queue[index]

                    embed.add_field(name=index + 1, value=track.title, inline=False)
                    count += 1
                except IndexError:
                    break

                index += 1

        await self.message.edit(content=None, embed=embed, view=self)

    async def reset(self):
        embed = discord.Embed(title=f'Não há músicas na fila')

        self.page = 0
        self.previous.disabled = True
        self.next.disabled = True

        await self.message.edit(content=None, embed=embed, view=None)


class DisplayView(discord.ui.View):
    def __init__(self, message: discord.Message, music_cog: Music):
        super().__init__(timeout=None)

        self.no_music_image = os.path.join(ROOT, 'assets', 'monki.jpg')
        self.message = message
        self.music_cog = music_cog

    @classmethod
    async def create_view(cls, message, music_cog):
        self = cls(message, music_cog)
        await self.reset()
        return self

    @discord.ui.button(label='Tocar/Pausar', emoji='⏯', style=discord.ButtonStyle.gray, custom_id='display:play_pause')
    async def play_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]

        if self.music_cog.vc.is_paused():
            embed.set_footer(text='Tocando...')
            await self.music_cog.resume(interaction)
        else:
            embed.set_footer(text='Pausado...')
            await self.music_cog.pause(interaction)

        await self.message.edit(content=None, embed=embed, view=self, attachments=[])

    @discord.ui.button(label='Próximo', emoji='⏭', style=discord.ButtonStyle.gray, custom_id='display:next')
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.music_cog.skip(interaction)

    @discord.ui.button(label='Anterior', emoji='⏮', style=discord.ButtonStyle.gray, custom_id='display:previous')
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.music_cog.previous(interaction)

    @discord.ui.button(label='Parar', emoji='⏹', style=discord.ButtonStyle.gray, custom_id='display:stop')
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.music_cog.stop(interaction, leave=False)

    @discord.ui.button(label='Loop', emoji='🔁', style=discord.ButtonStyle.gray, custom_id='display:loop',
                       row=1)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.music_cog.loop(interaction)

    @discord.ui.button(label='Aleatório', emoji='🔀', style=discord.ButtonStyle.gray, custom_id='display:shuffle',
                       row=1)
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.music_cog.shuffle(interaction)

    async def refresh(self, track: wavelink.YouTubeTrack):
        embed = discord.Embed(title=track.title)
        embed.add_field(name='Artista', value=track.author)
        embed.add_field(name='Duração', value=format_time(track.duration))
        embed.add_field(name='URL', value=track.uri)
        embed.set_image(url=track.thumb)
        embed.set_footer(text='Tocando...')

        for button in self.children:
            button.disabled = False

        await self.message.edit(content=None, embed=embed, view=self, attachments=[])

    async def reset(self):
        embed = discord.Embed(title='Não há músicas em reprodução', description='Use /Play [Pesquisa] ou envie um link'
                                                                                ' nesse canal')
        embed.set_image(url='attachment://no_music.jpg')
        file = discord.File(self.no_music_image, filename='no_music.jpg')

        for button in self.children:
            button.disabled = True

        await self.message.edit(content=None, embed=embed, view=self, attachments=[file])


# class SeekView(discord.ui.View, QueueView):
#     def __init__(self):
#         super().__init__()
#
#
# class Queue(wavelink.WaitQueue):
#     def __init__(self):
#         super().__init__()
#
#         self.duration = None


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
