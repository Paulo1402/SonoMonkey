"""
Cog responsável por encapsular recursos referente a funcionalidade de reprodução de músicas.

Comandos foram decorados usando "@commands.hybrid_command" para poder habilitar o uso do decorator
"@commands.before_invoke" e executar uma função antes do comando para verificar se o bot está no canal de voz ou não.
Esse approach foi necessário porque na época o framework possuía algum tipo de limitação que impedia o uso desse
decorator quando o comando fosse criado usando "@app_commands.command".
(VERIFICAR SE HOJE EM DIA O FRAMEWORK CORRIGIU ESSE PROBLEMA E/OU ADICIONOU ALGO PARA CONTORNAR)

Usar o decorator "@commands.hybrid_command" faz com que ambos os comandos chamados usando a "/" (app_commands) tanto
comandos usando o prefixo "$" (usado para comandos de debug e config na cog adm) funcionassem por iguais, mas para
se adequar ao novo padrão de comandos do discord decidi por bloquear a execução usando prefixos.
Usei o hook "cog_check" para bloquear todos os comandos executados usando o prefixo. Esse hook é disparado antes de
qualquer comando ser executado e deve retornar um boolean para permitir ou negar a execução do mesmo.
"""
from __future__ import annotations

import os
import json
import random
import logging
import asyncio
import re
from datetime import datetime, date
from math import floor

import discord
import wavelink
from wavelink.ext import spotify
from discord import app_commands
from discord.ext import commands

from utils import *


class GuildPool:
    """Pool para armazenar GuildHandlers."""

    def __init__(self):
        self._pool: dict[int, GuildHandler] = {}
        
    def add_handler(self, handler: GuildHandler):
        """
        Adiciona um handler a pool.

        :param handler: Objeto handler
        """
        self._pool[handler.guild.id] = handler

    def get_handler(self, guild_id: int) -> GuildHandler | None:
        """
        Retorna handler.

        :param guild_id: Id da guild
        :return: Caso existir retorna Handler da guild, do contrário retorna None
        """
        try:
            guild_handler = self._pool[guild_id]
        except KeyError:
            guild_handler = None

        return guild_handler
    
    def remove_handler(self, guild_id: int):
        """
        Remove handler da pool.

        :param guild_id: Id da guild
        """
        if guild_id in self._pool.keys():
            del self._pool[guild_id]


class GuildHandler:
    """Handler para armazenar dados da guild."""

    def __init__(self, guild: discord.Guild, music_cog: Music):
        self.guild = guild
        self.music_cog = music_cog

        self.display_view: DisplayView | None = None
        self.queue_view: QueueView | None = None
        self.views_channel_id: int | None = None
        self.reset: bool = False

        self.playlist_loop: asyncio.Task | None = None
        self.logger: Logger = Logger(guild.id)

    @property
    def player(self) -> Player | None:
        """
        Player da guild ou None.

        :return: Retorna player caso o bot esteja conectado a algum canal de voz, do contrário retorna None
        """
        return self.guild.voice_client

    async def setup_channel(self):
        """Configura views e recursos necessários."""
        ignoring_messages = []

        # Retorna dicionário com dados da guild
        guild = self.music_cog.config_proxy.get_guild_data(self.guild.id)

        # Retorna objeto do canal
        channel = self.music_cog.bot.get_channel(guild['channel_id'])

        # Caso o canal não exista, cria um
        if not channel:
            welcoming_message = await self._create_channel()
            channel = welcoming_message.channel

            ignoring_messages.append(welcoming_message)

        # Retorna mensagens usadas como containers para os menus interativos
        display_message = await self._check_message(channel, guild['display_message_id'])
        queue_message = await self._check_message(channel, guild['queue_message_id'])

        ignoring_messages.append(display_message)
        ignoring_messages.append(queue_message)

        # Deleta qualquer mensagem que não esteja na lista de mensagens permanentes
        await channel.purge(check=lambda m: m not in ignoring_messages)

        # Cria instancias das views e salva id do canal
        self.display_view = await DisplayView.create_view(display_message, self.music_cog, self)
        self.queue_view = await QueueView.create_view(queue_message, self)
        self.views_channel_id = channel.id

        # Adiciona views ao bot
        self.music_cog.bot.add_view(self.display_view, message_id=display_message.id)
        self.music_cog.bot.add_view(self.queue_view, message_id=queue_message.id)

        # Atualiza informações da guild (Esse dicionário é o mesmo salvo no proxy, portanto ambos são alterados)
        guild['guild_name'] = self.guild.name
        guild['channel_id'] = channel.id
        guild['display_message_id'] = display_message.id
        guild['queue_message_id'] = queue_message.id

    async def check_channel(self, ctx: commands.Context):
        """Checa se o canal exclusivo existe."""
        channel = self.music_cog.bot.get_channel(self.views_channel_id)

        # Se não existe recria-a
        if not channel:
            await ctx.defer()
            await self.setup_channel()
            self.music_cog.config_proxy.save()

    @staticmethod
    async def _check_message(channel: discord.TextChannel, message_id: int) -> discord.Message:
        """
        Verifica se a id da mensagem é válida, se não for devolve uma nova mensagem.
        
        :param channel: Canal da mensagem
        :param message_id: Id da mensagem
        :return: Objeto referente a mensagem
        """

        try:
            message = await channel.fetch_message(message_id)
        except (discord.NotFound, discord.HTTPException):
            message = await channel.send('...')

        return message

    async def _create_channel(self) -> discord.Message:
        """
        Cria canal de texto para uso interno.

        :return: Mensagem de Boas-vindas
        """
        name = self.music_cog.bot.user.name.lower()
        topic = ":green_circle: Chat de músicas e comandos! Envie um link do Spotify/YouTube ou use o comando " \
                "/play [PESQUISA] para pesquisar por palavras chaves :musical_note:"

        channel = await self.guild.create_text_channel(name=name, topic=topic)
        message = await channel.send('Fala aí Galera :heart_hands:! Criei esse canal para configurar '
                                     'meus menus interativos!\n'
                                     'Aqui vocês podem mandar links diretamente no chat sem a necessidade de usar '
                                     'o comando "/play" :tada::hear_no_evil:.', delete_after=300)

        return message


