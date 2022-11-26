# ❤ SonoMonkey

Bot do Discord escrito em Python usando o framework Discord.py, criado com o objetivo de praticar lógica de programação
enquanto se diverte com amigos.


Sobre o nome SonoMonkey... <br>
O 'Sono' vem de Sonoplastia, já que a ideia original era usar efeitos de Sonoplastia
conhecidos aqui no Brasil, porém acabou não se limitando apenas a isso. Já o 'Monkey' vem de uma piada
interna de um servidor no próprio Discord entre um grupo de amigos, que era justamente onde o bot seria inserido.

![preview](./.github/preview.png)

## 🕹 Recursos

- SonoMonkey quando se junta a um canal de voz toca de forma aleatória efeitos armazenados no diretório *effects/*
com base em um timer definido pelo usuário.

- SonoMonkey sai sozinho quando o último membro sair de um canal de voz.

- Ao tocar o efeito 'BANIDO.mp3' SonoMonkey irá mover aleatoriamente um usuário para um canal de voz alternativo
(É possível desativar essa opção com os comandos)

- SonoMonkey entra no canal de voz automaticamente ao identificar dois usuários no mesmo canal. 
(É possível desativar essa opção com comandos)

## 🚦 Pré Requisitos

- Criar um arquivo .env na raiz do projeto com o seguinte conteúdo:
`TOKEN=token_do_seu_bot_aqui`

- Instalar o programa [ffmpeg](https://ffmpeg.org/) e colocar o executável **'ffmpeg'**
na raiz do projeto e /ou ao PATH se estiver usando Windows.

- No arquivo *config.json* atribuir a id do canal de texto padrão a chave `"default_text_channel_id"` para notificar 
usuários sobre um possível erro. E para a chave `"ban_voice_channel_id"` atribuir a id do canal de voz para o evento 
***BANIDO***.

## ⚙ Comandos

- `$auto_join <mode>` Quando True o bot entra sozinho ao perceber uma atualização no canal de voz,
quando False o bot ignora qualquer atualização e só entra se for chamado. Default: False

- `$ban <mode>` Quando True o bot move aleatoriamente um usuário para um canal previamente configurado
quando o efeito 'BANIDO.mp3' é tocado. Default: True

- `$set <timer1> [timer2]` Configurar temporizador em segundos. Default: 300 500

- `$play` Iniciar bot.

- `$leave` Remover bot.

- `$timer` Retorna o atual temporizador. 

- `$help` Mostra a lista de comandos e sua descrição.

## 🛠 Tecnologias

- Python
- Discord.py
- JSON
- Git e GitHub