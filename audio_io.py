"""audio_io.py — the hardware layer: microphone in, speaker out.

This file knows nothing about Gemini, edge-tts, or the agent — only about
recording bytes and playing files. When Stage 3 replaces the mic with a phone
line, this file is what gets swapped, and nothing above it notices.
"""

import os
import time
import wave
from io import BytesIO

import sounddevice as sd

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "hide")  # silence pygame's banner

# 16 kHz mono int16 — the standard format speech-recognition models expect.
SAMPLE_RATE = 16000


def record_until_enter() -> bytes:
    """Record from the default microphone until the user presses Enter.

    Returns a complete WAV file as bytes. The stream callback collects raw
    audio chunks in the background while input() blocks waiting for Enter —
    no threads to manage ourselves.
    """
    chunks = []

    def callback(indata, frames, time_info, status):
        chunks.append(bytes(indata))

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="int16", callback=callback
    ):
        input()

    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # int16 = 2 bytes per sample
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(b"".join(chunks))
    return buffer.getvalue()


def play_mp3(path: str):
    """Play an mp3 and block until it finishes."""
    import pygame  # imported here so text-only mode never needs it

    if not pygame.mixer.get_init():
        pygame.mixer.init()
    pygame.mixer.music.load(path)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        time.sleep(0.1)
    pygame.mixer.music.unload()  # release the file so we can overwrite it next turn
