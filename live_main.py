"""live_main.py — Stage 2.5: a natural, interruptible voice conversation.

No push-to-talk: just speak. The Gemini Live API keeps a websocket open, mic
audio streams up, the agent's voice streams down, and the server's voice
activity detection notices when you start talking — even mid-agent-sentence
(barge-in), exactly like a real phone call. This is the same architecture
Stage 3 will run over a phone line; only the audio transport will change.

The agent's brain is still ReceptionistAgent: its system prompt, tool schemas,
and tool execution are reused as-is. Only the conversation loop moves to the
server (the Live API decides when a turn ends, not our while-loop).

Usage:
    python live_main.py --client demo_clinic
    python live_main.py --half-duplex     # no headphones? mic mutes while agent speaks

🎧 USE HEADPHONES for full-duplex mode — with laptop speakers the mic hears
the agent's own voice and it will interrupt itself. --half-duplex avoids that
at the cost of barge-in.

Press Ctrl+C to hang up; the transcript is saved automatically.
"""

import argparse
import asyncio
from datetime import datetime

import sounddevice as sd

import storage
from agent import TOOL_SCHEMAS, ReceptionistAgent
from llm import GeminiLive
from main import save_transcript

MIC_RATE = 16000       # what the Live API expects in
SPEAKER_RATE = 24000   # what the Live API sends back
MIC_CHUNK = 800        # 50 ms of mic audio per network packet


async def run(client_id: str, half_duplex: bool):
    agent = ReceptionistAgent(client_id)
    started = datetime.now()
    live = GeminiLive()
    await live.connect(agent.system_prompt, TOOL_SCHEMAS)

    loop = asyncio.get_running_loop()
    mic_queue: asyncio.Queue = asyncio.Queue()
    playback = bytearray()  # agent speech waiting to be played

    # Audio callbacks run on sounddevice's own thread — they must be tiny.
    # Mic: hand the chunk to asyncio. Speaker: pull whatever is buffered, pad silence.
    def on_mic(indata, frames, time_info, status):
        loop.call_soon_threadsafe(mic_queue.put_nowait, bytes(indata))

    def on_speaker(outdata, frames, time_info, status):
        n = len(outdata)
        chunk = bytes(playback[:n])
        del playback[:n]
        outdata[: len(chunk)] = chunk
        outdata[len(chunk):] = b"\x00" * (n - len(chunk))

    async def pump_mic():
        while True:
            chunk = await mic_queue.get()
            if half_duplex and playback:
                continue  # agent is speaking and we have no headphones: drop mic audio
            await live.send_audio(chunk)

    async def pump_events():
        user_line, agent_line = "", ""
        async for event in live.events():
            kind = event["type"]
            if kind == "audio":
                playback.extend(event["data"])
            elif kind == "interrupted":
                playback.clear()  # caller barged in — go silent immediately
            elif kind == "user_text":
                user_line += event["text"]
            elif kind == "agent_text":
                agent_line += event["text"]
            elif kind == "tool_calls":
                results = []
                for call in event["calls"]:
                    print(f"  [tool] {call['name']}({call['args']})")
                    # A tool failure (e.g. bookings.db busy) must not end the
                    # call — report it to the model like the phone bridge does.
                    try:
                        result = agent._execute_tool(call["name"], call["args"])
                    except Exception as e:
                        result = {"error": f"{type(e).__name__}: {e}"}
                    results.append({"id": call["id"], "name": call["name"], "result": result})
                await live.send_tool_results(results)
            elif kind == "turn_complete":
                # Log the finished exchange in the agent's normal history format,
                # so /transcript-style saving works identically to text mode.
                if user_line.strip():
                    print(f"You said: {user_line.strip()}")
                    agent.history.append({"role": "user", "text": user_line.strip()})
                if agent_line.strip():
                    print(f"Agent:    {agent_line.strip()}\n")
                    agent.history.append({"role": "assistant", "text": agent_line.strip()})
                user_line, agent_line = "", ""

    business = agent.config["business_name"]
    mode = "half-duplex (mic muted while agent speaks)" if half_duplex else "full-duplex (🎧 headphones!)"
    print(f"\n=== VoxAgent LIVE — receptionist of {business} ===")
    print(f"Just start talking. Mode: {mode}. Ctrl+C to hang up.\n")

    try:
        with sd.RawInputStream(
            samplerate=MIC_RATE, channels=1, dtype="int16",
            blocksize=MIC_CHUNK, callback=on_mic,
        ), sd.RawOutputStream(
            samplerate=SPEAKER_RATE, channels=1, dtype="int16", callback=on_speaker,
        ):
            await asyncio.gather(pump_mic(), pump_events())
    finally:
        await live.close()
        if agent.history:
            print(f"\n(transcript saved to {save_transcript(agent)})")
            storage.log_call_from_agent(agent, "live", started)


def main():
    parser = argparse.ArgumentParser(description="VoxAgent Stage 2.5 — live voice call")
    parser.add_argument("--client", default="demo_clinic")
    parser.add_argument(
        "--half-duplex", action="store_true",
        help="mute the mic while the agent speaks (use when you have no headphones)",
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(args.client, args.half_duplex))
    except KeyboardInterrupt:
        print("\nCall ended.")


if __name__ == "__main__":
    main()
