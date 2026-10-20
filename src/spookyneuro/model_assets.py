"""Pinned inference assets shared by the installer and runtime (no main-ref dependency)."""

SD_MODEL = "stable-diffusion-v1-5/stable-diffusion-v1-5"
LCM_MODEL = "latent-consistency/lcm-lora-sdv1-5"
DINO_MODEL = "facebook/dino-vitb16"
MODEL_REVISIONS = {
    SD_MODEL: "451f4fe16113bff5a5d2269ed5ad43b0592e9a14",
    LCM_MODEL: "cf2fced511dbe7e26c8d1d397e728fbab875db4b",
    "stabilityai/TripoSR": "5b521936b01fbe1890f6f9baed0254ab6351c04a",
    DINO_MODEL: "f205d5d8e640a89a2b8ef0369670dfc37cc07fc2",
}
MODEL_FILES = {
    SD_MODEL: [
        "model_index.json",
        "feature_extractor/preprocessor_config.json",
        "scheduler/scheduler_config.json",
        "tokenizer/merges.txt",
        "tokenizer/special_tokens_map.json",
        "tokenizer/tokenizer_config.json",
        "tokenizer/vocab.json",
        "text_encoder/config.json",
        "text_encoder/model.safetensors",
        "unet/config.json",
        "unet/diffusion_pytorch_model.safetensors",
        "vae/config.json",
        "vae/diffusion_pytorch_model.safetensors",
    ],
    LCM_MODEL: ["pytorch_lora_weights.safetensors"],
    "stabilityai/TripoSR": ["config.yaml", "model.ckpt"],
    # TripoSR's checkpoint already contains the image encoder weights.
    DINO_MODEL: ["config.json"],
}
