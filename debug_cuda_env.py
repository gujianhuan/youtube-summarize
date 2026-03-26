
import os
import sys
import ctypes
import site

print(f"Python: {sys.version}")
print(f"CWD: {os.getcwd()}")

# 1. Check nvidia packages
print("-" * 20)
print("Checking nvidia packages...")
try:
    import nvidia.cublas.lib
    import nvidia.cudnn.lib
    cublas_dir = os.path.dirname(nvidia.cublas.lib.__file__)
    cudnn_dir = os.path.dirname(nvidia.cudnn.lib.__file__)
    print(f"nvidia-cublas found at: {cublas_dir}")
    print(f"nvidia-cudnn found at: {cudnn_dir}")
    
    # List interesting files
    print("Files in cublas dir:", [f for f in os.listdir(cublas_dir) if f.endswith(".dll")])
    print("Files in cudnn dir:", [f for f in os.listdir(cudnn_dir) if f.endswith(".dll")])
    
    # Add to PATH temporarily for testing
    os.environ["PATH"] = cublas_dir + os.pathsep + cudnn_dir + os.pathsep + os.environ["PATH"]
except ImportError as e:
    print(f"❌ Failed to import nvidia packages: {e}")

# 2. Check ctranslate2
print("-" * 20)
print("Checking ctranslate2...")
try:
    import ctranslate2
    print(f"ctranslate2 version: {ctranslate2.__version__}")
    print(f"ctranslate2 file: {ctranslate2.__file__}")
except ImportError as e:
    print(f"❌ ctranslate2 not installed: {e}")

# 3. Test Loading DLLs directly
print("-" * 20)
print("Testing DLL loading...")

def try_load(dll_name):
    try:
        ctypes.CDLL(dll_name)
        print(f"✅ Loaded {dll_name}")
        return True
    except Exception as e:
        print(f"❌ Failed to load {dll_name}: {e}")
        return False

# Try loading dependency first? zlibwapi is often needed for cuDNN
try_load("zlibwapi.dll")

# Try loading cublas
if not try_load("cublas64_12.dll"):
    try_load("cublas64_11.dll")

# Try loading cudnn
# Note: cudnn 9.x might have different dll names or dependencies
try_load("cudnn64_8.dll") 
try_load("cudnn64_9.dll")
# Check for cudnn_ops_infer (part of cudnn 8/9)
try_load("cudnn_ops_infer64_8.dll")
try_load("cudnn_ops_infer64_9.dll")

# 4. Try faster-whisper init with verbose error
print("-" * 20)
print("Attempting faster-whisper init...")
try:
    from faster_whisper import WhisperModel
    model_path = os.path.join(os.getcwd(), "models")
    model = WhisperModel("tiny", device="cuda", compute_type="int8", download_root=model_path)
    print("✅ WhisperModel(cuda) initialized!")
except Exception as e:
    print(f"❌ WhisperModel(cuda) failed: {e}")
    # traceback.print_exc()
