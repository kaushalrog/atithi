import { BookingRecord } from "./BookingRecord";
import { PLAY_EVENT } from "./SampleBooking";
import { CheckMark, Signal } from "./Signal";

export function Hero() {
  return (
    <section className="hero" id="top" aria-labelledby="hero-title">
      <div className="wrap">
        <p className="kicker hero-kicker">AI receptionist for clinics, salons and coaching institutes</p>
        <div className="hero-grid">
          <h1 id="hero-title" className="display">
            A better first hello.<br />
            <span className="display-accent">A booking that lands.</span>
          </h1>
          <div className="hero-copy">
            <p className="lede">
              Atithi answers your customers, checks your live booking calendar and books them in. Then it shows you what it
              said and what it saved.
            </p>
            <div className="cta-row">
              <a href="#sample" className="btn btn-ink" onClick={() => window.dispatchEvent(new Event(PLAY_EVENT))}>
                Play a sample booking
              </a>
              <a href="#product" className="btn btn-ghost">See the owner's view</a>
            </div>
          </div>
        </div>

        {/* The signature: the customer's words travel through the front desk and end in a record. */}
        <figure className="hero-line" aria-label="A customer's question turning into a saved booking (sample)">
          <blockquote className="hero-ask">
            <span className="say-who">Customer</span>
            “Do you have a slot tomorrow at 10:30?”
          </blockquote>
          <div className="hero-signal">
            <Signal draw />
            <span className="hero-tick hero-tick-1">checks the calendar</span>
            <span className="hero-tick hero-tick-2">saves, then confirms</span>
          </div>
          <div className="hero-record">
            <span className="hero-entry" aria-hidden="true"><CheckMark /></span>
            <BookingRecord
              caption="Sample"
              state={{ status: "saved", fields: { name: "Priya Sharma", phone: "98765 43210", service: "Teeth cleaning", when: "Tomorrow · 10:30 AM" } }}
            />
          </div>
        </figure>
      </div>
    </section>
  );
}
