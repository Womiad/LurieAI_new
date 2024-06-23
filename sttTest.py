import speech_recognition as sr
from pydub import AudioSegment


r = sr.Recognizer()

sound = AudioSegment.from_file("output1.wav")
sound = sound.set_frame_rate(48000)
sound.export("output_modified.wav", format="wav")

WAV = sr.AudioFile("output_modified.wav")

with WAV as source:
    audio = r.record(source)

try:
    print(r.recognize_google(audio, show_all=True, language='zh-TW')["alternative"][0]["transcript"])
except sr.RequestError as e:
    print(f"Could not request results from Google Speech Recognition service; {e}")
except sr.UnknownValueError:
    print("Google Speech Recognition could not understand audio")