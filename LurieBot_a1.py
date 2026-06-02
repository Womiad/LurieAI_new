import discord
import discord.opus
import davey
from discord import app_commands
import json
import nacl
from pathlib import Path
from discord.ext import commands, voice_recv
import discord.ext.voice_recv.opus as voice_recv_opus
import discord.ext.voice_recv.rtp as voice_recv_rtp
import speech_recognition as sr
from pydub import AudioSegment
import threading
import LurieAI
import asyncio
import datetime
import logging
import queue
import re
import random
from openai import OpenAIError, RateLimitError
from audio2mouth import audio2mouth
from background_system import BackgroundGenerationSystem
from fish_speech_api import fish_generate
from PIL import Image

from vits.generateApi import generate


logging.getLogger("discord.ext.voice_recv.reader").setLevel(logging.WARNING)

opus_path = Path(discord.__file__).parent / "bin" / "libopus-0.x64.dll"
if not discord.opus.is_loaded() and opus_path.exists():
    discord.opus.load_opus(str(opus_path))
    print(f"Loaded opus library: {opus_path}")


def _parse_bede_header_fixed(self, data, length):
    offset = 4
    end = 4 + length * 4

    while offset < end:
        next_byte = data[offset : offset + 1]
        if next_byte == b"\x00":
            offset += 1
            continue

        header = next_byte[0]
        element_id = header >> 4
        element_len = 1 + (header & 0b0000_1111)
        self.extension_data[element_id] = data[offset + 1 : offset + 1 + element_len]
        offset += 1 + element_len


voice_recv_rtp.RTPPacket._parse_bede_header = _parse_bede_header_fixed

_original_decode_packet = voice_recv_opus.PacketDecoder._decode_packet


def _decode_packet_with_dave(self, packet):
    if packet:
        voice_client = self.sink.voice_client
        user_id = voice_client._get_id_from_ssrc(packet.ssrc)
        dave_session = voice_client._connection.dave_session

        if user_id is not None and dave_session is not None and dave_session.ready:
            try:
                packet.decrypted_data = dave_session.decrypt(
                    user_id,
                    davey.MediaType.audio,
                    packet.decrypted_data,
                )
            except Exception as e:
                print(f"DAVE decrypt failed for user {user_id}: {e}")
                return packet, b""

    try:
        return _original_decode_packet(self, packet)
    except discord.opus.OpusError as e:
        print(f"opus decode failed for ssrc {getattr(packet, 'ssrc', 'unknown')}: {e}")
        return packet, b""


voice_recv_opus.PacketDecoder._decode_packet = _decode_packet_with_dave

intents = discord.Intents.all()
intents.members = True 
bot = commands.Bot(command_prefix="/", intents=intents)

VOICE_CHANNEL_ID = 1196487874800013395
LODGE_CHANNEL_ID = 1196487874800013394
TEXT_CHAT_CHANNEL_IDS = {LODGE_CHANNEL_ID, 1212399293852291092}
LOG_CHANNEL_ID = 1212309865305735188
VOICE_CONNECT_TIMEOUT = 30.0
voice_connect_lock = asyncio.Lock()


logMsg = ""
isThinking = False
backgroundSystem = None
backgroundStartupTask = None
backgroundRefreshTask = None
photo_lock = asyncio.Lock()
RESET_MEMORY_TRIGGERS = {"重置記憶", "reset記憶", "reset memory", "/reset_memory", "/reset"}
qrCodeViewer = None



audio_playlist = []


