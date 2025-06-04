from dotenv import load_dotenv
load_dotenv()
import os
import discord
import time
import random
import asyncio
import requests
from gtts import gTTS
import io
from openai import OpenAI
from collections import defaultdict, deque
from datetime import datetime, timedelta
import yt_dlp as youtube_dl
import asyncio
from async_timeout import timeout
import tempfile
import subprocess
from pydub import AudioSegment
from blackjack_utils import parse_blackjack_situation, validate_blackjack_situation, get_basic_strategy_advice
from open_source_features import *

# Anti-spam settings
MESSAGE_LIMIT = 5  # Maximum messages a user can send in the time window
TIME_WINDOW = 10  # Time window in seconds
NOTIFICATION_LIMIT = 10  # Maximum notifications before timeout
TIMEOUT_DURATION = 300  # 5 minutes timeout in seconds
SPAMMER_ROLE_NAME = "ibb"  # Role to assign to detected spammers

# Initialize spam tracker
spam_tracker = defaultdict(list)
notification_tracker = defaultdict(int)
timeout_tracker = defaultdict(float)

# Initialize OpenAI client
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Track bonk usage and active sessions
bonk_tracker = defaultdict(list)
abusers = set()

# Memory system for dedicated chat channel
CHAT_CHANNEL_ID = 1378409982978035852
conversation_memory = defaultdict(list)  # Store conversation history per user
MAX_MEMORY_MESSAGES = 10  # Keep last 10 messages per user

# Voice chat settings
VOICE_CHAT_ENABLED = False  # Toggle voice chat mode
voice_connections = {}  # Track voice connections for voice chat
listening_users = set()  # Users currently being listened to

# Therapy channel for gambling addiction support
THERAPY_CHANNEL_ID = 1378126232872554708
therapy_memory = defaultdict(list)  # Store therapy conversation history per user
MAX_THERAPY_MEMORY = 15  # Keep more messages for therapy context

# Prompt-free channel (neutral bot responses)
PROMPT_FREE_CHANNEL_ID = 1379584188042448966
prompt_free_memory = defaultdict(list)  # Store conversation history per user
MAX_PROMPT_FREE_MEMORY = 10  # Keep fewer messages for prompt-free context

# Moderation logging channel
MODERATION_LOG_CHANNEL_ID = 1378124359834669207

# Bot commands logging channel
BOT_COMMANDS_LOG_CHANNEL_ID = 1378429743686357143

# Simple Music Bot Implementation
youtube_dl.utils.bug_reports_message = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'extract_flat': False
}

ffmpeg_options = {
    'before_options': '-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -reconnect_at_eof 1 -user_agent "Mozilla/5.0" -fflags +discardcorrupt',
    'options': '-vn -bufsize 256k -probesize 5M -analyzeduration 0 -tune zerolatency -preset ultrafast -threads 1'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

# Music queue system
music_queues = {}
now_playing = {}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)

async def log_moderation_action(action, moderator, target, reason, channel, until=None):
    """Log moderation actions to the designated channel"""
    log_channel = client.get_channel(MODERATION_LOG_CHANNEL_ID)
    if not log_channel:
        return

    try:
        colors = {
            "BAN": discord.Color.red(),
            "KICK": discord.Color.orange(),
            "TIMEOUT": discord.Color.yellow()
        }

        embed = discord.Embed(
            title=f"🛡️ Moderation Action: {action}",
            color=colors.get(action, discord.Color.blue()),
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(name="👮 Moderator", value=f"{moderator.mention} ({moderator.name})", inline=True)
        embed.add_field(name="🎯 Target", value=f"{target.mention} ({target.name})", inline=True)
        embed.add_field(name="📍 Channel", value=channel.mention, inline=True)
        embed.add_field(name="📝 Reason", value=reason, inline=False)

        if until:
            embed.add_field(name="⏰ Until", value=f"<t:{int(until.timestamp())}:F>", inline=False)

        embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)
        embed.set_footer(text=f"User ID: {target.id} | Moderator ID: {moderator.id}")

        await log_channel.send(embed=embed)

    except Exception as e:
        print(f"Failed to log moderation action: {e}")

