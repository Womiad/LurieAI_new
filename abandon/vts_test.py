import pyvts
import asyncio

plugin_info = {
    "plugin_name": "LurieAI",
    "developer": "Womiad",
    "authentication_token_path": "./token.txt"
}

async def main():
    myvts = pyvts.vts(plugin_info=plugin_info)
    await myvts.connect()
    await myvts.request_authenticate_token()  # get token
    await myvts.request_authenticate()  # use token

    response_data = await myvts.request(myvts.vts_request.requestHotKeyList())
    hotkey_list = []
    for hotkey in response_data['data']['availableHotkeys']:
        hotkey_list.append(hotkey['name'])
    print(hotkey_list) # ['My Animation 1', 'My Animation 2', ...]

    send_hotkey_request = myvts.vts_request.requestTriggerHotKey(hotkey_list[0])
    await myvts.request(send_hotkey_request) # send request to play 'My Animation 1'
    await myvts.close()

if __name__ == "__main__":
    asyncio.run(main())