class ConfigProxy:
    """Proxy para manipular configurações em memória."""

    def __init__(self):
        self._config_path = os.path.join(ROOT, 'config.json')
        self.config: dict | None = None
        self.guilds: dict[str, dict] | None = None

        # Cria json caso não exista
        if not os.path.exists(self._config_path):
            self.config = {
                "guilds": {}
            }

            self.save()

        self.load()

    def save(self):
        """Salva as alterações no arquivo json."""
        with open(self._config_path, 'w', encoding='utf8') as f:
            f.write(json.dumps(self.config, indent=2))

    def load(self):
        """Carrega dados armazenadas no arquivo json."""
        with open(self._config_path, 'r', encoding='utf8') as f:
            self.config = json.load(f)
            self.guilds = self.config['guilds']

    def get_guild_data(self, guild_id: int) -> dict[str, str | int] | None:
        """
        Retorna dados da guild.

        :param guild_id: Id da guild
        :return: Dicionário com dados da guild.
        KEYS: "guild_name", "channel_id", "display_message_id", "queue_message_id"
        """
        if str(guild_id) not in self.guilds:
            self._new_guild(guild_id)

        guild = self.guilds[str(guild_id)]

        return guild

    def add_guild(self, guild_id: int, data: dict):
        """
        Cria guild.

        :param guild_id: Id da guild
        :param data: Dados da guild
        """
        self.guilds[str(guild_id)] = data

    def remove_guild(self, guild_id: int):
        """
        Remove guild.

        :param guild_id: Id da guild
        """
        if str(guild_id) in self.guilds:
            del self.guilds[str(guild_id)]

    def _new_guild(self, guild_id: int):
        """
        Cria guild com dados temporários.

        :param guild_id: Id da guild
        """
        data = {
            "guild_name": None,
            "channel_id": None,
            "display_message_id": None,
            "queue_message_id": None
        }

        self.add_guild(guild_id, data)


