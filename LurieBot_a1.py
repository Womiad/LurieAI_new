import discord
from discord import app_commands
import json
import nacl
from discord.ext import commands, voice_recv
import speech_recognition as sr
import io
from pydub import AudioSegment
import threading
import LurieAI
import asyncio
import datetime
import re
from audio2mouth import audio2mouth
from fish_speech_api import fish_generate

from vits.generateApi import generate



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
    response = Lurie.getResponse(message.content)
    
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


    voiceChannel = bot.get_channel(1196487874800013395)
    voiceClient = await voiceChannel.connect(cls=voice_recv.VoiceRecvClient)
    await interaction.response.send_message("vc")

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
            return
        silence_timer = None

        combined_audio = AudioSegment.empty()
        for chunk in audio_chunks:
            combined_audio += chunk
        audio_chunks = []

        wav_io = io.BytesIO()
        # combined_audio.export(wav_io, format="wav")
        combined_audio.export("output1.wav", format="wav")

        wav_io.seek(0)

        r = sr.Recognizer()

        sound = AudioSegment.from_file("output1.wav")
        sound = sound.set_frame_rate(48000)
        sound.export("output_modified.wav", format="wav")

        WAV = sr.AudioFile("output_modified.wav")

        with WAV as source:
            audio = r.record(source)

        
        LogChannel = bot.get_channel(1212309865305735188)

        try:
            result = r.recognize_google(audio, show_all=True, language='zh-TW')["alternative"][0]["transcript"]
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
            frame_rate = 96000,
            channels = 1
        )
        audio_chunks.append(audio_chunk)
        reset_silence_timer()


    if (not interaction.guild.voice_client.is_playing()):
        voiceClient.listen(voice_recv.BasicSink(callback))

with open("token.json","r") as file:
    token=json.load(file)["token"]
bot.run(token)
