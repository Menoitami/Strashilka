"""Lazy model loading, correlated diffusion noise and optional CPU segmentation."""

import logging
import math
import time
import types

import cv2
import numpy as np
from PIL import Image

from .config import Settings
from .model_assets import MODEL_REVISIONS


def correlate_noise(previous, fresh, coefficient):
    """Follow a random latent trajectory without progressively reducing noise variance."""
    if previous is None or previous.shape != fresh.shape or coefficient <= 0:
        return fresh
    return previous * coefficient + fresh * math.sqrt(1 - coefficient**2)


class Renderer:
    def __init__(self, settings: Settings, mock=False, local_files_only=False, quality=False):
        self.settings = settings.validate()
        self.quality = quality
        self.mock = mock
        self.local_files_only = local_files_only
        self.pipe = None
        self.mask_session = None
        self.mask_provider = "none"
        self.noise_position = 0.0
        self.temporal_noise = None
        self.temporal_coherence = 0.0
        self.start_time = time.monotonic()
        if not mock:
            self._load()

    def _load(self):
        import torch
        from diffusers import DPMSolverMultistepScheduler, LCMScheduler, StableDiffusionImg2ImgPipeline

        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA unavailable. Install a CUDA PyTorch build or use --mock for plumbing tests."
            )
        free_mib = torch.cuda.mem_get_info()[0] / 2**20
        if free_mib < 3072:
            raise RuntimeError(
                f"Only {free_mib:.0f} MiB of GPU memory free; this model needs at least 3072 MiB. Wait for other GPU jobs to finish."
            )
        if self.settings.mask_mode == "free" and free_mib < 4864:
            if self.settings.mask_device == "cuda":
                raise RuntimeError(
                    "CUDA segmentation needs more free VRAM; use --mask-device cpu or wait for other GPU jobs."
                )
            if self.settings.mask_device == "auto":
                self.settings.mask_device = "cpu"
        self.torch = torch
        self.pipe = StableDiffusionImg2ImgPipeline.from_pretrained(
            self.settings.model,
            revision=MODEL_REVISIONS.get(self.settings.model),
            torch_dtype=torch.float16,
            use_safetensors=True,
            safety_checker=None,
            requires_safety_checker=False,
            local_files_only=self.local_files_only,
        ).to("cuda")
        if self.quality:
            self.pipe.scheduler = DPMSolverMultistepScheduler.from_config(
                self.pipe.scheduler.config, algorithm_type="dpmsolver++", use_karras_sigmas=True,
            )
        else:
            self.pipe.scheduler = LCMScheduler.from_config(self.pipe.scheduler.config)
            self.pipe.load_lora_weights(
                self.settings.lcm,
                revision=MODEL_REVISIONS.get(self.settings.lcm),
                adapter_name="lcm",
                local_files_only=self.local_files_only,
                **({"weight_name": "pytorch_lora_weights.safetensors"} if self.local_files_only else {}),
            )
        if self.settings.lora:
            self.pipe.load_lora_weights(
                self.settings.lora,
                adapter_name="horror",
                local_files_only=self.local_files_only,
                **({"weight_name": "pytorch_lora_weights.safetensors"} if self.local_files_only else {}),
            )
        self._set_adapters()
        self.pipe.set_progress_bar_config(disable=True)
        self.pipe.vae.enable_slicing()
        # Keep VAE encoding deterministic and explicitly inject smoothly changing noise.
        owner = self

        def prepare_latents(
            pipe, image, timestep, batch_size, num_images_per_prompt, dtype, device, generator=None
        ):
            if batch_size != 1 or num_images_per_prompt != 1:
                raise ValueError("Only single-image rendering is supported")
            image = image.to(device=device, dtype=dtype)
            clean = pipe.vae.encode(image).latent_dist.mode() * pipe.vae.config.scaling_factor
            phase = owner.noise_position
            index, mix = math.floor(phase), phase % 1

            def noise(key):
                gen = torch.Generator(device=device).manual_seed((owner.settings.seed + key) % (2**63 - 1))
                return torch.randn(clean.shape, generator=gen, device=device, dtype=dtype)

            # Equal-power interpolation keeps noise variance approximately constant.
            blended = noise(index) * math.cos(mix * math.pi / 2) + noise(index + 1) * math.sin(
                mix * math.pi / 2
            )
            if owner.temporal_coherence > 0:
                blended = correlate_noise(owner.temporal_noise, blended, owner.temporal_coherence)
                owner.temporal_noise = blended.detach()
            else:
                owner.temporal_noise = None
            return pipe.scheduler.add_noise(clean, blended, timestep)

        self.pipe.prepare_latents = types.MethodType(prepare_latents, self.pipe)
        self.embeddings = {}

    def _set_adapters(self):
        names, weights = ([], []) if self.quality else (["lcm"], [1.0])
        if self.settings.lora:
            names.append("horror")
            weights.append(self.settings.lora_scale)
        if names:
            self.pipe.set_adapters(names, adapter_weights=weights)

    def render(self, source: Image.Image, metadata=None) -> tuple[Image.Image, dict]:
        started = time.perf_counter()
        meta = metadata or {}
        coherence = float(meta.get("coherence", 0))
        if not math.isfinite(coherence) or not 0 <= coherence <= 0.95:
            raise ValueError("coherence must be in [0, .95]")
        self.temporal_coherence = coherence
        guidance = float(meta.get("guidance_scale", 1.0))
        maximum_guidance = 8 if self.quality else 3
        if not math.isfinite(guidance) or not 1 <= guidance <= maximum_guidance:
            raise ValueError(f"guidance_scale must be in [1, {maximum_guidance}]")
        # These are the only settings that may be changed by a scene request.
        old_weight = self.settings.lora_scale
        changes = {
            key: meta[key] for key in ("strength", "noise_period", "lora_scale", "mask_mode") if key in meta
        }
        from dataclasses import replace

        self.settings = replace(self.settings, **changes).validate()
        s = self.settings
        image = source.convert("RGBA").resize((s.size, s.size), Image.Resampling.LANCZOS)
        phase = float(meta.get("phase", time.monotonic() - self.start_time))
        if not math.isfinite(phase):
            raise ValueError("phase must be finite")
        self.noise_position = phase / s.noise_period
        if self.mock:
            # Deliberately labeled diagnostic effect; this is NOT diffusion output.
            arr = np.array(image)
            yy, xx = np.mgrid[: s.size, : s.size].astype(np.float32)
            xx += np.sin(yy / 12 + phase * 2) * 6
            rgb = cv2.remap(arr[..., :3], xx, yy, cv2.INTER_LINEAR)
            rgb[..., 0] = np.clip(rgb[..., 0].astype(float) * (1 + 0.25 * math.sin(phase)), 0, 255)
            result = Image.fromarray(rgb)
            peak = 0
        else:
            torch = self.torch
            if old_weight != s.lora_scale:
                self._set_adapters()
            prompt = s.prompt
            if prompt not in self.embeddings:
                with torch.inference_mode():
                    self.embeddings[prompt] = self.pipe.encode_prompt(
                        prompt, "cuda", 1, do_classifier_free_guidance=False
                    )[0]
            background = Image.new("RGB", image.size, (8, 8, 8))
            background.paste(image, mask=image.getchannel("A"))
            torch.cuda.reset_peak_memory_stats()
            with torch.inference_mode():
                result = self.pipe(
                    image=background,
                    prompt_embeds=self.embeddings[prompt],
                    num_inference_steps=s.steps,
                    strength=s.strength,
                    guidance_scale=guidance,
                    generator=torch.Generator(device="cuda").manual_seed(s.seed),
                ).images[0]
            torch.cuda.synchronize()
            peak = torch.cuda.max_memory_allocated() / 2**20
        inference_done = time.perf_counter()
        if s.mask_mode == "free":
            if self.mock:
                # Diagnostic free silhouette follows the same procedural warp as RGB.
                mask = Image.fromarray(cv2.remap(np.array(image.getchannel("A")), xx, yy, cv2.INTER_LINEAR))
            else:
                from rembg import new_session, remove

                if self.mask_session is None:
                    import onnxruntime as ort

                    providers = ["CPUExecutionProvider"]
                    if s.mask_device != "cpu" and "CUDAExecutionProvider" in ort.get_available_providers():
                        ort.preload_dlls()
                        providers.insert(
                            0,
                            (
                                "CUDAExecutionProvider",
                                {
                                    "gpu_mem_limit": str(512 * 2**20),
                                    "arena_extend_strategy": "kSameAsRequested",
                                    "cudnn_conv_algo_search": "HEURISTIC",
                                    "cudnn_conv_use_max_workspace": "0",
                                },
                            ),
                        )
                    self.mask_session = new_session("u2netp", providers=providers)
                    self.mask_provider = self.mask_session.inner_session.get_providers()[0]
                    if s.mask_device == "cuda" and self.mask_provider != "CUDAExecutionProvider":
                        raise RuntimeError(
                            "CUDA segmentation was requested but ONNX Runtime fell back to CPU"
                        )
                try:
                    mask = remove(result, session=self.mask_session, only_mask=True).convert("L")
                except Exception:
                    if s.mask_device != "auto" or self.mask_provider != "CUDAExecutionProvider":
                        raise
                    logging.getLogger(__name__).warning(
                        "GPU segmentation failed; retrying on CPU", exc_info=True
                    )
                    self.mask_session = new_session("u2netp", providers=["CPUExecutionProvider"])
                    self.mask_provider = "CPUExecutionProvider"
                    mask = remove(result, session=self.mask_session, only_mask=True).convert("L")
                # Empty segmentations must not erase the monster completely.
                if np.array(mask).max() < 16:
                    mask = image.getchannel("A")
        else:
            mask = image.getchannel("A")
        result = result.convert("RGBA")
        result.putalpha(mask)
        device_used = 0
        if not self.mock:
            free, total = self.torch.cuda.mem_get_info()
            device_used = (total - free) / 2**20
        return result, {
            "inference_ms": (inference_done - started) * 1000,
            "segmentation_ms": (time.perf_counter() - inference_done) * 1000,
            "render_ms": (time.perf_counter() - started) * 1000,
            "peak_vram_mib": peak,
            "actual_steps": s.actual_steps,
            "mock": self.mock,
            "mask_mode": s.mask_mode,
            "mask_provider": self.mask_provider,
            "device_used_mib": device_used,
            "steps": s.steps,
            "sampler": "DPM++ 2M Karras" if self.quality else "LCM",
            "strength": s.strength,
            "noise_position": self.noise_position,
            "noise_period": s.noise_period,
            "allocated_vram_mib": self.torch.cuda.memory_allocated() / 2**20 if not self.mock else 0,
            "reserved_vram_mib": self.torch.cuda.memory_reserved() / 2**20 if not self.mock else 0,
        }
