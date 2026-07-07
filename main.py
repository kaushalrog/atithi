"""main.py — Stage 1 terminal wrapper around the agent core.

This file is deliberately thin (architecture principle 3): it only reads lines
from the keyboard and prints replies. All the intelligence lives in agent.py.
In Stage 2 this file gets a sibling that feeds the same agent from a microphone.

Usage:
    python main.py --client demo_clinic

Commands inside the chat:
    /reset       clear the conversation history
    /transcript  save the conversation to transcripts/<timestamp>.txt
    /quit        exit
"""

import argparse
from datetime import datetime
from pathlib import Path

import storage
from agent import ReceptionistAgent

BASE_DIR = Path(__file__).resolve().parent


def save_transcript(agent: ReceptionistAgent) -> Path:
    folder = BASE_DIR / "transcripts"
    folder.mkdir(exist_ok=True)
    path = folder / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    path.write_text(agent.transcript_text(), encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description="VoxAgent Stage 1 — text receptionist")
    parser.add_argument(
        "--client",
        default="demo_clinic",
        help="client id — must match a file in clients/<client_id>.yaml",
    )
    args = parser.parse_args()

    agent = ReceptionistAgent(args.client)
    started = datetime.now()
    business = agent.config["business_name"]
    print(f"\n=== VoxAgent — you are chatting with the receptionist of {business} ===")
    print("Commands: /reset  /transcript  /quit\n")

    while True:
        try:
            user = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break

        if not user:
            continue
        if user == "/quit":
            print("Bye!")
            break
        if user == "/reset":
            agent.reset()
            print("(conversation history cleared)\n")
            continue
        if user == "/transcript":
            path = save_transcript(agent)
            print(f"(transcript saved to {path})\n")
            continue

        reply = agent.chat(user)
        print(f"\nAgent: {reply}\n")

    # Every conversation matters: save the transcript AND log the call so it
    # appears in the portal's call history like any other channel.
    if agent.history:
        print(f"(transcript saved to {save_transcript(agent)})")
        storage.log_call_from_agent(agent, "terminal", started)


if __name__ == "__main__":
    main()
