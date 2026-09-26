import os
import sys
from pathlib import Path
from huggingface_hub import hf_hub_download

# Create models directory
models_dir = os.path.join(os.path.dirname(__file__), "models")
os.makedirs(models_dir, exist_ok=True)

print("Downloading Qwen2.5-1.5B-Instruct-Q4_K_M.gguf (Qwen3-compatible local LLM)...")
try:
    model_path = hf_hub_download(
        repo_id="Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        filename="qwen2.5-1.5b-instruct-q4_k_m.gguf",
        local_dir=models_dir,
        local_dir_use_symlinks=False
    )
    print(f"Downloaded to {model_path}")
except Exception as e:
    print(f"Error downloading model: {e}")