async def alert_missing_reason(action, moderator, target):
    """Send an alert when a moderator doesn't provide a reason"""
    log_channel = client.get_channel(MODERATION_LOG_CHANNEL_ID)
    if not log_channel:
        return

    try:
        embed = discord.Embed(
            title="⚠️ Missing Reason Alert",
            description=f"**{moderator.mention}** performed a **{action}** action on **{target.mention}** without providing a reason!",
            color=discord.Color.dark_red(),
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(name="👮 Moderator", value=f"{moderator.mention} ({moderator.name})", inline=True)
        embed.add_field(name="🎯 Target", value=f"{target.mention} ({target.name})", inline=True)
        embed.add_field(name="⚠️ Issue", value="No reason provided", inline=False)

        embed.set_footer(text="Please remind moderators to always provide reasons for their actions")

        await log_channel.send(embed=embed)

    except Exception as e:
        print(f"Failed to send missing reason alert: {e}")

async def log_bot_command(user, command, channel, success=True, details=None):
    """Log bot command usage to the designated channel"""
    log_channel = client.get_channel(BOT_COMMANDS_LOG_CHANNEL_ID)
    if not log_channel:
        return

    try:
        color = discord.Color.green() if success else discord.Color.red()
        status_emoji = "✅" if success else "❌"

        embed = discord.Embed(
            title=f"{status_emoji} Bot Command Used",
            color=color,
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(name="👤 User", value=f"{user.mention} ({user.name})", inline=True)
        embed.add_field(name="📍 Channel", value=channel.mention, inline=True)
        embed.add_field(name="🤖 Command", value=f"`{command}`", inline=False)

        if details:
            embed.add_field(name="📝 Details", value=details, inline=False)

        embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
        embed.set_footer(text=f"User ID: {user.id}")

        await log_channel.send(embed=embed)

    except Exception as e:
        print(f"Failed to log bot command: {e}")

@client.event
async def on_ready():
    print('We have logged in as {0.user}'.format(client))

    # Clean up any existing voice connections on startup
    try:
        for guild in client.guilds:
            voice_client = discord.utils.get(client.voice_clients, guild=guild)
            if voice_client:
                await voice_client.disconnect(force=True)
    except Exception as e:
        print(f"Error cleaning up voice connections on startup: {e}")

    # Start connection health monitor
    client.loop.create_task(monitor_voice_connections())

async def monitor_voice_connections():
    """Monitor voice connections and attempt to recover from disconnections"""
    while True:
        try:
            await asyncio.sleep(30)  # Check every 30 seconds (less aggressive)

            for guild in client.guilds:
                voice_client = discord.utils.get(client.voice_clients, guild=guild)
                guild_id = guild.id

                if voice_client and guild_id in music_queues and music_queues[guild_id]:
                    # Check for various connection issues
                    if not voice_client.is_connected():
                        print(f"Monitor detected disconnected voice client for guild {guild_id}")
                        # Don't auto-reconnect aggressively, let manual commands handle it
                        continue
                    elif voice_client.is_connected() and not voice_client.is_playing() and music_queues[guild_id]:
                        # Connected but not playing despite having queue
                        print(f"Monitor detected stalled playback for guild {guild_id}, checking...")
                        # Only restart if we're sure it's stalled, not just between songs
                        await asyncio.sleep(5)
                        if not voice_client.is_playing() and music_queues[guild_id]:
                            try:
                                await play_next(guild)
                            except Exception as e:
                                print(f"Failed to restart stalled playback: {e}")

        except Exception as e:
            print(f"Error in voice connection monitor: {e}")
            await asyncio.sleep(10)  # Longer pause on error

# Music Bot Functions
async def join_voice_channel(ctx):
    """Join the voice channel of the user"""
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        if ctx.guild.voice_client is None:
            await channel.connect()
        elif ctx.guild.voice_client.channel != channel:
            await ctx.guild.voice_client.move_to(channel)
        return True
    return False

async def play_music(message, search):
    """Play music from YouTube search"""
    guild_id = message.guild.id

    # Initialize queue for this guild if it doesn't exist
    if guild_id not in music_queues:
        music_queues[guild_id] = []

    # Check if user is in voice channel
    if not message.author.voice:
        await message.channel.send("❌ You need to be in a voice channel to play music!")
        return

    # Join voice channel with enhanced retry logic
    voice_channel = message.author.voice.channel
    voice_client = discord.utils.get(client.voice_clients, guild=message.guild)

    # Simplified connection logic - less aggressive retry
    try:
        if not voice_client or not voice_client.is_connected():
            # Clean up any existing broken connections
            if voice_client:
                try:
                    await voice_client.disconnect(force=True)
                    await asyncio.sleep(2)  # Give Discord time to clean up
                except:
                    pass

            # Single connection attempt with longer timeout
            try:
                print(f"Attempting to connect to voice channel: {voice_channel.name}")
                voice_client = await voice_channel.connect(timeout=30.0, reconnect=False)
                await asyncio.sleep(2)  # Brief stabilization period

                if voice_client.is_connected():
                    print(f"Successfully connected to voice channel")
                else:
                    await message.channel.send("❌ Voice connection failed - Discord voice servers may be unstable. Try again in a few minutes.")
                    return

            except discord.errors.ConnectionClosed as e:
                if "4006" in str(e):
                    await message.channel.send("❌ Discord voice servers are currently unstable (Error 4006). This is a Discord issue. Try again later.")
                else:
                    await message.channel.send(f"❌ Voice connection closed: {e}")
                return
            except Exception as e:
                await message.channel.send(f"❌ Failed to connect to voice: {str(e)}")
                return

        elif voice_client.channel != voice_channel:
            try:
                await voice_client.move_to(voice_channel)
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Move failed: {e}")
                await message.channel.send("❌ Failed to move to your voice channel. Try the command again.")
                return

    except Exception as e:
        await message.channel.send(f"❌ Unexpected voice connection error: {str(e)}")
        return

    try:
        # Send loading message
        processing_msg = await message.channel.send(f"🔍 Searching for: **{search}**...")

        # Search for the song with longer timeout
        try:
            player = await YTDLSource.from_url(f"ytsearch:{search}", loop=client.loop, stream=True)
        except Exception as e:
            await processing_msg.edit(content=f"❌ Failed to find/load song: {str(e)}")
            return

        # Add to queue
        music_queues[guild_id].append({
            'player': player,
            'title': player.title,
            'requester': message.author.display_name
        })

        await processing_msg.edit(content=f"✅ Added to queue: **{player.title}**")

        # If nothing is playing, start playing
        if not voice_client.is_playing():
            await play_next(message.guild)

    except Exception as e:
        await processing_msg.edit(content=f"❌ Error playing music: {str(e)}")
        print(f"Music error details: {e}")  # For debugging

async def play_next(guild):
    """Play the next song in queue with enhanced error recovery"""
    guild_id = guild.id
    voice_client = discord.utils.get(client.voice_clients, guild=guild)

    # Enhanced connection check with auto-recovery
    if not voice_client or not voice_client.is_connected():
        print(f"Voice client not connected for guild {guild_id}, attempting recovery...")

        # Try to find users in voice channels and reconnect
        for channel in guild.voice_channels:
            if len([m for m in channel.members if not m.bot]) > 0:
                try:
                    if voice_client:
                        await voice_client.disconnect(force=True)
                    voice_client = await channel.connect(timeout=15.0, reconnect=True)
                    await asyncio.sleep(2)  # Stabilize connection
                    print(f"Successfully reconnected to {channel.name}")
                    break
                except Exception as e:
                    print(f"Failed to reconnect to {channel.name}: {e}")
                    continue
        else:
            print("No suitable voice channel found for reconnection")
            return

    if guild_id in music_queues and music_queues[guild_id]:
        next_song = music_queues[guild_id].pop(0)
        now_playing[guild_id] = next_song

        def after_song(error):
            if error:
                print(f"Player error: {error}")
                # Handle different types of errors
                if "4006" in str(error) or "ConnectionClosed" in str(error):
                    print("Connection error detected, scheduling recovery...")
                    asyncio.run_coroutine_threadsafe(handle_connection_recovery(guild), client.loop)
                else:
                    print("Other playback error, continuing to next song...")
                    asyncio.run_coroutine_threadsafe(play_next(guild), client.loop)
            else:
                print(f"Song finished normally: {next_song.get('title', 'Unknown')}")
                # Play next song after current one finishes
                try:
                    asyncio.run_coroutine_threadsafe(play_next(guild), client.loop)
                except Exception as e:
                    print(f"Error in after_song callback: {e}")

        try:
            # Double-check voice client health before playing
            if not voice_client.is_connected():
                print("Voice client disconnected just before playing, retrying...")
                await asyncio.sleep(1)
                await play_next(guild)  # Recursive retry
                return

            # Start playing with the enhanced audio source
            voice_client.play(next_song['player'], after=after_song)
            print(f"Started playing: {next_song['title']}")

            # Send now playing message
            text_channel = discord.utils.get(guild.text_channels, name='general') or guild.text_channels[0]
            if text_channel and text_channel.permissions_for(guild.me).send_messages:
                try:
                    embed = discord.Embed(
                        title="🎵 Now Playing",
                        description=f"**{next_song['title']}**",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="Requested by", value=next_song['requester'], inline=True)
                    await text_channel.send(embed=embed)
                except Exception as e:
                    print(f"Failed to send now playing message: {e}")

        except Exception as e:
            print(f"Error starting playback: {e}")
            # Add song back to front of queue and try next
            music_queues[guild_id].insert(0, next_song)
            await asyncio.sleep(2)
            asyncio.run_coroutine_threadsafe(play_next(guild), client.loop)
    else:
        # No more songs, schedule disconnect
        print("Queue empty, scheduling disconnect...")
        await asyncio.sleep(300)  # Wait 5 minutes
        if voice_client and not voice_client.is_playing():
            try:
                await voice_client.disconnect()
                if guild_id in now_playing:
                    del now_playing[guild_id]
                print("Disconnected due to inactivity")
            except Exception as e:
                print(f"Error during cleanup disconnect: {e}")

async def handle_connection_recovery(guild):
    """Handle voice connection recovery after errors"""
    guild_id = guild.id
    print(f"Starting connection recovery for guild {guild_id}")

    try:
        voice_client = discord.utils.get(client.voice_clients, guild=guild)

        # Force disconnect and wait
        if voice_client:
            await voice_client.disconnect(force=True)
        await asyncio.sleep(3)

        # Find active voice channels and reconnect
        for channel in guild.voice_channels:
            if len([m for m in channel.members if not m.bot]) > 0:
                try:
                    new_voice_client = await channel.connect(timeout=15.0, reconnect=True)
                    await asyncio.sleep(3)

                    if new_voice_client.is_connected():
                        print(f"Recovery successful, reconnected to {channel.name}")
                        # Continue playing if we have songs in queue
                        if guild_id in music_queues and music_queues[guild_id]:
                            await play_next(guild)
                        return
                except Exception as e:
                    print(f"Recovery attempt failed for {channel.name}: {e}")
                    continue

        print("Connection recovery failed - no suitable channels found")

    except Exception as e:
        print(f"Error during connection recovery: {e}")

async def handle_playback_error(guild, error):
    """Handle playback errors and attempt recovery"""
    print(f"Handling playback error for guild {guild.id}: {error}")

    # If it's a connection error, try to continue with next song
    if "4006" in str(error) or "ConnectionClosed" in str(error):
        print("Connection error detected, attempting to continue with next song...")
        await asyncio.sleep(2)  # Brief pause
        try:
            await play_next(guild)
        except Exception as e:
            print(f"Failed to recover from connection error: {e}")
    else:
        # For other errors, try to play next song
        try:
            await play_next(guild)
        except Exception as e:
            print(f"Failed to handle playback error: {e}")

async def pause_music(message):
    """Pause the current song"""
    voice_client = discord.utils.get(client.voice_clients, guild=message.guild)
    if voice_client and voice_client.is_playing():
        voice_client.pause()
        await message.channel.send("⏸️ Music paused!")
    else:
        await message.channel.send("❌ No music is currently playing!")

async def resume_music(message):
    """Resume the paused song"""
    voice_client = discord.utils.get(client.voice_clients, guild=message.guild)
    if voice_client and voice_client.is_paused():
        voice_client.resume()
        await message.channel.send("▶️ Music resumed!")
    else:
        await message.channel.send("❌ No music is currently paused!")

async def stop_music(message):
    """Stop music and clear queue"""
    guild_id = message.guild.id
    voice_client = discord.utils.get(client.voice_clients, guild=message.guild)

    if voice_client:
        voice_client.stop()
        await voice_client.disconnect()
        music_queues[guild_id] = []
        if guild_id in now_playing:
            del now_playing[guild_id]
        await message.channel.send("⏹️ Music stopped and disconnected!")
    else:
        await message.channel.send("❌ Not connected to a voice channel!")

async def skip_music(message):
    """Skip the current song"""
    voice_client = discord.utils.get(client.voice_clients, guild=message.guild)
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await message.channel.send("⏭️ Song skipped!")
    else:
        await message.channel.send("❌ No music is currently playing!")

async def show_queue(message):
    """Show the current music queue"""
    guild_id = message.guild.id

    if guild_id not in music_queues or not music_queues[guild_id]:
        await message.channel.send("📋 The music queue is empty!")
        return

    embed = discord.Embed(title="🎵 Music Queue", color=discord.Color.blue())

    # Show currently playing
    if guild_id in now_playing:
        embed.add_field(
            name="🎵 Now Playing",
            value=f"**{now_playing[guild_id]['title']}** (by {now_playing[guild_id]['requester']})",
            inline=False
        )

    # Show queue
    queue_text = ""
    for i, song in enumerate(music_queues[guild_id][:10], 1):
        queue_text += f"{i}. **{song['title']}** (by {song['requester']})\n"

    if queue_text:
        embed.add_field(name="📋 Up Next", value=queue_text, inline=False)

    if len(music_queues[guild_id]) > 10:
        embed.add_field(name="➕ More", value=f"And {len(music_queues[guild_id]) - 10} more songs...", inline=False)

    await message.channel.send(embed=embed)

# Memory functions
def add_to_memory(user_id, role, content):
    """Add a message to user's conversation memory"""
    conversation_memory[user_id].append({"role": role, "content": content})
    if len(conversation_memory[user_id]) > MAX_MEMORY_MESSAGES:
        conversation_memory[user_id] = conversation_memory[user_id][-MAX_MEMORY_MESSAGES:]

def get_conversation_context(user_id):
    """Get conversation history for context"""
    if user_id not in conversation_memory:
        return []
    return conversation_memory[user_id]

def clear_user_memory(user_id):
    """Clear a user's conversation memory"""
    if user_id in conversation_memory:
        del conversation_memory[user_id]

def add_to_therapy_memory(user_id, role, content):
    """Add a message to user's therapy conversation memory"""
    therapy_memory[user_id].append({"role": role, "content": content})
    if len(therapy_memory[user_id]) > MAX_THERAPY_MEMORY:
        therapy_memory[user_id] = therapy_memory[user_id][-MAX_THERAPY_MEMORY:]

def get_therapy_context(user_id):
    """Get therapy conversation history for context"""
    if user_id not in therapy_memory:
        return []
    return therapy_memory[user_id]

def clear_therapy_memory(user_id):
    """Clear a user's therapy conversation memory"""
    if user_id in therapy_memory:
        del therapy_memory[user_id]

def add_to_prompt_free_memory(user_id, role, content):
    """Add a message to user's prompt-free conversation memory"""
    prompt_free_memory[user_id].append({"role": role, "content": content})
    if len(prompt_free_memory[user_id]) > MAX_PROMPT_FREE_MEMORY:
        prompt_free_memory[user_id] = prompt_free_memory[user_id][-MAX_PROMPT_FREE_MEMORY:]

def get_prompt_free_context(user_id):
    """Get prompt-free conversation history for context"""
    if user_id not in prompt_free_memory:
        return []
    return prompt_free_memory[user_id]

def clear_prompt_free_memory(user_id):
    """Clear a user's prompt-free conversation memory"""
    if user_id in prompt_free_memory:
        del prompt_free_memory[user_id]

# Voice Chat Functions (Simplified - Recording disabled due to library limitations)
async def toggle_voice_chat(message):
    """Toggle voice chat mode for the chat channel"""
    global VOICE_CHAT_ENABLED

    # Check if user has admin permissions
    if not message.author.guild_permissions.administrator:
        await message.channel.send("🚫 Only administrators can toggle voice chat mode.")
        return

    VOICE_CHAT_ENABLED = not VOICE_CHAT_ENABLED
    status = "enabled" if VOICE_CHAT_ENABLED else "disabled"

    embed = discord.Embed(
        title="🎙️ Voice Chat Mode",
        description=f"Voice chat has been **{status}**!",
        color=discord.Color.green() if VOICE_CHAT_ENABLED else discord.Color.red()
    )

    if VOICE_CHAT_ENABLED:
        embed.add_field(
            name="How to use:",
            value="• Join a voice channel\n• Use `$voice connect` to connect\n• Bot will respond with text-to-speech!",
            inline=False
        )

    await message.channel.send(embed=embed)

async def speech_to_text(audio_file_path):
    """Convert speech to text using OpenAI Whisper"""
    try:
        with open(audio_file_path, "rb") as audio_file:
            transcript = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
        return transcript.strip()
    except Exception as e:
        print(f"STT failed: {e}")
        return None

async def handle_audio_file_transcription(message):
    """Handle transcription of uploaded audio files"""
    if not message.attachments:
        await message.channel.send(
            "❌ **No audio file attached!**\n\n"
            "📎 Please upload an audio file (mp3, wav, m4a, etc.) and try again.\n"
            "**Example:** Upload your voice recording and type: `$voice transcribe`"
        )
        return

    # Check for audio attachments
    audio_attachment = None
    supported_formats = ['.mp3', '.wav', '.m4a', '.flac', '.ogg', '.mp4', '.mpeg', '.mpga', '.webm']

    for attachment in message.attachments:
        if any(attachment.filename.lower().endswith(fmt) for fmt in supported_formats):
            audio_attachment = attachment
            break

    if not audio_attachment:
        await message.channel.send(
            "❌ **No supported audio file found!**\n\n"
            f"📎 **Supported formats:** {', '.join(supported_formats)}\n"
            "Please upload a valid audio file and try again."
        )
        return

    # Check file size (25MB limit for Discord, 25MB limit for OpenAI)
    if audio_attachment.size > 25 * 1024 * 1024:
        await message.channel.send(
            "❌ **File too large!**\n\n"
            "📏 **Maximum file size:** 25MB\n"
            f"📁 **Your file size:** {audio_attachment.size / (1024*1024):.1f}MB\n"
            "Please upload a smaller audio file."
        )
        return

    processing_msg = await message.channel.send("🎙️ **Transcribing audio...** This may take a moment...")

    try:
        # Download the audio file temporarily
        import tempfile
        import os

        # Create a temporary file with the correct extension
        file_extension = os.path.splitext(audio_attachment.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
            temp_file_path = temp_file.name

            # Download the attachment
            await audio_attachment.save(temp_file_path)

        # Transcribe using OpenAI Whisper
        transcript = await speech_to_text(temp_file_path)

        # Clean up temporary file
        try:
            os.unlink(temp_file_path)
        except:
            pass

        if transcript and transcript.strip():
            # Create transcription embed
            embed = discord.Embed(
                title="🎙️ Audio Transcription",
                description=f"**Transcribed text:**\n\n{transcript}",
                color=discord.Color.green()
            )
            embed.add_field(name="📁 File", value=audio_attachment.filename, inline=True)
            embed.add_field(name="📏 Size", value=f"{audio_attachment.size / 1024:.1f} KB", inline=True)
            embed.set_footer(text=f"Transcribed for {message.author.display_name}")

            await processing_msg.edit(content="", embed=embed)

            # Check if transcript contains bot commands
            if transcript.lower().strip().startswith(("bot", "hey bot", "gambly")):
                # Process as bot command
                clean_transcript = transcript.lower().strip()
                for prefix in ["bot", "hey bot", "gambly"]:
                    if clean_transcript.startswith(prefix):
                        clean_transcript = clean_transcript[len(prefix):].strip()
                        break

                if clean_transcript:
                    await message.channel.send(f"🗣️ **Processing voice command:** `{clean_transcript}`")
                    # You could integrate this with your existing bot command system here
                    # For now, just acknowledge the command
                    response = await generate_chatgpt_response(clean_transcript, message.author.name, message.author.display_name)
                    await message.channel.send(f"🤖 {response}")
        else:
            await processing_msg.edit(content="❌ **Could not transcribe audio.**\n\nPossible issues:\n• Audio quality too low\n• No speech detected\n• Unsupported audio format\n\nTry recording clearer audio or a different format.")

    except Exception as e:
        error_str = str(e)
        if "insufficient_quota" in error_str or "quota" in error_str.lower():
            await processing_msg.edit(content="💸 **Transcription unavailable** - The bot owner needs to top up their OpenAI credits.")
        elif "rate_limit" in error_str.lower():
            await processing_msg.edit(content="⏰ **Rate limited** - Please try again in a minute.")
        else:
            await processing_msg.edit(content=f"❌ **Transcription failed:** {e}")

        # Clean up temp file on error
        try:
            if 'temp_file_path' in locals():
                os.unlink(temp_file_path)
        except:
            pass

async def record_voice_audio(voice_client, duration=5):
    """Record audio from voice channel (simplified implementation)"""
    try:
        # Note: Discord.py doesn't have built-in recording capabilities
        # This is a placeholder for the concept
        print(f"Recording audio for {duration} seconds...")

        # In a real implementation, you'd need to:
        # 1. Set up audio recording from the voice channel
        # 2. Save the audio to a temporary file
        # 3. Return the file path

        # For now, return None to indicate recording isn't fully implemented
        return None

    except Exception as e:
        print(f"Recording failed: {e}")
        return None

async def start_voice_listening(message):
    """Connect to voice channel for speech-to-text listening"""
    if not VOICE_CHAT_ENABLED:
        await message.channel.send("🚫 Voice chat mode is disabled. Ask an admin to enable it with `$voice toggle`.")
        return

    user = message.author
    guild = message.guild

    # Check if user is in voice channel
    if not user.voice or not user.voice.channel:
        await message.channel.send("❌ You need to be in a voice channel to use voice chat!")
        return

    voice_channel = user.voice.channel

    try:
        # Connect to voice channel with better error handling
        voice_client = discord.utils.get(client.voice_clients, guild=guild)

        if not voice_client or not voice_client.is_connected():
            # Clean up broken connections
            if voice_client:
                try:
                    await voice_client.disconnect(force=True)
                    await asyncio.sleep(1)
                except:
                    pass

            # Single connection attempt
            try:
                voice_client = await voice_channel.connect(timeout=25.0, reconnect=False)
                await asyncio.sleep(1)
            except discord.errors.ConnectionClosed as e:
                if "4006" in str(e):
                    await message.channel.send("❌ Discord voice servers are unstable right now (Error 4006). Voice chat unavailable temporarily.")
                else:
                    await message.channel.send(f"❌ Voice connection failed: {e}")
                return
            except Exception as e:
                await message.channel.send(f"❌ Could not connect to voice: {e}")
                return

        elif voice_client.channel != voice_channel:
            try:
                await voice_client.move_to(voice_channel)
                await asyncio.sleep(1)
            except Exception as e:
                await message.channel.send(f"❌ Could not move to your voice channel: {e}")
                return

        # Verify connection worked
        if not voice_client.is_connected():
            await message.channel.send("❌ Voice connection failed. Discord voice servers may be having issues.")
            return

        # Add user to listening set
        listening_users.add(user.id)
        voice_connections[user.id] = voice_client

        embed = discord.Embed(
            title="🎙️ Voice Listening Connected!",
            description=f"🎯 Connected to **{voice_channel.name}**\n\n"
                       f"✨ **Available features:**\n"
                       f"• Speech-to-text transcription\n"
                       f"• Voice command processing\n"
                       f"• Music playback\n\n"
                       f"🗣️ **Speak into your mic and I'll convert it to text!**\n"
                       f"⚠️ *Note: Recording functionality is limited by Discord.py*\n"
                       f"📝 *Use `$voice record` to manually record speech*",
            color=discord.Color.green()
        )
        await message.channel.send(embed=embed)

    except Exception as e:
        await message.channel.send(f"❌ Failed to connect to voice: {e}")
        print(f"Voice connection error: {e}")

async def stop_voice_listening(message):
    """Disconnect from voice chat"""
    user = message.author

    if user.id in listening_users:
        listening_users.remove(user.id)

        if user.id in voice_connections:
            voice_client = voice_connections[user.id]

            # Don't disconnect if others are using it
            if len([u for u in listening_users if u in voice_connections and voice_connections[u] == voice_client]) == 0:
                await voice_client.disconnect()
            del voice_connections[user.id]

        embed = discord.Embed(
            title="🔇 Voice Chat Ended",
            description=f"Disconnected from voice chat.\n\n"
                       f"📊 **Session Summary:**\n"
                       f"• Voice connection closed\n"
                       f"• Use `$voice connect` to reconnect",
            color=discord.Color.orange()
        )
        await message.channel.send(embed=embed)
    else:
        await message.channel.send("❌ You're not currently in a voice chat session!")

async def handle_voice_commands(message, content):
    """Handle voice-related commands"""
    if content.startswith("toggle"):
        await toggle_voice_chat(message)
    elif content.startswith("connect") or content.startswith("listen"):
        await start_voice_listening(message)
    elif content.startswith("stop"):
        await stop_voice_listening(message)
    elif content.startswith("record"):
        await handle_voice_recording(message, content)
    elif content.startswith("transcribe"):
        await handle_audio_file_transcription(message)
    elif content.startswith("status"):
        status = "enabled" if VOICE_CHAT_ENABLED else "disabled"
        listening_count = len(listening_users)

        embed = discord.Embed(
            title="🎙️ Voice Chat Status",
            color=discord.Color.blue()
        )
        embed.add_field(name="Mode", value=status.title(), inline=True)
        embed.add_field(name="Active Listeners", value=listening_count, inline=True)

        if listening_users:
            user_mentions = []
            for user_id in listening_users:
                user = client.get_user(user_id)
                if user:
                    user_mentions.append(user.mention)
            embed.add_field(name="Connected Users", value="\n".join(user_mentions) or "None", inline=False)

        if VOICE_CHAT_ENABLED:
            embed.add_field(name="💡 TTS Feature", value="When connected to voice:\n• Bot speaks chat responses aloud\n• TTS pauses music temporarily\n• Uses OpenAI's natural voice synthesis", inline=False)

        await message.channel.send(embed=embed)
    else:
        embed = discord.Embed(
            title="🎙️ Voice Chat Commands",
            description="Available voice commands:",
            color=discord.Color.blue()
        )
        embed.add_field(name="$voice toggle", value="Enable/disable voice chat (Admin only)", inline=False)
        embed.add_field(name="$voice connect", value="Connect to voice channel", inline=False)
        embed.add_field(name="$voice transcribe", value="Transcribe uploaded audio file", inline=False)
        embed.add_field(name="$voice record", value="Instructions for audio upload", inline=False)
        embed.add_field(name="$voice stop", value="Disconnect from voice channel", inline=False)
        embed.add_field(name="$voice status", value="Check voice chat status", inline=False)

        await message.channel.send(embed=embed)

async def handle_voice_recording(message, content):
    """Handle audio file upload for transcription (STT)"""
    await message.channel.send(
        "🎙️ **Speech-to-Text Available!**\n\n"
        "📎 **Upload an audio file** (mp3, wav, m4a, etc.) with your message and I'll transcribe it!\n\n"
        "**Example:** Upload your voice recording and type: `$voice transcribe`\n\n"
        "**Supported formats:** MP3, WAV, M4A, FLAC, OGG\n"
        "**Max file size:** 25MB\n\n"
        "💡 **Tip:** Record voice memos on your phone and upload them here!"
    )

async def handle_chat_channel_message(message):
    """Handle messages in the dedicated chat channel with memory and all bot features"""
    user_id = message.author.id
    username = message.author.name
    display_name = message.author.display_name
    content = message.content.strip()

    # Handle voice commands in chat channel
    if content.startswith('$voice'):
        voice_content = content[7:].strip()
        await handle_voice_commands(message, voice_content)
        return

    # Handle special commands in chat channel
    if content.lower() in ["clear memory", "reset memory", "forget me"]:
        clear_user_memory(user_id)
        await message.channel.send(f"🧠 Memory cleared for {display_name}! Starting fresh.")
        return

    if content.lower() in ["my memory", "show memory"]:
        memory = get_conversation_context(user_id)
        if not memory:
            await message.channel.send(f"🤔 No conversation history found for {display_name}.")
            return

        memory_text = f"**Memory for {display_name}:**\n"
        for msg in memory[-5:]:
            role_emoji = "🤖" if msg["role"] == "assistant" else "👤"
            memory_text += f"{role_emoji} {msg['content'][:100]}{'...' if len(msg['content']) > 100 else ''}\n"

        await message.channel.send(memory_text[:2000])
        return

    # Handle music commands
    if any(word in content.lower() for word in ["play", "music"]):
        song_query = content.lower().replace("play", "").replace("music", "").strip()
        if song_query:
            await play_music(message, song_query)
            add_to_memory(user_id, "user", f"Asked me to play: {song_query}")
            add_to_memory(user_id, "assistant", f"Playing music: {song_query}")
            return
    elif "pause" in content.lower():
        await pause_music(message)
        return
    elif "resume" in content.lower():
        await resume_music(message)
        return
    elif "stop" in content.lower():
        await stop_music(message)
        return
    elif "skip" in content.lower():
        await skip_music(message)
        return
    elif "queue" in content.lower():
        await show_queue(message)
        return

    # Regular conversation handling
    if not content and not message.attachments:
        embed = discord.Embed(
            title="🤖 Gambly Wambly Bot",
            description="I'm here to help! Just tell me what you want to do:\n\n"
                       "• Ask me questions or chat with me\n"
                       "• Music: `play [song name]`, `pause`, `resume`, `stop`, `skip`, `queue`\n"
                       "• Memory: `clear memory` or `show memory`",
            color=discord.Color.blue()
        )
        await message.channel.send(embed=embed)
        return

    # Handle regular conversation with OpenAI
    processing_msg = await message.channel.send("*processing...*")
    add_to_memory(user_id, "user", content)
    context_messages = get_conversation_context(user_id)

    try:
        messages = [
            {
                "role": "system", 
                "content": (
                    f"You are Gambly Wambly, a Discord bot with a gambling theme. "
                    f"You're talking to {display_name} (username: {username}). "
                    f"Be engaging and maintain your gambling personality. "
                    f"Keep responses under 150 words for speed."
                )
            }
        ]
        messages.extend(context_messages)

        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=150,  # Reduced for faster responses
            temperature=0.8,
        )

        bot_response = response.choices[0].message.content.strip()
        await processing_msg.edit(content=f"🤖 {bot_response}")

        # Add TTS for voice chat mode
        if VOICE_CHAT_ENABLED and user_id in voice_connections:
            voice_client = voice_connections[user_id]
            if voice_client and voice_client.is_connected():
                # Clean response for TTS (remove emojis and formatting)
                tts_text = bot_response.replace("🤖", "").replace("*", "").strip()
                if len(tts_text) > 500:  # Limit TTS length
                    tts_text = tts_text[:500] + "..."
                await text_to_speech_and_play(tts_text, voice_client)

    except Exception as e:
        await processing_msg.edit(content=f"🤖 Having technical difficulties: {e}")

async def handle_therapy_channel_message(message):
    """Handle messages in the therapy channel"""
    user_id = message.author.id
    username = message.author.name
    display_name = message.author.display_name
    content = message.content.strip()

    # Handle voice commands in therapy channel
    if content.startswith('$voice'):
        voice_content = content[7:].strip()
        await handle_voice_commands(message, voice_content)
        return

    # Handle special commands in therapy channel
    if content.lower() in ["clear therapy memory", "reset therapy", "start over"]:
        clear_therapy_memory(user_id)
        await message.channel.send(f"🧠 Your therapy session has been reset, {display_name}.")
        return

    if content.lower() in ["my therapy memory", "show therapy memory"]:
        memory = get_therapy_context(user_id)
        if not memory:
            await message.channel.send(f"🤔 No therapy conversation history found for {display_name}.")
            return

        memory_text = f"**Therapy Memory for {display_name}:**\n"
        for msg in memory[-5:]:
            role_emoji = "💚" if msg["role"] == "assistant" else "👤"
            memory_text += f"{role_emoji} {msg['content'][:100]}{'...' if len(msg['content']) > 100 else ''}\n"

        await message.channel.send(memory_text[:2000])
        return

    # Regular conversation handling
    if not content and not message.attachments:
        embed = discord.Embed(
            title="💚 Therapy Support Bot",
            description="I'm here to provide support for gambling addiction recovery. Feel free to share your thoughts, concerns, or ask for advice.\n\n"
                       "• Share your feelings or experiences\n"
                       "• Ask for coping strategies\n"
                       "• Memory: `clear therapy memory` or `show therapy memory`",
            color=discord.Color.green()
        )
        await message.channel.send(embed=embed)
        return

    processing_msg = await message.channel.send("*thinking...*")
    add_to_therapy_memory(user_id, "user", content)
    context_messages = get_therapy_context(user_id)

    try:
        messages = [
            {
                "role": "system", 
                "content": (
                    f"You are a compassionate therapy assistant for gambling addiction recovery. "
                    f"You're talking to {display_name} (username: {username}). "
                    f"Provide supportive, non-judgmental responses focused on recovery. "
                    f"Keep responses under 300 words. Be empathetic and encouraging."
                )
            }
        ]
        messages.extend(context_messages)

        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=300,
            temperature=0.7,
        )

        bot_response = response.choices[0].message.content.strip()
        add_to_therapy_memory(user_id, "assistant", bot_response)
        await processing_msg.edit(content=f"💚 {bot_response}")

        # Add TTS for voice chat mode
        if VOICE_CHAT_ENABLED and user_id in voice_connections:
            voice_client = voice_connections[user_id]
            if voice_client and voice_client.is_connected():
                # Clean response for TTS (remove emojis and formatting)
                tts_text = bot_response.replace("💚", "").replace("*", "").strip()
                if len(tts_text) > 500:  # Limit TTS length
                    tts_text = tts_text[:500] + "..."
                await text_to_speech_and_play(tts_text, voice_client)

    except Exception as e:
        await processing_msg.edit(content=f"💚 I'm having technical difficulties, but I'm here for you.")

async def handle_prompt_free_channel_message(message):
    """Handle messages in the prompt-free channel with minimal prompting"""
    user_id = message.author.id
    username = message.author.name
    display_name = message.author.display_name
    content = message.content.strip()

    # Handle voice commands in prompt-free channel
    if content.startswith('$voice'):
        voice_content = content[7:].strip()
        await handle_voice_commands(message, voice_content)
        return

    # Handle special commands in prompt-free channel
    if content.lower() in ["clear memory", "reset memory", "forget me"]:
        clear_prompt_free_memory(user_id)
        await message.channel.send(f"🧠 Memory cleared for {display_name}! Starting fresh.")
        return

    if content.lower() in ["my memory", "show memory"]:
        memory = get_prompt_free_context(user_id)
        if not memory:
            await message.channel.send(f"🤔 No conversation history found for {display_name}.")
            return

        memory_text = f"**Memory for {display_name}:**\n"
        for msg in memory[-5:]:
            role_emoji = "🤖" if msg["role"] == "assistant" else "👤"
            memory_text += f"{role_emoji} {msg['content'][:100]}{'...' if len(msg['content']) > 100 else ''}\n"

        await message.channel.send(memory_text[:2000])
        return

    # Handle music commands
    if any(word in content.lower() for word in ["play", "music"]):
        song_query = content.lower().replace("play", "").replace("music", "").strip()
        if song_query:
            await play_music(message, song_query)
            add_to_prompt_free_memory(user_id, "user", f"Asked me to play: {song_query}")
            add_to_prompt_free_memory(user_id, "assistant", f"Playing music: {song_query}")
            return
    elif "pause" in content.lower():
        await pause_music(message)
        return
    elif "resume" in content.lower():
        await resume_music(message)
        return
    elif "stop" in content.lower():
        await stop_music(message)
        return
    elif "skip" in content.lower():
        await skip_music(message)
        return
    elif "queue" in content.lower():
        await show_queue(message)
        return

    # Regular conversation handling
    if not content and not message.attachments:
        embed = discord.Embed(
            title="🤖 Discord Bot",
            description="I'm a Discord bot assistant. Feel free to ask me anything or chat!\n\n"
                       "• Ask me questions or chat with me\n"
                       "• Music: `play [song name]`, `pause`, `resume`, `stop`, `skip`, `queue`\n"
                       "• Memory: `clear memory` or `show memory`",
            color=discord.Color.blue()
        )
        await message.channel.send(embed=embed)
        return

    # Handle regular conversation with minimal prompting
    processing_msg = await message.channel.send("*processing...*")
    add_to_prompt_free_memory(user_id, "user", content)
    context_messages = get_prompt_free_context(user_id)

    try:
        messages = [
            {
                "role": "system", 
                "content": (
                    f"You are a Discord bot assistant. "
                    f"You're talking to {display_name} (username: {username}). "
                    f"Be helpful and natural. Keep responses under 150 words for speed."
                )
            }
        ]
        messages.extend(context_messages)

        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=150,  # Reduced for faster responses
            temperature=0.8,
        )

        bot_response = response.choices[0].message.content.strip()
        add_to_prompt_free_memory(user_id, "assistant", bot_response)
        await processing_msg.edit(content=f"🤖 {bot_response}")

        # Add TTS for voice chat mode
        if VOICE_CHAT_ENABLED and user_id in voice_connections:
            voice_client = voice_connections[user_id]
            if voice_client and voice_client.is_connected():
                # Clean response for TTS (remove emojis and formatting)
                tts_text = bot_response.replace("🤖", "").replace("*", "").strip()
                if len(tts_text) > 500:  # Limit TTS length
                    tts_text = tts_text[:500] + "..."
                await text_to_speech_and_play(tts_text, voice_client)

    except Exception as e:
        await processing_msg.edit(content=f"🤖 Having technical difficulties: {e}")

