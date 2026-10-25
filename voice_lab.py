"""voice_lab.py — hear every voice say the same sentence, then pick one.

    python voice_lab.py                  # all languages, every configured provider
    python voice_lab.py --language te    # just Telugu
    python voice_lab.py --text "..."     # your own sentence

It writes mp3s plus an `index.html` into `voice_lab/` and opens it, so the two
of you can listen side by side and decide with your ears instead of reading a
comparison table. Providers without a key are skipped and listed as missing,
so the page also shows what a key would unlock.

WHY this exists: regional voice quality is the clearest gap between us and the
competition, and it is the one thing a customer judges in the first sentence.
Opinions are cheap here; listening is not.
"""

import argparse
import datetime as dt
import html
import pathlib
import time
import webbrowser

from dotenv import load_dotenv

import voices

load_dotenv()

OUT_DIR = pathlib.Path(__file__).resolve().parent / "voice_lab"

# One realistic receptionist line per language — the kind of sentence a
# customer actually hears, not "the quick brown fox".
SAMPLES = {
    "en": ("Sri Balaji Dental Care is open Monday to Saturday, 9:30 AM to 1 PM "
           "and 4 PM to 8:30 PM. A teeth cleaning is 1,200 rupees. "
           "Shall I book you for tomorrow at 10:30?"),
    "te": ("శ్రీ బాలాజీ డెంటల్ కేర్ సోమవారం నుండి శనివారం వరకు ఉదయం 9:30 నుండి "
           "మధ్యాహ్నం 1:00 వరకు తెరిచి ఉంటుంది. పళ్ళు శుభ్రం చేయటానికి 1,200 రూపాయలు. "
           "రేపు ఉదయం 10:30కి బుక్ చేయమంటారా?"),
    "ta": ("ஸ்ரீ பாலாஜி டென்டல் கேர் திங்கள் முதல் சனி வரை காலை 9:30 முதல் "
           "மதியம் 1:00 வரை திறந்திருக்கும். பல் சுத்தம் செய்ய 1,200 ரூபாய். "
           "நாளை காலை 10:30 மணிக்கு பதிவு செய்யலாமா?"),
    "hi": ("श्री बालाजी डेंटल केयर सोमवार से शनिवार तक सुबह 9:30 से दोपहर 1:00 बजे तक "
           "खुला रहता है। दाँत की सफाई 1,200 रुपये है। "
           "क्या मैं आपके लिए कल सुबह 10:30 बजे बुक कर दूँ?"),
}


def render(results: list[dict], missing: list[str]) -> str:
    rows = []
    for r in results:
        if r["ok"]:
            player = (f'<audio controls preload="none" src="{html.escape(r["file"])}"></audio>'
                      f'<div class="meta">{r["ms"]} ms · {r["kb"]} KB</div>')
        else:
            player = f'<div class="fail">failed: {html.escape(r["error"])}</div>'
        rows.append(
            f'<tr><td class="lang">{html.escape(r["language"])}</td>'
            f'<td class="prov">{html.escape(r["provider"])}</td>'
            f'<td class="voice">{html.escape(str(r["voice"]))}</td>'
            f'<td>{player}</td></tr>')

    missing_html = ""
    if missing:
        items = "".join(f"<li><code>{html.escape(m)}</code></li>" for m in missing)
        missing_html = (
            '<div class="missing"><strong>Not configured</strong> — add a key to '
            f'<code>.env</code> and run again to compare these:<ul>{items}</ul></div>')

    return f"""<!doctype html><meta charset="utf-8">
<title>Atithi voice lab</title>
<style>
 body{{font-family:system-ui,Segoe UI,sans-serif;margin:32px;max-width:900px;color:#16202e}}
 h1{{margin:0 0 4px}} .sub{{color:#667; margin-bottom:24px}}
 table{{border-collapse:collapse;width:100%}}
 th,td{{text-align:left;padding:10px 12px;border-bottom:1px solid #e6eaf0;vertical-align:middle}}
 th{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#667}}
 .lang{{font-weight:700;text-transform:uppercase}}
 .prov{{font-weight:600}} .voice{{color:#667;font-family:ui-monospace,monospace;font-size:13px}}
 .meta{{color:#889;font-size:12px;margin-top:4px}}
 .fail{{color:#b4232c;font-size:13px}}
 .missing{{margin-top:28px;padding:14px 18px;background:#f6f8fb;border-radius:10px;font-size:14px}}
 .missing ul{{margin:8px 0 0 18px}} audio{{height:34px}}
</style>
<h1>Atithi voice lab</h1>
<div class="sub">Same sentence, every configured provider. Generated {dt.datetime.now():%Y-%m-%d %H:%M}.
Pick per language, then put it in the business YAML under <code>voice:</code>.</div>
<table><tr><th>Lang</th><th>Provider</th><th>Voice</th><th>Listen</th></tr>
{"".join(rows)}
</table>{missing_html}
"""


def main():
    parser = argparse.ArgumentParser(description="Compare TTS voices side by side")
    parser.add_argument("--language", "-l", choices=sorted(SAMPLES),
                        help="only this language (default: all)")
    parser.add_argument("--text", "-t", help="say this instead of the sample line")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    languages = [args.language] if args.language else list(SAMPLES)
    registry = voices.registry()
    configured = voices.available_providers()
    missing = [f"{p.env_key} ({name})" for name, p in registry.items()
               if not p.available() and p.env_key]

    OUT_DIR.mkdir(exist_ok=True)
    print(f"\nProviders configured: {', '.join(configured)}")
    if missing:
        print(f"Not configured: {', '.join(missing)}")
    print()

    results = []
    for language in languages:
        text = args.text or SAMPLES[language]
        for name in configured:
            provider = registry[name]
            voice = provider.voice_for(language)
            if not voice:
                continue
            row = {"language": language, "provider": name, "voice": voice}
            t0 = time.perf_counter()
            try:
                audio = provider.synthesize(text, voice)
                elapsed = int((time.perf_counter() - t0) * 1000)
                filename = f"{language}_{name}_{str(voice).replace('/', '-')}.mp3"
                (OUT_DIR / filename).write_bytes(audio)
                row.update(ok=True, file=filename, ms=elapsed, kb=len(audio) // 1024)
                print(f"  ok    {language:<3} {name:<11} {voice:<24} "
                      f"{elapsed:>5} ms  {len(audio)//1024:>4} KB")
            except Exception as e:
                row.update(ok=False, error=str(e)[:200])
                print(f"  FAIL  {language:<3} {name:<11} {voice:<24} {e}")
            results.append(row)

    page = OUT_DIR / "index.html"
    page.write_text(render(results, missing), encoding="utf-8")
    print(f"\nListen here: {page}")
    if not args.no_open:
        webbrowser.open(page.as_uri())


if __name__ == "__main__":
    main()