# noinspection PyCallingNonCallable
class Music(commands.Cog):
    """Cog para recursos de músicas."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self.guild_pool: GuildPool = GuildPool()
        self.config_proxy: ConfigProxy = ConfigProxy()
        self.views_channels: list[int] = []
        
        self.spotify_support = False
        self.ready = False

        bot.loop.create_task(self.connect_nodes())

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, node: wavelink.Node):
        """Disparado ao node se conectar corretamente ao lavalink."""
        print(f'Node: <{node.id}> is ready!')

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEventPayload):
        """Disparado ao acabar uma música."""
        if payload.reason == 'REPLACED':
            return

        handler = self.guild_pool.get_handler(payload.player.guild.id)

        # Essa flag vai garantir que o método não seja chamado quando self.reset() for chamado
        if not handler.reset:
            await self.play_song(handler)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, _, after: discord.VoiceState):
        """Disparado ao ter uma alteração em algum canal de voz."""
        handler = self.guild_pool.get_handler(member.guild.id)

        # Retorna caso o bot não esteja conectado
        if not handler.player:
            return

        # Caso todos saiam do canal ou o bot seja desconectado manualmente, desconecta o bot
        if len(handler.player.channel.members) == 1 or \
                (member.display_name == self.bot.user.name and not after.channel):
            await self.reset(handler, leave=True)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """
        Disparado ao bot se juntar a um novo server.
        Realiza setup no novo server e salva configurações.

        :param guild: Objeto de guild
        """
        handler = GuildHandler(guild, self)
        await handler.setup_channel()

        self.guild_pool.add_handler(handler)
        self.config_proxy.save()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """
        Disparado ao bot sair de um server.
        Remove dados do server e salva configurações.

        :param guild: Objeto de guild
        """
        self.guild_pool.remove_handler(guild.id)

        # self.config_proxy.remove_guild(guild.id)
        # self.config_proxy.save()
        
    @commands.Cog.listener()
    async def on_ready(self):
        """Disparado ao bot se conectar a api do discord."""

        # Garante que esse método seja executado apenas uma vez
        if self.ready:
            return

        # Salva handlers na memória
        for guild in self.bot.guilds:
            handler = GuildHandler(guild, self)
            await handler.setup_channel()

            self.guild_pool.add_handler(handler)
            self.views_channels.append(handler.views_channel_id)

        self.config_proxy.save()
        self.ready = True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Disparado ao enviar uma mensagem em um canal de texto.
        Esse evento não é disparado ao usar slash commands.
        Usado para receber links diretamente do canal exclusivo do bot.

        :param message: Objeto de mensagem
        """

        # Retorna caso a mensagem seja disparada pelo bot ou em outro canal de texto
        if message.channel.id not in self.views_channels or message.author.id == self.bot.user.id:
            return

        # Verifica se o conteúdo enviado é um link suportado
        if is_url(message.content):
            ctx = await self.bot.get_context(message)

            if await self.parse_url(ctx, message.content):
                await self.play(ctx, message.content, check_url=False)

        # Deleta toda e qualquer mensagem após isso
        await message.delete(delay=5)

    async def connect_nodes(self):
        """Conecta nodes ao lavalink."""
        await self.bot.wait_until_ready()

        # Obtém dados sensíveis armazenados como variáveis de ambiente
        client_id = os.getenv('SPOTIFY_ID')
        client_secret = os.getenv('SPOTIFY_SECRET')
        uri = os.getenv('LAVALINK_HOST')
        password = os.getenv('LAVALINK_PASSWORD')

        spotify_client = None

        # Cria objeto spotify_client
        if client_id and client_secret:
            spotify_client = spotify.SpotifyClient(client_id=client_id, client_secret=client_secret)
            self.spotify_support = True

        # Verifica se a conexão é segura ou não (HTTPS/HTTP)
        secure = True if uri.startswith('https://') else False
        uri_parsed = re.sub(r'https?://', '', uri)

        # Cria node
        node = wavelink.Node(id='main', uri=uri_parsed, password=password, secure=secure)
        await wavelink.NodePool.connect(client=self.bot, nodes=[node], spotify=spotify_client)
        
    def cog_check(self, ctx: commands.Context) -> bool:
        """
        Verifica se o comando foi executado corretamente.

        Apenas comandos chamados usando "/" ou por interações com botões de views possuem o objeto "interaction".
        Em todos outros casos esse atributo retornará None.

        :param ctx: Objeto de contexto
        :return: True se o comando foi executado usando "/" ou False caso foi executado usando prefixos
        """
        return bool(ctx.interaction)
    
    async def bot_is_ready(self, ctx: commands.Context) -> bool:
        """
        Verifica se o bot está conectado

        :param ctx: Objeto context
        :return: True se o bot estiver conectado, do contrário False
        """
        handler = self.guild_pool.get_handler(ctx.guild.id)

        if handler.player:
            return True

        # noinspection PyUnresolvedReferences
        await ctx.interaction.response.send_message(
            'Não estou conectado a nenhum canal!',
            ephemeral=True,
            delete_after=5
        )

        return False

    async def parse_url(self, ctx: commands.Context, url: str) -> bool:
        """
        Checa se o conteúdo da mensagem é uma URL válida.

        :param ctx: Objeto de contexto
        :param url: URL para verificar
        :return: True se for uma URL suportada, do contrário False
        """
        supported_urls = SUPPORTED_URL_PATTERNS

        # Remove padrões de URL do Spotify caso não haja suporte
        if not self.spotify_support:
            supported_urls = list(filter(lambda x: 'spotify' not in x, supported_urls))

        if is_spotify_url(url):
            # Caso for uma URL do Spotify, mas não haja suporte
            if not self.spotify_support:
                await ctx.reply(
                    'Suporte para links do Spotify está desabilitado! :sob:',
                    ephemeral=True,
                    delete_after=5
                )
                return False
        # Caso não seja uma URL do YouTube
        elif not is_youtube_url(url):
            supported_urls = '\n'.join(supported_urls)

            await ctx.reply(
                'Esse link não é suportado monkey! :see_no_evil:\nEnvie apenas links do YouTube '
                f'{"e do Spotify " if self.spotify_support else ""}nesse padrão: \n`{supported_urls}`',
                ephemeral=True,
                delete_after=20
            )
            return False

        return True

    # noinspection PyTypeChecker
    async def join(self, ctx: commands.Context) -> bool:
        """
        Entra no canal do usuário caso esteja em um.

        :param ctx: Objeto de contexto
        :return: True se o bot conseguir se juntar ao canal, do contrário False
        """
        user = ctx.author

        if not user.voice:
            await ctx.reply('Entre na call primeiro, corno! :monkey_face::raised_back_of_hand:', ephemeral=True,
                            delete_after=5)

            return False

        handler = self.guild_pool.get_handler(user.guild.id)
        handler.reset = False

        player = handler.player
        channel = user.voice.channel

        if player:
            await player.move_to(channel)
        else:
            # Checa se o canal exclusivo existe
            await handler.check_channel(ctx)
            await channel.connect(cls=Player())

        return True

    async def play(self, ctx: commands.Context, search: str, check_url: bool = True):
        # Verifica se é uma URL válida
        if check_url and is_url(search):
            if not await self.parse_url(ctx, search):
                return

        # Verifica se o bot se juntou ao canal
        if not await self.join(ctx):
            return

        handler = self.guild_pool.get_handler(ctx.guild.id)
        player = handler.player

        requester = ctx.author.name
        waiting_time = self.get_waiting_time(player)
        spotify_decode = spotify.decode_url(search)

        if is_playlist(search, spotify_decode):
            # Verifica se já existe uma pesquisa sendo feita
            if handler.playlist_loop and not handler.playlist_loop.done():
                await ctx.reply(
                    'Ainda estou processando a última playlist enviada! Tente novamente em alguns segundos!',
                    ephemeral=True,
                    delete_after=5
                )
                return

            # Faz a pesquisa em segundo plano
            handler.playlist_loop = self.bot.loop.create_task(
                self.playlist_lookup(search, requester, handler, spotify_decode=spotify_decode)
            )

            await ctx.reply(
                'Estou adicionando a playlist na fila! Pode demorar algum tempo para todas as músicas '
                f'serem adicionadas! \nTempo para execução: `{waiting_time}`',
                ephemeral=True,
                delete_after=5
            )
        else:
            if spotify_decode:
                track = await spotify.SpotifyTrack.search(query=search, return_first=True)
            else:
                track = await wavelink.YouTubeTrack.search(search, return_first=True)

            # Cria um atributo para referenciar o solicitante do comando, usado para logar no arquivo de log mais tarde
            setattr(track, 'requester', requester)

            # Adiciona música na fila e atualiza o queue_view
            await player.queue.put_wait(track)
            await handler.queue_view.refresh()

            await ctx.reply(
                f'{track.title} adicionado a fila! \nTempo para execução: `{waiting_time}`',
                ephemeral=True,
                delete_after=5
            )

        # Caso o bot não esteja tocando inicia a música imediatamente
        if not player.is_playing() and not player.is_paused():
            await self.play_song(handler)

    # noinspection PyTypeChecker
    async def play_song(self, handler: GuildHandler):
        """
        Reproduz música e carrega views.

        :param handler: Handler referente
        """
        player = handler.player

        if player.queue.is_empty:
            await handler.display_view.reset()

        try:
            track = await asyncio.wait_for(player.queue.get_wait(), timeout=180)
        except asyncio.TimeoutError:
            await self.reset(handler, leave=True)
            return

        print(handler.guild.name, ' - ', track.title, ' - ', 'session_id:', player.current_node.session_id)

        # Converte música para YouTubeTrack
        # Isso já é feito automaticamente em player.play(), porém acaba demorando alguns segundos para retornar
        # E as views ficam aguardando o retorno para serem atualizadas.
        if isinstance(track, spotify.SpotifyTrack):
            track = await track.fulfill(player=player, cls=wavelink.YouTubeTrack, populate=False)

        # Às vezes a conexão com o lavalink dá algum problema e precisa ser reiniciada "on the fly".
        try:
            await player.play(track)
        except wavelink.InvalidLavalinkResponse:
            print('Error during connection to lavalink server, restarting node...')

            try:
                # Retorna dicionário de nodes
                nodes = wavelink.NodePool.nodes

                # Para websocket do node principal
                await nodes['main'].websocket.cleanup()

                # Deleta node da NodePool
                del nodes['main']

                # Reconecta nodes
                await self.connect_nodes()

                # Reconecta canal e tenta reproduzir track
                channel = player.channel

                await player.disconnect()
                await asyncio.sleep(1)
                player = await channel.connect(cls=Player())

                await player.play(track)
            except Exception as e:
                print('Error during reconnecting', e.__class__, e)

        # Atualiza views
        await handler.display_view.refresh(track)
        await handler.queue_view.refresh()

        # Loga informações no arquivo de log
        requester = track.requester if hasattr(track, 'requester') else None
        handler.logger.info(f'{track.title} requested by {requester}')

    # noinspection PyUnresolvedReferences
    async def pause(self, interaction: discord.Interaction):
        """
        Pausa a música.

        :param interaction: Objeto de interação
        """
        handler = self.guild_pool.get_handler(interaction.guild_id)
        player = handler.player
        display = handler.display_view

        if not player.is_playing() and not player.is_paused():
            await interaction.response.send_message(
                'Coloque algo para tocar primeiro! :see_no_evil: ',
                ephemeral=True,
                delete_after=5
            )
            return

        if player.is_paused():
            await interaction.response.send_message('Já estou pausado!', ephemeral=True, delete_after=5)
            return

        # Atualiza view
        embed = display.message.embeds[0]
        embed.set_footer(text='Pausado')
        embed.colour = discord.Colour.orange()

        button = display.play_pause
        button.label = 'Tocar'
        button.emoji = '⏸'

        await player.pause()
        await display.message.edit(content=None, embed=embed, view=display, attachments=[])

        await interaction.response.send_message('Pediu pra parar parou!', ephemeral=True, delete_after=5)

    # noinspection PyUnresolvedReferences
    async def resume(self, interaction: discord.Interaction):
        """
        Retoma música.

        :param interaction: Objeto de interação
        """
        handler = self.guild_pool.get_handler(interaction.guild_id)
        player = handler.player
        display = handler.display_view

        if not player.is_playing() and not player.is_paused():
            await interaction.response.send_message(
                'Coloque algo para tocar primeiro! :see_no_evil: ',
                ephemeral=True,
                delete_after=5
            )
            return

        if not player.is_paused():
            await interaction.response.send_message('Não estou pausado!', ephemeral=True, delete_after=5)
            return

        # Atualiza view
        embed = display.message.embeds[0]
        embed.set_footer(text='Tocando')
        embed.colour = discord.Colour.green()

        button = display.play_pause
        button.label = 'Pausar'
        button.emoji = '▶'

        await player.resume()
        await display.message.edit(content=None, embed=embed, view=display, attachments=[])

        await interaction.response.send_message('Pediu pra voltar voltou!', ephemeral=True, delete_after=5)

    async def skip(self, interaction: discord.Interaction):
        """
        Pula música atual.

        :param interaction: Objeto de interação
        """
        handler = self.guild_pool.get_handler(interaction.guild_id)
        player = handler.player

        # Exception levantada dentro de stop e não é tratada
        await player.stop()
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message('Música skipada!', ephemeral=True, delete_after=5)

    async def stop(self, interaction: discord.Interaction, leave: bool):
        """
        Interrompe reprodução.

        :param interaction: Objeto de interação
        :param leave: Flag se o bot deve ou não sair do canal
        """
        handler = self.guild_pool.get_handler(interaction.guild_id)

        message = 'Saindo!' if leave else 'Parado!'
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(message, ephemeral=True, delete_after=5)

        await self.reset(handler, leave=leave)

    async def loop(self, interaction: discord.Interaction):
        """
        Ativa loop para música atual.

        :param interaction: Objeto de interação
        """
        handler = self.guild_pool.get_handler(interaction.guild_id)
        player = handler.player

        status = 'Pausado' if player.is_paused() else 'Tocando'
        embed = interaction.message.embeds[0]

        if player.queue.loop:
            player.queue.loop = False

            embed.set_footer(text=status)
            message = 'Loop desativado!'
        else:
            player.queue.loop = True

            embed.set_footer(text=f'{status} | Loop ativado')
            message = 'Música atual em loop!'

        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(message, ephemeral=True, delete_after=5)
        await handler.display_view.message.edit(embed=embed)

    async def shuffle(self, interaction: discord.Interaction):
        """
        Embaralha a fila de músicas.

        :param interaction: Objeto de interação
        """
        handler = self.guild_pool.get_handler(interaction.guild_id)
        player = handler.player

        if player.queue.is_empty:
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message('Não há músicas na fila!', ephemeral=True, delete_after=5)
            return

        # Faz cópia da fila e a embaralha
        temp_queue = [track for track in player.queue]
        random.shuffle(temp_queue)

        # Limpa fila e adiciona itens novamente
        player.queue.clear()

        for track in temp_queue:
            await player.queue.put_wait(track)

        await handler.queue_view.refresh()
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message('Fila embaralhada!', ephemeral=True, delete_after=5)

    @staticmethod
    async def playlist_lookup(search: str, requester: str, handler: GuildHandler, spotify_decode: dict | None = None):
        """
        Faz a pesquisa de playlists.

        :param search: URL da playlist
        :param requester: Solicitante do comando
        :param handler: Handler referente
        :param spotify_decode: Tipo de mídia do Spotify, caso houver
        """

        async def add_track(track: wavelink.YouTubeTrack | spotify.SpotifyTrack):
            """
            Adiciona música na fila.

            :param track: Objeto de música
            """
            nonlocal count

            # Cria um atributo para referenciar o solicitante do comando, usado para logar no arquivo de log mais tarde
            setattr(track, 'requester', requester)
            await handler.player.queue.put_wait(track)

            # Atualiza view a cada 15 músicas
            if count and count % 15 == 0:
                await handler.queue_view.refresh()

            count += 1

        count = 0

        if spotify_decode:
            tracks = await spotify.SpotifyTrack.search(query=search, type=spotify_decode['type'])

            for track in tracks:
                await add_track(track)
        else:
            tracks = await wavelink.YouTubePlaylist.search(search)

            for track in tracks.tracks:
                await add_track(track)

        # Atualiza view
        await handler.queue_view.refresh()

    @staticmethod
    async def reset(handler: GuildHandler, leave: bool):
        """
        Reseta o bot e variáveis.

        :param handler: Handler referente
        :param leave: Flag se o bot deve ou não sair do canal
        :return:
        """
        player = handler.player

        if handler.playlist_loop and not handler.playlist_loop.done():
            handler.playlist_loop.cancel()

        player.queue.clear()

        # Caso player.stop() seja executado sem erros isso irá acionar o hook on_wavelink_track_end que por sua vez
        # tentará coletar outra música na fila, para evitar esse comportamento bloqueamos a execução de play_song()
        # através da flag handler.reset
        try:
            handler.reset = True

            # Por alguma razão quando se para o bot e imediatamente o desconecta do canal a conexão com o lavalink
            # é perdida, portanto, inseri um delay para tentar corrigir essa falha
            if player.is_playing():
                await player.stop()
                await asyncio.sleep(1)
        except wavelink.InvalidLavalinkResponse:
            pass

        if leave:
            await player.disconnect()

        await handler.display_view.reset()
        await handler.queue_view.reset()

    @staticmethod
    def get_waiting_time(player: Player):
        """Retorna tempo de fila."""
        track = player.current
        track_duration = track.duration if track else 0
        seconds = (track_duration - player.position) - player.queue.duration

        return format_time(seconds / 1000)

    @commands.hybrid_command(name='play', description='Pesquisa por uma música e adiciona na fila')
    @app_commands.rename(search='pesquisa')
    @app_commands.describe(search='URL ou palavras chaves de busca')
    async def _play(self, ctx: commands.Context, search: str):
        """Delega método."""
        await self.play(ctx, search)

    @commands.hybrid_command(name='pause', description='Pausa o bot')
    @commands.before_invoke(bot_is_ready)
    async def _pause(self, ctx: commands.Context):
        """Mesmo método da DisplayView."""
        await self.pause(ctx.interaction)

    @commands.hybrid_command(name='resume', description='Despausa o bot')
    @commands.before_invoke(bot_is_ready)
    async def _resume(self, ctx: commands.Context):
        """Mesmo método da DisplayView."""
        await self.resume(ctx.interaction)

    @commands.hybrid_command(name='skip', description='Pula a música atual')
    @commands.before_invoke(bot_is_ready)
    async def _skip(self, ctx: commands.Context):
        """Mesmo método da DisplayView."""
        await self.skip(ctx.interaction)

    @commands.hybrid_command(name='stop', description='Para a execução e limpa a fila de músicas')
    @commands.before_invoke(bot_is_ready)
    @app_commands.rename(leave='sair')
    @app_commands.describe(leave='Desconectar bot do canal')
    async def _stop(self, ctx: commands.Context, leave: bool = False):
        """Mesmo método da DisplayView."""
        await self.stop(ctx.interaction, leave)

    @commands.hybrid_command(name='shuffle', description='Embaralha a fila de músicas')
    @commands.before_invoke(bot_is_ready)
    async def _shuffle(self, ctx: commands.Context):
        """Mesmo método da DisplayView."""
        await self.shuffle(ctx.interaction)

    # Coloca uma música em uma posição específica na fila
    @commands.hybrid_command(name='put-at', description='Coloca uma música na ordem desejada')
    @commands.before_invoke(bot_is_ready)
    @app_commands.rename(index='índice', new_index='novo_índice')
    @app_commands.describe(index='Índice atual', new_index='Novo índice')
    async def _put_at(self, ctx: commands.Context, index: int, new_index: int):
        """
        Altera o índice de um item na fila.

        :param ctx: Objeto de contexto
        :param index: Índice do item
        :param new_index: Novo índice do item
        """
        interaction = ctx.interaction

        handler = self.guild_pool.get_handler(interaction.guild_id)
        player = handler.player

        index -= 1
        new_index -= 1

        try:
            track = player.queue[index]

            if new_index < 0 or new_index > player.queue.count:
                message = 'Novo índice não existe!'
            else:
                del player.queue[index]
                player.queue.put_at_index(new_index, track)
                message = f'{track.title} mudado para a posição {new_index + 1} na fila!'
        except IndexError:
            message = 'Índice atual não existe!'

        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(message, ephemeral=True, delete_after=5)

    @commands.hybrid_command(name='history', description='Histórico de músicas tocadas')
    async def _history(self, ctx: commands.Context):
        """
         Retorna um view com todos os logs do bot.

        :param ctx: Objeto de contexto
        """
        def _sorted(x: str):
            """Ordena string por dia e mês"""
            day = int(x[:2])
            month = int(x[3:5])

            return month, day

        interaction = ctx.interaction
        handler = self.guild_pool.get_handler(interaction.guild_id)

        root = handler.logger.root_dir

        # Retorna logs e ordena em ordem de data
        options = [file for file in os.listdir(root)]
        options = sorted(options, key=_sorted)

        if len(options) == 0:
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message('Não há nenhum arquivo de log no sistema', delete_after=5)
            return

        view = HistoryView(options, handler)
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(view=view)

        view.message = await interaction.original_response()


