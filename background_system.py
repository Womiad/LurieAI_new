import asyncio
import os
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import discord


def _load_env_file(path: Path = Path(".env")):
    try:
        from dotenv import load_dotenv

        load_dotenv(path)
        return
    except ModuleNotFoundError:
        pass

    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_env_file()


@dataclass
class BackgroundGenerationConfig:
    enabled: bool = True
    log_channel_id: int = 1212309865305735188
    output_dir: Path = Path("diffusion/backgrounds")
    model_id: str = "runwayml/stable-diffusion-v1-5"
    width: int = 640
    height: int = 360
    num_inference_steps: int = 28
    guidance_scale: float = 7.0
    cooldown_seconds: int = 90
    show_window: bool = True
    viewer_title: str = "Lurie Background"
    max_context_messages: int = 8
    negative_prompt: str = (
        "low quality, blurry, text, watermark, logo, cropped, extra limbs, bad anatomy, "
        "modern city, apartment block, concrete housing, market stall, cars, traffic lights, "
        "electric poles, power lines, asphalt road, convenience store, supermarket, office, "
        "photorealistic, documentary photo, close-up, portrait, selfie, face, headshot, "
        "upper body, character focus, foreground person, macro shot, shallow depth of field"
    )
    world_style: str = (
        "isekai fantasy world, medieval fantasy architecture, magical atmosphere, "
        "storybook scenery, painterly anime background"
    )
    style_suffix: str = (
        "wide establishing shot, scenic landscape background, environment concept art, "
        "isekai fantasy anime background art, cinematic composition, beautiful lighting, "
        "detailed environment, painterly illustration, no modern objects, no close-up, "
        "no portrait, no characters in foreground, high quality"
    )

    @classmethod
    def from_env(cls):
        return cls(
            enabled=_env_bool("LURIE_BG_ENABLED", True),
            log_channel_id=int(os.getenv("LURIE_BG_LOG_CHANNEL_ID", "1212309865305735188")),
            output_dir=Path(os.getenv("LURIE_BG_OUTPUT_DIR", "diffusion/backgrounds")),
            model_id=os.getenv("LURIE_BG_MODEL_ID", "runwayml/stable-diffusion-v1-5"),
            width=int(os.getenv("LURIE_BG_WIDTH", "640")),
            height=int(os.getenv("LURIE_BG_HEIGHT", "360")),
            num_inference_steps=int(os.getenv("LURIE_BG_STEPS", "28")),
            guidance_scale=float(os.getenv("LURIE_BG_GUIDANCE", "7.0")),
            cooldown_seconds=int(os.getenv("LURIE_BG_COOLDOWN", "90")),
            show_window=_env_bool("LURIE_BG_SHOW_WINDOW", True),
            viewer_title=os.getenv("LURIE_BG_VIEWER_TITLE", "Lurie Background"),
            negative_prompt=os.getenv(
                "LURIE_BG_NEGATIVE_PROMPT",
                cls.negative_prompt,
            ),
            world_style=os.getenv("LURIE_BG_WORLD_STYLE", cls.world_style),
            style_suffix=os.getenv("LURIE_BG_STYLE_SUFFIX", cls.style_suffix),
        )


@dataclass
class BackgroundGenerationResult:
    prompt: str
    image_path: Path
    elapsed_seconds: float


