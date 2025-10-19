import discord
from discord.ext import commands
import asyncio
import yt_dlp as youtube_dl
import os
import json
import platform
import urllib.request
import zipfile
import tarfile
import shutil
from dotenv import load_dotenv
import urllib.parse

# --- FFmpeg Setup ---
def setup_ffmpeg():
    """
    Checks for FFmpeg and downloads it if not found into a local ./bin directory.
    Returns the path to the FFmpeg executable.
    """
    bin_dir = os.path.join(os.getcwd(), "bin")
    
    if platform.system() == "Windows":
        ffmpeg_path = os.path.join(bin_dir, "ffmpeg.exe")
    else:
        ffmpeg_path = os.path.join(bin_dir, "ffmpeg")

    if os.path.exists(ffmpeg_path):
        print(f"[DEBUG] FFmpeg found at: {ffmpeg_path}")
        return ffmpeg_path

    print("[INFO] FFmpeg not found, starting download...")
    os.makedirs(bin_dir, exist_ok=True)

    if platform.system() == "Windows":
        url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        zip_path = os.path.join(bin_dir, "ffmpeg.zip")
        
        try:
            print(f"[INFO] Downloading from {url}...")
            urllib.request.urlretrieve(url, zip_path)
            print("[INFO] Download complete. Extracting...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for member in zip_ref.infolist():
                    if member.filename.endswith('ffmpeg.exe') or member.filename.endswith('ffprobe.exe'):
                        member.filename = os.path.basename(member.filename)
                        zip_ref.extract(member, bin_dir)
            os.remove(zip_path)
            print("[INFO] FFmpeg setup complete.")
            return ffmpeg_path
        except Exception as e:
            print(f"[FATAL] Error downloading/extracting FFmpeg: {e}")
            return None

    elif platform.system() == "Linux":
        arch = platform.machine()
        if arch != "x86_64":
            print(f"[FATAL] Unsupported Linux architecture '{arch}'. Please install FFmpeg manually.")
            return None

        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        tar_path = os.path.join(bin_dir, "ffmpeg.tar.xz")
        
        try:
            print(f"[INFO] Downloading from {url}...")
            urllib.request.urlretrieve(url, tar_path)
            print("[INFO] Download complete. Extracting...")
            with tarfile.open(tar_path, 'r:xz') as tar_ref:
                for member in tar_ref.getmembers():
                    if member.name.endswith('/ffmpeg'):
                        member.name = os.path.basename(member.name)
                        tar_ref.extract(member, bin_dir)
                    elif member.name.endswith('/ffprobe'):
                        member.name = os.path.basename(member.name)
                        tar_ref.extract(member, bin_dir)
            
            os.chmod(ffmpeg_path, 0o755)
            os.chmod(os.path.join(bin_dir, "ffprobe"), 0o755)

            os.remove(tar_path)
            print("[INFO] FFmpeg setup complete.")
            return ffmpeg_path
        except Exception as e:
            print(f"[FATAL] Error downloading/extracting FFmpeg: {e}")
            return None
    
    print(f"[FATAL] Unsupported operating system: {platform.system()}")
    return None

# --- Bot Code ---

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

ydl_opts = {
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'outtmpl': 'downloads/%(id)s.%(ext)s',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
}

class MusicBot(commands.Cog):
    def __init__(self, bot, ffmpeg_executable):
        self.bot = bot
        self.ffmpeg_executable = ffmpeg_executable
        self.voice_client = None
        self.current_song = None
        self.song_queue = []
        self.loop = False

    async def cleanup(self, filename):
        try:
            if os.path.exists(filename):
                print(f"[DEBUG] Cleaning up file: {filename}")
                os.remove(filename)
        except Exception as e:
            print(f"[ERROR] Error during cleanup: {e}")

    async def after_playback(self, e):
        if e:
            print(f'[ERROR] Player error: {e}')

        if self.current_song and not self.loop:
            await self.cleanup(self.current_song['filename'])

        if self.loop and self.current_song:
            self.song_queue.insert(0, self.current_song)

        if self.song_queue:
            next_song_data = self.song_queue.pop(0)
            await self.play_next_song(next_song_data)
        else:
            self.current_song = None
            if self.voice_client:
                await asyncio.sleep(5) # Wait a bit before disconnecting
                if self.voice_client and not self.voice_client.is_playing():
                    await self.voice_client.disconnect()
                    self.voice_client = None

    async def play_next_song(self, song_data):
        expected_filename = song_data["filename"]
        title = song_data["title"]
        duration = song_data["duration"]
        
        if not os.path.exists(expected_filename):
            print(f"[ERROR] File not found for playback: {expected_filename}")
            # Handle this case, maybe try redownloading or just skip
            await self.after_playback(None) # Try next song
            return

        print(f"[DEBUG] Starting playback of: {expected_filename}")
        audio_source = discord.FFmpegPCMAudio(expected_filename, executable=self.ffmpeg_executable)
        
        self.voice_client.play(audio_source, after=lambda e: self.bot.loop.create_task(self.after_playback(e)))
        self.current_song = song_data

        # This part is tricky because we don't have the original context `ctx`
        # We can't send a message to the channel where the command was invoked.
        # A common solution is to save the channel ID and fetch it later.
        # For now, we'll just print to console.
        minutes, seconds = divmod(duration, 60)
        duration_str = f"{minutes}:{seconds:02d}" if duration > 0 else "Неизвестно"
        print(f"🎵 Now playing: {title} | Duration: {duration_str}")


    @commands.hybrid_command(name='play', description='Воспроизвести музыку с YouTube или добавить в очередь')
    async def play_music(self, ctx, *, query: str):
        print(f"[DEBUG] 'play' command invoked by {ctx.author} with query: \"{query}\"")
        if not ctx.author.voice:
            await ctx.send("❌ Вы должны находиться в голосовом канале!")
            return

        voice_channel = ctx.author.voice.channel
        if not voice_channel.permissions_for(ctx.guild.me).connect or not voice_channel.permissions_for(ctx.guild.me).speak:
            await ctx.send("❌ У меня нет прав для подключения или воспроизведения аудио в этом канале!")
            return

        loading_msg = await ctx.send(f"🔄 Обработка запроса `{query}`...")

        try:
            os.makedirs('downloads', exist_ok=True)
            local_ydl_opts = ydl_opts.copy()
            local_ydl_opts['ffmpeg_location'] = os.path.dirname(self.ffmpeg_executable)

            with youtube_dl.YoutubeDL(local_ydl_opts) as ydl:
                try:
                    is_url = query.strip().startswith('http')
                    search_query = query

                    if is_url and 'youtube.com' in query and 'search_query' in query:
                        parsed_url = urllib.parse.urlparse(query)
                        search_query = urllib.parse.parse_qs(parsed_url.query)['search_query'][0]
                        print(f"[DEBUG] Extracted search query from URL: '{search_query}'")
                        search_query = f"ytsearch:{search_query}"
                    elif not is_url:
                        search_query = f"ytsearch:{query}"

                    info = ydl.extract_info(search_query, download=False)

                    if 'entries' in info:
                        if not info['entries']:
                            await loading_msg.edit(content=f"❌ Ничего не найдено по запросу: `{query}`")
                            return
                        video_info = info['entries'][0]
                    else:
                        video_info = info
                    
                    video_id = video_info['id']
                    title = video_info.get('title', 'Неизвестная песня')
                    duration = video_info.get('duration', 0)
                    webpage_url = video_info['webpage_url']
                    expected_filename = os.path.join('downloads', f"{video_id}.mp3")

                    song_data = {
                        "filename": expected_filename,
                        "title": title,
                        "duration": duration,
                        "webpage_url": webpage_url,
                        "requester": ctx.author.mention
                    }

                    if not os.path.exists(expected_filename):
                        await loading_msg.edit(content=f"📥 Загружаю `{title}`...")
                        ydl.download([webpage_url])

                except Exception as e:
                    print(f"[ERROR] Exception during yt-dlp processing: {e}")
                    await loading_msg.edit(content=f"❌ Ошибка при обработке запроса: {e}")
                    return

            if self.voice_client and self.voice_client.is_playing():
                self.song_queue.append(song_data)
                await loading_msg.edit(content=f"✅ **Добавлено в очередь:** {title}")
            else:
                if self.voice_client is None or not self.voice_client.is_connected():
                    self.voice_client = await voice_channel.connect()
                elif self.voice_client.channel != voice_channel:
                    await self.voice_client.move_to(voice_channel)
                
                await self.play_next_song(song_data)
                
                minutes, seconds = divmod(duration, 60)
                duration_str = f"{minutes}:{seconds:02d}" if duration > 0 else "Неизвестно"
                await loading_msg.edit(
                    content=f"🎵 **Сейчас играет:** {title}\n⏱️ **Длительность:** {duration_str}\n🔊 **Канал:** {voice_channel.name}"
                )

        except Exception as e:
            import traceback
            print(f"[ERROR] General exception in play_music: {e}")
            traceback.print_exc()
            await ctx.send(f"❌ Произошла ошибка: {str(e)}")

    @commands.hybrid_command(name='stop', description='Остановить воспроизведение и очистить очередь')
    async def stop_music(self, ctx):
        print(f"[DEBUG] 'stop' command invoked by {ctx.author}")
        if self.voice_client:
            self.song_queue = []
            self.loop = False
            self.voice_client.stop()
            await self.voice_client.disconnect()
            self.voice_client = None
            self.current_song = None
            await ctx.send("⏹️ Воспроизведение остановлено и очередь очищена!")
        else:
            await ctx.send("❌ Бот не в голосовом канале!")

    @commands.hybrid_command(name='pause', description='Приостановить воспроизведение музыки')
    async def pause_music(self, ctx):
        print(f"[DEBUG] 'pause' command invoked by {ctx.author}")
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            await ctx.send("⏸️ Воспроизведение приостановлено!")
        else:
            await ctx.send("❌ Музыка не воспроизводится!")

    @commands.hybrid_command(name='resume', description='Возобновить воспроизведение музыки')
    async def resume_music(self, ctx):
        print(f"[DEBUG] 'resume' command invoked by {ctx.author}")
        if self.voice_client and self.voice_client.is_paused():
            self.voice_client.resume()
            await ctx.send("▶️ Воспроизведение возобновлено!")
        else:
            await ctx.send("❌ Музыка не приостановлена!")

    @commands.hybrid_command(name='disconnect', description='Отключить бота от голосового канала')
    async def disconnect(self, ctx):
        print(f"[DEBUG] 'disconnect' command invoked by {ctx.author}")
        if self.voice_client:
            self.song_queue = []
            self.loop = False
            await self.voice_client.disconnect()
            self.voice_client = None
            self.current_song = None
            await ctx.send("🔌 Бот отключен от голосового канала!")
        else:
            await ctx.send("❌ Бот не подключен к голосовому каналу!")

    @commands.hybrid_command(name='nowplaying', description='Показать текущую играющую песню')
    async def now_playing(self, ctx):
        print(f"[DEBUG] 'nowplaying' command invoked by {ctx.author}")
        if self.current_song and self.voice_client and self.voice_client.is_playing():
            title = self.current_song['title']
            await ctx.send(f"🎵 **Сейчас играет:** {title}")
        else:
            await ctx.send("❌ Сейчас ничего не играет!")

    @commands.hybrid_command(name='skip', description='Пропустить текущую песню')
    async def skip(self, ctx):
        print(f"[DEBUG] 'skip' command invoked by {ctx.author}")
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
            await ctx.send("⏭️ Песня пропущена!")
        else:
            await ctx.send("❌ Нечего пропускать!")

    @commands.hybrid_command(name='queue', description='Показать всю очередь песен', aliases=['list'])
    async def queue(self, ctx):
        print(f"[DEBUG] 'queue' command invoked by {ctx.author}")
        if not self.song_queue:
            await ctx.send("🎶 Очередь пуста!")
            return

        embed = discord.Embed(title="🎶 Очередь песен", color=discord.Color.blue())
        
        queue_list = ""
        for i, song in enumerate(self.song_queue):
            queue_list += f"{i+1}. {song['title']}\n"
        
        embed.description = queue_list

        await ctx.send(embed=embed)

    @commands.hybrid_command(name='clear', description='Очистить очередь песен')
    async def clear(self, ctx):
        print(f"[DEBUG] 'clear' command invoked by {ctx.author}")
        self.song_queue = []
        await ctx.send("🗑️ Очередь очищена!")

async def setup(bot, ffmpeg_executable):
    await bot.add_cog(MusicBot(bot, ffmpeg_executable))

@bot.event
async def on_ready():
    print(f'[INFO] 🤖 Бот {bot.user} готов к работе!')
    print(f'[INFO] 📊 Подключен к {len(bot.guilds)} серверам')
    try:
        synced = await bot.tree.sync()
        print(f'[INFO] ✅ Синхронизировано {len(synced)} команд')
    except Exception as e:
        print(f'[ERROR] ❌ Ошибка синхронизации команд: {e}')

async def main():
    load_dotenv()
    ffmpeg_executable = setup_ffmpeg()
    if not ffmpeg_executable:
        print("[FATAL] Завершение работы из-за ошибки с FFmpeg.")
        return

    async with bot:
        await setup(bot, ffmpeg_executable)
        TOKEN = os.environ.get("DISCORD_TOKEN")
        if not TOKEN:
            print("❌ Токен бота не найден! Пожалуйста, создайте файл .env и добавьте в него DISCORD_TOKEN=ВАШ_ТОКЕН")
            return
        
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())