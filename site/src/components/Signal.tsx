// The Welcome Signal: one stroke that starts as a voice (wave), passes through
// the front-desk doorway (arch), and settles into a straight line that ends in
// the booking record. Paths are hand-written; pathLength="1" lets CSS draw any
// of them with the same dash animation.

// Baseline y=64 in a 640 x 96 box. The wave's 12 half-cycles rise and settle
// like a spoken sentence; the arch is the threshold of the business.
export const WAVE =
  "M2 64 H40 q6 -8 12 0 q6 10 12 0 q6 -22 12 0 q6 26 12 0 q6 -40 12 0 q6 36 12 0 " +
  "q6 -28 12 0 q6 20 12 0 q6 -12 12 0 q6 8 12 0 q6 -4 12 0 q6 2 12 0";
export const DOOR = "M184 64 H300 V36 a28 28 0 0 1 56 0 V64";
export const SETTLE = "M356 64 H638";
// How it works, step 3: the settled line resolves into the booking check.
export const CONFIRM = "M356 64 H540 l16 16 l36 -44";
export const CHECK = "M7 15.5 l5.5 5.5 L22.5 9";

type Props = {
  className?: string;
  /** Draw on entry. The drawing is decorative; the content never waits for it. */
  draw?: boolean;
  /** Which parts to show (How it works shows them one at a time). */
  parts?: Array<"wave" | "door" | "settle" | "confirm">;
  label?: string;
};

export function Signal({ className = "", draw = false, parts = ["wave", "door", "settle"], label }: Props) {
  const d = { wave: WAVE, door: DOOR, settle: SETTLE, confirm: CONFIRM };
  // A single part is cropped to its own stretch of the line.
  const view = parts.length === 1 ? { wave: "0 0 192 96", door: "176 0 188 96", settle: "350 0 292 96", confirm: "350 0 250 96" }[parts[0]]
    // The full line is framed with its baseline (y=64) at the vertical centre,
    // so a neighbour aligned to the middle meets the line exactly.
    : "0 4 640 120";
  return (
    <svg
      className={`signal ${draw ? "signal-draw" : ""} ${className}`}
      viewBox={view}
      fill="none"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
      preserveAspectRatio="xMinYMid meet"
    >
      {parts.map((p, i) => (
        <path key={p} d={d[p]} pathLength={1} style={{ ["--i" as string]: i }} />
      ))}
    </svg>
  );
}

/** The check that ends the signal, drawn inside the booking record. */
export function CheckMark({ className = "", status = "saved" }: { className?: string; status?: "saved" | "not-saved" }) {
  return (
    <svg className={`check ${className}`} viewBox="0 0 30 30" aria-hidden="true" focusable="false">
      <circle cx="15" cy="15" r="13.5" pathLength={1} />
      {status === "saved" ? <path d={CHECK} pathLength={1} /> : <path d="M10 10 L20 20 M20 10 L10 20" pathLength={1} />}
    </svg>
  );
}
