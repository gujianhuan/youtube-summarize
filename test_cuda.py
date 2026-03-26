
import os
import sys
import time

print(f"Python: {sys.version}")
print(f"CWD: {os.getcwd()}")

try:
    import torch
    print(f"PyTorch installed: {torch.__version__}")
    print(f"PyTorch CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"PyTorch CUDA device: {torch.cuda.get_device_name(0)}")
except ImportError:
    print("PyTorch not installed")

print("-" * 20)

try:
    import ctranslate2
    print(f"ctranslate2 version: {ctranslate2.__version__}")
    print(f"ctranslate2 CUDA device count: {ctranslate2.get_cuda_device_count()}")
    
    # Try to verify if libraries are loaded
    print("Attempting to load ctranslate2 generator on CUDA...")
    # This might fail if DLLs are missing
except ImportError:
    print("ctranslate2 not installed")
except Exception as e:
    print(f"ctranslate2 error: {e}")

print("-" * 20)

try:
    from faster_whisper import WhisperModel
    print("faster_whisper imported successfully")
except ImportError:
    print("faster_whisper not installed")

