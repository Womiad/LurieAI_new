from openai import OpenAI

class LurieAI():

    def __init__(self) -> None:

        path = 'openAIkey.txt'
        f = open(path, 'r')
        mykey = f.read()
        f.close()

        self.client = OpenAI(
            api_key = mykey
        )

        path = 'memories/systemPrompt.txt'
        f = open(path, 'r')
        systemPrompt = f.read()
        f.close()

        path = 'memories/personality.txt'
        f = open(path, 'r')
        personality = f.read()
        f.close()

        path = 'memories/charactors.txt'
        f = open(path, 'r')
        charactors = f.read()
        f.close()

        configPrompt = systemPrompt.replace("[personality]",personality).replace("[charactors]",charactors) # charactors為認人用，暫不實裝
        self.system_message = {
            "role": "system",
            "name": "Lurie",
            "content": configPrompt
        }
        self.initial_greeting = "你好，歡迎來到異世界旅遊團。\n我是你今天的導遊。\n準備好跟我一起暢遊異世界了嗎？"
        self.reset_memory()

    def _stream_response(self, model):
        stream = self.client.chat.completions.create(
            model = model,
            messages = self.msg,
            max_completion_tokens = 300,
            stream = True,
        )
        content = ""
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                # print(chunk.choices[0].delta.content, end="")
                content += chunk.choices[0].delta.content
        return content.strip()

    def getResponse(self, inputText):
        self.msg.append({"role": "user", "content": inputText})
        content = self._stream_response("gpt-5-nano")
        if content == "":
            print("gpt-5-nano returned an empty response, retrying with gpt-4.1-nano")
            content = self._stream_response("gpt-4.1-nano")
        if content == "":
            content = "琉璃剛剛沒有收到可發送的回覆，請再試一次。"

        self.msg.append({"role": "assistant", "content": content})
        if(len(self.msg)>10):
            self.msg.pop(1)

        return content

    def get_recent_messages(self):
        return list(self.msg)

    def reset_memory(self):
        self.msg = [self.system_message.copy()]
        return self.initial_greeting
    
    def recognizeUser(self, name):
        if(name == "womiad"):
            return "womiad"
        else:
            return name

if(__name__=="__main__"):
    Lurie = LurieAI()

    while True:
        user_input = input("user:")
        print("琉璃：" + Lurie.getResponse(user_input))