async def analyze_user_intent(message_content, has_attachments=False, has_mentions=False):
    """Use AI to understand what the user wants to do"""

    # Define available features
    features_context = """
    Available bot features:
    1. Answer questions and have conversations
    2. Analyze images (when images are attached)
    3. Generate roasts for mentioned users
    4. Voice channel management (bonk/unbonk users)
    5. Role assignment (sharmota, sharmotait_halab, gay, Gambler_addict, gyat)
    6. Blackjack strategy advice
    7. Music playback (play, pause, stop, skip, queue management)
    8. Moderation commands (ban, kick, timeout) - Administrator only
    """

    # Create a prompt to analyze intent
    intent_prompt = f"""
    {features_context}

    User message: "{message_content}"
    Has image attachments: {has_attachments}
    Has user mentions: {has_mentions}

    Based on the user's message, determine what they want to do. Respond with ONE of these categories:
    - "question" - for general questions, conversations, or help requests
    - "image" - if they want image analysis (especially if attachments present)
    - "roast" - if they want to roast someone (especially if mentions present)
    - "voice" - if they mention bonk, unbonk, voice, kick from voice
    - "role" - if they ask for roles, want to assign roles, or mention role names
    - "blackjack" - if they mention blackjack, cards, strategy, gambling advice
    - "music" - if they mention play, pause, stop, skip, queue, music, song
    - "moderation" - if they mention ban, kick, timeout, or other moderation actions

    Just respond with the category name, nothing else.
    """

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": intent_prompt}],
            max_tokens=10,
            temperature=0.1,
        )

        intent = response.choices[0].message.content.strip().lower()
        return intent
    except:
        # Fallback to simple keyword detection
        content_lower = message_content.lower()

        if has_attachments and any(word in content_lower for word in ["image", "picture", "photo", "analyze", "what", "see"]):
            return "image"
        elif has_mentions and any(word in content_lower for word in ["roast", "burn", "insult", "destroy"]):
            return "roast"
        elif any(word in content_lower for word in ["bonk", "unbonk", "voice", "disconnect", "remove", "move", "transfer", "send"]) or "kick out" in content_lower:
            return "voice"
        elif any(word in content_lower for word in ["ban", "kick", "timeout", "mute"]):
            return "moderation"
        elif any(word in content_lower for word in ["role", "sharmota", "sharmotait_halab", "gay", "gambler_addict", "gyat"]):
            return "role"
        elif any(word in content_lower for word in ["blackjack", "card", "strategy", "hit", "stand", "dealer"]):
            return "blackjack"
        elif any(word in content_lower for word in ["joke", "fact", "quote", "trivia", "poll", "coin", "dice", "flip", "roll"]):
            return "fun"
        elif any(word in content_lower for word in ["xp", "level", "leaderboard", "stats", "user info", "server info"]):
            return "stats"
        else:
            return "question"

