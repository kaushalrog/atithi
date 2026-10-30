import { PILOT_EMAIL, PILOT_MAILTO, RETENTION } from "../data/pilot";

/** The real call to action: request an early-access pilot by email,
 *  with exactly what happens next. */
export function Pilot() {
  const steps = [
    ["You email us", "The button opens your email app with a short form to fill in: your business, who answers the phone today, and a recent missed call if you remember one. Nothing is sent until you press send."],
    ["We reply by email", "We set up a short call about how your front desk handles calls now. We'll ask for a real example before suggesting anything."],
    ["A free two-week pilot, if it fits", "We set Atithi up with your services, prices and hours. You use it through the test chat. Chat on your own website comes later, once we've checked it with you. Phone calls aren't part of the pilot until they've been tested on a real line."],
    ["No payment, no contract", "Stop whenever you like. Ask us to delete your pilot data and we will."],
  ];
  return (
    <section id="pilot" className="pilot" aria-labelledby="pilot-title">
      <div className="wrap pilot-grid">
        <div>
          <p className="kicker">Early access</p>
          <h2 id="pilot-title" className="h2">Try Atithi with your own business.</h2>
          <p className="lede">We're running a small number of free pilots with clinics and other appointment-based businesses.</p>
          <div className="cta-row">
            <a href={PILOT_MAILTO} className="btn btn-ink">Request a pilot by email</a>
          </div>
          <p className="small pilot-mail">
            Or write to <a href={`mailto:${PILOT_EMAIL}`}>{PILOT_EMAIL}</a>. See the <a href="#privacy">privacy notice</a>.
          </p>
        </div>
        <ol className="pilot-steps">
          {steps.map(([t, d], i) => (
            <li key={t}>
              <span className="caps-num" aria-hidden="true">0{i + 1}</span>
              <div><h3>{t}</h3><p>{d}</p></div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

export function Privacy() {
  return (
    <section id="privacy" className="privacy" aria-labelledby="privacy-title">
      <div className="wrap privacy-grid">
        <div>
          <p className="kicker">Privacy notice</p>
          <h2 id="privacy-title" className="h3 privacy-title">What we collect, and for how long</h2>
          <p className="small">Last updated 21 October 2026.</p>
        </div>
        <div className="privacy-body">
          <h3>This website</h3>
          <p>No cookies, no analytics, no forms, and nothing loaded from other companies. The sample booking runs entirely in your browser.</p>
          <h3>If you email us</h3>
          <p>Your email goes to <strong>{PILOT_EMAIL}</strong>, a Gmail inbox run by the Atithi team (so Google stores it). We use it only to reply about the pilot. We don't add you to a mailing list or share your details. To have your emails deleted, ask at the same address.</p>
          <h3>During a pilot</h3>
          <p>At the start of every conversation, Atithi tells your customers it is an AI receptionist and that the conversation is saved as text so your team can follow up. It keeps what it needs to run your bookings, for these periods, and deletes the rest automatically:</p>
          <table className="status retention">
            <caption className="sr-only">How long pilot data is kept</caption>
            <tbody>
              {RETENTION.map(([what, how]) => (
                <tr key={what}><th scope="row">{what}</th><td>{how}</td></tr>
              ))}
            </tbody>
          </table>
          <p>To generate replies, conversation text (and, on phone calls, audio) is processed by Google's Gemini service. Phone calls and WhatsApp messages are carried by Twilio. The optional spoken replies in the owner's test chat use Microsoft's text-to-speech service. Everything else stays on the server that runs your Atithi. You or your customers can ask us to delete a person's records, and we will.</p>
        </div>
      </div>
    </section>
  );
}
