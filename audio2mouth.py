from pydub import AudioSegment
import pyaudio
import wave
import io

def audio2mouth(file):
        

    # 设置播放的音效输出设备索引
    # output_device_index = 20  # 使用支持输出通道数的设备索引

    # 打开并转换音频文件为 PCM 格式
    audio_file_path = "voice/" + file
    audio = AudioSegment.from_file(audio_file_path)

    # 打印原始音频文件的通道数
    print(f"原始音频文件通道数: {audio.channels}")

    # 获取设备支持的最大输出通道数
    p = pyaudio.PyAudio()

    def find_device_index():
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if(info['name'] == "CABLE Input (VB-Audio Virtual C" and info['maxOutputChannels'] == 8):
                print(f"设备索引: {info['index']}, 设备名称: {info['name']}, 输出通道数: {info['maxOutputChannels']}")
                return info['index']


    device_info = p.get_device_info_by_index(find_device_index())
    max_channels = device_info['maxOutputChannels']
    p.terminate()

    print(f"设备支持的最大输出通道数: {max_channels}")

    # 根据设备支持的通道数调整音频文件的通道数
    audio = audio.set_frame_rate(44100).set_channels(min(audio.channels, max_channels)).set_sample_width(2)

    # 打印调整后的音频文件的通道数
    print(f"调整后的音频文件通道数: {audio.channels}")

    # 将转换后的音频文件保存为 WAV 格式
    wav_io = io.BytesIO()
    audio.export(wav_io, format='wav')
    wav_io.seek(0)

    # 打开音频流
    p = pyaudio.PyAudio()
    wf = wave.open(wav_io, 'rb')

    stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
                    channels=wf.getnchannels(),
                    rate=wf.getframerate(),
                    output=True,
                    output_device_index=find_device_index())

    # 播放音频文件
    data = wf.readframes(1024)
    while data:
        stream.write(data)
        data = wf.readframes(1024)

    # 关闭流和PyAudio
    stream.stop_stream()
    stream.close()
    p.terminate()

if(__name__=="__main__"):
    audio2mouth("2024-07-07-15-41-49.wav")