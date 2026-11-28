"""Download the local Hindi voice for the app's spoken read-back (Piper hi_IN pratham, about 64 MB).

    python scripts/get_voice.py            # into ./models
    python scripts/get_voice.py /app/models

Source: Hugging Face rhasspy/piper-voices (MIT licensed voices). Run once; the
Docker image runs it at build time.
"""
import os
import socket
import sys
import urllib.request

VOICE = "hi_IN-pratham-medium"
BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/hi/hi_IN/pratham/medium/"


def main():
    socket.setdefaulttimeout(60)  # a stalled download must not hang the Docker build
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "models")
    os.makedirs(out, exist_ok=True)
    for name in (f"{VOICE}.onnx", f"{VOICE}.onnx.json"):
        path = os.path.join(out, name)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            print("have", path)
            continue
        print("downloading", name)
        urllib.request.urlretrieve(BASE + name, path + ".part")
        os.replace(path + ".part", path)
    print("voice ready in", os.path.abspath(out))


if __name__ == "__main__":
    main()
