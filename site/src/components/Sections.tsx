import { useEffect, useRef, useState } from "react";
import { PILOT_EMAIL, PILOT_MAILTO } from "../data/pilot";
import { PLAY_EVENT } from "./SampleBooking";
import { CheckMark, Signal } from "./Signal";
import { Mark } from "./Nav";

const img = (p: string) => `${import.meta.env.BASE_URL}${p}`;

/** Draw an element's signal when it scrolls into view (once). Without JS, or
 *  with reduced motion, the drawing is simply already there. */
function useDrawOnView<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [state, setState] = useState<"static" | "waiting" | "in">("static");
  useEffect(() => {
    const el = ref.current;
    if (!el || !("IntersectionObserver" in window)) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const r = el.getBoundingClientRect();
    if (r.top < window.innerHeight * 0.9) return;          // already on screen: leave it drawn
    setState("waiting");
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { setState("in"); io.disconnect(); }
    }, { rootMargin: "0px 0px -20% 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return [ref, state] as const;
}

export function Capabilities() {
  const points = [
    ["Understands the request", "“Tomorrow at 10:30 for a cleaning” becomes a date, a time and a service. If a detail is missing or a phone number is short, it asks again instead of guessing."],
    ["Uses your live booking calendar", "It offers times from a live look-up of the bookings Atithi holds for you, and checks again as it saves, so a past time, a holiday or a taken slot can't be booked. Bookings land on your dashboard and export as CSV."],
    ["Finishes the job with tools", "It books, cancels, moves bookings and saves leads through the same system you see. The database refuses a second booking for the same time."],
    ["Leaves a trail you can read", "Every conversation is saved with its transcript, each action it took, and whether its “you're booked” matched a saved record."],
  ];
  return (
    <section className="caps" aria-labelledby="caps-title">
      <div className="wrap caps-grid">
        <div className="caps-lead">
          <p className="kicker">What makes it useful</p>
          <h2 id="caps-title" className="h2 serif">It doesn't just talk. It gets the booking right, and shows its work.</h2>
          <ol className="caps-list">
            {points.map(([t, d], i) => (
              <li key={t}>
                <span className="caps-num" aria-hidden="true">0{i + 1}</span>
                <div><h3>{t}</h3><p>{d}</p></div>
              </li>
            ))}
          </ol>
        </div>
        <figure className="shot shot-chat">
          <img src={img("product/chat.webp")} width={520} height={640} loading="lazy" decoding="async"
            alt="Atithi's test chat in the owner portal: it checks availability for 21 October, books Priya Sharma's teeth cleaning at 10:30, and when asked about UPI says the front desk will call back." />
          <figcaption>The owner portal's test chat, on sample data. Note the actions between messages, and the UPI question it didn't guess at.</figcaption>
        </figure>
      </div>
    </section>
  );
}

export function Product() {
  return (
    <section id="product" className="product" aria-labelledby="product-title">
      <div className="wrap">
        <div className="section-head">
          <p className="kicker">The owner's view</p>
          <h2 id="product-title" className="h2">Everything it said and did, in one place.</h2>
          <p className="lede">Screens from the Atithi owner portal, captured on sample data.</p>
        </div>
        <figure className="shot shot-wide">
          <div className="shot-frame" tabIndex={0} role="region" aria-label="Dashboard screenshot (scrolls sideways on small screens)">
          <img src={img("product/dashboard.webp")} width={1010} height={584} loading="lazy" decoding="async"
            alt="Owner dashboard: '2 of 2 promises backed by a real record', a seven-day activity chart, a recent call marked booked and verified, and Priya Sharma's teeth cleaning in recent bookings." />
          </div>
          <figcaption><strong>Dashboard.</strong> The promise check counts each “you're booked” it recognises and whether a saved record backs it. Each conversation is marked <em>booked</em> and <em>verified</em>.</figcaption>
        </figure>
        <div className="shot-pair">
          <figure className="shot">
            <div className="shot-frame" tabIndex={0} role="region" aria-label="Questions inbox screenshot (scrolls sideways on small screens)">
            <img src={img("product/questions.webp")} width={1280} height={360} loading="lazy" decoding="async"
              alt="Questions inbox: 'Can I pay by UPI?', asked once, with the owner typing the answer 'Yes, we accept UPI, cards and cash' and an Add to FAQ button." />
            </div>
            <figcaption><strong>Questions inbox.</strong> What Atithi couldn't answer waits here. Answer once and it becomes part of what it knows.</figcaption>
          </figure>
          <figure className="shot">
            <div className="shot-frame" tabIndex={0} role="region" aria-label="Bookings screenshot (scrolls sideways on small screens)">
            <img src={img("product/bookings.webp")} width={1280} height={260} loading="lazy" decoding="async"
              alt="Bookings list: Priya Sharma, 9876543210, Scaling and polishing (teeth cleaning), 2026-10-21 10:30, confirmed, with a Cancel button." />
            </div>
            <figcaption><strong>Bookings.</strong> Every confirmed slot, with one-click cancel. The slot opens up again straight away.</figcaption>
          </figure>
        </div>
        <div className="walkthrough" id="walkthrough">
          <div>
            <h3 className="h3">The 3½-minute walkthrough</h3>
            <p>A narrated tour of the real portal, recorded on sample data with the live model: a booking, the promise check, the questions inbox, Telugu, a cancellation and the settings.</p>
            <p className="small">The video loads only when you press play (3.8 MB).</p>
          </div>
          <video controls preload="none" playsInline width={1280} height={800}
            poster={img("media/walkthrough-poster.webp")}
            aria-label="Narrated walkthrough of the Atithi owner portal">
            <source src={img("media/atithi-walkthrough.mp4")} type="video/mp4" />
            <a href={img("media/atithi-walkthrough.mp4")}>Download the walkthrough (MP4, 3.8 MB)</a>
          </video>
        </div>
      </div>
    </section>
  );
}

export function UseCases() {
  const cases = [
    {
      who: "Clinic",
      ask: "My son has a toothache. Can he be seen this evening?",
      does: ["Checks this evening's free times", "Books a kids' check-up (₹250 in the sample clinic)", "Confirms only after the booking is saved"],
      owner: "The booking, the transcript and the parent's number.",
    },
    {
      who: "Salon",
      ask: "How much is a hair spa? Are you open on Monday?",
      does: ["Answers ₹1,200 from your own price list", "Says Monday is closed, because your hours say so", "Offers Tuesday's free slots instead"],
      owner: "The conversation, and a booking if they took one.",
    },
    {
      who: "Coaching institute",
      ask: "What are the weekend batch fees? I'll decide after talking to my parents.",
      does: ["Quotes fees only if you've entered them", "Saves a lead with what they wanted and their number", "Leaves the callback to you, with the details"],
      owner: "A lead to follow up, with notes and a callback date.",
    },
  ];
  return (
    <section id="businesses" className="cases" aria-labelledby="cases-title">
      <div className="wrap">
        <div className="section-head">
          <p className="kicker">Real situations</p>
          <h2 id="cases-title" className="h2">The questions your front desk hears every day.</h2>
          <p className="lede">Illustrative situations built on our sample clinic and salon, not customer stories.</p>
        </div>
        <ul className="case-list">
          {cases.map((c) => (
            <li key={c.who} className="case">
              <h3 className="case-who">{c.who}</h3>
              <blockquote className="case-ask">“{c.ask}”</blockquote>
              <div className="case-does">
                <p className="case-label">What Atithi does</p>
                <ul>{c.does.map((d) => <li key={d}>{d}</li>)}</ul>
              </div>
              <p className="case-owner"><span className="case-label">You see</span> {c.owner}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export function HowItWorks() {
  const [ref, state] = useDrawOnView<HTMLOListElement>();
  const steps = [
    { part: "wave" as const, t: "Listen", d: "The customer asks in their own words, in English or Telugu. Atithi answers only from your business details: services, prices, hours, FAQs and policies." },
    { part: "door" as const, t: "Check", d: "Anything that changes by the minute, like free slots, is looked up live, and every booking is checked again as it's saved." },
    { part: "confirm" as const, t: "Confirm", d: "It reads the details back, saves the booking, and only then says “booked”. If the save fails, it says so and offers another time." },
  ];
  return (
    <section id="how" className="how" aria-labelledby="how-title">
      <div className="wrap">
        <div className="section-head">
          <p className="kicker">How it works</p>
          <h2 id="how-title" className="h2">Listen. Check. Confirm.</h2>
        </div>
        <ol ref={ref} className={`how-steps draw-${state}`}>
          {steps.map((s, i) => (
            <li key={s.t} className="how-step" style={{ ["--i" as string]: i }}>
              <Signal parts={[s.part]} className={`how-signal how-${s.part}`} />
              <h3><span aria-hidden="true">0{i + 1}</span> {s.t}</h3>
              <p>{s.d}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

export function Trust() {
  const status: Array<[string, "live" | "testing" | "off", string]> = [
    ["Test chat in the owner portal", "live", "Working today, on sample data."],
    ["English and Telugu", "live", "Passes our scripted checks (11 conversations, one in Telugu). Hindi and Tamil can be switched on but aren't checked yet."],
    ["Website chat on your site", "testing", "Built and off by default. Not yet used by a real business."],
    ["Phone calls", "testing", "Built. Never run on a real phone line yet."],
    ["WhatsApp replies", "testing", "Built. Never run through WhatsApp itself yet."],
    ["SMS confirmations and reminders", "off", "Built, switched off until verified. Indian delivery needs DLT registration."],
  ];
  const label = { live: "Available", testing: "Not live yet", off: "Switched off" };
  return (
    <section id="trust" className="trust" aria-labelledby="trust-title">
      <div className="wrap trust-grid">
        <div>
          <p className="kicker">Trust and boundaries</p>
          <h2 id="trust-title" className="h2">You can read every conversation it had.</h2>
          <ul className="check-list">
            <li><CheckMark /> Full transcripts, with each action between the messages.</li>
            <li><CheckMark /> In English text chats, each “booked”, “cancelled” or “moved” is checked against a saved record before it's sent. It catches common wordings, not every one.</li>
            <li><CheckMark /> Bookings and leads you can export as CSV, and an inbox of questions it couldn't answer.</li>
            <li><CheckMark /> Each business sees only its own data.</li>
          </ul>
          <h3 className="h3 trust-sub">What it's built not to do</h3>
          <p className="trust-wont">Invent prices, discounts or offers. Give medical, legal or financial advice. Answer “yes” to something your details don't say. These are rules it's tested against, not guarantees, which is why every conversation is saved for you to read.</p>
        </div>
        <div>
          <h3 className="h3">Where Atithi is today</h3>
          <table className="status">
            <caption className="sr-only">Status of each channel</caption>
            <tbody>
              {status.map(([what, s, note]) => (
                <tr key={what}>
                  <th scope="row">{what}</th>
                  <td><span className={`status-pill status-${s}`}>{label[s]}</span><span className="status-note">{note}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          <figure className="shot shot-telugu">
            <img src={img("product/telugu.webp")} width={520} height={330} loading="lazy" decoding="async"
              alt="Test chat: a customer asks in Telugu for the timings and the price of a cleaning; Atithi replies in Telugu with the clinic's hours and the ₹1,200 price for scaling and polishing." />
            <figcaption>Asked in Telugu, answered in Telugu with the clinic's real hours and price.</figcaption>
          </figure>
        </div>
      </div>
    </section>
  );
}

export function Closing() {
  return (
    <section className="closing" aria-labelledby="closing-title">
      <div className="wrap closing-inner">
        <Signal className="closing-signal" />
        <h2 id="closing-title" className="display closing-title">Every caller, welcomed.</h2>
        <p className="lede">Named after <em>Atithi Devo Bhava</em>: the guest is God. That's how a good front desk treats every caller.</p>
        <div className="cta-row">
          <a href={PILOT_MAILTO} className="btn btn-ink">Request an early-access pilot</a>
          <a href="#sample" className="btn btn-ghost" onClick={() => window.dispatchEvent(new Event(PLAY_EVENT))}>Play the sample booking</a>
        </div>
      </div>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="footer">
      <div className="wrap footer-inner">
        <a href="#top" className="brand"><Mark size={22} /> <span>Atithi</span></a>
        <p>An AI receptionist in development. Sample data only on this page.</p>
        <p>This site sets no cookies and loads nothing from third parties. <a href="#privacy">Privacy notice</a></p>
        <p><a href={`mailto:${PILOT_EMAIL}`}>{PILOT_EMAIL}</a></p>
      </div>
    </footer>
  );
}
