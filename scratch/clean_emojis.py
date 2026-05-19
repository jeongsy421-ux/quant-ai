import os
import re

def remove_emojis(text):
    # Remove characters outside the Basic Multilingual Plane (which includes most emojis)
    return re.sub(r'[^\u0000-\uFFFF]', '', text)

backend_dir = r"c:\Users\jihun\Desktop\quant_ai\backend"
for root, dirs, files in os.walk(backend_dir):
    for file in files:
        if file.endswith(".py"):
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            
            new_content = remove_emojis(content)
            
            if content != new_content:
                print(f"Cleaning {file}...")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_content)

print("Emoji cleanup complete.")
