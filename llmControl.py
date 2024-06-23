import google.generativeai as genai
import json

class Gemini:
    def __init__(self) -> None:
        with open("gemini/GeminiApiKey.json","r") as file:
            self.GOOGLE_API_KEY = json.load(file)["token"]
        genai.configure(api_key=self.GOOGLE_API_KEY)
        self.model = genai.GenerativeModel('gemini-pro')
        self.chat = self.model.start_chat(history=[])

    def sendMsg(self,msg):
        response = self.chat.send_message(msg).text
        return response