async def handle_intelligent_request(message):
    """Handle user request intelligently based on intent analysis"""

    content = message.content[4:].strip()  # Remove "$bot" prefix
    has_attachments = bool(message.attachments and any(att.content_type.startswith('image') for att in message.attachments))
    has_mentions = bool(message.mentions)

    # Check for -n flag (neutral mode without gambling prompts)
    neutral_mode = False
    if content.startswith('-n '):
        neutral_mode = True
        content = content[3:].strip()  # Remove "-n " prefix
    elif content == '-n':
        neutral_mode = True
        content = ""

    # If no content after $bot, show quick help
    if not content:
        embed = discord.Embed(
            title="🤖 Gambly Wambly Bot",
            description="I'm here to help! Just tell me what you want to do:\n\n"
                       "• Ask me questions: `$bot what's the weather?`\n"
                       "• Neutral mode: `$bot -n your question` (no gambling theme)\n"
                       "• Analyze images: `$bot what's in this image?` (attach image)\n"
                       "• Roast someone: `$bot roast @user`\n"
                       "• Voice tools: `$bot bonk @user`\n"
                       "• Get roles: `$bot give me the gay role`\n"
                       "• Blackjack help: `$bot I have 16, dealer shows 10`\n"
                       "• Music: `$bot play song` or `$bot pause`\n"
                       "• Moderation (Admin): `$bot ban/kick/timeout @user reason`",
            color=discord.Color.blue()
        )
        await message.channel.send(embed=embed)
        return

    # Analyze what the user wants (but skip gambling detection in neutral mode)
    if neutral_mode:
        # In neutral mode, only detect basic intents, no gambling/blackjack
        if has_attachments and any(word in content.lower() for word in ["image", "picture", "photo", "analyze", "what", "see"]):
            intent = "image"
        elif has_mentions and any(word in content.lower() for word in ["roast", "burn", "insult", "destroy"]):
            intent = "roast"
        elif any(word in content.lower() for word in ["bonk", "unbonk", "voice", "kick", "disconnect", "remove"]) or "kick out" in content.lower():
            intent = "voice"
        elif any(word in content.lower() for word in ["role", "sharmota", "sharmotait_halab", "gay", "gambler_addict", "gyat"]):
            intent = "role"
        elif any(word in content.lower() for word in ["play", "music"]):
            intent = "music" # Adding music intent in neutral mode
        else:
            intent = "question"  # Default to neutral conversation
    else:
        intent = await analyze_user_intent(content, has_attachments, has_mentions)

    # Handle based on detected intent
    if intent == "image" and has_attachments:
        if content:
            await handle_image_analysis_with_question(message, content)
        else:
            await handle_image_command(message)

    elif intent == "roast" and has_mentions:
        try:
            # Send processing message
            processing_msg = await message.channel.send("🤖 Generating roast...")

            target = message.mentions[0]
            # Get avatar URL (use default if no custom avatar)
            avatar_url = target.avatar.url if target.avatar else target.default_avatar.url
            # Extract context from the message (everything after removing mentions)
            roast_context = content
            for mention in message.mentions:
                roast_context = roast_context.replace(f"@{mention.name}", "").replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
            roast_context = roast_context.replace("roast", "").strip()

            roast = await generate_chatgpt_roast(target.name, target.display_name, avatar_url, roast_context)
            await processing_msg.edit(content=f"🔥 {target.mention}, {roast}")

        except Exception as e:
            # If error occurs, edit processing message instead of deleting
            await processing_msg.edit(content=f"🤖 Error generating roast: {e}")

    elif intent == "voice":
        content_lower = content.lower()
        if (any(word in content_lower for word in ["bonk", "kick", "disconnect", "remove"]) or "kick out" in content_lower) and has_mentions:
            await handle_bonk_command(message, message.mentions[0])
        elif "unbonk" in content_lower and has_mentions:
            await handle_unbonk_command(message, message.mentions[0])
        elif (any(word in content_lower for word in ["move", "transfer", "send"]) or "move to" in content_lower) and has_mentions:
            await handle_move_command(message, content)
        else:
            await message.channel.send("🔨 For voice tools, try: `$bot bonk @user`, `$bot unbonk @user`, or `$bot move @user to [channel name]`")

    elif intent == "moderation":
        content_lower = content.lower()
        if "ban" in content_lower and has_mentions:
            await handle_ban_command(message, content)
        elif "kick" in content_lower and has_mentions:
            await handle_kick_command(message, content)
        elif "timeout" in content_lower and has_mentions:
            await handle_timeout_command(message, content)
        else:
            await message.channel.send("🛡️ For moderation, try: `$bot ban @user reason`, `$bot kick @user reason`, or `$bot timeout @user 10m reason`")

    elif intent == "role":
        # Extract role name from the message
        role_name = extract_role_from_message(content)
        if role_name:
            await handle_role_command(message, role_name)
        else:
            allowed_roles = ["sharmota", "sharmotait_halab", "gay", "Gambler_addict", "gyat"]
            roles_list = ", ".join(allowed_roles)
            await message.channel.send(f"🎭 Available roles: {roles_list}\nTry: `$bot give me the gay role`")

    elif intent == "blackjack":
        advice = await get_blackjack_advice_from_ai(content, message.author.name, message.author.id)
        full_response = f"🃏 {advice}"
        await message.channel.send(full_response)

    elif intent == "music":
        # Extract song name
        song_query = content.lower().replace("play", "").replace("music", "").strip()
        if song_query:
            await play_music(message, song_query)
        else:
            await message.channel.send("🎵 What would you like me to play? Try: `$bot play never gonna give you up`")

    elif intent == "fun":
        content_lower = content.lower()
        if "fact" in content_lower:
            await handle_fun_fact_command(message)
        elif "joke" in content_lower:
            await handle_joke_command(message)
        elif "quote" in content_lower:
            await handle_quote_command(message)
        elif "trivia" in content_lower:
            await handle_trivia_command(message)
        elif "poll" in content_lower:
            poll_content = content.replace("poll", "").strip()
            await handle_poll_command(message, poll_content)
        elif "coin" in content_lower or "flip" in content_lower:
            await handle_coin_flip_command(message)
        elif "dice" in content_lower or "roll" in content_lower:
            # Extract number of sides if specified
            import re
            sides_match = re.search(r'd(\d+)', content_lower)
            sides = int(sides_match.group(1)) if sides_match else 6
            await handle_dice_roll_command(message, sides)
        else:
            await handle_fun_fact_command(message)  # Default to fun fact

    elif intent == "stats":
        content_lower = content.lower()
        if "xp" in content_lower or "level" in content_lower:
            target_user = message.mentions[0] if message.mentions else None
            await handle_xp_command(message, target_user)
        elif "leaderboard" in content_lower:
            await handle_leaderboard_command(message)
        elif "server" in content_lower:
            await handle_server_stats_command(message)
        elif "user" in content_lower:
            target_user = message.mentions[0] if message.mentions else None
            await handle_user_info_command(message, target_user)
        else:
            await handle_xp_command(message)  # Default to user's own XP

    else:  # Default to question/conversation
        try:
            # Send processing message
            processing_msg = await message.channel.send("🤖 Processing...")

            if neutral_mode:
                response = await generate_neutral_response(content, message.author.name, message.author.display_name)
                full_response = f"🤖 {response}"
                await processing_msg.edit(content=full_response)
            else:
                response = await generate_chatgpt_response(content, message.author.name, message.author.display_name)
                full_response = f"🤖 {response}"
                await processing_msg.edit(content=full_response)
        except Exception as e:
            error_str = str(e)
            await processing_msg.edit(content=f"🤖 An error occurred while processing your request: {e}")