class QRCodeViewer:
    def __init__(self, title="Lurie Photo QRCode"):
        self.title = title
        self._updates = queue.Queue()
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="LurieQRCodeViewer", daemon=True)
        self._thread.start()

    def show_url(self, url):
        if not url:
            return
        self._updates.put(url)
        print(f"QRCode 視窗準備顯示圖片網址：{url}")

    def _make_qr_image(self, url, size=420, padding=32):
        from PIL import Image
        import qrcode

        qr_image = qrcode.make(url).convert("L")
        qr_size = max(1, size - padding * 2)
        qr_image = qr_image.resize((qr_size, qr_size), Image.Resampling.NEAREST)

        canvas = Image.new("RGB", (size, size), "white")
        canvas.paste(qr_image.convert("RGB"), (padding, padding))
        return canvas

    def _run(self):
        try:
            import tkinter as tk
            from PIL import ImageTk
        except Exception as exc:
            print(f"QRCode viewer disabled: {exc}")
            return

        green = "#00ff00"
        root = tk.Tk()
        root.title(self.title)
        root.geometry("480x480")
        root.configure(background=green)

        label = tk.Label(root, background=green, borderwidth=0, highlightthickness=0)
        label.pack(fill="both", expand=True)
        label.image_ref = None
        label.source_image = None

        def render_current_image():
            if label.source_image is None:
                label.configure(image="")
                label.image_ref = None
                return
            width = max(root.winfo_width(), 1)
            height = max(root.winfo_height(), 1)
            image = label.source_image.copy()
            image.thumbnail((width, height), Image.Resampling.NEAREST)
            photo = ImageTk.PhotoImage(image, master=root)
            try:
                label.configure(image=photo)
                label.image_ref = photo
            except tk.TclError as exc:
                print(f"QRCode viewer render failed: {exc}")

        def show_url(url):
            try:
                label.source_image = self._make_qr_image(url)
                render_current_image()
                root.deiconify()
            except Exception as exc:
                print(f"QRCode viewer update failed: {exc}")

        def poll_updates():
            latest_url = None
            while True:
                try:
                    latest_url = self._updates.get_nowait()
                except queue.Empty:
                    break

            if latest_url is not None:
                show_url(latest_url)

            root.after(250, poll_updates)

        root.bind("<Configure>", lambda _event: render_current_image())
        root.after(250, poll_updates)
        root.mainloop()


def _safe_channel_name(channel):
    return getattr(channel, "name", str(getattr(channel, "id", "unknown")))


def _latest_background_path():
    if backgroundSystem is not None:
        background_path = backgroundSystem.get_current_background_path()
        if background_path is not None and background_path.exists():
            return background_path

    background_dir = Path("diffusion/backgrounds")
    backgrounds = [path for path in background_dir.glob("*.png") if path.is_file()]
    if not backgrounds:
        return None
    return max(backgrounds, key=lambda path: path.stat().st_mtime)


