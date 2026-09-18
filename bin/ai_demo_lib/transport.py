"""Output sinks: HEC (byte-batched, gzip, worker threads, retries), NDJSON files, stdout."""
import gzip
import json
import os
import queue
import ssl
import sys
import threading
import time
import urllib.request
import urllib.error

from .catalog import SOURCETYPE_INDEX
from .topology import HOST, SOURCE
from .timeutil import iso_ms

_DUMPS = json.JSONEncoder(separators=(",", ":"), ensure_ascii=False).encode


def event_line(tz, ts, st, ev, extra_fields=None):
    """Plain NDJSON line (stream/--out): the event with an ISO timestamp first."""
    d = {"timestamp": iso_ms(tz, ts)}
    d.update(ev)
    if extra_fields:
        d.update(extra_fields)
    return _DUMPS(d)


def hec_record(tz, ts, st, ev, extra_fields=None):
    """HEC JSON: metrics as multi-metric "event":"metric" with fields, everything else to /event."""
    idx = SOURCETYPE_INDEX[st]
    if st == "ai:gpu:metrics":
        fields = {}
        for k, v in ev.items():
            if k.startswith("DCGM_") or k.startswith("storage_"):
                fields["metric_name:" + k] = v
            else:
                fields[k] = v
        if extra_fields:
            fields.update(extra_fields)
        rec = {"time": round(ts, 3), "host": HOST, "source": SOURCE, "index": idx, "sourcetype": st, "event": "metric", "fields": fields}
        return True, _DUMPS(rec)
    body = {"timestamp": iso_ms(tz, ts)}
    body.update(ev)
    if extra_fields:
        body.update(extra_fields)
    rec = {"time": round(ts, 3), "host": HOST, "source": SOURCE, "index": idx, "sourcetype": st, "event": body}
    return False, _DUMPS(rec)


class Counter(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.counts = {}
        self.bytes = 0
        self.posts = 0
        self.failed = 0

    def add(self, st, n=1):
        with self.lock:
            self.counts[st] = self.counts.get(st, 0) + n


class FileSink(object):
    """One <index>__<sourcetype>.ndjson per sourcetype under out_dir."""

    def __init__(self, tz, out_dir, counter, extra_fields=None):
        self.tz = tz
        self.dir = out_dir
        self.counter = counter
        self.extra = extra_fields
        self.files = {}
        os.makedirs(out_dir, exist_ok=True)

    def write(self, ts, st, ev):
        f = self.files.get(st)
        if f is None:
            name = "%s__%s.ndjson" % (SOURCETYPE_INDEX[st], st.replace(":", "_"))
            f = open(os.path.join(self.dir, name), "a", encoding="utf-8")
            self.files[st] = f
        f.write(event_line(self.tz, ts, st, ev, self.extra))
        f.write("\n")
        self.counter.add(st)

    def close(self):
        for f in self.files.values():
            f.close()


class StdoutSink(object):
    def __init__(self, tz, counter, extra_fields=None):
        self.tz = tz
        self.counter = counter
        self.extra = extra_fields
        self.out = sys.stdout

    def write(self, ts, st, ev):
        self.out.write(event_line(self.tz, ts, st, ev, self.extra))
        self.out.write("\n")
        self.counter.add(st)

    def close(self):
        self.out.flush()


class HecSink(object):
    """Byte-batched HEC sender: producer fills two batches (events -> /services/collector/event,
    metrics -> /services/collector); worker threads POST with gzip (probed once) and retries."""

    def __init__(self, tz, url, token, counter, workers=4, batch_bytes=3000000, insecure=True, extra_fields=None, log=None):
        self.tz = tz
        self.base = url.rstrip("/")
        if self.base.endswith("/services/collector/event"):
            self.base = self.base[:-len("/services/collector/event")]
        elif self.base.endswith("/services/collector"):
            self.base = self.base[:-len("/services/collector")]
        self.token = token
        self.counter = counter
        self.batch_bytes = batch_bytes
        self.extra = extra_fields
        self.log = log or (lambda m: sys.stderr.write(m + "\n"))
        self.ctx = ssl._create_unverified_context() if insecure else None
        self.gzip = None
        self.q = queue.Queue(maxsize=max(2, workers * 2))
        self.bufs = {True: [], False: []}
        self.sizes = {True: 0, False: 0}
        self.pending = {True: {}, False: {}}
        self.errors = []
        self.threads = [threading.Thread(target=self._worker, daemon=True) for _ in range(workers)]
        for t in self.threads:
            t.start()

    def probe(self):
        """10-event probe: gzip first, identity fallback. Raises on hard failure."""
        import random
        rec = _DUMPS({"time": time.time(), "host": HOST, "source": SOURCE, "index": "ai_summary", "sourcetype": "ai:probe",
                      "event": {"probe": True, "n": random.random()}})
        body = ("\n".join([rec] * 10)).encode("utf-8")
        for gz in (True, False):
            code, text = self._post("/services/collector/event", body, gz)
            if code == 200:
                self.gzip = gz
                self.log("HEC probe ok (gzip=%s): %s" % (gz, text.strip()[:80]))
                return gz
            self.log("HEC probe gzip=%s failed: HTTP %s %s" % (gz, code, text.strip()[:120]))
        raise RuntimeError("HEC probe failed for both gzip and identity encodings")

    def _post(self, path, body, gz):
        headers = {"Authorization": "Splunk " + self.token, "Content-Type": "application/json"}
        data = body
        if gz:
            data = gzip.compress(body, 4)
            headers["Content-Encoding"] = "gzip"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120, context=self.ctx) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception as e:  # connection errors
            return 0, str(e)

    def write(self, ts, st, ev):
        is_metric, rec = hec_record(self.tz, ts, st, ev, self.extra)
        buf = self.bufs[is_metric]
        buf.append(rec)
        self.sizes[is_metric] += len(rec) + 1
        p = self.pending[is_metric]
        p[st] = p.get(st, 0) + 1
        if self.sizes[is_metric] >= self.batch_bytes:
            self._flush(is_metric)

    def _flush(self, is_metric):
        if not self.bufs[is_metric]:
            return
        body = "\n".join(self.bufs[is_metric]).encode("utf-8")
        path = "/services/collector" if is_metric else "/services/collector/event"
        self.q.put((path, body, dict(self.pending[is_metric])))
        self.bufs[is_metric] = []
        self.sizes[is_metric] = 0
        self.pending[is_metric] = {}

    def _worker(self):
        while True:
            item = self.q.get()
            if item is None:
                self.q.task_done()
                return
            path, body, counts = item
            gz = self.gzip if self.gzip is not None else False
            ok = False
            for attempt in range(5):
                code, text = self._post(path, body, gz)
                if code == 200:
                    ok = True
                    break
                time.sleep(2 ** attempt)
                if attempt == 3:
                    self.log("HEC POST retry %d: HTTP %s %s" % (attempt + 1, code, text[:120]))
            with self.counter.lock:
                self.counter.posts += 1
                self.counter.bytes += len(body)
                if ok:
                    for st, n in counts.items():
                        self.counter.counts[st] = self.counter.counts.get(st, 0) + n
                else:
                    self.counter.failed += sum(counts.values())
                    self.errors.append("POST %s failed after retries: HTTP %s %s" % (path, code, text[:200]))
            self.q.task_done()

    def close(self):
        self._flush(True)
        self._flush(False)
        self.q.join()
        for _ in self.threads:
            self.q.put(None)
        for t in self.threads:
            t.join()
