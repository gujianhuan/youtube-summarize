
import os

def convert_to_utf8(file_path):
    try:
        data = open(file_path, 'rb').read()
        
        # Try UTF-8 first
        try:
            content = data.decode('utf-8')
            print("Already UTF-8.")
            return
        except UnicodeDecodeError:
            pass
            
        # Try GBK
        try:
            content = data.decode('gbk')
            print("Detected GBK, converting to UTF-8.")
        except UnicodeDecodeError:
            # Fallback to errors='replace'
            content = data.decode('utf-8', errors='replace')
            print("Could not detect encoding, converted with 'replace' (errors='replace')")
            
        # Backup
        if not os.path.exists(file_path + ".bak"):
             os.rename(file_path, file_path + ".bak")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print("Successfully converted.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    convert_to_utf8(r"d:\Program Files\Trae\YouTubeSummarizer\core_logic.py")
