// Scripted sample conversations. Every behaviour here mirrors the real product:
// - prices, hours and policies come from the repo's demo businesses
//   (clients/demo_clinic.yaml, clients/lakshmi_beauty_salon.yaml);
// - Atithi confirms the details before booking (evals: no_booking_without_confirmation);
// - it saves the booking BEFORE saying "booked" (agent.py _book_appointment);
// - "just booked by someone else" is the real error the database guard returns.
// Nothing here runs a model or saves anything.

export type RecordState =
  | { status: "empty" }
  | { status: "saving"; fields: BookingFields }
  | { status: "saved"; fields: BookingFields }
  | { status: "not-saved"; fields: BookingFields; reason: string };

/** What a finished save leaves behind: saved, or refused. */
export type FinalRecord = Extract<RecordState, { status: "saved" | "not-saved" }>;

export interface BookingFields {
  name: string;
  phone: string;
  service: string;
  when: string;
}

export type Step =
  | { kind: "customer"; text: string }
  | { kind: "agent"; text: string; claim?: "booked" | "none" }
  | { kind: "tool"; label: string; pending: string; result: string; outcome: "ok" | "taken" | "failed";
      record?: FinalRecord };

export interface Scenario {
  id: string;
  tab: string;
  business: string;
  summary: string;
  steps: Step[];
}

const priya: BookingFields = {
  name: "Priya Sharma", phone: "98765 43210", service: "Teeth cleaning", when: "Tomorrow · 10:30 AM",
};
const meena: BookingFields = {
  name: "Meena R.", phone: "90031 22018", service: "Hair spa", when: "Saturday · 6:30 PM",
};
const arjun: BookingFields = {
  name: "Arjun K.", phone: "99440 51723", service: "Dental consultation", when: "Tomorrow · 11:00 AM",
};

export const SCENARIOS: Scenario[] = [
  {
    id: "free",
    tab: "The slot is free",
    business: "Sri Balaji Dental Care (sample clinic)",
    summary: "The customer asks for a time that is free. Atithi checks, confirms the details, saves, then says “booked”.",
    steps: [
      { kind: "customer", text: "Hi, do you have a slot tomorrow at 10:30 for a teeth cleaning?" },
      { kind: "tool", label: "Check availability · tomorrow", pending: "Checking the calendar…",
        result: "10:30 is free · also 9:30, 10:00, 11:30", outcome: "ok" },
      { kind: "agent", text: "Yes, 10:30 tomorrow is free. Teeth cleaning is ₹1,200. May I have your name and mobile number?" },
      { kind: "customer", text: "Priya Sharma, 98765 43210." },
      { kind: "agent", text: "Just to confirm: teeth cleaning, tomorrow at 10:30 AM, for Priya Sharma on 98765 43210. Shall I book it?" },
      { kind: "customer", text: "Yes, please." },
      { kind: "tool", label: "Save booking", pending: "Saving to the bookings database…",
        result: "Saved · confirmed", outcome: "ok", record: { status: "saved", fields: priya } },
      { kind: "agent", claim: "booked",
        text: "You're booked for tomorrow at 10:30 AM. The ₹100 booking fee is adjusted against your final bill. See you then!" },
    ],
  },
  {
    id: "taken",
    tab: "The slot is taken",
    business: "Lakshmi Beauty Salon (sample salon)",
    summary: "The time the customer wants is gone. Atithi offers what is really free instead of guessing.",
    steps: [
      { kind: "customer", text: "Can I get a hair spa on Saturday at 6 PM?" },
      { kind: "tool", label: "Check availability · Saturday", pending: "Checking the calendar…",
        result: "6:00 PM is taken · free: 6:30 PM, 7:00 PM", outcome: "taken" },
      { kind: "agent", text: "6 PM on Saturday is already booked, but 6:30 and 7:00 PM are free. Hair spa is ₹1,200. Would either work?" },
      { kind: "customer", text: "6:30 is fine. Meena, 90031 22018." },
      { kind: "agent", text: "Hair spa, Saturday at 6:30 PM, for Meena on 90031 22018. Shall I book it?" },
      { kind: "customer", text: "Yes." },
      { kind: "tool", label: "Save booking", pending: "Saving to the bookings database…",
        result: "Saved · confirmed", outcome: "ok", record: { status: "saved", fields: meena } },
      { kind: "agent", claim: "booked", text: "Done. You're booked for Saturday at 6:30 PM. See you at the salon!" },
    ],
  },
  {
    id: "fails",
    tab: "The save fails",
    business: "Sri Balaji Dental Care (sample clinic)",
    summary: "Demonstration of a failure: someone else takes the slot a moment before the save. Atithi does not say “booked”.",
    steps: [
      { kind: "customer", text: "Is 11 tomorrow morning free for a consultation?" },
      { kind: "tool", label: "Check availability · tomorrow", pending: "Checking the calendar…",
        result: "11:00 is free", outcome: "ok" },
      { kind: "agent", text: "Yes, 11:00 tomorrow is free. A consultation is ₹300. Your name and number, please?" },
      { kind: "customer", text: "Arjun, 99440 51723. Go ahead and book it." },
      { kind: "tool", label: "Save booking", pending: "Saving to the bookings database…",
        result: "Refused · 11:00 was just booked by someone else", outcome: "failed",
        record: { status: "not-saved", fields: arjun, reason: "The database allows one confirmed booking per slot." } },
      { kind: "agent", claim: "none",
        text: "I'm sorry, 11:00 was taken a moment ago, so I haven't booked it. 11:30 and 12:00 are free. Would either suit you?" },
    ],
  },
];
