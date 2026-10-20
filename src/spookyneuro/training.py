"""Single-GPU SD1.5 UNet LoRA training with cached latents/text and resumable state."""

import hashlib
import json
import logging
import time
from pathlib import Path

import numpy as np
from PIL import Image

LOG = logging.getLogger(__name__)
BASE = "stable-diffusion-v1-5/stable-diffusion-v1-5"


def train(args):
    started = time.perf_counter()
    import torch
    import torch.nn.functional as F
    from accelerate import Accelerator
    from accelerate.utils import set_seed
    from diffusers import AutoencoderKL, DDPMScheduler, StableDiffusionPipeline, UNet2DConditionModel
    from diffusers.utils import convert_state_dict_to_diffusers
    from peft import LoraConfig
    from peft.utils import get_peft_model_state_dict
    from torch.utils.data import DataLoader, WeightedRandomSampler
    from transformers import CLIPTextModel, CLIPTokenizer

    if not torch.cuda.is_available():
        raise RuntimeError("Training requires CUDA")
    if min(args.steps, args.rank, args.batch_accumulation) < 1:
        raise ValueError("Training steps, rank and accumulation must be positive")
    root, out = Path(args.data), Path(args.output)
    manifest = [json.loads(line) for line in (root / "manifest.jsonl").read_text().splitlines()]
    labels = sorted({r["class"] for r in manifest})
    if not labels or not all(
        any(r["split"] == split and r["class"] == label for r in manifest)
        for split in ("train", "validation")
        for label in labels
    ):
        raise ValueError("Need at least one example of every class in both train and validation")
    signature = hashlib.sha256(
        (root / "manifest.jsonl").read_bytes() + f"{args.size}:{args.rank}:{args.batch_accumulation}".encode()
    ).hexdigest()
    if args.resume:
        saved = json.loads((Path(args.resume) / "progress.json").read_text())
        if saved.get("signature", signature) != signature:
            raise ValueError("Resume requires the same dataset, image size, rank and accumulation")
    out.mkdir(parents=True, exist_ok=True)
    accelerator = Accelerator(
        mixed_precision="fp16",
        gradient_accumulation_steps=args.batch_accumulation,
        log_with="tensorboard",
        project_dir=str(out / "logs"),
    )
    set_seed(42)
    accelerator.init_trackers("horror-lora")
    tokenizer = CLIPTokenizer.from_pretrained(BASE, subfolder="tokenizer")
    text_encoder = CLIPTextModel.from_pretrained(BASE, subfolder="text_encoder", torch_dtype=torch.float16)
    vae = AutoencoderKL.from_pretrained(BASE, subfolder="vae", torch_dtype=torch.float16)
    vae.requires_grad_(False).to(accelerator.device)
    text_encoder.requires_grad_(False).to(accelerator.device)
    examples = []
    # Cache on CPU; text encoder and VAE are freed before allocating the training UNet.
    for index, record in enumerate(manifest):
        with Image.open(root / record["prepared_file"]) as image:
            image = image.convert("RGB").resize((args.size, args.size), Image.Resampling.LANCZOS)
            array = np.array(image).astype(np.float32) / 127.5 - 1
        pixel = torch.from_numpy(array).permute(2, 0, 1).unsqueeze(0).to(accelerator.device, torch.float16)
        tokens = tokenizer(
            record["caption"],
            padding="max_length",
            truncation=True,
            max_length=tokenizer.model_max_length,
            return_tensors="pt",
        ).input_ids
        with torch.inference_mode():
            latent = vae.encode(pixel).latent_dist.sample() * vae.config.scaling_factor
            embed = text_encoder(tokens.to(accelerator.device))[0]
        # clone outside inference_mode to allow backward through UNet operations.
        examples.append(
            {
                "latents": latent[0].cpu().clone(),
                "embeds": embed[0].cpu().clone(),
                "split": record["split"],
                "class": record["class"],
            }
        )
        if index % 50 == 0:
            LOG.info("Cached %d/%d", index + 1, len(manifest))
    del vae, text_encoder, pixel, tokens, latent, embed
    torch.cuda.empty_cache()
    unet = UNet2DConditionModel.from_pretrained(BASE, subfolder="unet", torch_dtype=torch.float16)
    unet.requires_grad_(False)
    unet.add_adapter(
        LoraConfig(
            r=args.rank,
            lora_alpha=args.rank,
            init_lora_weights="gaussian",
            target_modules=["to_q", "to_k", "to_v", "to_out.0"],
        )
    )
    for p in unet.parameters():
        if p.requires_grad:
            p.data = p.data.to(torch.float32)
    unet.enable_gradient_checkpointing()
    trainable = [p for p in unet.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable, lr=1e-4)
    from collections import Counter

    train_examples = [e for e in examples if e["split"] == "train"]
    counts = Counter(e["class"] for e in train_examples)
    weights = [1.0 / counts[e["class"]] for e in train_examples]
    loader = DataLoader(
        train_examples,
        batch_size=1,
        sampler=WeightedRandomSampler(weights, len(train_examples), replacement=True),
    )
    validation = [
        e
        for label in labels
        for e in [v for v in examples if v["split"] == "validation" and v["class"] == label][:4]
    ]
    scheduler = DDPMScheduler.from_pretrained(BASE, subfolder="scheduler")
    unet, optimizer, loader = accelerator.prepare(unet, optimizer, loader)
    global_step = 0
    if args.resume:
        accelerator.load_state(args.resume)
        global_step = json.loads((Path(args.resume) / "progress.json").read_text())["step"]

    def save(step):
        folder = out / f"checkpoint-{step}"
        accelerator.save_state(str(folder))
        (folder / "progress.json").write_text(json.dumps({"step": step, "signature": signature}))
        weights = convert_state_dict_to_diffusers(get_peft_model_state_dict(accelerator.unwrap_model(unet)))
        StableDiffusionPipeline.save_lora_weights(
            str(folder / "lora"), unet_lora_layers=weights, safe_serialization=True
        )
        StableDiffusionPipeline.save_lora_weights(
            str(out / "lora"), unet_lora_layers=weights, safe_serialization=True
        )

    def loss(example, generator=None):
        z = example["latents"].to(accelerator.device, torch.float16)
        embedding = example["embeds"].to(accelerator.device, torch.float16)
        if z.ndim == 3:
            z, embedding = z.unsqueeze(0), embedding.unsqueeze(0)
        noise = torch.randn(z.shape, generator=generator, device=z.device, dtype=z.dtype)
        timesteps = torch.randint(
            0, scheduler.config.num_train_timesteps, (z.shape[0],), generator=generator, device=z.device
        ).long()
        noisy = scheduler.add_noise(z, noise, timesteps)
        prediction = unet(noisy, timesteps, embedding).sample
        target = (
            noise
            if scheduler.config.prediction_type == "epsilon"
            else scheduler.get_velocity(z, noise, timesteps)
        )
        return F.mse_loss(prediction.float(), target.float())

    def validate():
        unet.eval()
        gen = torch.Generator(device=accelerator.device).manual_seed(1234)
        with torch.no_grad(), accelerator.autocast():
            val = sum(loss(e, gen).item() for e in validation) / len(validation)
        accelerator.log({"validation_loss": val}, step=global_step)
        with (out / "metrics.jsonl").open("a") as metrics:
            metrics.write(json.dumps({"step": global_step, "validation_loss": val}) + "\n")
        LOG.info("Validation at step %d: %.5f", global_step, val)
        unet.train()

    torch.cuda.reset_peak_memory_stats()
    if global_step == 0:
        validate()
    try:
        while global_step < args.steps:
            unet.train()
            for example in loader:
                with accelerator.accumulate(unet):
                    with accelerator.autocast():
                        value = loss(example)
                    accelerator.backward(value)
                    if accelerator.sync_gradients:
                        accelerator.clip_grad_norm_(trainable, 1.0)
                    optimizer.step()
                    optimizer.zero_grad()
                if accelerator.sync_gradients:
                    global_step += 1
                    accelerator.log({"train_loss": value.item()}, step=global_step)
                    if global_step % 10 == 0:
                        LOG.info("Step %d/%d, loss %.4f", global_step, args.steps, value.item())
                    if global_step % 250 == 0 or global_step == args.steps:
                        validate()
                        save(global_step)
                        unet.train()
                    if global_step >= args.steps:
                        break
    except KeyboardInterrupt:
        if global_step:
            save(global_step)
        LOG.info("Interrupted; saved completed optimizer step %d", global_step)
    finally:
        (out / "training.json").write_text(
            json.dumps(
                {
                    "model": BASE,
                    "rank": args.rank,
                    "size": args.size,
                    "completed_steps": global_step,
                    "requested_steps": args.steps,
                    "seed": 42,
                    "examples": len(examples),
                    "dataset_signature": signature,
                    "balanced_classes": True,
                    "elapsed_seconds": time.perf_counter() - started,
                    "peak_vram_mib": torch.cuda.max_memory_allocated() / 2**20,
                },
                indent=2,
            )
        )
        accelerator.end_training()
