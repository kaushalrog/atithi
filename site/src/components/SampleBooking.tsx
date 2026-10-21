import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, m, useReducedMotion } from "motion/react";
import { SCENARIOS, type RecordState, type Step } from "../data/scenarios";
import { BookingRecord } from "./BookingRecord";

// How long each kind of step stays on screen before the next one (ms).
// Agent lines get reading time in proportion to their length.
const PAUSE = { customer: 1100, tool: 900, agent: 900 };
const RESOLVE_MS = 950; // a tool's "Checking…" before its result
const readTime = (s: Step) => (s.kind === "agent" ? PAUSE.agent + s.text.length * 18 : PAUSE[s.kind]);

export const PLAY_EVENT = "atithi:play-sample";

type State = { scenario: number; shown: number; resolved: boolean; playing: boolean };

export function SampleBooking() {
  // First render (and the prerendered HTML) shows the whole first scenario,
  // so the page tells the story even before JavaScript runs.
  const [st, setSt] = useState<State>({ scenario: 0, shown: SCENARIOS[0].steps.length, resolved: true, playing: false });
  const reduce = useReducedMotion();
  const sc = SCENARIOS[st.scenario];
  const done = st.shown >= sc.steps.length && st.resolved;
  const section = useRef<HTMLElement>(null);
  const talk = useRef<HTMLOListElement>(null);

  const start = useCallback((scenario: number) => {
    const first = SCENARIOS[scenario].steps[0];
    setSt({ scenario, shown: 1, resolved: first.kind !== "tool", playing: true });
  }, []);

  // Advance one beat: resolve a pending tool, or reveal the next step.
  const advance = useCallback(() => {
    setSt((s) => {
      const steps = SCENARIOS[s.scenario].steps;
      if (!s.resolved) return { ...s, resolved: true };
      if (s.shown >= steps.length) return { ...s, playing: false };
      const next = steps[s.shown];
      return { ...s, shown: s.shown + 1, resolved: next.kind !== "tool" };
    });
  }, []);

  useEffect(() => {
    if (!st.playing) return;
    if (done) { setSt((s) => ({ ...s, playing: false })); return; }
    const last = sc.steps[st.shown - 1];
    const wait = !st.resolved ? RESOLVE_MS : readTime(last);
    const t = window.setTimeout(advance, wait);
    return () => window.clearTimeout(t);
  }, [st, sc, done, advance]);

  // The hero's "Play a sample booking" button starts scenario 1.
  useEffect(() => {
    const onPlay = () => start(0);
    window.addEventListener(PLAY_EVENT, onPlay);
    return () => window.removeEventListener(PLAY_EVENT, onPlay);
  }, [start]);

  const visible = sc.steps.slice(0, st.shown);
  // Keep the newest line in view inside the conversation box (never scrolls the page).
  useEffect(() => {
    const el = talk.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: reduce ? "auto" : "smooth" });
  }, [st.shown, st.resolved, st.scenario, reduce]);
  const record: RecordState = useMemo(() => {
    for (let i = visible.length - 1; i >= 0; i--) {
      const s = visible[i];
      if (s.kind === "tool" && s.record) {
        const pending = i === visible.length - 1 && !st.resolved;
        return pending ? { status: "saving", fields: s.record.fields } : s.record;
      }
    }
    return { status: "empty" };
  }, [visible, st.resolved]);

  const enter = reduce ? { initial: false as const } : { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 } };
  const claim = visible.find((s) => s.kind === "agent" && s.claim) as Extract<Step, { kind: "agent" }> | undefined;

  return (
    <section id="sample" className="sample" ref={section} aria-labelledby="sample-title">
      <div className="wrap sample-grid">
        <header className="sample-intro">
          <p className="kicker">Sample booking</p>
          <h2 id="sample-title" className="h2">Watch a question become a booking.</h2>
          <p className="lede">{sc.summary}</p>
          <p className="honest-label">
            <strong>Sample conversation.</strong> Scripted in your browser: no AI is running and nothing is saved.
            It follows what Atithi really does, step by step.
          </p>
          <div className="scenario-picker" role="group" aria-label="Choose a scenario">
            {SCENARIOS.map((s, i) => (
              <button key={s.id} type="button" className="chip" aria-pressed={st.scenario === i} onClick={() => start(i)}>
                {s.tab}
              </button>
            ))}
          </div>
          <div className="player js-only" role="group" aria-label="Playback">
            <button type="button" className="btn btn-ink" onClick={() => (done ? start(st.scenario) : setSt((s) => ({ ...s, playing: !s.playing })))}>
              {done ? "Replay" : st.playing ? "Pause" : "Play"}
            </button>
            <button type="button" className="btn btn-ghost" onClick={advance} disabled={done || st.playing}>Next step</button>
            {!done && <button type="button" className="btn btn-text" onClick={() => start(st.scenario)}>Restart</button>}
          </div>
        </header>

        <div className="stage" aria-label={`Sample: ${sc.business}`}>
          <div className="stage-head">
            <span className="dot" aria-hidden="true" />
            <span>{sc.business}</span>
            <span className="stage-step" aria-hidden="true">{Math.min(st.shown, sc.steps.length)} / {sc.steps.length}</span>
          </div>
          <div className="stage-body">
            <ol ref={talk} className="talk" aria-live="polite" aria-relevant="additions" tabIndex={0} aria-label="Conversation">
              <AnimatePresence initial={false}>
                {visible.map((s, i) => {
                  const pending = i === visible.length - 1 && !st.resolved;
                  if (s.kind === "tool") {
                    return (
                      <m.li key={`${sc.id}-${i}`} className={`act act-${pending ? "pending" : s.outcome}`} {...enter}>
                        <span className="act-label">{s.label}</span>
                        <span className="act-result">{pending ? s.pending : s.result}</span>
                      </m.li>
                    );
                  }
                  return (
                    <m.li key={`${sc.id}-${i}`} className={`say say-${s.kind}`} {...enter}>
                      <span className="say-who">{s.kind === "customer" ? "Customer" : "Atithi"}</span>
                      <p>{s.text}</p>
                    </m.li>
                  );
                })}
              </AnimatePresence>
            </ol>
            <aside className="stage-side" aria-label="What was saved">
              <m.div layout={!reduce} transition={{ duration: 0.3 }}>
                <BookingRecord state={record} caption="Sample" />
              </m.div>
              {claim && (
                <p className={`promise ${claim.claim === "booked" ? "promise-ok" : "promise-held"}`}>
                  <strong>Promise check:</strong>{" "}
                  {claim.claim === "booked"
                    ? "“booked” matches the saved record."
                    : "the save failed, so Atithi did not say “booked”."}
                </p>
              )}
            </aside>
          </div>
        </div>
      </div>
    </section>
  );
}
