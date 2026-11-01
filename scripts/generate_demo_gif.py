#!/usr/bin/env python3
"""
Generate animated showcase demo GIF for DevGit README.
Runs server, captures headless Chrome frames across key dashboard features,
and compiles them into an optimized looping GIF.
"""

import os
import sys
import time
import subprocess
from pathlib import Path
from PIL import Image

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
TARGET_MULTI_WORKSPACE = Path("/home/sunil-bakale/IdeaProjects/dev----projects/dev-projects")
if not TARGET_MULTI_WORKSPACE.exists():
    TARGET_MULTI_WORKSPACE = WORKSPACE_ROOT

PORT = 8096
TOKEN = "demo1234567890"
OUTPUT_DIR = WORKSPACE_ROOT / "docs" / "assets"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_GIF = OUTPUT_DIR / "demo.gif"

TMP_DIR = Path("/tmp/devgit_demo_frames")
TMP_DIR.mkdir(parents=True, exist_ok=True)

VIEWS = [
    ("frame_1_overview", ""),
    ("frame_2_gitflow", "&demo=gitflow"),
    ("frame_3_worktree", "&demo=worktree"),
    ("frame_4_release", "&demo=release"),
    ("frame_5_shortcuts", "&demo=shortcuts"),
]

def main():
    env = dict(os.environ, DEVGIT_TOKEN=TOKEN)
    server_cmd = [
        sys.executable,
        str(WORKSPACE_ROOT / "backend" / "server.py"),
        "--workspace", str(TARGET_MULTI_WORKSPACE),
        "--port", str(PORT),
    ]

    print(f"Starting DevGit server on port {PORT}...")
    server_proc = subprocess.Popen(server_cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.5)

    captured_images = []

    try:
        for name, query in VIEWS:
            url = f"http://127.0.0.1:{PORT}/?token={TOKEN}{query}"
            out_png = TMP_DIR / f"{name}.png"
            print(f"Capturing view: {name} ({url})...")
            
            chrome_cmd = [
                "google-chrome",
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--window-size=1280,800",
                "--virtual-time-budget=6500",
                f"--screenshot={str(out_png)}",
                url
            ]
            subprocess.run(chrome_cmd, timeout=15, check=True)

            if out_png.exists() and out_png.stat().st_size > 0:
                img = Image.open(out_png).convert("RGBA")
                # Resize to clean documentation width (960x600)
                resized = img.resize((960, 600), Image.Resampling.LANCZOS)
                # Convert to palette mode for GIF
                quantized = resized.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT)
                captured_images.append(quantized)
                print(f"  Captured and processed {out_png.stat().st_size} bytes -> {quantized.size}")
            else:
                print(f"  Warning: failed to capture {name}")

    finally:
        server_proc.terminate()
        server_proc.wait()
        print("Server stopped.")

    if not captured_images:
        print("Error: No frames captured!")
        sys.exit(1)

    print(f"Compiling {len(captured_images)} frames into animated GIF: {OUTPUT_GIF}...")
    # Frame duration: 2500ms (2.5 seconds per screen)
    captured_images[0].save(
        OUTPUT_GIF,
        save_all=True,
        append_images=captured_images[1:],
        duration=2500,
        loop=0,
        optimize=True,
    )

    print(f"Successfully generated demo GIF at {OUTPUT_GIF} ({OUTPUT_GIF.stat().st_size // 1024} KB)")

if __name__ == "__main__":
    main()