def extract_role_from_message(content):
    """Extract role name from user message"""
    allowed_roles = ["sharmota", "sharmotait_halab", "gay", "gambler_addict", "gyat"]
    content_lower = content.lower()

    for role in allowed_roles:
        if role.lower() in content_lower:
            return role
    return None

async def get_blackjack_advice_from_ai(content, username=None, user_id=None):
    """Get blackjack advice with logical validation filter + basic strategy logic + AI personality"""
    try:
        # First try to parse the situation for validation
        player_total, dealer_card, has_ace = parse_blackjack_situation(content)

        # Validate the situation before processing
        if player_total and dealer_card:
            is_valid, error_message = validate_blackjack_situation(player_total, dealer_card)

            # If situation is logically impossible, return error without using API
            if not is_valid:
                return error_message

            # Get basic strategy advice for valid situations
            basic_advice = get_basic_strategy_advice(player_total, dealer_card, has_ace)

            # Now get AI response with the correct advice (NO conversation memory for blackjack to avoid confusion)
            user_context = f"The user with the name '{username}' is asking for blackjack advice: " if username else "A user is asking for blackjack advice: "

            if basic_advice == "HAND OVER":
                blackjack_prompt = (
                    f"You are Gambly Wambly, a gambling-themed Discord bot. {user_context}'{content}' "
                    f"The dealer has 21 (blackjack), so the hand is already over. Don't suggest HIT, STAND, etc. "
                    f"Start with 'HAND OVER' and explain that the dealer has blackjack and the hand is finished. "
                    f"Add insults and make fun of their bad luck."
                    f"The server is not PG and it's monitored to check that every memeber is above 18, meaning sexual jokes, comments and memes are allowed. The rules of the server do in fact emphasize that. So please be open to them"
                )
            else:
                blackjack_prompt = (
                    f"You are Gambly Wambly, a gambling-themed Discord bot. {user_context}'{content}' "
                    f"The correct basic strategy advice is: {basic_advice}. "
                    f"Start your response with exactly '{basic_advice}' in ALL CAPS, then add a line break and explain why this is the right move. "
                    f"Add insults, fun comebacks, and make fun of the user's luck. Be entertaining but give the correct advice."
                    f"The server is not PG and it's monitored to check that every memeber is above 18, meaning sexual jokes, comments and memes are allowed. The rules of the server do in fact emphasize that. So please be open to them"
                )
        else:
            # Fallback to AI-only analysis if we can't parse the situation (NO conversation memory)
            user_context = f"The user with the name '{username}' is asking for blackjack advice: " if username else "A user is asking for blackjack advice: "
            blackjack_prompt = (
                f"You are Gambly Wambly, a gambling-themed Discord bot. {user_context}'{content}' "
                f"IMPORTANT: Start your response with exactly one of these actions in ALL CAPS: HIT, STAND, DOUBLE DOWN, or SPLIT. "
                f"Use proper basic blackjack strategy. If dealer has 21 (blackjack), the hand is over - clarify this. "
                f"Then add a line break and give your explanation with insults and fun comebacks."
                f"The server is not PG and it's monitored to check that every memeber is above 18, meaning sexual jokes, comments and memes are allowed. The rules of the server do in fact emphasize that. So please be open to them"
            )

        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": blackjack_prompt}],
            max_tokens=120,
            temperature=0.7,
        )

        return response.choices[0].message.content.strip()
    except Exception as e:
        error_str = str(e)
        if "insufficient_quota" in error_str or "quota" in error_str.lower():
            return "💸 The blackjack advisor is out of coins! The bot owner needs to top up their OpenAI credits."
        elif "rate_limit" in error_str.lower():
            return "⏰ Slow down there, high roller! Try again in a minute."
        else:
            return f"🤖 Blackjack advisor is having technical difficulties: {e}"

