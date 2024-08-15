import pyvts
import asyncio

class vtsManager():

    async def vts_init(self):
        self.plugin_info = {
            "plugin_name": "LurieAI",
            "developer": "Womiad",
            "authentication_token_path": "./token.txt"
        }
        self.init_done = False
        try:
            self.myvts = pyvts.vts(plugin_info=self.plugin_info)
            await self.myvts.connect()
            await self.myvts.request_authenticate_token()  # get token
            await self.myvts.request_authenticate()  # use token

            response_data = await self.myvts.request(self.myvts.vts_request.requestHotKeyList())
            self.hotkey_list = []
            for hotkey in response_data['data']['availableHotkeys']:
                self.hotkey_list.append(hotkey['name'])
            print(self.hotkey_list) # ['My Animation 1', 'My Animation 2', ...]

            self.init_done = True
        except:
            print("vts初始化未成功")

    async def send_gotkey_request(self):
        if(self.init_done != True):
            print("vts未初始化，無法顯示動畫")
            return
        send_hotkey_request = self.myvts.vts_request.requestTriggerHotKey(self.hotkey_list[0])
        await self.myvts.request(send_hotkey_request) # send request to play 'My Animation 1'

if __name__ == "__main__":
    vts = vtsManager()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(vts.vts_init())
    loop.run_until_complete(vts.send_gotkey_request())
    loop.close()

    