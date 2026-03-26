
import sys
import os

def read_lines(file_path, start, end):
    try:
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            return
            
        with open(file_path, 'rb') as f:
            content = f.read()
            # Try some common encodings
            for enc in ['utf-8', 'gbk', 'utf-16', 'latin-1']:
                try:
                    text = content.decode(enc)
                    lines = text.splitlines()
                    print(f"Detected encoding: {enc}")
                    for i in range(start-1, min(end, len(lines))):
                        print(f"{i+1}: {lines[i]}")
                    return
                except:
                    continue
            print("Failed to decode with common encodings.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python inspect_file.py <file_path> <start_line> <end_line>")
    else:
        read_lines(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