def _create_photo_image():
    background_path = _latest_background_path()
    if background_path is None:
        raise FileNotFoundError("找不到可用的背景圖片。")

    lurie_dir = Path("lurie_png")
    lurie_paths = sorted(path for path in lurie_dir.glob("*.png") if path.is_file())
    if not lurie_paths:
        raise FileNotFoundError("找不到 lurie_png 裡的角色圖片。")

    lurie_path = random.choice(lurie_paths)
    with Image.open(background_path).convert("RGBA") as background:
        with Image.open(lurie_path).convert("RGBA") as lurie:
            max_overlay_width = int(background.width * 0.45)
            max_overlay_height = int(background.height * 0.55)
            scale = min(
                max_overlay_width / lurie.width,
                max_overlay_height / lurie.height,
                1.0,
            )
            overlay_size = (
                max(1, int(lurie.width * scale)),
                max(1, int(lurie.height * scale)),
            )
            lurie = lurie.resize(overlay_size, Image.Resampling.LANCZOS)

            if lurie_path.name == "1.png":
                position = (
                    background.width - lurie.width,
                    background.height - lurie.height,
                )
            elif lurie_path.name == "2.png":
                position = ((background.width - lurie.width) // 2, background.height - lurie.height)
            elif lurie_path.name == "3.png":
                position = (0, background.height - lurie.height)
            else:
                position = (
                    background.width - lurie.width,
                    background.height - lurie.height,
                )

            background.alpha_composite(lurie, position)
            output_dir = Path("diffusion/photos")
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            output_path = output_dir / f"photo_{timestamp}_{lurie_path.stem}.png"
            background.convert("RGB").save(output_path)

    return output_path, background_path, lurie_path


async def send_photo(channels, source_label):
    async with photo_lock:
        try:
            photo_path, background_path, lurie_path = await asyncio.to_thread(_create_photo_image)
        except Exception as e:
            print(f"photo generation failed: {e}")
            for channel in channels:
                if channel is not None:
                    await channel.send(f"拍照失敗：```{e}```")
            return

    sent_channel_ids = set()
    content = (
        f"拍照完成（{source_label}）\n"
        f"背景：{background_path.name}\n"
        f"角色：{lurie_path.name}"
    )
    for channel in channels:
        if channel is None or channel.id in sent_channel_ids:
            continue
        sent_channel_ids.add(channel.id)
        sent_message = await channel.send(content=content, file=discord.File(str(photo_path)))
        if qrCodeViewer is not None and sent_message.attachments:
            qrCodeViewer.show_url(sent_message.attachments[0].url)


def schedule_voice_photo(source_label):
    channels = [
        bot.get_channel(LOG_CHANNEL_ID),
        bot.get_channel(LODGE_CHANNEL_ID),
    ]
    bot.loop.call_soon_threadsafe(
        lambda: bot.loop.create_task(send_photo(channels, source_label))
    )


@bot.event
async def on_ready():

    slash = await bot.tree.sync()
    print(f"目前登入身份 --> {bot.user}")
    print(f"載入 {len(slash)} 個斜線指令")

    global Lurie
    global LurieChannel
    global backgroundSystem
    global backgroundStartupTask
    global backgroundRefreshTask
    global qrCodeViewer

    LurieChannel = bot.get_channel(LODGE_CHANNEL_ID)
    print("啟動discord bot......")
    await LurieChannel.send("啟動discord bot......")
    Lurie = LurieAI.LurieAI()
    if qrCodeViewer is None:
        qrCodeViewer = QRCodeViewer()
    qrCodeViewer.start()
    await LurieChannel.send("啟動背景系統......")
    backgroundSystem = BackgroundGenerationSystem(openai_client=Lurie.client)
    if backgroundStartupTask is None or backgroundStartupTask.done():
        backgroundStartupTask = bot.loop.create_task(warm_up_startup_background())
    startup_result = await backgroundStartupTask
    if backgroundRefreshTask is None or backgroundRefreshTask.done():
        backgroundRefreshTask = bot.loop.create_task(periodic_background_refresh())
    if startup_result is None:
        await LurieChannel.send("背景系統啟動，但初始背景尚未顯示成功。")
        return
    await LurieChannel.send("召喚成功！可以開始對話！")


async def warm_up_startup_background():
    if backgroundSystem is None:
        return None

    destination_channel = bot.get_channel(backgroundSystem.config.log_channel_id)
    print("背景模型預載與開機首張背景生成中...")
    result = await backgroundSystem.generate_startup_background(
        destination_channel=destination_channel,
        source_label="開機預載",
    )
    if result is None:
        print("背景模型預載完成，未產生開機背景")
    else:
        print(f"開機背景完成：{result.image_path}（{result.elapsed_seconds:.2f} 秒）")
    return result


async def periodic_background_refresh():
    while True:
        if backgroundSystem is None:
            await asyncio.sleep(1)
            continue

        await asyncio.sleep(backgroundSystem.config.refresh_interval_seconds)
        if backgroundSystem is None:
            continue

        await backgroundSystem.refresh_from_conversation(
            notify_discord=False,
            source_label="場景自動刷新",
        )


def schedule_background_generation(user_text, response_text, source_label, destination_channel=None):
    if backgroundSystem is None:
        return

    if destination_channel is None:
        destination_channel = bot.get_channel(backgroundSystem.config.log_channel_id)
    context_messages = Lurie.get_recent_messages()
    backgroundSystem.remember_conversation(context_messages, user_text, response_text)
    coroutine = backgroundSystem.generate_for_discord(
        context_messages=context_messages,
        user_text=user_text,
        response_text=response_text,
        destination_channel=destination_channel,
        source_label=source_label,
    )
    bot.loop.call_soon_threadsafe(lambda: bot.loop.create_task(coroutine))


def reset_lurie_memory():
    greeting = Lurie.reset_memory()
    if backgroundSystem is not None:
        backgroundSystem.reset_conversation()
    return greeting


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.channel.id not in TEXT_CHAT_CHANNEL_IDS:
        return
    
    global isThinking
    channel = message.channel
    normalized_content = message.content.strip().lower()

    if normalized_content in RESET_MEMORY_TRIGGERS:
        response = reset_lurie_memory()
        await channel.send(response)
        return

    if "拍照" in message.content:
        await send_photo([channel], f"文字頻道 #{_safe_channel_name(channel)}")
        return

    if (isThinking==True):
        await channel.send(content="琉璃現在在忙喔")
        return
    
    # response = Lurie.getResponse(message.author,message.content)
    isThinking = True
    try:
        response = Lurie.getResponse(message.content)
    except RateLimitError as e:
        error_code = getattr(e, "code", None)
        if error_code == "insufficient_quota":
            response = "OpenAI API 額度不足或帳單尚未啟用，請主人檢查一下 Platform 的 billing / credits。"
        else:
            response = "OpenAI API 目前請求太頻繁，請稍等一下再試。"
    except OpenAIError:
        response = "OpenAI API 連線或服務發生錯誤，請稍後再試。"
    except Exception as e:
        print(f"on_message error: {e}")
        response = "琉璃這邊發生了一點錯誤，請稍後再試。"
    finally:
        isThinking = False

    if response is None or response.strip() == "":
        response = "琉璃剛剛沒有收到可發送的回覆，請再試一次。"

    await channel.send(response)
    schedule_background_generation(
        message.content,
        response,
        f"文字頻道 #{message.channel.name}",
        destination_channel=message.channel,
    )

@bot.tree.command(name = "reset_memory", description = "重置琉璃記憶並回到初次問候")
async def reset_memory(interaction: discord.Interaction):
    global isThinking

    if isThinking == True:
        await interaction.response.send_message("琉璃現在在忙喔")
        return

    response = reset_lurie_memory()
    await interaction.response.send_message(response)

@bot.tree.command(name = "say", description = "叫琉璃說話")
async def say(interaction: discord.Interaction, text: str):

    global isThinking

    if (interaction.guild.voice_client.is_playing() or isThinking==True):
        await interaction.channel.send(content="琉璃現在在忙喔")
        return

    await interaction.response.send_message(text)
    isThinking = True
    try:
        theReturn = fish_generate(text)
    except:
        theReturn = generate(text,language="ZH")

    print(theReturn)#print出返回的音檔路徑

    if(interaction.guild.voice_client):
        interaction.guild.voice_client.play(discord.FFmpegPCMAudio("voice/" + theReturn))
    else:
        await interaction.channel.send(content="未連線至語音頻道")

    await interaction.channel.send(file=discord.File("voice/" + theReturn))
    isThinking = False
    
@bot.tree.command(name = "vc", description = "進入語音頻道")
async def vc(interaction: discord.Interaction):

    await interaction.response.defer()

    if interaction.guild is None:
        await interaction.followup.send("這個指令只能在伺服器裡使用。")
        return

    voiceChannel = bot.get_channel(VOICE_CHANNEL_ID)
    if voiceChannel is None:
        await interaction.followup.send("找不到指定的語音頻道。")
        return

    bot_member = interaction.guild.me or interaction.guild.get_member(bot.user.id)
    if bot_member is None:
        await interaction.followup.send("找不到琉璃在伺服器裡的成員資料。")
        return

    permissions = voiceChannel.permissions_for(bot_member)
    if not permissions.connect or not permissions.speak:
        await interaction.followup.send("琉璃沒有進入或發話這個語音頻道的權限。")
        return

    async with voice_connect_lock:
        voiceClient = interaction.guild.voice_client
        try:
            if voiceClient is not None and voiceClient.is_connected():
                if voiceClient.channel.id != voiceChannel.id:
                    await voiceClient.move_to(voiceChannel)
            else:
                if voiceClient is not None:
                    await voiceClient.disconnect(force=True)
                    await asyncio.sleep(1.0)

                last_error = None
                for attempt in range(2):
                    try:
                        voiceClient = await voiceChannel.connect(
                            cls=voice_recv.VoiceRecvClient,
                            timeout=VOICE_CONNECT_TIMEOUT,
                            reconnect=True,
                        )
                        break
                    except (asyncio.TimeoutError, discord.ClientException) as e:
                        last_error = e
                        print(f"voice connect attempt {attempt + 1} failed: {e}")
                        if interaction.guild.voice_client is not None:
                            await interaction.guild.voice_client.disconnect(force=True)
                        await asyncio.sleep(1.0)
                else:
                    if isinstance(last_error, asyncio.TimeoutError):
                        await interaction.followup.send("連接語音頻道逾時，已清理連線狀態，請再試一次。")
                    else:
                        await interaction.followup.send("語音連線狀態異常，已清理連線狀態，請再試一次。")
                    return
        except Exception as e:
            print(f"voice connect error: {e}")
            if interaction.guild.voice_client is not None:
                await interaction.guild.voice_client.disconnect(force=True)
            await interaction.followup.send("語音連線失敗，已清理連線狀態，請再試一次。")
            return

    await interaction.followup.send("vc")
    print(f"voice encryption mode: {getattr(voiceClient, 'mode', 'unknown')}")
    print(f"dave protocol version: {getattr(voiceClient._connection, 'dave_protocol_version', 'unknown')}")

    audio_chunks = []
    silence_timer = None

    global logMsg
    logMsg = ""

    def split_content(text):
        # 使用正则表达式按标点符号分割文本
        sentences = re.split(r"(。|，|!|,|\.|：|；|;|\?|？|！)", text)
        # 合并标点符号到前一个句子
        sentences = [sentences[i] + sentences[i+1] for i in range(0, len(sentences) - 1, 2)]
        return sentences

    def reset_silence_timer():
        nonlocal silence_timer
        if silence_timer is not None:
            silence_timer.cancel()
        silence_timer = threading.Timer(1.0, process_audio)
        silence_timer.start()

    def process_audio():

        global startPrecessAudioTime
        startPrecessAudioTime = datetime.datetime.now()

        global isThinking
        isThinking = True

        nonlocal audio_chunks, silence_timer
        if not audio_chunks:
            isThinking = False
            return
        silence_timer = None

        combined_audio = AudioSegment.empty()
        for chunk in audio_chunks:
            combined_audio += chunk
        audio_chunks = []

        r = sr.Recognizer()

        combined_audio.export("output1.wav", format="wav")

        sound = AudioSegment.from_file("output1.wav")
        sound = sound.set_channels(1).set_frame_rate(16000).set_sample_width(2)
        sound.export("output_modified.wav", format="wav")

        WAV = sr.AudioFile("output_modified.wav")

        with WAV as source:
            audio = r.record(source)

        
        LogChannel = bot.get_channel(LOG_CHANNEL_ID)

        try:
            stt_result = r.recognize_google(audio, show_all=True, language='zh-TW')
            if not stt_result or "alternative" not in stt_result or len(stt_result["alternative"]) == 0:
                raise sr.UnknownValueError()
            result = stt_result["alternative"][0]["transcript"]
            user = Lurie.recognizeUser(interaction.user.name) + "："
            print(user + result)

            if "拍照" in result:
                isThinking = False
                schedule_voice_photo(f"語音頻道 {interaction.user.name}")
                return

            global getSttTime
            getSttTime = datetime.datetime.now()

            LurieResponse = Lurie.getResponse(user + result)
            LurieResponse = LurieResponse.replace("\n","。")

            # split_response = split_content(LurieResponse)

            global getLurieResponseTime
            getLurieResponseTime = datetime.datetime.now()
            schedule_background_generation(result, LurieResponse, f"語音頻道 {interaction.user.name}")

            #回覆&log
            global logMsg
            logMsg = ""

            #異步加速由於tts問題，暫時無法實裝
            # for i in range(0,len(split_response)):
            #     file = generate(split_response[i],language="ZH")
            #     print(file)
            #     audio_playlist.append(file)
            #     if(not interaction.guild.voice_client.is_playing()):
            #         interaction.guild.voice_client.play(discord.FFmpegPCMAudio("voice/" + audio_playlist[0]))
            #         del audio_playlist[0]

            # while(audio_playlist):
            #     if(not interaction.guild.voice_client.is_playing()):
            #         interaction.guild.voice_client.play(discord.FFmpegPCMAudio("voice/" + audio_playlist[0]))
            #         del audio_playlist[0]

            # isThinking = False
            
            try:
                try:
                    theReturn = fish_generate(LurieResponse)
                except:
                    theReturn = generate(LurieResponse,language="ZH")
                    
                print(theReturn)#print出返回的音檔路徑

                global getAudioReturnTime
                getAudioReturnTime = datetime.datetime.now()

                try:
                    interaction.guild.voice_client.play(discord.FFmpegPCMAudio("voice/" + theReturn))
                    audio2mouth(theReturn)
                    

                    logMsg = "語音辨識結果：" + result + "\n" + "琉璃：" + LurieResponse + "\n"

                    isThinking = False

                    SttTotalTime = (getSttTime - startPrecessAudioTime).total_seconds()
                    getTextResponseTime = (getLurieResponseTime - getSttTime).total_seconds()
                    TtsTotalTime = (getAudioReturnTime - getLurieResponseTime).total_seconds()
                    TotalLurieResponseTime = SttTotalTime + getTextResponseTime + TtsTotalTime
                    timeLog = f"```stt花費時間:{SttTotalTime}秒\n回答生成花費時間:{getTextResponseTime}秒\ntts花費時間:{TtsTotalTime}秒\n總花費時間:{TotalLurieResponseTime}秒\nuser:{interaction.user.name}```"
                    bot.loop.create_task(LogChannel.send(logMsg + timeLog))
                    
                except:
                    logMsg = "~~語音辨識結果：" + result + "\n" + "琉璃：" + LurieResponse + "~~" +"\n" + "播放" + theReturn + "時出現錯誤" + "\n"
                    print("播放" + theReturn + "時出現錯誤")
                    isThinking = False
                    
                    SttTotalTime = (getSttTime - startPrecessAudioTime).total_seconds()
                    getTextResponseTime = (getLurieResponseTime - getSttTime).total_seconds()
                    TtsTotalTime = (getAudioReturnTime - getLurieResponseTime).total_seconds()
                    TotalLurieResponseTime = SttTotalTime + getTextResponseTime + TtsTotalTime
                    timeLog = f"~~~stt花費時間:{SttTotalTime}秒\n回答生成花費時間:{getTextResponseTime}秒\ntts花費時間:{TtsTotalTime}秒\n總花費時間:{TotalLurieResponseTime}秒~~~"
                    bot.loop.create_task(LogChannel.send(logMsg + timeLog))
            except:
                isThinking = False
                print("生成語音時發生錯誤："+ result)
                logMsg = "~~語音辨識結果：" + result + "\n" + "琉璃：" + LurieResponse + "~~" +"\n" + "生成語音時發生錯誤" + "\n"

                SttTotalTime = (getSttTime - startPrecessAudioTime).total_seconds()
                getTextResponseTime = (getLurieResponseTime - getSttTime).total_seconds()
                TtsTotalTime = (getAudioReturnTime - getLurieResponseTime).total_seconds()
                TotalLurieResponseTime = SttTotalTime + getTextResponseTime + TtsTotalTime
                timeLog = f"~~~stt花費時間:{SttTotalTime}秒\n回答生成花費時間:{getTextResponseTime}秒\ntts花費時間:{TtsTotalTime}秒\n總花費時間:{TotalLurieResponseTime}秒~~~"
                bot.loop.create_task(LogChannel.send(logMsg + timeLog))
         
        except sr.RequestError as e:
            isThinking = False
            print(f"Could not request results from Google Speech Recognition service; {e}")
            if logMsg=="```Could not request results from Google Speech Recognition service```": return
            logMsg = "```Could not request results from Google Speech Recognition service```"
            bot.loop.create_task(LogChannel.send(logMsg))
            

        except sr.UnknownValueError:
            isThinking = False   
            print("Google Speech Recognition could not understand audio")
            if logMsg=="```Google Speech Recognition could not understand audio```": return
            logMsg = "```Google Speech Recognition could not understand audio```"
            bot.loop.create_task(LogChannel.send(logMsg))

    def callback(user, data: voice_recv.VoiceData):
        
        global isThinking
        if(isThinking == True): 
            return

        nonlocal audio_chunks
        raw_data = data.pcm
        if not raw_data:
            return

        audio_chunk = AudioSegment(
            data = raw_data,
            sample_width = 2,
            frame_rate = 48000,
            channels = 2
        )
        audio_chunks.append(audio_chunk)
        reset_silence_timer()


    if voiceClient is not None and voiceClient.is_connected():
        print(f"opus loaded before listen: {discord.opus.is_loaded()}")
        try:
            if hasattr(voiceClient, "is_listening") and voiceClient.is_listening():
                print("voice client is already listening")
            else:
                voiceClient.listen(voice_recv.BasicSink(callback))
        except discord.ClientException as e:
            print(f"voice listen error: {e}")
            await interaction.followup.send("已連上語音頻道，但啟動收音時發生錯誤。")

@bot.tree.command(name = "shutdown", description = "關閉琉璃")
async def shutdown(interaction: discord.Interaction):
    if interaction.user.guild_permissions.administrator == False:
        await interaction.response.send_message("只有管理員可以關閉琉璃。", ephemeral=True)
        return

    await interaction.response.send_message("琉璃要先下線了。")

    if interaction.guild.voice_client is not None:
        await interaction.guild.voice_client.disconnect(force=True)

    await bot.close()

with open("token.json","r") as file:
    token=json.load(file)["token"]
bot.run(token)
