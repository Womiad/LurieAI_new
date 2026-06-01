import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import torch
from diffusers import AutoPipelineForText2Image


def load_pipeline(args):
    start_time = time.time()
    model_local_path = Path(args.model_local_path) if args.model_local_path else None

    if model_local_path and model_local_path.exists():
        print(f"從本地載入模型：{model_local_path}", flush=True)
        pipe = AutoPipelineForText2Image.from_pretrained(
            str(model_local_path),
            torch_dtype=torch.float16,
        ).to("cuda")
    else:
        print(f"本地無模型，從 HF 載入：{args.model_id}", flush=True)
        pipe = AutoPipelineForText2Image.from_pretrained(
            args.model_id,
            torch_dtype=torch.float16,
            variant=args.variant or None,
        ).to("cuda")
        if model_local_path:
            pipe.save_pretrained(model_local_path)
            print(f"模型已儲存至 {model_local_path}", flush=True)

    pipe.enable_attention_slicing()
    if hasattr(pipe, "vae") and pipe.vae is not None:
        pipe.vae.enable_slicing()
    try:
        pipe.enable_xformers_memory_efficient_attention()
        print("xformers 已啟用", flush=True)
    except Exception:
        print("xformers 未啟用，使用一般 attention", flush=True)

    load_time = time.time() - start_time
    print(f"模型載入時間: {load_time:.2f} 秒", flush=True)
    return pipe, load_time


def generate_image(pipe, job, load_time=0.0):
    start_time = time.time()
    width = int(job.get("width", 1024))
    height = int(job.get("height", 576))
    steps = int(job.get("steps", 4))
    guidance = float(job.get("guidance", 0.0))
    seed = int(job.get("seed", 42))
    prompt = job["prompt"]
    output_dir = Path(job.get("output_dir", "diffusion/backgrounds"))

    print(
        "背景圖片生成中..."
        f" size={width}x{height},"
        f" steps={steps},"
        f" seed={seed}",
        flush=True,
    )

    gen_start = time.time()
    image = pipe(
        prompt,
        width=width,
        height=height,
        guidance_scale=guidance,
        num_inference_steps=steps,
        generator=torch.Generator("cuda").manual_seed(seed),
    ).images[0]
    gen_time = time.time() - gen_start

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"background_{timestamp}.png"
    image.save(output_path)

    total_time = time.time() - start_time + load_time
    result = {
        "prompt": prompt,
        "image_path": str(output_path),
        "elapsed_seconds": total_time,
        "load_seconds": load_time,
        "generation_seconds": gen_time,
    }
    Path(job["result_json"]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

    print("完成！", flush=True)
    print(f"圖片已儲存：{output_path}", flush=True)
    print(
        f"模型載入: {load_time:.2f} 秒 | 生成: {gen_time:.2f} 秒 | 總計: {total_time:.2f} 秒",
        flush=True,
    )
    return result


def run_once(args):
    pipe, load_time = load_pipeline(args)
    job = {
        "prompt": args.prompt,
        "output_dir": args.output_dir,
        "result_json": args.result_json,
        "width": args.width,
        "height": args.height,
        "steps": args.steps,
        "guidance": args.guidance,
        "seed": args.seed,
    }
    generate_image(pipe, job, load_time=load_time)


def run_daemon(args):
    job_dir = Path(args.job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    ready_file = job_dir / "daemon_ready"

    pipe, load_time = load_pipeline(args)
    ready_file.write_text("ok", encoding="utf-8")
    print("背景 worker daemon 已就緒", flush=True)

    while True:
        jobs = sorted(job_dir.glob("job_*.json"))
        if not jobs:
            time.sleep(0.2)
            continue

        job_path = jobs[0]
        job = None
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
            generate_image(pipe, job, load_time=0.0)
        except Exception as exc:
            if job and job.get("result_json"):
                result_json = Path(job["result_json"])
            else:
                result_json = job_dir / job_path.name.replace("job_", "result_")
            error_result = {
                "error": str(exc),
                "prompt": job.get("prompt", "") if job else "",
                "image_path": "",
                "elapsed_seconds": 0.0,
            }
            result_json.write_text(json.dumps(error_result, ensure_ascii=False), encoding="utf-8")
            print(f"daemon job failed: {exc}", flush=True)
        finally:
            try:
                job_path.unlink()
            except OSError:
                pass


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt")
    parser.add_argument("--output-dir", default="diffusion/backgrounds")
    parser.add_argument("--result-json")
    parser.add_argument("--job-dir", default="diffusion/backgrounds/jobs")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--model-id", default="stabilityai/sdxl-turbo")
    parser.add_argument("--model-local-path", default="D:/huggingFace/models--stabilityai--sdxl-turbo")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=576)
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--guidance", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--variant", default="fp16")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.daemon:
        run_daemon(args)
        return

    if not args.prompt or not args.result_json:
        parser.error("--prompt and --result-json are required unless --daemon is set")

    run_once(args)


if __name__ == "__main__":
    main()
