import type { RecordState } from "../data/scenarios";
import { CheckMark } from "./Signal";

// A faithful recreation of the booking row the owner portal stores
// (name, phone, service, date+time, status). Labelled as a sample.
export function BookingRecord({ state, caption = "Sample record" }: { state: RecordState; caption?: string }) {
  if (state.status === "empty") {
    return (
      <div className="record record-empty">
        <div className="record-head"><span className="record-kicker">Booking record</span><span className="record-tag">{caption}</span></div>
        <p className="record-none">No booking yet. A record appears only after the database saves one.</p>
      </div>
    );
  }
  const f = state.fields;
  const saved = state.status === "saved";
  const failed = state.status === "not-saved";
  return (
    <div className={`record record-${state.status}`}>
      <div className="record-head">
        <span className="record-kicker">Booking record</span>
        <span className="record-tag">{caption}</span>
      </div>
      <dl className="record-fields">
        <div><dt>Customer</dt><dd>{f.name}</dd></div>
        <div><dt>Phone</dt><dd>{f.phone}</dd></div>
        <div><dt>Service</dt><dd>{f.service}</dd></div>
        <div><dt>When</dt><dd>{f.when}</dd></div>
      </dl>
      <div className="record-status">
        {state.status === "saving" ? (
          <span className="status-pill status-saving">Saving…</span>
        ) : (
          <>
            <CheckMark status={saved ? "saved" : "not-saved"} />
            <span className={`status-pill ${saved ? "status-ok" : "status-fail"}`}>{saved ? "Confirmed" : "Not saved"}</span>
          </>
        )}
      </div>
      {failed && <p className="record-note">{state.reason} Nothing was confirmed to the customer.</p>}
    </div>
  );
}