class BackgroundGenerationSystem:
    def __init__(self, openai_client=None, config: BackgroundGenerationConfig | None = None):
        self.openai_client = openai_client
        self.config = config or BackgroundGenerationConfig.from_env()
        self._pipe = None
        self._last_generation_time = 0.0
        self._lock = asyncio.Lock()
        self._viewer = BackgroundImageViewer(self.config.viewer_title) if self.config.show_window else None
        if self._viewer is not None:
            self._viewer.start()

    async def generate_for_discord(
        self,
        *,
        context_messages: Iterable[dict],
        user_text: str,
        response_text: str,
        destination_channel: discord.abc.Messageable | None,
        source_label: str,
    ):
        if not self.config.enabled:
            return None

        async with self._lock:
            now = time.monotonic()
            if now - self._last_generation_time < self.config.cooldown_seconds:
                return None
            self._last_generation_time = now

            try:
                scene_prompt = await asyncio.to_thread(
                    self._build_scene_prompt,
                    list(context_messages)[-self.config.max_context_messages :],
                    user_text,
                    response_text,
                )
                result = await asyncio.to_thread(self._generate_image, scene_prompt)
                if self._viewer is not None:
                    self._viewer.show(result.image_path)
                await self._send_result(destination_channel, result, source_label)
                return result
            except Exception as exc:
                print(f"background generation failed: {exc}")
                if destination_channel is not None:
                    await destination_channel.send(f"背景生成失敗：```{exc}```")
                return None

    def _build_scene_prompt(self, context_messages, user_text: str, response_text: str) -> str:
        if self.openai_client is None:
            return self._fallback_prompt(user_text, response_text)

        compact_context = "\n".join(
            f"{message.get('role', 'unknown')}: {message.get('content', '')}"
            for message in context_messages
            if message.get("role") != "system"
        )
        instruction = (
            "You are creating a text-to-image prompt for a Discord chat bot background image. "
            "Read the recent conversation and infer the current scene, mood, time, weather, "
            "location, and visual motifs. Output one concise English prompt only. "
            f"The image must belong to this world style: {self.config.world_style}. "
            "If the conversation sounds mundane or modern, reinterpret it as an isekai fantasy "
            "equivalent instead of using real modern places. "
            "The result must be a wide landscape or environmental background suitable for OBS, "
            "not a close-up, portrait, product shot, selfie, or character-focused image. "
            "Do not mention Discord, chat logs, UI, speech bubbles, subtitles, text, "
            "modern cities, cars, power lines, apartments, supermarkets, close-up photos, "
            "faces, portraits, or photorealistic photography."
        )
        user_prompt = (
            f"Recent conversation:\n{compact_context}\n\n"
            f"Latest user message: {user_text}\n"
            f"Bot reply: {response_text}\n\n"
            f"Append this style naturally: {self.config.style_suffix}"
        )

        try:
            completion = self.openai_client.chat.completions.create(
                model=os.getenv("LURIE_BG_PROMPT_MODEL", "gpt-5-nano"),
                messages=[
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": user_prompt},
                ],
                max_completion_tokens=120,
            )
            prompt = completion.choices[0].message.content.strip()
            if prompt:
                return prompt[:900]
        except Exception as exc:
            print(f"scene prompt generation failed, using fallback: {exc}")

        return self._fallback_prompt(user_text, response_text)

    def _fallback_prompt(self, user_text: str, response_text: str) -> str:
        seed_text = " ".join([user_text, response_text])[:400]
        return f"{seed_text}, {self.config.world_style}, {self.config.style_suffix}"[:900]

    def _generate_image(self, prompt: str) -> BackgroundGenerationResult:
        start_time = time.time()
        pipe = self._load_pipeline()
        image = pipe(
            prompt,
            negative_prompt=self.config.negative_prompt,
            width=self.config.width,
            height=self.config.height,
            num_inference_steps=self.config.num_inference_steps,
            guidance_scale=self.config.guidance_scale,
        ).images[0]

        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = self.config.output_dir / f"background_{timestamp}.png"
        image.save(output_path)

        return BackgroundGenerationResult(
            prompt=prompt,
            image_path=output_path,
            elapsed_seconds=time.time() - start_time,
        )

    def _load_pipeline(self):
        if self._pipe is not None:
            return self._pipe

        import torch
        from diffusers import StableDiffusionPipeline

        use_cuda = torch.cuda.is_available()
        dtype = torch.float16 if use_cuda else torch.float32
        pipe = StableDiffusionPipeline.from_pretrained(
            self.config.model_id,
            torch_dtype=dtype,
            safety_checker=None,
            requires_safety_checker=False,
        )
        pipe = pipe.to("cuda" if use_cuda else "cpu")
        pipe.enable_attention_slicing()
        self._pipe = pipe
        return self._pipe

    async def _send_result(
        self,
        destination_channel: discord.abc.Messageable | None,
        result: BackgroundGenerationResult,
        source_label: str,
    ):
        if destination_channel is None:
            return

        content = (
            f"背景生成完成（{source_label}）\n"
            f"生成時間：{result.elapsed_seconds:.2f} 秒\n"
            f"Prompt：```{result.prompt}```"
        )
        await destination_channel.send(
            content=content,
            file=discord.File(str(result.image_path)),
        )


class BackgroundImageViewer:
    def __init__(self, title: str):
        self.title = title
        self._updates = queue.Queue()
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="LurieBackgroundViewer", daemon=True)
        self._thread.start()

    def show(self, image_path: Path):
        self._updates.put(Path(image_path))

    def _run(self):
        try:
            import tkinter as tk
            from PIL import Image, ImageTk
        except Exception as exc:
            print(f"background viewer disabled: {exc}")
            return

        root = tk.Tk()
        root.title(self.title)
        root.geometry("960x540")
        root.configure(background="black")

        label = tk.Label(root, background="black")
        label.pack(fill="both", expand=True)
        label.image_ref = None
        label.source_image = None

        def render_current_image():
            if label.source_image is None:
                return
            width = max(root.winfo_width(), 1)
            height = max(root.winfo_height(), 1)
            image = label.source_image.copy()
            image.thumbnail((width, height), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            label.configure(image=photo)
            label.image_ref = photo

        def poll_updates():
            latest_path = None
            while True:
                try:
                    latest_path = self._updates.get_nowait()
                except queue.Empty:
                    break

            if latest_path is not None:
                try:
                    label.source_image = Image.open(latest_path).convert("RGB")
                    render_current_image()
                except Exception as exc:
                    print(f"background viewer update failed: {exc}")

            root.after(250, poll_updates)

        root.bind("<Configure>", lambda _event: render_current_image())
        root.after(250, poll_updates)
        root.mainloop()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
