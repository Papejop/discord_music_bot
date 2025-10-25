import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
import yt_dlp
import asyncio
from collections import deque

load_dotenv()
token = os.getenv("DISCORD_TOKEN")

SONG_QUEUES = {}
LOOP_CURRENT = {}

async def search_ytdlp_async(query, ydl_opts):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _extract(query, ydl_opts))

def _extract(query, ydl_opts):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(query, download=False)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

@bot.tree.command(name="loop", description="loop current song")
async def loop_song(interaction: discord.Interaction):
    await interaction.response.defer()
    guild_id = str(interaction.guild_id)

    if LOOP_CURRENT.get(guild_id):
        LOOP_CURRENT[guild_id] = False
        await interaction.followup.send("Loop disabled", ephemeral=True)
    else:
        LOOP_CURRENT[guild_id] = True
        await interaction.followup.send("Loop enabled", ephemeral=True)
    
    msg = await interaction.original_response()
    await cleanup(msg)

@bot.tree.command(name="queue", description="show the queue")
async def show_queue(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    if guild_id not in SONG_QUEUES or not SONG_QUEUES[guild_id]:
        await interaction.response.send_message("queue is empty")
        msg = await interaction.original_response()
        await cleanup(msg, 10)
        return
    
    queue = SONG_QUEUES[guild_id]
    embed = discord.Embed(
        title="Current Queue",
        color=discord.Color.blue()
    )
    
    queue_list = []
    for i, song in enumerate(list(queue)[:10], 1):
        queue_list.append(f"**{i}.** {song[1]}")
    
    if queue_list:
        embed.add_field(
            name=f"Up Next ({len(queue)} total)",
            value="\n".join(queue_list),
            inline=False
        )

    if len(queue) > 10:
        embed.set_footer(text=f"And {len(queue) - 10} more songs...")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="play", description="play music duh")
async def play_music(interaction: discord.Interaction, song_query: str):
    await interaction.response.defer()
    voice_channel = interaction.user.voice.channel

    if voice_channel is None:
        await interaction.followup.send("You must be in a voice channel")
        msg = await interaction.original_response()
        await cleanup(msg)
        return

    voice_client = interaction.guild.voice_client

    if voice_client is None:
        voice_client = await voice_channel.connect()
    elif voice_client.channel != voice_channel:  # FIXED: Compare channel to channel
        await voice_client.move_to(voice_channel)

    ydl_options_link = {
        "format": "bestaudio/best",
        "noplaylist": False,
        "playlist_items": "1",
        "youtube_include_dash_manifest": False,
        "youtube_include_hls_manifest": False,
    }

    ydl_options_dropdown = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
        "noplaylist": True,
    }

    if song_query.startswith("https://"):
        query = song_query
        results = await search_ytdlp_async(query, ydl_options_link)
        tracks = results.get("entries", [])
        if not tracks:
            await interaction.followup.send("No results found.")
            msg = await interaction.original_response()
            await cleanup(msg, 10)
            return
    else:
        results = await search_ytdlp_async(f"ytsearch5:{song_query}", ydl_options_dropdown)
        tracks = results.get("entries", [])
        if tracks:
            await dropdownMenu(interaction, tracks, voice_client)  # ADDED: voice_client parameter
            return 
        else:
            await interaction.followup.send("No results found", ephemeral=True)
            msg = await interaction.original_response()
            await cleanup(msg,10)
            return



    first_track = tracks[0]

    audio_url = first_track["url"]
    title = first_track.get("title", "Untitled")

    guild_id = str(interaction.guild_id)
    if SONG_QUEUES.get(guild_id) is None:
        SONG_QUEUES[guild_id] = deque()

    SONG_QUEUES[guild_id].append((audio_url, title))

    if voice_client.is_playing() or voice_client.is_paused():
        await interaction.followup.send(f"Added to queue: **{title}**")
        msg = await interaction.original_response()
        await cleanup(msg)
    else:
        await play_next_song(voice_client, guild_id, interaction.channel)

    await send_to_archive(
        f"Added to queue: **{title}** requested by {interaction.user.name}",
        1427664996497621095,
    )