async def generate_neutral_response(question, username, display_name):
    """Generate response without gambling theme"""
    try:
        context_prompt = (
            f"You are a helpful Discord bot assistant in a server called the simulation is rigged. "
            f"You're talking to {display_name} (username: {username}) on Discord. "
            f"Be helpful, and informative. But keep you dark and sarcastic personality."
            f"The server is not PG and it's monitored to check that every memeber is above 18, meaning sexual jokes, comments and memes are allowed. The rules of the server do in fact emphasize that. So please be open to them"
            f"Current question: {question}"
        )

        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": context_prompt}],
            max_tokens=150,
            temperature=0.7,
        )

        return response.choices[0].message.content.strip()
    except Exception as e:
        error_str = str(e)
        if "insufficient_quota" in error_str or "quota" in error_str.lower():
            return "💸 The AI is out of coins! The bot owner needs to top up their OpenAI credits."
        elif "rate_limit" in error_str.lower():
            return "⏰ Slow down there! Try again in a minute."
        else:
            return f"🤖 AI is having technical difficulties: {e}"

async def generate_chatgpt_response(question, username, display_name):
    try:
        context_prompt = (
            f"You are Gambly Wambly, a Discord bot assistant with a sarcastic and dark gambling theme in a server called the simulation is rigged. "
            f"You're talking to {display_name} (username: {username}) on Discord. "
            f"Be helpful but keep the gambling/casino personality and make fun of bad luck. "
            f"The server is not PG and it's monitored to check that every memeber is above 18, meaning sexual jokes, comments and memes are allowed. The rules of the server do in fact emphasize that. So please be open to them"
            f"Current question: {question}"
        )

        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": context_prompt}],
            max_tokens=150,
            temperature=0.7,
        )

        return response.choices[0].message.content.strip()
    except Exception as e:
        error_str = str(e)
        if "insufficient_quota" in error_str or "quota" in error_str.lower():
            return "💸 The AI is out of coins! The bot owner needs to top up their OpenAI credits."
        elif "rate_limit" in error_str.lower():
            return "⏰ Slow down there! Try again in a minute."
        else:
            return f"🤖 AI is having technical difficulties: {e}"

async def generate_chatgpt_roast(username, display_name, avatar_url, context=""):
    """Generate a roast using full context and profile image analysis"""
    try:
        # Very gentle prompt to avoid safety filters
        base_prompt = (
            f"You are Gambly Wambly, a fun Discord bot making playful jokes. "
            f"Write a dark, humorous comment about {display_name} (username: {username}). "
            f"It's comebacks between friends - silly, funny, and harmless. But powerful. "
            f"Think of it like playful banter, actual roasting. Keep it fun and creative while still being dark and tough."
        )

        # Add context if provided
        if context:
            base_prompt += f" Include this context in your roast: '{context}'"

        # If we have an avatar, analyze it for more personalized roasting
        if avatar_url:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text", 
                            "text": f"{base_prompt} Also comment on what you see in their profile picture for extra comedic effect."
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": avatar_url}
                        }
                    ]
                }
            ]
            model = "gpt-4o"  # Use vision model for image analysis
        else:
            messages = [{"role": "user", "content": base_prompt}]
            model = "gpt-3.5-turbo"

        response = openai_client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=120,
            temperature=0.8,
        )

        result = response.choices[0].message.content.strip()

        # Check if AI refused and provide fallback
        if any(phrase in result.lower() for phrase in ["i can't", "i'm sorry", "i cannot", "not appropriate", "not able to"]):
            fallback_roasts = [
                f"looks like someone who still thinks flip phones are cutting-edge technology! 📱",
                f"the type of person who gets excited about grocery store grand openings! 🛒✨",
                f"probably asks for the manager when their Wi-Fi is 'only' 99% reliable! 📶😤",
                f"definitely the person who brings a calculator to split a $5 bill! 🧮💸",
                f"looks like they'd lose a debate with a magic 8-ball! 🎱🤔",
                f"the human equivalent of buffering at 99%! ⏳💔",
                f"probably thinks 'Netflix and chill' means watching documentaries about penguins! 🐧📺",
                f"definitely celebrates their Duolingo streak more than their birthday! 🦉🎉",
                f"the type who asks 'are we there yet?' on a 5-minute car ride! 🚗😫",
                f"looks like they'd get lost following GPS in their own driveway! 🗺️🏠",
                f"probably thinks 'going viral' means catching the flu! 🤧📈",
                f"definitely the person who brings homework to a party! 📚🎊"
            ]
            return random.choice(fallback_roasts)

        return result

    except Exception as e:
        error_str = str(e)
        if "insufficient_quota" in error_str or "quota" in error_str.lower():
            return "Nah you have to pay for that shit. 💸 Or try again later."
        elif "rate_limit" in error_str.lower():
            return "⏰ Slow down there, roast master! Try again in a minute."
        else:
            # Fallback roast if API fails
            fallback_roasts = [
                f"so basic that even the AI needed a coffee break! ☕🤖",
                f"congratulations, you broke the roast machine with your... uniqueness! 🎉🔧",
                f"the servers are too busy laughing at you to respond! 😂💻",
                f"even ChatGPT said 'nah, I'm good' and went offline! 🤖💤",
                f"you're so unique that the AI needs to update its database! 🔄📚"
            ]
            return random.choice(fallback_roasts)

async def handle_bonk_command(message, target=None):
    author = message.author

    if not target:
        target = message.mentions[0] if message.mentions else None

    if author.id in abusers:
        await message.channel.send(f"😏 Nice try {author.mention}, but you bonk too much. Chill.")
        return

    if not target:
        await message.channel.send("❌ You need to mention someone to bonk! Example: `$bot bonk @user`")
        return

    if not target.voice or not target.voice.channel:
        await message.channel.send(f"🤷 {target.display_name} is not in a voice channel.")
        return

    now = time.time()
    bonk_tracker[author.id] = [t for t in bonk_tracker[author.id] if now - t < 600]
    bonk_tracker[author.id].append(now)

    if len(bonk_tracker[author.id]) > 3:
        abusers.add(author.id)
        await message.channel.send(f"🚨 {author.mention}, you've been bonk-banned for abusing the system.")
        return

    try:
        await target.move_to(None)

        # Funny bonk messages
        bonk_messages = [
            f"🔨 BONK! {target.mention} got yeeted into the shadow realm by {author.mention}! 💀",
            f"⚡ ZAP! {target.mention} has been teleported to the land of disconnected dreams by {author.mention}! ✨",
            f"🚀 WHOOSH! {target.mention} just got launched into orbit by {author.mention}! 🌌",
            f"💥 BAM! {target.mention} got slapped so hard they disconnected from reality by {author.mention}! 🤪",
            f"🌪️ TORNADO KICK! {target.mention} got spun into another dimension by {author.mention}! 🌀",
            f"🎪 POOF! {target.mention} vanished like a bad magic trick thanks to {author.mention}! 🎭",
            f"⚰️ RIP {target.mention} - cause of death: absolutely destroyed by {author.mention}! 💀",
            f"🏌️ FORE! {target.mention} got golf-clubbed out of existence by {author.mention}! ⛳",
            f"🎯 BULLSEYE! {target.mention} got precision-deleted by sniper {author.mention}! 🎪",
            f"🧨 KABOOM! {target.mention} exploded into digital confetti courtesy of {author.mention}! 🎊",
            f"🥊 KNOCKOUT! {target.mention} got punched into next week by {author.mention}! 📅",
            f"🌮 TACO BELL'D! {target.mention} got sent to the bathroom dimension by {author.mention}! 🚽"
        ]

        random_message = random.choice(bonk_messages)
        await message.channel.send(random_message)
    except discord.Forbidden:
        await message.channel.send("🚫 I don't have permission to bonk that user.")
    except Exception as e:
        await message.channel.send(f"⚠️ Something went wrong: {e}")

async def handle_unbonk_command(message, target=None):
    if not message.author.guild_permissions.manage_messages:
        await message.channel.send("🚫 You don't have permission to unbonk anyone.")
        return

    if not target:
        target = message.mentions[0] if message.mentions else None

    if not target:
        await message.channel.send("❌ You need to mention someone to unbonk.")
        return

    abusers.discard(target.id)
    bonk_tracker.pop(target.id, None)
    await message.channel.send(f"✅ {target.mention} has been unbonked. Use your powers wisely.")

async def handle_move_command(message, content):
    # Check if user has admin permissions
    if not message.author.guild_permissions.administrator:
        await message.channel.send("🚫 Only administrators can move users between voice channels.")
        return

    target = message.mentions[0] if message.mentions else None

    if not target:
        await message.channel.send("❌ You need to mention someone to move! Example: `$bot move @user to General`")
        return

    if not target.voice or not target.voice.channel:
        await message.channel.send(f"🤷 {target.display_name} is not in a voice channel.")
        return

    # Extract channel name from the message
    content_lower = content.lower()

    # Find "to" keyword and extract everything after it as channel name
    if " to " in content_lower:
        channel_name = content.split(" to ", 1)[1].strip()
        # Remove any mentions from the channel name
        for mention in message.mentions:
            channel_name = channel_name.replace(f"@{mention.name}", "").replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
        channel_name = channel_name.strip()
    else:
        await message.channel.send("❌ Please specify the target channel! Example: `$bot move @user to General`")
        return

    if not channel_name:
        await message.channel.send("❌ Please specify a valid channel name! Example: `$bot move @user to General`")
        return

    # Find the voice channel by name (case insensitive, partial match)
    target_channel = None
    channel_name_clean = channel_name.lower().strip()

    # First try exact match
    for channel in message.guild.voice_channels:
        if channel.name.lower() == channel_name_clean:
            target_channel = channel
            break

    # If no exact match, try partial match (channel name contains the search term)
    if not target_channel:
        for channel in message.guild.voice_channels:
            if channel_name_clean in channel.name.lower():
                target_channel = channel
                break

    if not target_channel:
        available_channels = [vc.name for vc in message.guild.voice_channels]
        channels_list = ", ".join(available_channels) if available_channels else "None"
        await message.channel.send(f"❌ Voice channel '{channel_name}' not found.\n📋 Available channels: {channels_list}")
        return

    try:
        await target.move_to(target_channel)

        move_messages = [
            f"📍 {target.mention} has been teleported to **{target_channel.name}** by admin {message.author.mention}! ✨",
            f"🚀 WHOOSH! {target.mention} got launched to **{target_channel.name}** by {message.author.mention}! 🌌",
            f"🎯 PRECISION MOVE! {target.mention} successfully relocated to **{target_channel.name}** by {message.author.mention}! 🎪",
            f"🌪️ PORTAL ACTIVATED! {target.mention} warped to **{target_channel.name}** courtesy of {message.author.mention}! 🌀",
            f"⚡ ZAP! {target.mention} has been admin-transported to **{target_channel.name}** by {message.author.mention}! ✨"
        ]

        random_message = random.choice(move_messages)
        await message.channel.send(random_message)

    except discord.Forbidden:
        await message.channel.send("🚫 I don't have permission to move that user to the specified channel.")
    except Exception as e:
        await message.channel.send(f"⚠️ Something went wrong while moving the user: {e}")