class HistoryView(discord.ui.View):
    """View para selecionar um arquivo de log para visualização."""

    def __init__(self, options: list, handler: GuildHandler):
        super().__init__(timeout=300)

        self.handler = handler
        self.response: discord.Message | None = None
        self.message: discord.Message | None = None

        for option in options:
            self.select_history.add_option(label=option)

    async def on_timeout(self):
        """Deleta mensagens no timeout."""
        await self.message.delete()

        if self.response:
            await self.response.delete()

    # noinspection PyUnresolvedReferences
    @discord.ui.select(cls=discord.ui.Select, placeholder='Selecione a data de referência')
    async def select_history(self, interaction: discord.Interaction, select: discord.ui.Select):
        selection = select.values[0]
        root = self.handler.logger.root_dir

        fullname = os.path.join(root, selection)
        file = discord.File(fullname, filename=selection)

        # Caso seja a primeira resposta responde à interação e salva resposta
        if not self.response:
            await interaction.response.send_message(file=file)
            self.response = await interaction.original_response()
        # Do contrário atrasa a interação e apenas edita a resposta anterior
        else:
            await interaction.response.defer()
            await self.response.edit(attachments=[file])


class QueueView(discord.ui.View):
    """View para visualizar fila de músicas."""

    def __init__(self, message: discord.Message, handler: GuildHandler):
        super().__init__(timeout=None)

        self.message = message
        self.handler = handler

        self.page = 0
        self.max_page = 0
        self.previous.disabled = True
        self.next.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """
        Verifica se o usuário está no canal de voz para interagir

        :param interaction: Objeto de interação
        :return: True se o usuário estiver no canal de voz, do contrário False
        """
        player = self.handler.player

        if player and interaction.user in player.channel.members:
            return True

        await interaction.response().send_message('Entre no canal primeiro!', delete_after=5)
        return False

    @classmethod
    async def create_view(cls, message: discord.Message, handler: GuildHandler) -> QueueView:
        """
        Cria view e a retorna.
        Para chamar a função assíncrona "reset" é necessário partir de uma função assíncrona, como o construtor
        "__init__" não permite ser declarado usando "async", precisei criar um método de classe para contornar isso.

        :param message: Container da view
        :param handler: Referência ao handler
        :return: Instância de DisplayView
        """
        self = cls(message, handler)
        await self.reset()
        return self

    @discord.ui.button(emoji='◀', style=discord.ButtonStyle.blurple, custom_id='queue:previous')
    async def previous(self, interaction: discord.Interaction, _):
        """
        Carrega página anterior.

        :param interaction: Objeto de interação
        :param _: Botão de interação (Não será usado aqui)
        """
        if self.page > 0:
            self.page -= 1

        # Desabilita botões até a interação terminar
        self.previous.disabled = True
        self.next.disabled = True

        # noinspection PyUnresolvedReferences
        await interaction.response.edit_message(view=self)
        await self.refresh()

    @discord.ui.button(emoji='▶', style=discord.ButtonStyle.blurple, custom_id='queue:next')
    async def next(self, interaction: discord.Interaction, _):
        """
        Carrega página seguinte.

        :param interaction: Objeto de interação
        :param _: Botão de interação (Não será usado aqui)
        """
        if self.page < self.max_page:
            self.page += 1

        # Desabilita botões até a interação terminar
        self.previous.disabled = True
        self.next.disabled = True

        # noinspection PyUnresolvedReferences
        await interaction.response.edit_message(view=self)
        await self.refresh()

    async def refresh(self):
        """Atualiza dados na view."""
        player = self.handler.player

        # Reseta view caso não haja músicas
        if player.queue.is_empty:
            await self.reset()
            return

        # Retorna possível página máxima para ocultar/mostrar os botões
        # Uma embed pode ter no máximo 25 campos, portanto cada página deve conter esse tamanho
        self.max_page = floor(player.queue.count / 25) if player.queue.count > 0 else 0

        # Guard clause
        if self.page < 0 or self.page > self.max_page:
            return

        embed = discord.Embed(title=f'{player.queue.count} música(s) na fila', colour=discord.Colour.gold())

        index = 0 if self.page == 0 else self.page * 25
        count = 0

        # Abastece embed com dados da fila
        while count < 25:
            try:
                track: wavelink.Playable = player.queue[index]
                embed.add_field(name=index + 1, value=track.title, inline=False)
                count += 1
            except IndexError:
                break

            index += 1

        # Habilita botões condicionalmente
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page == self.max_page

        await self.message.edit(content=None, embed=embed, view=self)

    async def reset(self):
        """Reseta a view para o padrão."""
        embed = discord.Embed(title=f'Não há músicas na fila', colour=discord.Colour.dark_gold())

        self.page = 0
        self.previous.disabled = True
        self.next.disabled = True

        await self.message.edit(content=None, embed=embed, view=None)


