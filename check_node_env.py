
import sys
import os
import shutil

# Import core_logic to trigger the environment setup code
try:
    import core_logic
    print("core_logic imported successfully.")
except Exception as e:
    print(f"Error importing core_logic: {e}")

def check_node():
    print(f"\nCurrent PATH: {os.environ.get('PATH')}")
    
    node_path = shutil.which("node")
    print(f"\nshutil.which('node'): {node_path}")
    
    if node_path:
        print("Node.js found!")
        # Try executing it
        try:
            import subprocess
            res = subprocess.run([node_path, "--version"], capture_output=True, text=True)
            print(f"Node version: {res.stdout.strip()}")
        except Exception as e:
            print(f"Error executing node: {e}")
    else:
        print("Node.js NOT found in PATH.")

if __name__ == "__main__":
    check_node()
