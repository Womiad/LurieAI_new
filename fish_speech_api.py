import datetime
import os
from pathlib import Path

import requests
from to_simple_zh import to_simple_zh


FISH_TTS_URL = "https://api.fish.audio/v1/tts"


def read_secret(env_name, file_name):
    value = os.environ.get(env_name)
    if value:
        return value.strip()

    path = Path(file_name)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()

    return None


def synthesize_audio(
    text,
    reference_id=None,
    api_key=None,
    model="s2-pro",
    max_new_tokens=1024,
    chunk_length=300,
    top_p=0.7,
    repetition_penalty=1.2,
    temperature=0.7,
    audio_format="wav",
    sample_rate=44100,
    output_dir="./voice",
):
    api_key =  read_secret("FISH_API_KEY", "fishAPIkey.txt")
    if not api_key:
        raise RuntimeError("Fish Audio API key is missing.")

    reference_id = read_secret("FISH_REFERENCE_ID", "fishReferenceId.txt")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    data = {
        "text": to_simple_zh(text),
        "top_p": top_p,
        "temperature": temperature,
        "chunk_length": chunk_length,
        "normalize": True,
        "format": audio_format,
        "sample_rate": sample_rate,
        "max_new_tokens": max_new_tokens,
        "repetition_penalty": repetition_penalty,
        "latency": "normal",
        "prosody": {
            "speed": 1,
            "volume": 0,
            "normalize_loudness": True,
        },
    }

    if reference_id:
        data["reference_id"] = reference_id

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "model": model,
    }

    response = requests.post(FISH_TTS_URL, headers=headers, json=data, timeout=120)
    if response.status_code != 200:
        print(f"Fish Audio request failed with status code {response.status_code}")
        try:
            print(response.json())
        except ValueError:
            print(response.text)
        return None

    datetime_str = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    file_name = f"{datetime_str}.{audio_format}"
    output_file_path = output_path / file_name
    output_file_path.write_bytes(response.content)
    print(f"Audio has been saved to '{output_file_path}'.")

    return file_name


def fish_generate(_text):
    return synthesize_audio(text=_text)


if __name__ == "__main__":
    fish_generate("晚安呀人類！希望你有美夢，琉璃會在這裡等你明天回來哦~ 晚安呀~")
