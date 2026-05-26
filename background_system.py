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
    model_id: str = "stabilityai/sdxl-turbo"
    model_local_path: Path | None = Path("D:/huggingFace/models--stabilityai--sdxl-turbo")
    model_variant: str | None = "fp16"
    width: int = 1024
    height: int = 576
    num_inference_steps: int = 4
    guidance_scale: float = 0.0
    seed: int | None = 42
    cooldown_seconds: int = 90
    show_window: bool = True
    viewer_title: str = "Lurie Background"
    max_context_messages: int = 8
    negative_prompt: str = (
        "low quality, blurry, text, watermark, logo, cropped, extra limbs, bad anatomy, "
        "person, people, human, character, figure, silhouette, bold black outlines, "
        "flat vector art, coloring book style, sticker-like shapes, "
        "modern city, apartment block, concrete housing, market stall, cars, traffic lights, "
        "electric poles, power lines, asphalt road, convenience store, supermarket, office, "
        "photorealistic, documentary photo, close-up, portrait, selfie, face, headshot, "
        "upper body, character focus, foreground person, macro shot, shallow depth of field"
    )
    world_style: str = (
        "fantasy RPG world, grand environmental concept art, digital matte painting, "
        "immersive spatial depth, magical atmosphere"
    )
    prompt_prefix: str = (
        "fantasy RPG environment concept art, digital matte painting, wide shot,\n"
        "uninhabited landscape, cinematic fantasy scenery"
    )
    style_suffix: str = (
        "soft painted edges, cinematic light, atmospheric depth, layered scenery, detailed textures"
    )

    @classmethod
    def from_env(cls):
        return cls(
            enabled=_env_bool("LURIE_BG_ENABLED", True),
            log_channel_id=int(os.getenv("LURIE_BG_LOG_CHANNEL_ID", "1212309865305735188")),
            output_dir=Path(os.getenv("LURIE_BG_OUTPUT_DIR", "diffusion/backgrounds")),
            model_id=os.getenv("LURIE_BG_MODEL_ID", "stabilityai/sdxl-turbo"),
            model_local_path=_env_optional_path(
                "LURIE_BG_MODEL_LOCAL_PATH",
                Path("D:/huggingFace/models--stabilityai--sdxl-turbo"),
            ),
            model_variant=_env_optional_str("LURIE_BG_MODEL_VARIANT", "fp16"),
            width=int(os.getenv("LURIE_BG_WIDTH", "1024")),
            height=int(os.getenv("LURIE_BG_HEIGHT", "576")),
            num_inference_steps=int(os.getenv("LURIE_BG_STEPS", "4")),
            guidance_scale=float(os.getenv("LURIE_BG_GUIDANCE", "0.0")),
            seed=_env_optional_int("LURIE_BG_SEED", 42),
            cooldown_seconds=int(os.getenv("LURIE_BG_COOLDOWN", "90")),
            show_window=_env_bool("LURIE_BG_SHOW_WINDOW", True),
            viewer_title=os.getenv("LURIE_BG_VIEWER_TITLE", "Lurie Background"),
            negative_prompt=os.getenv(
                "LURIE_BG_NEGATIVE_PROMPT",
                cls.negative_prompt,
            ),
            world_style=os.getenv("LURIE_BG_WORLD_STYLE", cls.world_style),
            prompt_prefix=os.getenv("LURIE_BG_PROMPT_PREFIX", cls.prompt_prefix),
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
        scene_hint = self._keyword_scene_hint(user_text, response_text)
        if self.openai_client is None:
            return self._fallback_prompt(user_text, response_text, scene_hint)

        compact_context = "\n".join(
            f"{message.get('role', 'unknown')}: {message.get('content', '')}"
            for message in context_messages
            if message.get("role") != "system"
        )
        instruction = (
            "Convert the recent Chinese chat into one concise English image scene prompt. "
            "Output only comma-separated English visual phrases, 20 to 45 words. "
            "Infer the current place, mood, time, weather, landmarks, colors, and important objects. "
            "If the chat is mundane, reinterpret it as a fantasy RPG travel scene. "
            f"Keep it inside this world: {self.config.world_style}. "
            "Make the scene a wide environmental background, not a portrait or character scene. "
            "Never output Chinese, labels, explanations, quotes, markdown, UI terms, modern cities, cars, "
            "close-up photos, faces, anime, cartoon, line art, vector art, or generic quality tags. "
            "Example: luminous ancient ruins in a misty valley, twilight, glowing crystal flowers, "
            "moonlit stone arches, quiet magical atmosphere."
        )
        user_prompt = (
            f"Recent conversation:\n{compact_context}\n\n"
            f"Latest user message: {user_text}\n"
            f"Bot reply: {response_text}"
        )

        try:
            completion = self.openai_client.chat.completions.create(
                model=os.getenv("LURIE_BG_PROMPT_MODEL", "gpt-4.1-nano"),
                messages=[
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": user_prompt},
                ],
                max_completion_tokens=120,
            )
            prompt = completion.choices[0].message.content.strip()
            if prompt:
                prompt = self._merge_scene_hint(prompt, scene_hint)
                normalized_prompt = self._normalize_scene_prompt(prompt)
                if normalized_prompt:
                    return normalized_prompt
                print(f"scene prompt rejected, using fallback: {prompt}")
        except Exception as exc:
            print(f"scene prompt generation failed, using fallback: {exc}")

        return self._fallback_prompt(user_text, response_text, scene_hint)

    def _fallback_prompt(self, user_text: str, response_text: str, scene_hint: str = "") -> str:
        if scene_hint:
            return scene_hint

        seed_text = f"{user_text} {response_text}"
        if any(word in seed_text for word in ("港", "海", "船", "霧")):
            return "misty fantasy harbor, floating lanterns, ancient docks, calm sea, silver fog"
        if any(word in seed_text for word in ("夢", "睡", "未完成")):
            return "unfinished dreamland, floating islands, surreal ruins, soft dawn light"
        if any(word in seed_text for word in ("史萊姆", "黏液")):
            return "enchanted slime forest, glowing mushrooms, wet moss, playful magical atmosphere"
        if any(word in seed_text for word in ("夜", "遺跡", "光", "精靈")):
            return "glowing ancient ruins, luminous crystals, twilight, soft mist, mysterious"
        if any(word in seed_text for word in ("森林", "樹", "木屋")):
            return "enchanted forest clearing, ancient trees, warm cottage lights, golden hour"
        return "fantasy travel landscape, golden hour, soft glowing mist, peaceful"

    def _compose_generation_prompt(self, scene_prompt: str) -> str:
        scene_prompt = self._clean_scene_prompt(scene_prompt)
        return (
            f"{self.config.prompt_prefix},\n"
            f"{self.config.style_suffix},\n"
            f"{scene_prompt}"
        )[:450]

    def _normalize_scene_prompt(self, prompt: str) -> str:
        prompt = self._clean_scene_prompt(prompt)
        if not prompt or self._contains_cjk(prompt):
            return ""
        words = prompt.split()
        if len(words) > 60:
            prompt = " ".join(words[:60]).strip(" ,")
        return prompt

    @staticmethod
    def _clean_scene_prompt(scene_prompt: str) -> str:
        scene_prompt = " ".join(scene_prompt.split())
        for label in ("location:", "time:", "weather:", "mood:", "motifs:"):
            scene_prompt = scene_prompt.replace(label, "")
        scene_prompt = scene_prompt.replace(";", ",")
        return scene_prompt[:180].strip(" ,")

    @staticmethod
    def _contains_cjk(text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    @staticmethod
    def _merge_scene_hint(prompt: str, scene_hint: str) -> str:
        if not scene_hint:
            return prompt[:900]
        if scene_hint.lower() in prompt.lower():
            return prompt[:900]
        return f"{scene_hint}, {prompt}"[:900]

    @staticmethod
    def _keyword_scene_hint(user_text: str, response_text: str) -> str:
        seed_text = f"{user_text} {response_text}"
        hints = []

        if any(word in seed_text for word in ("花", "花海", "蘭", "紫薇", "向日葵")):
            hints.append(
                "vast dense flower meadow, carpet of colorful blossoms, many flowers across the foreground"
            )
        if any(word in seed_text for word in ("星光", "閃耀", "水晶", "夜光", "光之精靈")):
            hints.append("glowing petals, crystal flowers, soft magical sparkle")
        if any(word in seed_text for word in ("遺跡", "神殿", "古代")):
            hints.append("ancient fantasy ruins")
        if any(word in seed_text for word in ("夜", "夜光")):
            hints.append("twilight, luminous mist")
        if any(word in seed_text for word in ("森林", "樹", "木屋")):
            hints.append("enchanted forest clearing")

        return ", ".join(hints)

    def _generate_image(self, prompt: str) -> BackgroundGenerationResult:
        start_time = time.time()
        pipe = self._load_pipeline()
        generation_prompt = self._compose_generation_prompt(prompt)
        generator = self._make_generator()
        generate_kwargs = {
            "width": self.config.width,
            "height": self.config.height,
            "num_inference_steps": self.config.num_inference_steps,
            "guidance_scale": self.config.guidance_scale,
        }
        if generator is not None:
            generate_kwargs["generator"] = generator
        if self.config.guidance_scale > 0 and self.config.negative_prompt:
            generate_kwargs["negative_prompt"] = self.config.negative_prompt

        image = pipe(generation_prompt, **generate_kwargs).images[0]

        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = self.config.output_dir / f"background_{timestamp}.png"
        image.save(output_path)

        return BackgroundGenerationResult(
            prompt=generation_prompt,
            image_path=output_path,
            elapsed_seconds=time.time() - start_time,
        )

    def _load_pipeline(self):
        if self._pipe is not None:
            return self._pipe

        import torch
        from diffusers import AutoPipelineForText2Image

        use_cuda = torch.cuda.is_available()
        device = "cuda" if use_cuda else "cpu"
        dtype = torch.float16 if use_cuda else torch.float32

        load_path = self.config.model_id
        loading_local_model = False
        should_save_local = False
        if self.config.model_local_path is not None:
            if self.config.model_local_path.exists():
                load_path = str(self.config.model_local_path)
                loading_local_model = True
                print(f"從本地載入背景模型：{self.config.model_local_path}")
            else:
                should_save_local = True
                print(f"本地背景模型不存在，從 HF 載入：{self.config.model_id}")

        load_kwargs = {"torch_dtype": dtype}
        if use_cuda and self.config.model_variant and not loading_local_model:
            load_kwargs["variant"] = self.config.model_variant

        pipe = AutoPipelineForText2Image.from_pretrained(load_path, **load_kwargs).to(device)
        if should_save_local and self.config.model_local_path is not None:
            self.config.model_local_path.mkdir(parents=True, exist_ok=True)
            pipe.save_pretrained(self.config.model_local_path)
            print(f"背景模型已儲存至 {self.config.model_local_path}")

        pipe.enable_attention_slicing()
        if hasattr(pipe, "vae") and pipe.vae is not None:
            pipe.vae.enable_slicing()
        try:
            pipe.enable_xformers_memory_efficient_attention()
            print("背景模型 xformers 已啟用")
        except Exception:
            print("背景模型 xformers 未啟用，使用一般 attention")
        self._pipe = pipe
        return self._pipe

    def _make_generator(self):
        if self.config.seed is None:
            return None

        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        return torch.Generator(device).manual_seed(self.config.seed)

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


def _env_optional_int(name: str, default: int | None) -> int | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    if not value:
        return None
    return int(value)


def _env_optional_path(name: str, default: Path | None) -> Path | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    if not value:
        return None
    return Path(value)


def _env_optional_str(name: str, default: str | None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or None
