# Atithi launch film

`brag.mp4` is a 25-second, 1920x1080 film of Atithi, made with the
[brag](https://github.com/latent-spaces/brag) skill and
[HyperFrames](https://hyperframes.heygen.com). `brag.jpg` is its poster (also
baked in as frame 0, so link previews show it). `share-copy.txt` is the caption.

**What it shows:** a real owner-portal test chat on synthetic data (Demo Dental
Studio; customer "Ananya Rao", 9000012345). The receptionist checks the real
calendar, books a teeth cleaning, and the owner sees the transcript's
"Result: confirmed" next to the saved booking row. Every claim on screen is
backed by the product as it is: the booking confirmation matches a successful
tool result, and nothing claims live phone or WhatsApp service.

**Re-render** (from `brag-output/composition`):

```bash
npx hyperframes@0.8.221 check
npx hyperframes@0.8.221 render --quality delivery --output ../brag.mp4
```

`brag-plan.md` is the storyboard and `composition-brief.md` the handoff brief.
The source captures are in `demo/film/`.

## Credits

- Music: "Happy Beats / Business Moves Vol. 1" by Sascha Ende, ende.app
  ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)). Credit it
  wherever the film is posted (it's in `share-copy.txt`).
- Sound effects: Kenney.nl impact sounds (CC0, public domain).
- Fonts: Instrument Serif and Instrument Sans (SIL Open Font License).
- Animation: GSAP 3.14.2 (vendored in `composition/assets/vendor`).