class DisplayView(discord.ui.View):
    """View para interagir com o Player e mostrar informações da música atual."""

    def __init__(self, message: discord.Message, music_cog: Music, handler: GuildHandler):
        super().__init__(timeout=None)

        self.message = message
        self.music_cog = music_cog
        self.handler = handler

        self._default_img_path = os.path.join(ROOT, 'assets', 'monki.jpg')

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """
        Verifica se o usuário está no canal de voz para interagir

        :param interaction: Objeto de interação
        :return: True se o usuário estiver no canal de voz, do contrário False
        """
        player = self.handler.player

        if player and interaction.user in player.channel.members:
            return True

        await interaction.response().send_message('Entre no canal primeiro!', delete_after=5)
        return False

    @classmethod
    async def create_view(cls, message: discord.Message, music_cog: Music, handler: GuildHandler) -> DisplayView:
        """
        Cria view e a retorna.
        Para chamar a função assíncrona "reset" é necessário partir de uma função assíncrona, como o construtor
        "__init__" não permite ser declarado usando "async", precisei criar um método de classe para contornar isso.

        :param message: Container da view
        :param music_cog: Referência a cog
        :param handler: Referência ao handler
        :return: Instância de DisplayView
        """
        self = cls(message, music_cog, handler)
        await self.reset()
        return self

    @discord.ui.button(label='Pausar', emoji='⏸', style=discord.ButtonStyle.gray, custom_id='display:play_pause')
    async def play_pause(self, interaction: discord.Interaction, _):
        """
        Pausa ou retoma música atual.

        :param interaction: Objeto de interação
        :param _: Button de interação
        """
        player = self.handler.player

        if player.is_paused():
            await self.music_cog.resume(interaction)
        else:
            await self.music_cog.pause(interaction)

    @discord.ui.button(label='Próximo', emoji='⏭', style=discord.ButtonStyle.gray, custom_id='display:next')
    async def skip(self, interaction: discord.Interaction, _):
        """Utiliza o mesmo método da slash command."""
        await self.music_cog.skip(interaction)

    @discord.ui.button(label='Parar', emoji='⏹', style=discord.ButtonStyle.gray, custom_id='display:stop')
    async def stop(self, interaction: discord.Interaction, _):
        """Utiliza o mesmo método da slash command."""
        await self.music_cog.stop(interaction, leave=False)

    @discord.ui.button(label='Loop', emoji='🔁', style=discord.ButtonStyle.gray, custom_id='display:loop', )
    async def loop(self, interaction: discord.Interaction, _):
        """Utiliza o mesmo método da slash command."""
        await self.music_cog.loop(interaction)

    @discord.ui.button(label='Aleatório', emoji='🔀', style=discord.ButtonStyle.gray, custom_id='display:shuffle', )
    async def shuffle(self, interaction: discord.Interaction, _):
        """Utiliza o mesmo método da slash command."""
        await self.music_cog.shuffle(interaction)

    async def refresh(self, track: wavelink.Playable):
        """
        Atualiza dados na view.

        :param track: Objeto track
        """

        # track.duration retorna o resultado em milliseconds
        duration = format_time(track.duration / 1000)

        attachments = []

        if hasattr(track, 'thumb'):
            thumb = track.thumb
        else:
            thumb = 'attachment://no_music.jpg'
            default = discord.File(self._default_img_path, filename='no_music.jpg')
            attachments.append(default)

        embed = discord.Embed(title=track.title, colour=discord.Colour.green())
        embed.add_field(name='Artista', value=track.author)
        embed.add_field(name='Duração', value=duration)
        embed.add_field(name='URL', value=track.uri)
        embed.set_image(url=thumb)
        embed.set_footer(text='Tocando')

        for button in self.children:
            button.disabled = False

        self.message = await self.message.edit(content=None, embed=embed, view=self, attachments=attachments)

    async def reset(self):
        """Reseta a view para o padrão."""
        embed = discord.Embed(
            title='Não há músicas em reprodução',
            description='Use /Play [Pesquisa] ou envie um link nesse canal',
            colour=discord.Color.dark_green()
        )

        embed.set_image(url='attachment://no_music.jpg')
        default = discord.File(self._default_img_path, filename='no_music.jpg')

        for button in self.children:
            button.disabled = True

        self.message = await self.message.edit(content=None, embed=embed, view=self, attachments=[default])


