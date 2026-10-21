// The one real contact route: an email to the Atithi team. A mailto link has
// no server to break and sends nothing until the visitor presses send.
export const PILOT_EMAIL = "atithi.support@gmail.com";

const SUBJECT = "Atithi early-access pilot request";
const BODY = [
  "Hello Atithi team,",
  "",
  "I'd like to hear about the early-access pilot.",
  "",
  "Business name:",
  "Type of business (clinic, salon, coaching...):",
  "City:",
  "Who answers the phone today:",
  "Roughly how many calls a day:",
  "A recent time a missed call cost you a booking (if any):",
  "",
  "Best number or time to reach me:",
].join("\n");

export const PILOT_MAILTO =
  `mailto:${PILOT_EMAIL}?subject=${encodeURIComponent(SUBJECT)}&body=${encodeURIComponent(BODY)}`;

/** Retention periods for pilot data. Keep in step with docs/DATA_HANDLING.md
 *  in the main repo, which the server enforces. */
export const RETENTION = [
  ["Conversation transcripts and their action traces", "90 days"],
  ["Leads: name, number and what they asked about", "180 days"],
  ["Bookings", "the customer's name and number are removed 1 year after the appointment"],
  ["Unanswered questions", "180 days after you answer or dismiss them"],
  ["Log of text messages (sent or dry-run)", "30 days"],
  ["Call audio", "not stored by Atithi: calls are turned into text"],
] as const;
