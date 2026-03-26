
import os
import sys
import time
import traceback

print(f"Python: {sys.version}")
print(f"CWD: {os.getcwd()}")

print("-" * 20)
print("Testing faster-whisper import...")
try:
    from faster_whisper import WhisperModel
    print("✅ Import successful")
except Exception as e:
    print(f"❌ Import failed: {e}")
    traceback.print_exc()
    sys.exit(1)

print("-" * 20)
print("Testing model initialization (CPU INT8)...")
try:
    # Use 'tiny' for quick test
    model_path = os.path.join(os.getcwd(), "models")
    model = WhisperModel("tiny", device="cpu", compute_type="int8", download_root=model_path)
    print("✅ Model initialized successfully")
except Exception as e:
    print(f"❌ Model initialization failed: {e}")
    traceback.print_exc()
    sys.exit(1)

print("-" * 20)
print("Testing dummy transcription...")
try:
    # Create a dummy silent wav file
    import wave
    dummy_wav = "test_audio.wav"
    with wave.open(dummy_wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00" * 32000) # 2 seconds silence
    
    segments, info = model.transcribe(dummy_wav, beam_size=1)
    print("Transcribing...")
    count = 0
    for segment in segments:
        count += 1
        print(f"Segment: {segment.text}")
    print(f"✅ Transcription successful (segments: {count})")
    
    os.remove(dummy_wav)
except Exception as e:
    print(f"❌ Transcription failed: {e}")
    traceback.print_exc()