class SeekView(QueueView):
    """View para visualizar conteúdo filtrado em uma queue."""

    def __init__(self, message: discord.Message, handler: GuildHandler):
        super().__init__(message, handler)

        raise NotImplementedError("Class not yet implemented!")


class Player(wavelink.Player):
    """Subclasse de Player apenas para substituir o atributo Queue padrão para a Queue subclasse."""
    def __init__(self):
        super().__init__()

        self.queue: Queue = Queue()


class Queue(wavelink.Queue):
    """Subclasse de Queue para adicionar uma propriedade de duração para o total de itens na fila."""

    def __init__(self):
        super().__init__()

        self._duration = 0
        self._last_track: wavelink.Playable | None = None

    @property
    def duration(self):
        return self._duration

    @duration.setter
    def duration(self, value):
        self._duration = value

    async def get_wait(self) -> wavelink.YouTubeTrack | spotify.SpotifyTrack:
        """
        Retorna próximo item da fila e subtrai duração da fila.

        :return: Objeto de música
        """
        # track = cast(YouTubeTrack, await super().get_wait())
        track = await super().get_wait()

        # Somente diminui duração da fila caso a música atual não seja o mesmo objeto anterior
        # Caso a flag loop esteja ativada, a função anterior irá retornar o exato mesmo objeto.
        if self._last_track != track:
            self._duration -= track.duration

        self._last_track = track

        return track

    async def put_wait(self, item: wavelink.YouTubeTrack | spotify.SpotifyTrack):
        """
        Adiciona item e soma duração da fila.

        :param item: Música para adicionar a fila
        """
        await super().put_wait(item)
        self._duration += item.duration

    def clear(self):
        """Limpa fila."""
        super().clear()

        self._duration = 0
        self._loaded = None
        self.loop = False
        self.loop_all = False