async def handle_ban_command(message, content):
    """Ban a user from the server (Administrator only)"""
    if not message.author.guild_permissions.administrator:
        await message.channel.send("🚫 Only administrators can ban users.")
        return

    target = message.mentions[0] if message.mentions else None

    if not target:
        await message.channel.send("❌ You need to mention someone to ban! Example: `$bot ban @user spamming`")
        return

    if target == message.author:
        await message.channel.send("❌ You can't ban yourself!")
        return

    if target.guild_permissions.administrator:
        await message.channel.send("❌ You can't ban another administrator!")
        return

    # Extract reason from the message
    reason = content
    for mention in message.mentions:
        reason = reason.replace(f"@{mention.name}", "").replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
    reason = reason.replace("ban", "").strip()

    # Store whether reason was actually provided
    reason_provided = bool(reason)
    if not reason:
        reason = "No reason provided"

    try:
        await target.ban(reason=f"Banned by {message.author.name}: {reason}")

        ban_messages = [
            f"🔨 HAMMER DOWN! {target.mention} has been permanently banned by {message.author.mention}! 💀",
            f"⚖️ JUSTICE SERVED! {target.mention} got the ultimate ban hammer from {message.author.mention}! 🔨",
            f"🚪 EXIT STAGE LEFT! {target.mention} has been shown the door by {message.author.mention}! 👋",
            f"💥 BOOM! {target.mention} got banned into the shadow realm by {message.author.mention}! 🌑",
            f"🎭 FINAL CURTAIN! {target.mention} has been permanently removed from the show by {message.author.mention}! 🎪"
        ]

        random_message = random.choice(ban_messages)
        embed = discord.Embed(
            title="🔨 User Banned",
            description=f"{random_message}\n**Reason:** {reason}",
            color=discord.Color.red()
        )
        await message.channel.send(embed=embed)

        # Log to moderation channel
        await log_moderation_action("BAN", message.author, target, reason, message.channel)

        # Alert if no reason was provided
        if not reason_provided:
            await alert_missing_reason("BAN", message.author, target)

    except discord.Forbidden:
        await message.channel.send("🚫 I don't have permission to ban that user.")
    except Exception as e:
        await message.channel.send(f"⚠️ Something went wrong while banning: {e}")

async def handle_kick_command(message, content):
    """Kick a user from the server (Administrator only)"""
    if not message.author.guild_permissions.administrator:
        await message.channel.send("🚫 Only administrators can kick users.")
        return

    target = message.mentions[0] if message.mentions else None

    if not target:
        await message.channel.send("❌ You need to mention someone to kick! Example: `$bot kick @user being disruptive`")
        return

    if target == message.author:
        await message.channel.send("❌ You can't kick yourself!")
        return

    if target.guild_permissions.administrator:
        await message.channel.send("❌ You can't kick another administrator!")
        return

    # Extract reason from the message
    reason = content
    for mention in message.mentions:
        reason = reason.replace(f"@{mention.name}", "").replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
    reason = reason.replace("kick", "").strip()

    # Store whether reason was actually provided
    reason_provided = bool(reason)
    if not reason:
        reason = "No reason provided"

    try:
        await target.kick(reason=f"Kicked by {message.author.name}: {reason}")

        kick_messages = [
            f"👢 BOOT TO THE FACE! {target.mention} got kicked out by {message.author.mention}! 🦵",
            f"🚪 OUT YOU GO! {target.mention} has been shown the exit by {message.author.mention}! 👋",
            f"⚡ ZAP! {target.mention} got electrically ejected by {message.author.mention}! ⚡",
            f"🎪 YEETED! {target.mention} got launched out of the server by {message.author.mention}! 🚀",
            f"🥾 KICKED! {target.mention} got the boot from {message.author.mention}! 👢"
        ]

        random_message = random.choice(kick_messages)
        embed = discord.Embed(
            title="👢 User Kicked",
            description=f"{random_message}\n**Reason:** {reason}",
            color=discord.Color.orange()
        )
        await message.channel.send(embed=embed)

        # Log to moderation channel
        await log_moderation_action("KICK", message.author, target, reason, message.channel)

        # Alert if no reason was provided
        if not reason_provided:
            await alert_missing_reason("KICK", message.author, target)

    except discord.Forbidden:
        await message.channel.send("🚫 I don't have permission to kick that user.")
    except Exception as e:
        await message.channel.send(f"⚠️ Something went wrong while kicking: {e}")

async def handle_timeout_command(message, content):
    """Timeout a user (Administrator only)"""
    if not message.author.guild_permissions.administrator:
        await message.channel.send("🚫 Only administrators can timeout users.")
        return

    target = message.mentions[0] if message.mentions else None

    if not target:
        await message.channel.send("❌ You need to mention someone to timeout! Example: `$bot timeout @user 10m spamming`")
        return

    if target == message.author:
        await message.channel.send("❌ You can't timeout yourself!")
        return

    if target.guild_permissions.administrator:
        await message.channel.send("❌ You can't timeout another administrator!")
        return

    # Parse duration and reason from content
    import re

    # Extract duration (e.g., 5m, 1h, 30s)
    duration_match = re.search(r'(\d+)([smhd])', content.lower())
    if not duration_match:
        await message.channel.send("❌ Please specify a duration! Examples: `5m`, `1h`, `30s`, `2d`\nUsage: `$bot timeout @user 10m reason`")
        return

    duration_value = int(duration_match.group(1))
    duration_unit = duration_match.group(2)

    # Convert to timedelta
    if duration_unit == 's':
        timeout_duration = timedelta(seconds=duration_value)
    elif duration_unit == 'm':
        timeout_duration = timedelta(minutes=duration_value)
    elif duration_unit == 'h':
        timeout_duration = timedelta(hours=duration_value)
    elif duration_unit == 'd':
        timeout_duration = timedelta(days=duration_value)

    # Check maximum timeout (28 days)
    if timeout_duration > timedelta(days=28):
        await message.channel.send("❌ Maximum timeout duration is 28 days!")
        return

    # Extract reason
    reason = content
    for mention in message.mentions:
        reason = reason.replace(f"@{mention.name}", "").replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
    reason = reason.replace("timeout", "").strip()
    reason = re.sub(r'\d+[smhd]', '', reason).strip()  # Remove duration from reason

    # Store whether reason was actually provided
    reason_provided = bool(reason)
    if not reason:
        reason = "No reason provided"

    try:
        until = discord.utils.utcnow() + timeout_duration
        await target.timeout(until, reason=f"Timed out by {message.author.name}: {reason}")

        timeout_messages = [
            f"⏰ TIME OUT! {target.mention} got silenced for {duration_value}{duration_unit} by {message.author.mention}! 🤐",
            f"🔇 MUTED! {target.mention} is in timeout jail for {duration_value}{duration_unit} thanks to {message.author.mention}! 🚔",
            f"⏸️ PAUSED! {target.mention} got put on ice for {duration_value}{duration_unit} by {message.author.mention}! 🧊",
            f"🚫 SILENCED! {target.mention} is taking a {duration_value}{duration_unit} break courtesy of {message.author.mention}! 😶",
            f"⏱️ CLOCK OUT! {target.mention} is in timeout for {duration_value}{duration_unit} by order of {message.author.mention}! ⚖️"
        ]

        random_message = random.choice(timeout_messages)
        embed = discord.Embed(
            title="⏰ User Timed Out",            description=f"{random_message}\n**Duration:** {duration_value}{duration_unit}\n**Reason:** {reason}\n**Until:** <t:{int(until.timestamp())}:F>",
            color=discord.Color.yellow()
        )
        await message.channel.send(embed=embed)

        # Log to moderation channel
        await log_moderation_action("TIMEOUT", message.author, target, f"{reason} (Duration: {duration_value}{duration_unit})", message.channel, until)

        # Alert if no reason was provided
        if not reason_provided:
            await alert_missing_reason("TIMEOUT", message.author, target)

    except discord.Forbidden:
        await message.channel.send("🚫 I don't have permission to timeout that user.")
    except Exception as e:
        await message.channel.send(f"⚠️ Something went wrong while timing out: {e}")

async def handle_purge_command(message):
    """Purge messages from channel (Moderator only)"""
    # Check if user has manage_messages permission (moderator level)
    if not message.author.guild_permissions.manage_messages:
        await message.channel.send("🚫 Only moderators can use the purge command.")
        return

    content = message.content[6:].strip()  # Remove "$clear" prefix

    # Default to 10 messages if no number specified
    try:
        if content:
            amount = int(content)
            if amount <= 0:
                await message.channel.send("❌ Please specify a positive number of messages to delete.")
                return
            if amount > 100:
                await message.channel.send("❌ Maximum 100 messages can be deleted at once.")
                return
        else:
            amount = 10
    except ValueError:
        await message.channel.send("❌ Please specify a valid number of messages to delete. Example: `$clear 20`")
        return

    try:
        # Delete the command message first
        await message.delete()

        # Purge the specified number of messages
        deleted = await message.channel.purge(limit=amount)

        # Send confirmation message that will auto-delete
        confirm_msg = await message.channel.send(f"🧹 **Purged {len(deleted)} messages** by {message.author.mention}")

        # Auto-delete the confirmation message after 5 seconds
        await confirm_msg.delete(delay=5)

        # Log to moderation channel
        log_channel = client.get_channel(MODERATION_LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="🧹 Channel Purge",
                description=f"**Moderator:** {message.author.mention} ({message.author.name})\n"
                           f"**Channel:** {message.channel.mention}\n"
                           f"**Messages Deleted:** {len(deleted)}\n"
                           f"**Time:** <t:{int(time.time())}:F>",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=message.author.avatar.url if message.author.avatar else message.default_avatar.url)
            embed.set_footer(text=f"Moderator ID: {message.author.id}")
            await log_channel.send(embed=embed)

    except discord.Forbidden:
        await message.channel.send("🚫 I don't have permission to delete messages in this channel.")
    except discord.HTTPException as e:
        if "50034" in str(e):  # Bulk delete messages too old
            await message.channel.send("❌ Can't delete messages older than 14 days. Try a smaller number.")
        else:
            await message.channel.send(f"⚠️ Something went wrong while purging: {e}")
    except Exception as e:
        await message.channel.send(f"⚠️ Unexpected error during purge: {e}")

async def handle_role_command(message, role_name):
    member = message.author
    blocked_roles = ["admin", "administrator", "mod", "moderator", "owner", "staff"]
    allowed_roles = ["sharmota", "sharmotait_halab", "gay", "Gambler_addict", "gyat"]

    role = discord.utils.get(message.guild.roles, name=role_name)
    allowed_roles_display = "- " + "\n- ".join(allowed_roles)

    if role is None:
        await message.channel.send(
            f"❌ The role '**{role_name}**' doesn't exist or isn't allowed.\n"
            f"👉 You can ask for one of these roles:\n{allowed_roles_display}"
        )
        return

    if role.name.lower() in blocked_roles or role.permissions.administrator:
        await message.channel.send(f"❌ The role '**{role_name}**' can only be given by a Mod.")
        return

    if role.name.lower() not in allowed_roles:
        await message.channel.send(
            f"❌ You can't assign yourself the role '**{role_name}**'.\n"
            f"👉 Try one of the allowed roles:\n{allowed_roles_display}"
        )
        return

    try:
        await member.add_roles(role)
        await message.channel.send(f"✅ {member.mention} has been given the role: **{role.name}**!")
    except discord.Forbidden:
        await message.channel.send("🚫 I don't have permission to assign that role.")
    except Exception as e:
        await message.channel.send(f"⚠️ Something went wrong: {e}")

