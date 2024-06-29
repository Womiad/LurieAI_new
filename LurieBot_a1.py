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

from vits.generateApi import generate


intents = discord.Intents.all()
intents.members = True 
bot = commands.Bot(command_prefix="/", intents=intents)

# model_size = "large-v3"
# model = WhisperModel(model_size, device="cuda", compute_type="float16")  # Adjust device and compute_type as needed

@bot.event
async def on_ready():

    slash = await bot.tree.sync()
    print(f"目前登入身份 --> {bot.user}")
    print(f"載入 {len(slash)} 個斜線指令")

    global Lurie
    global LurieChannel
    global LogChannel

    LurieChannel = bot.get_channel(1196487874800013394)
    LogChannel = bot.get_channel(1212309865305735188)
    print("online")
    Lurie = LurieAI.LurieAI()
    await LurieChannel.send("online")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if ((message.channel.id==1196487874800013394 or message.channel.id==1212399293852291092) == False):
        return
    
    # response = Lurie.getResponse(message.author,message.content)
    response = Lurie.getResponse(message.content)
    channel = message.channel
    await channel.send(response)

    # #紀錄
    # await LogChannel.send(f"```{Lurie.tellUser(message.author.id)+message.content}```")
    # if(response[0] == "filtered"):
    #     await LogChannel.send(f"{response[1]}")
    # else:
    #     await LogChannel.send(f"```琉璃:{response[0]}```")
    #     await LogChannel.send(f"洗腦值：{Lurie.hyp}")

    # await channel.send("0")

@bot.tree.command(name = "say", description = "叫琉璃說話a")
async def say(interaction: discord.Interaction, text: str):

    if interaction.guild.voice_client.is_playing():
        await interaction.channel.send(content="琉璃現在在忙喔")

    await interaction.response.send_message(text)
    theReturn = generate(text,language="ZH")
    print(theReturn)#print出返回的音檔路徑

    if(interaction.guild.voice_client):
        interaction.guild.voice_client.play(discord.FFmpegPCMAudio("voice/" + theReturn))
    else:
        await interaction.channel.send(content="未連線至語音頻道")

    await interaction.channel.send(file=discord.File("voice/" + theReturn))
    
@bot.tree.command(name = "vc", description = "進入語音頻道")
async def vc(interaction: discord.Interaction):
    voiceChannel = bot.get_channel(1196487874800013395)
    voiceClient = await voiceChannel.connect(cls=voice_recv.VoiceRecvClient)
    await interaction.response.send_message("vc")

    audio_chunks = []
    silence_timer = None

    def reset_silence_timer():
        nonlocal silence_timer
        if silence_timer is not None:
            silence_timer.cancel()
        silence_timer = threading.Timer(1.0, process_audio)
        silence_timer.start()

    def process_audio():
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

        try:
            result = r.recognize_google(audio, show_all=True, language='zh-TW')["alternative"][0]["transcript"]
            print(result)

            LurieResponse = Lurie.getResponse(result)

            #復讀機
            
            try:
                theReturn = generate(LurieResponse,language="ZH")
                print(theReturn)#print出返回的音檔路徑

                try:
                    interaction.guild.voice_client.play(discord.FFmpegPCMAudio("voice/" + theReturn))
                except:
                    print("播放" + theReturn + "時出現錯誤")

            except:
                print("生成語音時發生錯誤："+ result)

            


        except sr.RequestError as e:
            print(f"Could not request results from Google Speech Recognition service; {e}")
        except sr.UnknownValueError:
            print("Google Speech Recognition could not understand audio")

    def callback(user, data: voice_recv.VoiceData):
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
        


    voiceClient.listen(voice_recv.BasicSink(callback))

with open("token.json","r") as file:
    token=json.load(file)["token"]
bot.run(token)
