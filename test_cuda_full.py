
import os
import sys
from faster_whisper import WhisperModel

# Use the same logic as core_logic.py
model_size = "small" # User mentioned small mode
model_dir = os.path.join(os.getcwd(), "models")
os.makedirs(model_dir, exist_ok=True)

print(f"Testing loading '{model_size}' model from {model_dir}")
print(f"Current CWD: {os.getcwd()}")

try:
    print("\n--- Attempt 1: CUDA float16 ---")
    model = WhisperModel(model_size, device="cuda", compute_type="float16", download_root=model_dir)
    print("✅ Success! Loaded on CUDA float16")
except Exception as e:
    print(f"❌ Failed: {e}")
    
    try:
        print("\n--- Attempt 2: CUDA int8 ---")
        model = WhisperModel(model_size, device="cuda", compute_type="int8", download_root=model_dir)
        print("✅ Success! Loaded on CUDA int8")
    except Exception as e2:
        print(f"❌ Failed: {e2}")
        
        try:
            print("\n--- Attempt 3: CPU int8 ---")
            model = WhisperModel(model_size, device="cpu", compute_type="int8", download_root=model_dir)
            print("✅ Success! Loaded on CPU int8")
        except Exception as e3:
             print(f"❌ Failed: {e3}")
