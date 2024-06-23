import llmControl

class LurieAI():

    #屬性
    #self.hyp
    #self.llm

    def __init__(self) -> None:

        self.hyp=0
        self.llm=llmControl.Gemini()

    #生成prompt
    def prompt(self,user, msg):
        prompt = user + msg
        #每5句洗一次腦
        if(self.hyp % 5 == 0):
            prompt = self.getSystemPrompt() + user + msg
        return prompt

    #取得琉璃回應(array)
    def getResponse(self,user, msg):
        #若訊息為空不回應
        if msg=="":
            return "input error"
        #認人
        _user = self.tellUser(user.id)
        #取得prompt
        prompt = self.prompt(_user, msg)
        #洗腦計數器+1
        self.hyp+=1
        #嘗試獲得回覆
        try:
            response = self.llm.sendMsg(prompt)
            return [response]
        except:
            return ["filtered",response.prompt_feedback]

    #閱讀系統prompt
    def getSystemPrompt(self):

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

        configPrompt = systemPrompt.replace("[personality]",personality).replace("[charactors]",charactors)

        return configPrompt
    
    #辨別使用者(DiscordId -> str)
    def tellUser(self, UserId):
        if UserId == 363682541145948162:
            user = "埃德："
        elif UserId == 708940692235354154:
            user = "堆堆："
        elif UserId == 660472882014584842:
            user = "琴："
        elif UserId == 615187548351758336:
            user = "塔克："
        else:
            user = "陌生人："
        return user
    
    #開機訊息(array)
    def getOpenMsg(self):

        introStstemPrompt = self.getSystemPrompt()
        prompt = self.prompt(introStstemPrompt, "開機了，請妳向大家問好")

        try:
            response = self.llm.sendMsg(prompt)
            return [response]
        except:
            return ["filtered",response.prompt_feedback]
        