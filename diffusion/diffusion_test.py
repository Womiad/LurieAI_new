from diffusers import AutoPipelineForText2Image
import torch
import time
from datetime import datetime
from pathlib import Path

# 開始計時
start_time = time.time()

# ✔ 載入模型（優先本地，沒有就從 HF 下載並儲存）
model_local_path = "D:/huggingFace/models--stabilityai--sdxl-turbo"

if Path(model_local_path).exists():
    print("從本地載入模型...")
    pipe = AutoPipelineForText2Image.from_pretrained(
        model_local_path,
        torch_dtype=torch.float16
    ).to("cuda")
else:
    print("本地無模型，從 HF 下載並儲存...")
    pipe = AutoPipelineForText2Image.from_pretrained(
        "stabilityai/sdxl-turbo",
        torch_dtype=torch.float16,
        variant="fp16"
    ).to("cuda")
    pipe.save_pretrained(model_local_path)
    print(f"模型已儲存至 {model_local_path}")

# ✔ 加速設定
pipe.enable_attention_slicing()
pipe.vae.enable_slicing()
try:
    pipe.enable_xformers_memory_efficient_attention()
    print("xformers 已啟用")
except Exception:
    print("xformers 未安裝，跳過")

load_time = time.time() - start_time
print(f"模型載入時間: {load_time:.2f} 秒")

# =========================
# 🎮 世界場景
# =========================
location = "floating fantasy city"
time_of_day = "sunset"
weather = "soft glowing mist"
mood = "peaceful"

prompt = f"""
fantasy RPG game background, concept art, wide shot,
no characters, environment only,
location: {location},
time: {time_of_day},
weather: {weather},
mood: {mood},
cinematic lighting, highly detailed, beautiful composition
"""

# ✔ 生成
gen_start = time.time()

image = pipe(
    prompt,
    width=1024,
    height=576,
    guidance_scale=0.0,
    num_inference_steps=4,
    generator=torch.Generator("cuda").manual_seed(42)
).images[0]

gen_time = time.time() - gen_start

# =========================
# 💾 輸出
# =========================
output_dir = Path("diffusion")
output_dir.mkdir(exist_ok=True)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_path = output_dir / f"{timestamp}.png"

image.save(output_path)

# 結束計時
total_time = time.time() - start_time

print("完成！")
print(f"圖片已儲存：{output_path}")
print(f"模型載入: {load_time:.2f} 秒 | 生成: {gen_time:.2f} 秒 | 總計: {total_time:.2f} 秒")