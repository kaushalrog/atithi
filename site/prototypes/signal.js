// The Welcome Signal, prototype version (the site's final version lives in src/).
// One continuous stroke: voice wave -> calm line -> doorway (arch) -> booking check.
window.SIGNAL = {
  viewBox: "0 0 720 180",
  // baseline y=120. Wave: 12 half-cycles of rising-then-settling amplitude.
  path:
    "M8 120 H64 " +
    "q6 -10 12 0 q6 12 12 0 q6 -26 12 0 q6 30 12 0 q6 -48 12 0 q6 44 12 0 " +
    "q6 -34 12 0 q6 26 12 0 q6 -16 12 0 q6 10 12 0 q6 -5 12 0 q6 3 12 0 " +
    "H300 " +
    // doorway: up, round arch over the top, down — the threshold of a front desk
    "V66 a38 38 0 0 1 76 0 V120 " +
    "H470 " +
    // resolve: a confident check that lands on the baseline
    "l20 20 l44 -52",
  // the booking mark the check sits in: a rounded tile, drawn last
  mark: "M486 86 h96 a14 14 0 0 1 14 14 v44 a14 14 0 0 1 -14 14 h-96 a14 14 0 0 1 -14 -14 v-44 a14 14 0 0 1 14 -14 z",
};
