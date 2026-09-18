"""Clock, timezone, diurnal/ramp shapes, deterministic RNG and trace ids."""
import hashlib
import math
import random
from datetime import datetime, date, time, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

DEFAULT_TZ = "America/Los_Angeles"


def get_tz(name):
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def wall(tz, day, h, m=0, s=0, ms=0):
    """Wall-clock local time on `day` (date) as an aware datetime; DST-safe (fold=0)."""
    return datetime.combine(day, time(h, m, s, ms * 1000)).replace(tzinfo=tz, fold=0)


def wall_epoch(tz, day, h, m=0, s=0, ms=0):
    return wall(tz, day, h, m, s, ms).timestamp()


def local_dt(tz, epoch):
    return datetime.fromtimestamp(epoch, tz)


def local_day(tz, epoch):
    return local_dt(tz, epoch).date()


def iso_ms(tz, epoch):
    """ISO-8601 with milliseconds and numeric offset: 2026-09-18T14:49:12.000-0700."""
    dt = local_dt(tz, epoch)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    off = dt.strftime("%z") or "+0000"
    return "%s.%03d%s" % (base, int(round(dt.microsecond / 1000.0)) % 1000, off)


def local_hour(tz, epoch):
    dt = local_dt(tz, epoch)
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


def diurnal(h):
    """d(h) = 0.55 + 0.45*sin(pi*(h-8)/12): peak 1.0 at 14:00, trough 0.10 at 02:00, mean 0.55.

    (The plan writes the phase as h-2, which would peak at 08:00; the stated peak/trough win.)"""
    return 0.55 + 0.45 * math.sin(math.pi * (h - 8.0) / 12.0)


DIURNAL_MEAN = 0.55


def ramp(h):
    """Incident ramp r(h): 0 -> 1 over 12:45-13:05, hold to 14:55, 1 -> 0 by 15:00."""
    if h < 12.75 or h >= 15.0:
        return 0.0
    if h < 13.0 + 5.0 / 60:
        return (h - 12.75) / (20.0 / 60)
    if h < 14.0 + 55.0 / 60:
        return 1.0
    return max(0.0, (15.0 - h) / (5.0 / 60))


def in_window(h):
    return 12.75 <= h < 15.0


def rng_for(seed, *parts):
    key = "|".join(str(p) for p in (seed,) + parts)
    h = hashlib.sha1(key.encode("utf-8")).digest()
    return random.Random(int.from_bytes(h[:8], "big"))


def trace_id(seed, day, key):
    return hashlib.sha1(("%s|%s|%s" % (seed, day, key)).encode("utf-8")).hexdigest()[:12]


def hex_id(rng, n):
    return "%0*x" % (n, rng.getrandbits(4 * n))


def cumulative_alloc(total, weights):
    """Split `total` (int) over buckets proportionally to weights, exact by cumulative rounding."""
    s = float(sum(weights))
    out = []
    prev = 0
    acc = 0.0
    for w in weights:
        acc += w
        cur = int(round(total * acc / s)) if s > 0 else 0
        out.append(cur - prev)
        prev = cur
    return out


def minute_weights_for_day(tz, day):
    """Diurnal weight per local minute of `day` (1440 entries, DST days may be 1380/1500)."""
    start = wall_epoch(tz, day, 0)
    end = wall_epoch(tz, day + timedelta(days=1), 0)
    n = int(round((end - start) / 60.0))
    return start, [diurnal(local_hour(tz, start + 60 * i)) for i in range(n)]


def parse_duration_days(text):
    t = text.strip().lower()
    if t.endswith("d"):
        return int(t[:-1])
    if t.endswith("h"):
        return max(1, int(math.ceil(int(t[:-1]) / 24.0)))
    return int(t)


def parse_now(text, tz):
    if not text:
        return datetime.now(tz).timestamp()
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.timestamp()


def lognormal(rng, median, sigma):
    return median * math.exp(rng.gauss(0.0, sigma))


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def pick_distinct(rng, population, k):
    """k distinct items drawn without replacement (deterministic for a seeded rng)."""
    items = list(population)
    rng.shuffle(items)
    return items[:k]