@bot.tree.command(name="skip", description="skip this song duh")
async def skip(interaction: discord.Interaction):
    await interaction.response.defer() 
    
    if interaction.guild.voice_client and (
        interaction.guild.voice_client.is_playing()
        or interaction.guild.voice_client.is_paused()
    ):
        interaction.guild.voice_client.stop()
        await interaction.followup.send("Skipping current song")
    else:
        await interaction.followup.send("Not playing anything to skip")

    msg = await interaction.original_response()
    await cleanup(msg, 20)

async def play_next_song(voice_client, guild_id, channel):
    if SONG_QUEUES[guild_id]:
        audio_url, title = SONG_QUEUES[guild_id].popleft()

        current_track = (audio_url, title)

        ffmpeg_options = {
            "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            "options": "-vn",
        }

        source = discord.FFmpegOpusAudio(
            audio_url, **ffmpeg_options, executable="ffmpeg"
        )

        def after_play(error):
            if error:
                print(f"error playing {title}: {error}")
            
            if LOOP_CURRENT.get(guild_id):
                SONG_QUEUES[guild_id].appendleft(current_track)
            
            asyncio.run_coroutine_threadsafe(
                play_next_song(voice_client, guild_id, channel), bot.loop
            )
        voice_client.play(source, after=after_play)
        asyncio.create_task(channel.send(f"Now playing: **{title}**", delete_after=60))

    else:
        LOOP_CURRENT[guild_id] = False
        await voice_client.disconnect()
        SONG_QUEUES[guild_id] = deque()

async def send_to_archive(message, CHANNEL_ID):
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        await channel.send(message)

async def cleanup(message, timer=60):
    await asyncio.sleep(timer)
    await message.delete()

async def dropdownMenu(interaction, tracks, voice_client): 
    view = SelectView(tracks, voice_client, interaction)  
    message = await interaction.followup.send("Select a song:", view=view) 
    view.message = message 

class Select(discord.ui.Select):
    def __init__(self, tracks, voice_client, original_interaction):
        options = [
            discord.SelectOption(
                label=track.get("title", "Untitled")[:100],
                description=track.get("uploader", "Unknown")[:100],
                value=str(i)
            )
            for i, track in enumerate(tracks[:5]) 
        ]

        super().__init__(
            placeholder="select song", max_values=1, min_values=1, options=options
        )
        self.tracks = tracks
        self.voice_client = voice_client
        self.original_interaction = original_interaction  

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) 
        
        try:
            selected_index = int(self.values[0])
            selected_track = self.tracks[selected_index]

            ydl_options = {
                "format": "bestaudio/best",
                "noplaylist": True,
                "quiet": True,
            }

            if selected_track.get('url'):
                video_url = selected_track['url']
            elif selected_track.get('id'):
                video_url = f"https://www.youtube.com/watch?v={selected_track['id']}"
            else:
                await interaction.followup.send("Could not get video URL", ephemeral=True)
                msg = await interaction.original_response()
                await cleanup(msg, 20)
                return

            full_info = await search_ytdlp_async(video_url, ydl_options)
            audio_url = full_info['url']
            title = full_info.get('title', 'Unknown Title')
            
            guild_id = str(interaction.guild_id)
            if SONG_QUEUES.get(guild_id) is None:
                SONG_QUEUES[guild_id] = deque()

            SONG_QUEUES[guild_id].append((audio_url, title))
            
            try:
                await self.view.message.edit(content=f" Selected: **{title}**", view=None)
            except:
                pass

            if self.voice_client.is_playing() or self.voice_client.is_paused():
                await interaction.followup.send(f"Added to queue: **{title}**", ephemeral=True)
            else:
                await interaction.followup.send(f"Now playing: **{title}**", ephemeral=True)
                await play_next_song(self.voice_client, guild_id, interaction.channel)
            
            msg = await interaction.original_response()
            await cleanup(msg, 20)

            await send_to_archive(
                f"Added to queue: **{title}** requested by {interaction.user.name}",
                1427664996497621095,
            )
            
        except Exception as e:
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            msg = await interaction.original_response()
            await cleanup(msg, 20)

class SelectView(discord.ui.View):
    def __init__(self, tracks, voice_client, original_interaction, *, timeout=30):
        super().__init__(timeout=timeout)
        self.add_item(Select(tracks, voice_client, original_interaction))
        self.message = None

bot.run(token)