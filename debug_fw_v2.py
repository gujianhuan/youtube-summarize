
import os
import sys
import traceback
from faster_whisper import WhisperModel

print(f"Python: {sys.version}")
model_path = os.path.join(os.getcwd(), "models")
os.makedirs(model_path, exist_ok=True)

print("-" * 20)
print("Attempting CUDA load (should fail if DLLs missing)...")
try:
    model = WhisperModel("tiny", device="cuda", compute_type="int8", download_root=model_path)
    print("✅ CUDA load successful (Unexpected)")
except Exception as e:
    print(f"✅ CUDA load failed as expected: {e}")
    
    print("-" * 20)
    print("Attempting CPU fallback after CUDA failure...")
    try:
        model = WhisperModel("tiny", device="cpu", compute_type="int8", download_root=model_path)
        print("✅ CPU fallback successful")
        
        # Try transcribe
        import wave
        dummy_wav = "test_audio_v2.wav"
        with wave.open(dummy_wav, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00" * 32000)
            
        segments, _ = model.transcribe(dummy_wav, beam_size=1)
        list(segments) # consume
        print("✅ CPU Transcription successful")
        os.remove(dummy_wav)
        
    except Exception as e_cpu:
        print(f"❌ CPU fallback failed: {e_cpu}")
        traceback.print_exc()
