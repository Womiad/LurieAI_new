import speech_recognition as sr
r = sr.Recognizer()
WAV = sr.AudioFile("output1.wav")
with WAV as source:
    audio = r.record(source)
print(r.recognize_google(audio, show_all=True))