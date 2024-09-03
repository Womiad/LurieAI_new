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
        self.msg = [
            {
                "role": "system",
                "name": "Lurie",
                "content": configPrompt
            },
        ]

    def getResponse(self, inputText):
        self.msg.append({"role": "user", "content": inputText})
        stream = self.client.chat.completions.create(
            model = "gpt-4o-mini",
            messages = self.msg,
            stream = True,
        )
        content = ""
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                # print(chunk.choices[0].delta.content, end="")
                content += chunk.choices[0].delta.content
        self.msg.append({"role": "assistant", "content": content})
        if(len(self.msg)>10):
            self.msg.pop(1)

        return content
    
    def recognizeUser(self, name):
        if(name == "womiad"):
            return "埃德"
        else:
            return name

if(__name__=="__main__"):
    Lurie = LurieAI()

    while True:
        user_input = input("user:")
        print("琉璃：" + Lurie.getResponse(user_input))