async def handle_image_analysis_with_question(message, question):
    try:
        # Send processing message
        processing_msg = await message.channel.send("🤖 Processing image analysis...")

        for attachment in message.attachments:
            if attachment.content_type.startswith('image'):
                try:
                    image_url = attachment.url
                    response = openai_client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": f"You are Gambly Wambly, a Discord bot with a gambling theme. Answer this question about the image: {question}"},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": image_url,
                                        },
                                    },
                                ],
                            }
                        ],
                        max_tokens=300,
                    )
                    image_description = response.choices[0].message.content
                    await processing_msg.edit(content=f"🤖 {image_description}")
                    return

                except Exception as e:
                    error_str = str(e)
                    if "insufficient_quota" in error_str or "quota" in error_str.lower():
                        await processing_msg.edit(content="💸 The image analysis feature is out of coins! The bot owner needs to top up their OpenAI credits.")
                    elif "rate_limit" in error_str.lower():
                        await processing_msg.edit(content="⏰ Slow down there! Try again in a minute.")
                    else:
                        await processing_msg.edit(content=f"⚠️ Image analysis failed: {e}")
                    return
            else:
                await processing_msg.edit(content="❌ Attachment is not an image.")
                return
    except Exception as e:
        await message.channel.send(f"⚠️ Image analysis setup failed: {e}")

async def handle_image_command(message):
    try:
        # Send processing message
        processing_msg = await message.channel.send("🤖 Processing image analysis...")

        if message.attachments:
            for attachment in message.attachments:
                if attachment.content_type.startswith('image'):
                    try:
                        image_url = attachment.url
                        response = openai_client.chat.completions.create(
                            model="gpt-4o",
                            messages=[
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": "What's in this image?"},
                                        {
                                            "type": "image_url",
                                            "image_url": {
                                                "url": image_url,
                                            },
                                        },
                                    ],
                                }
                            ],
                            max_tokens=300,
                        )
                        image_description = response.choices[0].message.content
                        await processing_msg.edit(content=f"🤖 Image analysis: {image_description}")

                    except Exception as e:
                        await processing_msg.edit(content=f"⚠️ Image analysis failed: {e}")
                else:
                    await processing_msg.edit(content="❌ No image attached. Please attach an image to analyze.")
        else:
            await processing_msg.edit(content="❌ No image attached. Please attach an image to analyze.")
    except Exception as e:
        await message.channel.send(f"⚠️ Image analysis setup failed: {e}")

async def assign_role(member, role_name):
    role = discord.utils.get(member.guild.roles, name=role_name)
    if role is None:
        print(f"Role '{role_name}' not found in the server.")
        return

    try:
        await member.add_roles(role)
        print(f"Assigned role '{role.name}' to {member.name}.")
    except discord.Forbidden:
        print("Bot does not have permission to assign this role.")
    except Exception as e:
        print(f"Failed to assign role: {e}")

async def text_to_speech_and_play(text, voice_client):
    """Convert text to speech using OpenAI TTS and play in voice channel"""
    if not voice_client or not voice_client.is_connected():
        print("No voice connection available for TTS")
        return

    try:
        print(f"Starting TTS for text: {text[:50]}...")

        # Generate TTS audio using OpenAI
        response = openai_client.audio.speech.create(
            model="tts-1",
            voice="alloy",  # You can change this to: alloy, echo, fable, onyx, nova, shimmer
            input=text,
            response_format="mp3"
        )

        # Save to temporary file
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
            temp_file_path = temp_file.name
            response.stream_to_file(temp_file_path)

        print(f"TTS file created: {temp_file_path}")

        # Play the audio
        await play_tts_audio(voice_client, temp_file_path)

    except Exception as e:
        print(f"TTS failed: {e}")

async def play_tts_audio(voice_client, audio_file_path):
    """Play TTS audio in voice channel"""
    try:
        if not voice_client.is_connected():
            print("Voice client not connected")
            return

        # Wait for music to pause/stop before TTS
        if voice_client.is_playing():
            voice_client.pause()
            await asyncio.sleep(0.5)

        print(f"Playing TTS audio: {audio_file_path}")

        # Create audio source with better options
        audio_source = discord.FFmpegPCMAudio(
            audio_file_path,
            options='-vn -filter:a "volume=0.7,aresample=48000" -reconnect 1 -reconnect_streamed 1'
        )

        def cleanup_tts(error):
            if error:
                print(f"TTS playback error: {error}")
            else:
                print("TTS playback completed successfully")

            # Resume music if it was paused
            try:
                if voice_client.is_paused():
                    voice_client.resume()
            except:
                pass

            # Clean up temp file
            try:
                import os
                os.unlink(audio_file_path)
                print(f"Cleaned up TTS file: {audio_file_path}")
            except Exception as e:
                print(f"Failed to clean up TTS file: {e}")

        voice_client.play(audio_source, after=cleanup_tts)
        print("TTS playback started")

    except Exception as e:
        print(f"Error playing TTS audio: {e}")
        # Resume music on error
        try:
            if voice_client.is_paused():
                voice_client.resume()
        except:
            pass
        # Try to clean up on error
        try:
            import os
            os.unlink(audio_file_path)
        except:
            pass

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    # Check if user has the "ibb" role and ignore them
    if hasattr(message.author, 'roles'):
        for role in message.author.roles:
            if role.name.lower() == "ibb":
                return

    # Anti-spam check
    user_id = message.author.id
    now = time.time()

    # Remove timestamps older than the time window
    spam_tracker[user_id] = [timestamp for timestamp in spam_tracker[user_id] if now - timestamp < TIME_WINDOW]

    # Check if user exceeded message limit
    if len(spam_tracker[user_id]) >= MESSAGE_LIMIT:
        notification_tracker[user_id] += 1

        # Check if they hit the notification limit
        if notification_tracker[user_id] >= NOTIFICATION_LIMIT:
            # Assign spammer role
            spammer_role = discord.utils.get(message.guild.roles, name=SPAMMER_ROLE_NAME)
            role_assigned = False

            if spammer_role:
                try:
                    await message.author.add_roles(spammer_role)
                    role_assigned = True
                except discord.Forbidden:
                    print(f"No permission to assign {SPAMMER_ROLE_NAME} role to {message.author.name}")
                except Exception as e:
                    print(f"Failed to assign spammer role: {e}")
            else:
                print(f"Spammer role '{SPAMMER_ROLE_NAME}' not found in server")

            # Report incident to specific channel
            report_channel_id = 1378124359834669207
            report_channel = client.get_channel(report_channel_id)

            if report_channel:
                role_status = "✅ Role assigned" if role_assigned else "❌ Role assignment failed"
                embed = discord.Embed(
                    title="🚨 Spam Incident Report",
                    description=f"**User:** {message.author.mention} ({message.author.name})\n"
                               f"**User ID:** {message.author.id}\n"
                               f"**Channel:** {message.channel.mention}\n"
                               f"**Reason:** Exceeded {NOTIFICATION_LIMIT} spam warnings\n"
                               f"**Role Status:** {role_status}\n"
                               f"**Time:** <t:{int(now)}:F>",
                    color=discord.Color.red()
                )
                embed.set_thumbnail(url=message.author.avatar.url if message.author.avatar else message.default_avatar.url)

                try:
                    await report_channel.send(embed=embed)
                except Exception as e:
                    print(f"Failed to send report to channel: {e}")

            # Reset counters after reporting
            notification_tracker[user_id] = 0
            spam_tracker[user_id] = []

            role_message = f" and assigned the {SPAMMER_ROLE_NAME} role" if role_assigned else ""
            await message.channel.send(f"🚨 {message.author.mention}, your spam behavior has been reported to the moderators{role_message}. Please slow down!")
            return

        await message.channel.send(f"🚫 {message.author.mention}, you are sending messages too quickly! Please slow down. ({notification_tracker[user_id]}/{NOTIFICATION_LIMIT} warnings)")
        return

    # Add current timestamp to the tracker
    spam_tracker[user_id].append(now)

    # Handle dedicated chat channel (no commands needed)
    if message.channel.id == CHAT_CHANNEL_ID:
        await handle_chat_channel_message(message)
        return

    # Handle therapy channel for gambling addiction support
    if message.channel.id == THERAPY_CHANNEL_ID:
        await handle_therapy_channel_message(message)
        return

    # Handle prompt-free channel with minimal prompting
    if message.channel.id == PROMPT_FREE_CHANNEL_ID:
        await handle_prompt_free_channel_message(message)
        return

    # Voice chat commands
    if message.content.startswith('$voice'):
        content = message.content[7:].strip()  # Remove "$voice " prefix
        await handle_voice_commands(message, content)
        return

    # Main bot command - now intelligent
    if message.content.startswith('$bot'):
        # Log the bot command
        await log_bot_command(message.author, message.content, message.channel, success=True, details="Bot command executed")
        await handle_intelligent_request(message)
        return

    # Purge command for moderators only
    if message.content.startswith('$clear'):
        await handle_purge_command(message)
        return

    # Music commands using ! prefix
    if message.content.startswith('!play '):
        song = message.content[6:]
        await play_music(message, song)
    elif message.content == '!pause':
        await pause_music(message)
    elif message.content == '!resume':
        await resume_music(message)
    elif message.content == '!stop':
        await stop_music(message)
    elif message.content == '!skip':
        await skip_music(message)
    elif message.content == '!queue':
        await show_queue(message)
    elif message.content == '!help':
        embed = discord.Embed(
            title="🎵 Music Bot Commands",
            description="**Music Commands:**\n"
                       "`!play <song>` - Play a song\n"
                       "`!pause` - Pause music\n"
                       "`!resume` - Resume music\n"
                       "`!stop` - Stop and disconnect\n"
                       "`!skip` - Skip current song\n"
                       "`!queue` - Show queue\n"
                       "`!debug` - Show connection status",
            color=discord.Color.blue()
        )
        await message.channel.send(embed=embed)
    elif message.content == '!debug':
        voice_client = discord.utils.get(client.voice_clients, guild=message.guild)
        if voice_client:
            status = f"Connected to: {voice_client.channel.name}\n"
            status += f"Is connected: {voice_client.is_connected()}\n"
            status += f"Is playing: {voice_client.is_playing()}\n"
            status += f"Is paused: {voice_client.is_paused()}\n"
            status += f"Latency: {voice_client.latency:.2f}s\n"

            guild_id = message.guild.id
            queue_length = len(music_queues.get(guild_id, []))
            status += f"Queue length: {queue_length}\n"

            if guild_id in now_playing:
                status += f"Now playing: {now_playing[guild_id]['title']}"
            else:
                status += "Nothing currently playing"
        else:
            status = "Not connected to any voice channel"

        embed = discord.Embed(
            title="🔧 Music Bot Debug Info",
            description=status,
            color=discord.Color.orange()
        )
        await message.channel.send(embed=embed)

    # Handle trivia answers
    if message.channel.id in active_trivia:
        trivia_handled = await handle_trivia_answer(message)
        if trivia_handled:
            return

    # Keep $test for debugging
    if message.content.startswith('$test'):
        await message.channel.send('I am up and running! Use `$bot <your request>` and I\'ll understand what you want!')

try:
    token = os.getenv("TOKEN") or ""
    if token == "":
        raise Exception("Please add your token to the Secrets pane.")
    client.run(token)
except discord.HTTPException as e:
    if e.status == 429:
        print("Too many requests to Discord. See: https://stackoverflow.com/questions/66724687")
    else:
        raise e