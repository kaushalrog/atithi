"""voice_main.py — Stage 2: talk to the receptionist with your voice.

Notice what did NOT change: agent.py. The voice pipeline wraps the exact same
ReceptionistAgent as the text terminal — that's architecture principle 3
paying off. Each turn is a pipeline:

    mic (audio_io) -> WAV -> Gemini STT (llm.transcribe) -> agent.chat(text)
                                   -> reply text -> edge-tts (tts.py) -> speaker

Usage:
    python voice_main.py --client demo_clinic
    python voice_main.py --mute        # see replies without hearing them

At the prompt: press ENTER alone to talk (ENTER again to stop recording),
or just type a message. /reset, /transcript and /quit work as before.
"""

import argparse
import tempfile
from datetime import datetime
from pathlib import Path

import storage
from agent import ReceptionistAgent
from audio_io import play_mp3, record_until_enter
from main import save_transcript
from tts import EdgeTTS


def speak(tts: EdgeTTS, text: str):
    mp3_path = Path(tempfile.gettempdir()) / "voxagent_reply.mp3"
    tts.synthesize(text, str(mp3_path))
    play_mp3(str(mp3_path))


def main():
    parser = argparse.ArgumentParser(description="VoxAgent Stage 2 — voice receptionist")
    parser.add_argument("--client", default="demo_clinic")
    parser.add_argument("--mute", action="store_true", help="text-only replies (no speaker)")
    args = parser.parse_args()

    agent = ReceptionistAgent(args.client)
    started = datetime.now()
    tts = EdgeTTS()
    business = agent.config["business_name"]
    print(f"\n=== VoxAgent VOICE — receptionist of {business} ===")
    print("Press ENTER to start talking, ENTER again to stop. Or type a message.")
    print("Commands: /reset  /transcript  /quit\n")

    while True:
        try:
            typed = input("You (ENTER = talk, or type): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break

        if typed == "/quit":
            print("Bye!")
            break
        if typed == "/reset":
            agent.reset()
            print("(conversation history cleared)\n")
            continue
        if typed == "/transcript":
            print(f"(transcript saved to {save_transcript(agent)})\n")
            continue

        if typed:
            user_text = typed
        else:
            print("  🎙  recording... press ENTER to stop")
            wav_bytes = record_until_enter()
            print("  transcribing...")
            user_text = agent.llm.transcribe(wav_bytes)
            if not user_text:
                print("  (didn't catch any speech — try again)\n")
                continue
            print(f"You said: {user_text}")

        reply = agent.chat(user_text)
        print(f"\nAgent: {reply}\n")

        if not args.mute:
            try:
                speak(tts, reply)
            except Exception as e:
                # Voice output must never kill the conversation — same philosophy
                # as the best-effort Google Sheets copy in storage.py.
                print(f"  [warning] voice output failed ({e}) — continuing text-only.")

    if agent.history:
        print(f"(transcript saved to {save_transcript(agent)})")
        storage.log_call_from_agent(agent, "voice", started)


if __name__ == "__main__":
    main()
