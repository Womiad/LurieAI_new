import pyaudio

p = pyaudio.PyAudio()

# 列出所有可用的音频输出设备并打印详细信息
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    print(f"设备索引: {info['index']}, 设备名称: {info['name']}, 输出通道数: {info['maxOutputChannels']}")

p.terminate()