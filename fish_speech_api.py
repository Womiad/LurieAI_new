import base64
import datetime
import json
from pathlib import Path
import pyaudio
import requests
from to_simple_zh import to_simple_zh


def wav_to_base64(file_path):
    if not file_path or not Path(file_path).exists():
        return None
    with open(file_path, "rb") as wav_file:
        wav_content = wav_file.read()
        base64_encoded = base64.b64encode(wav_content)
        return base64_encoded.decode("utf-8")


def play_audio(audio_content, format, channels, rate):
    p = pyaudio.PyAudio()
    stream = p.open(format=format, channels=channels, rate=rate, output=True)
    stream.write(audio_content)
    stream.stop_stream()
    stream.close()
    p.terminate()



def synthesize_audio(
    url,
    text,
    reference_audio=None,
    reference_text=None,
    max_new_tokens=1024,
    chunk_length=100,
    top_p=0.7,
    repetition_penalty=1.2,
    temperature=0.7,
    speaker=None,
    emotion=None,
    audio_format="wav",
    streaming=False,
    channels=1,
    rate=44100,
    output_dir="./voice"
):
    base64_audio = wav_to_base64(reference_audio)

    text = to_simple_zh(text)

    data = {
        "text": text,
        "reference_text": reference_text,
        "reference_audio": base64_audio,
        "max_new_tokens": max_new_tokens,
        "chunk_length": chunk_length,
        "top_p": top_p,
        "repetition_penalty": repetition_penalty,
        "temperature": temperature,
        "speaker": speaker,
        "emotion": emotion,
        "format": audio_format,
        "streaming": streaming,
    }

    response = requests.post(url, json=data, stream=streaming)

    audio_format = pyaudio.paInt16  # Assuming 16-bit PCM format

    if response.status_code == 200:
        if streaming:
            p = pyaudio.PyAudio()
            stream = p.open(
                format=audio_format, channels=channels, rate=rate, output=True
            )
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    stream.write(chunk)
            stream.stop_stream()
            stream.close()
            p.terminate()
        else:
            audio_content = response.content

            # 获取当前日期时间
            current_datetime = datetime.datetime.now()
            # 将日期时间对象转换为字符串
            datetime_str = current_datetime.strftime("%Y-%m-%d-%H-%M-%S")
            output_file_path = Path(output_dir) / f"{datetime_str}.wav"

            with open(output_file_path, "wb") as audio_file:
                audio_file.write(audio_content)
            print(f"Audio has been saved to '{output_file_path}'.")

            return f"{datetime_str}.wav"
    else:
        print(f"Request failed with status code {response.status_code}")
        print(response.json())
        return None
    
def fish_generate(_text):
    # Example usage:
    return synthesize_audio(
        url="http://127.0.0.1:8080/v1/invoke",
        text=_text,
        reference_audio="Lurie-zh-fishspeech02.wav",
        reference_text="你说得对，但是《原神》是由米哈游自主研发的一款全新开放世界冒险游戏。游戏发生在一个被称作「提瓦特」的幻想世界，"
    )

if __name__ == "__main__":
    fish_generate("晚安呀人類！希望你有美夢，琉璃會在這裡等你明天回來哦~ 晚安呀~")
