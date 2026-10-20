"""callbacks.py — ring back customers Atithi owes a call.

Who is owed a call (rows in the `callbacks` table, see storage.py):
  * a "missed call": the business turned on missed-call mode, so its number
    rejects calls with a busy tone (free for the caller, the way Indian
    customers already ask to be called back) and Atithi calls them back;
  * a caller who heard "all our lines are busy".

Every rule that keeps this from becoming a nuisance lives here or in storage:
  * OFF unless ENABLE_CALLBACKS=true (and live calls + Twilio are set up);
  * only while the business is open, in its own timezone (never at 11 PM);
  * one callback per number per 6 hours, at most 30 per business per day;
  * a callback older than CALLBACK_MAX_AGE_H is dropped, not made a day late;
  * one attempt: a row is claimed atomically before dialling, so two workers
    can't ring the same person twice;
  * a busy line comes first: callbacks only use free call slots.

Run by the server every CALLBACK_POLL_S while switched on, or by hand:
    python callbacks.py run
"""

import datetime as dt
import sys
import threading

import billing
import notify
import scheduling
import storage
import telephony
from agent import _business_timezone

CALLBACK_MAX_AGE_H = 24
CALLBACK_POLL_S = 60


def run_due(now_utc: dt.datetime | None = None) -> dict:
    """Dial every callback that is due now. Returns counts by outcome."""
    counts = {"called": 0, "failed": 0, "waiting": 0, "dropped": 0}
    if not telephony.callbacks_enabled():
        return {"disabled": True, **counts}
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    for cb in storage.pending_callbacks():
        cfg = storage.read_client_config(cb["client_id"])
        if cfg is None or not billing.client_active(cb["client_id"]):
            storage.mark_callback(cb["id"], "dismissed", "business inactive")
            counts["dropped"] += 1
            continue
        tz, _ = _business_timezone(cfg)
        local = now_utc.astimezone(tz).replace(tzinfo=None)
        created = dt.datetime.fromisoformat(cb["created"])
        if local - created > dt.timedelta(hours=CALLBACK_MAX_AGE_H):
            storage.mark_callback(cb["id"], "dismissed", "too old to call back")
            counts["dropped"] += 1
            continue
        if not scheduling.is_open(cfg, local):
            counts["waiting"] += 1                     # stays pending until opening time
            continue
        if telephony._calls_in_flight() >= telephony.max_concurrent_calls():
            counts["waiting"] += 1                     # customers calling in come first
            break
        to = notify.to_e164(cb["phone"])
        if to is None:
            storage.mark_callback(cb["id"], "dismissed", "not a phone number")
            counts["dropped"] += 1
            continue
        if not storage.claim_callback(cb["id"]):
            continue                                   # another worker took it
        try:
            sid = telephony.start_outbound_call(cb["client_id"], to, purpose="callback")
            storage.mark_callback(cb["id"], "done", f"called ({sid})")
            counts["called"] += 1
        except Exception as e:
            storage.mark_callback(cb["id"], "failed", type(e).__name__)
            print(f"  [callbacks] could not call back #{cb['id']}: {type(e).__name__}: {e}")
            counts["failed"] += 1
    return counts


def start_worker(stop: threading.Event) -> threading.Thread | None:
    """The server's background dialer. Never runs in test mode."""
    if storage.in_test_mode():
        return None

    def loop():
        while not stop.wait(CALLBACK_POLL_S):
            try:
                run_due()
            except Exception as e:      # a bad row must never kill the worker
                print(f"  [callbacks] round failed: {type(e).__name__}: {e}")

    t = threading.Thread(target=loop, name="callbacks", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    if sys.argv[1:] == ["run"]:
        print(run_due())
    else:
        print(__doc__)
