import discord
import discord.opus
from discord import app_commands
import json
import nacl
from pathlib import Path
from discord.ext import commands, voice_recv
import discord.ext.voice_recv.opus as voice_recv_opus
import speech_recognition as sr
from pydub import AudioSegment
import threading
import LurieAI
import asyncio
import datetime
import re
from openai import OpenAIError, RateLimitError
from audio2mouth import audio2mouth
from fish_speech_api import fish_generate

from vits.generateApi import generate


opus_path = Path(discord.__file__).parent / "bin" / "libopus-0.x64.dll"
if not discord.opus.is_loaded() and opus_path.exists():
    discord.opus.load_opus(str(opus_path))
    print(f"Loaded opus library: {opus_path}")

_original_decode_packet = voice_recv_opus.PacketDecoder._decode_packet


def _decode_packet_skip_corrupted(self, packet):
    try:
        return _original_decode_packet(self, packet)
    except discord.opus.OpusError as e:
        print(f"Skipping corrupted voice packet: {e}")
        self._decoder = voice_recv_opus.Decoder()
        silence = b"\x00\x00" * voice_recv_opus.Decoder.SAMPLES_PER_FRAME * voice_recv_opus.Decoder.CHANNELS
        return packet, silence


voice_recv_opus.PacketDecoder._decode_packet = _decode_packet_skip_corrupted


intents = discord.Intents.all()
intents.members = True 
bot = commands.Bot(command_prefix="/", intents=intents)


logMsg = ""
isThinking = False



audio_playlist = []


@bot.event
async def on_ready():

    slash = await bot.tree.sync()
    print(f"目前登入身份 --> {bot.user}")
    print(f"載入 {len(slash)} 個斜線指令")

    global Lurie
    global LurieChannel

    LurieChannel = bot.get_channel(1196487874800013394)
    print("online")
    Lurie = LurieAI.LurieAI()
    await LurieChannel.send("online")


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if ((message.channel.id==1196487874800013394 or message.channel.id==1212399293852291092) == False):
        return
    
    global isThinking
    channel = message.channel

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

    voiceChannel = bot.get_channel(1196487874800013395)
    if voiceChannel is None:
        await interaction.followup.send("找不到指定的語音頻道。")
        return

    voiceClient = interaction.guild.voice_client
    try:
        if voiceClient is not None and voiceClient.is_connected():
            if voiceClient.channel.id != voiceChannel.id:
                await voiceClient.move_to(voiceChannel)
        else:
            if voiceClient is not None:
                await voiceClient.disconnect(force=True)
            voiceClient = await voiceChannel.connect(cls=voice_recv.VoiceRecvClient, timeout=15.0, reconnect=False)
    except asyncio.TimeoutError:
        await interaction.followup.send("連接語音頻道逾時，請稍後再試。")
        return
    except discord.ClientException as e:
        print(f"voice connect client error: {e}")
        await interaction.followup.send("語音連線狀態異常，請稍後再試。")
        return
    except Exception as e:
        print(f"voice connect error: {e}")
        if interaction.guild.voice_client is not None:
            await interaction.guild.voice_client.disconnect(force=True)
        await interaction.followup.send("語音連線失敗，已清理連線狀態，請再試一次。")
        return

    await interaction.followup.send("vc")

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

        
        LogChannel = bot.get_channel(1212309865305735188)

        try:
            stt_result = r.recognize_google(audio, show_all=True, language='zh-TW')
            if not stt_result or "alternative" not in stt_result or len(stt_result["alternative"]) == 0:
                raise sr.UnknownValueError()
            result = stt_result["alternative"][0]["transcript"]
            user = Lurie.recognizeUser(interaction.user.name) + "："
            print(user + result)

            global getSttTime
            getSttTime = datetime.datetime.now()

            LurieResponse = Lurie.getResponse(user + result)
            LurieResponse = LurieResponse.replace("\n","。")

            # split_response = split_content(LurieResponse)

            global getLurieResponseTime
            getLurieResponseTime = datetime.datetime.now()

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

        audio_chunk = AudioSegment(
            data = raw_data,
            sample_width = 2,
            frame_rate = 48000,
            channels = 2
        )
        audio_chunks.append(audio_chunk)
        reset_silence_timer()


    if (voiceClient is not None and not voiceClient.is_playing()):
        print(f"opus loaded before listen: {discord.opus.is_loaded()}")
        voiceClient.listen(voice_recv.BasicSink(callback))

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