class Logger(logging.Logger):
    """Subclasse de logging.Logger responsável por logar músicas ao tocá-las."""

    def __init__(self, guild_id: int, name=__name__):
        super().__init__(name)

        self.date: date | None = None
        self.root_dir: str = os.path.join(ROOT, 'logs', str(guild_id))

        os.makedirs('logs', exist_ok=True)
        os.makedirs(self.root_dir, exist_ok=True)

        self.setLevel(logging.INFO)

    def _create_handler(self, new_date: date):
        """
        Cria um novo handler.

        :param new_date: Nova data para criar o arquivo de log
        """
        filename = f"{new_date.strftime('%d-%m')}.log"

        handler = logging.FileHandler(os.path.join(self.root_dir, filename), mode='a')
        formatter = logging.Formatter('%(asctime)s | %(message)s', datefmt='%d/%m/%y %H:%M:%S')

        handler.setFormatter(formatter)

        # Deleta o handler existente e adiciona um novo
        self.handlers.clear()
        self.addHandler(handler)
        self.date = new_date

        logs = os.listdir(self.root_dir)

        # Caso a quantidade de logs ultrapasse 7, deleta o mais antigo
        if len(logs) > 7:
            oldest_log = OldestLog(creation_date=datetime.now(), fullname='')

            for file in logs:
                fullname = os.path.join(self.root_dir, file)
                creation_date = datetime.fromtimestamp(os.path.getctime(fullname))

                if creation_date < oldest_log.creation_date:
                    oldest_log = OldestLog(creation_date=creation_date, fullname=fullname)

            os.remove(oldest_log.fullname)

    def info(self, *args, **kwargs):
        """Loga informações."""
        current_date = datetime.now().date()

        # Verifica se o handler é referente a data atual, se não for cria outro
        if current_date != self.date:
            self._create_handler(current_date)

        super().info(*args, **kwargs)


async def setup(bot: commands.Bot):
    """
    Função chamada internamente pelo framework discord.py para vincular a cog ao bot

    :param bot: Instância do bot
    """
    await bot.add_cog(Music(bot))
