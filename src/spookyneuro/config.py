import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Settings:
    model: str = "stable-diffusion-v1-5/stable-diffusion-v1-5"
    lcm: str = "latent-consistency/lcm-lora-sdv1-5"
    lora: str | None = None
    lora_scale: float = 0.8
    size: int = 256
    steps: int = 4
    strength: float = 0.65
    seed: int = 42
    noise_period: float = 3.0
    prompt: str = (
        "spookycreature, a single full body humanoid monster, pale mottled flesh, hybrid human and animal anatomy, "
        "elongated limbs, distorted face, practical horror movie creature, dark plain background"
    )
    mask_mode: str = "free"
    mask_device: str = "auto"
    interpolation: str = "flow"

    def validate(self):
        if self.size not in (256, 384, 512):
            raise ValueError("size must be 256, 384 or 512")
        if self.steps not in (2, 4, 6, 8):
            raise ValueError("steps must be 2, 4, 6 or 8")
        if not 0 < self.strength <= 1 or int(self.steps * self.strength) < 1:
            raise ValueError("strength must yield at least one actual denoising step")
        if self.noise_period <= 0 or not 0 <= self.lora_scale <= 2:
            raise ValueError("Invalid noise period or LoRA weight")
        if self.mask_mode not in ("fixed", "free") or self.interpolation not in ("flow", "blend"):
            raise ValueError("Invalid mask/interpolation mode")
        if self.mask_device not in ("auto", "cpu", "cuda"):
            raise ValueError("mask_device must be auto, cpu or cuda")
        return self

    @property
    def actual_steps(self):
        return int(self.steps * self.strength)

    @classmethod
    def load(cls, path=None):
        return cls(**(json.loads(Path(path).read_text()) if path else {})).validate()

    def to_dict(self):
        return asdict(self)
