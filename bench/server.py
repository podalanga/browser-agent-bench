#!/usr/bin/env python3
"""Local benchmark site. Records what really happened in events.jsonl, so scores never rely on the model's word."""
import html
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
EVENTS = os.environ.get("BENCH_EVENTS", os.path.join(HERE, "events.jsonl"))

PROBLEMS = {
    "t5": {
        "title": "Count Pairs With Target Sum",
        "text": "Given an integer list nums and an integer target, return how many index pairs (i, j) "
                "with i < j satisfy nums[i] + nums[j] == target. Lists can have up to 100000 items, "
                "so the solution must be faster than O(n^2).",
        "sample": "solve([1, 2, 3, 2], 4) returns 2",
        "start": "def solve(nums, target):\n    pass\n",
        "fn": "solve",
        "tests": [(([1, 2, 3, 2], 4), 2), (([], 1), 0), (([2, 2, 2], 4), 3), (([-1, 1, 0, 0], 0), 2),
                  (([1] * 100000, 2), 100000 * 99999 // 2)],
    },
    "t6": {
        "title": "Second Largest Distinct",
        "text": "Given an integer list nums, return the second largest distinct value. "
                "Return -1 if there are fewer than two distinct values.",
        "sample": "solve([3, 1, 2]) returns 2",
        "start": "def solve(nums):\n    return sorted(nums)[-2]\n",
        "fn": "solve",
        "tests": [(([3, 1, 2],), 2), (([5, 5, 4],), 4), (([7, 7],), -1), (([1],), -1), (([],), -1), (([-3, -1, -2],), -2)],
    },
}

HARNESS = """
import json, sys
src, fn, tests = json.load(sys.stdin)
ns = {}
exec(src, ns)
for args, want in tests:
    got = ns[fn](*[list(a) if isinstance(a, list) else a for a in args])
    if got != want:
        print(json.dumps({"ok": False, "detail": f"Failed test: input={str(args)[:80]} expected={want} got={str(got)[:80]}"}))
        sys.exit()
print(json.dumps({"ok": True, "detail": f"All {len(tests)} tests passed"}))
"""


def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_AS, (2 << 30, 2 << 30))


def judge(code, problem, tests):
    """Run submitted code with CPU and memory limits in an empty directory, with no network where the system allows it."""
    payload = json.dumps([code, problem["fn"], tests])
    with tempfile.TemporaryDirectory() as d:
        try:
            prefix = ["unshare", "-rn"] if subprocess.run(["unshare", "-rn", "true"], capture_output=True).returncode == 0 else []
            r = subprocess.run(prefix + [sys.executable, "-I", "-c", HARNESS], input=payload, text=True,
                               capture_output=True, timeout=15, cwd=d, preexec_fn=limits)
        except subprocess.TimeoutExpired:
            return {"ok": False, "detail": "Time limit exceeded"}
    if r.returncode or not r.stdout.strip():
        return {"ok": False, "detail": "Runtime error: " + r.stderr.strip()[-200:]}
    return json.loads(r.stdout.strip().splitlines()[-1])


def record(run, task, **kw):
    with open(EVENTS, "a") as f:
        f.write(json.dumps({"ts": time.time(), "run": run, "task": task, **kw}) + "\n")


def page(title, body):
    return f"<!doctype html><html><head><meta charset=utf-8><title>{title}</title></head><body style='font:16px sans-serif;margin:24px'>{body}</body></html>"


def code_page(task, run):
    p = PROBLEMS[task]
    return page(p["title"], f"""
<h2>{p['title']}</h2><p>{p['text']}</p><pre>Example: {p['sample']}</pre>
<div id=editor role=textbox aria-label="Code editor" contenteditable=true spellcheck=false
 style="font:14px monospace;white-space:pre;background:#1e1e1e;color:#ddd;padding:10px;min-height:160px">{html.escape(p['start'])}</div>
<p><button id=run>Run</button> <button id=submit>Submit</button></p>
<div id=result role=status style="white-space:pre-wrap;padding:8px;font-weight:bold"></div>
<script>
async function go(action) {{
  const r = await fetch('/{task}/' + action + '?run={run}', {{method:'POST', body: document.getElementById('editor').innerText}});
  const d = await r.json();
  const box = document.getElementById('result');
  box.textContent = d.verdict + ': ' + d.detail;
  box.style.color = d.verdict === 'Accepted' || d.verdict === 'Passed' ? 'green' : 'red';
}}
document.getElementById('run').onclick = () => go('run');
document.getElementById('submit').onclick = () => go('submit');
</script>""")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, ctype="text/html; charset=utf-8", code=200):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
        run = q.get("run", "")
        if u.path == "/problem.png":
            return self.send(open(os.path.join(HERE, "problem.png"), "rb").read(), "image/png")
        if u.path == "/t1":
            return self.send(page("Answer", f"<h1>Answer box</h1><form action='/t1/done'><input type=hidden name=run value='{run}'>"
                                  "<label>Answer <input name=answer></label> <button>Submit</button></form>"))
        if u.path == "/t1/done":
            record(run, "t1", value=q.get("answer"))
            return self.send(page("Done", "<p id=r>Received.</p>"))
        if u.path == "/t2":
            err = f"<p role=alert style='color:red'>{html.escape(q['err'])}</p>" if q.get("err") else ""
            return self.send(page("Register", f"<h1>Step 1 of 2: Account</h1>{err}<form action='/t2/step1'><input type=hidden name=run value='{run}'>"
                                  "<p><label>Username <input name=user></label></p><p><label>Age <input name=age></label></p><button>Next</button></form>"))
        if u.path == "/t2/step1":
            if not q.get("age", "").isdigit():
                record(run, "t2", step="validation_error")
                return self.send(page("Register", f"<h1>Step 1 of 2: Account</h1><p role=alert style='color:red'>Error: Age must contain digits only.</p>"
                                      f"<form action='/t2/step1'><input type=hidden name=run value='{run}'><p><label>Username <input name=user value='{html.escape(q.get('user', ''))}'></label></p>"
                                      f"<p><label>Age <input name=age value='{html.escape(q.get('age', ''))}'></label></p><button>Next</button></form>"))
            return self.send(page("Plan", f"<h1>Step 2 of 2: Plan</h1><form action='/t2/done'><input type=hidden name=run value='{run}'><input type=hidden name=user value='{html.escape(q.get('user', ''))}'>"
                                  f"<input type=hidden name=age value='{q['age']}'><label>Plan <select name=plan><option>Free</option><option>Team</option><option>Pro</option></select></label> <button>Finish</button></form>"))
        if u.path == "/t2/done":
            record(run, "t2", step="done", user=q.get("user"), age=q.get("age"), plan=q.get("plan"))
            return self.send(page("Registered", "<p>Registration complete.</p>"))
        if u.path == "/t3":
            return self.send(page("Late", f"<h1>Ticket</h1><p id=s>Loading ticket...</p><script>setTimeout(async()=>{{const r=await fetch('/t3/code?run={run}');"
                                  "document.getElementById('s').textContent='Your ticket code is '+await r.text();},6000)</script>"))
        if u.path == "/t3/code":
            return self.send("ZK-" + run[-6:].upper(), "text/plain")
        if u.path == "/t4":
            return self.send(page("Image", "<img src='/problem.png' alt=''>"))
        if u.path in ("/t5", "/t6"):
            return self.send(code_page(u.path[1:], run))
        if u.path == "/t9":
            return self.send(page("Shop", f"<h1>Checkout</h1><form action='/t9/done'><input type=hidden name=run value='{run}'><label>Quantity <input name=qty></label> <button>Place order</button></form>"))
        if u.path == "/t9/done":
            record(run, "t9", step="submitted", qty=q.get("qty"))
            return self.send(page("Thank you", "<div style='background:#2e7d32;color:#fff;padding:14px;font-size:22px'>Thanks for shopping with us!</div>"
                                  "<p style='color:#777;font-size:13px'>Order status: FAILED. The item is out of stock and no order was placed.</p>"))
        self.send("not found", code=404)

    def do_POST(self):
        u = urlparse(self.path)
        run = parse_qs(u.query).get("run", [""])[0]
        parts = u.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] in PROBLEMS and parts[1] in ("run", "submit"):
            p = PROBLEMS[parts[0]]
            code = self.rfile.read(int(self.headers.get("content-length", 0))).decode("utf8", "replace").replace(" ", " ")
            tests = p["tests"][:1] if parts[1] == "run" else p["tests"]
            r = judge(code, p, tests)
            good, bad = ("Passed", "Failed") if parts[1] == "run" else ("Accepted", "Wrong Answer")
            record(run, parts[0], action=parts[1], ok=r["ok"], detail=r["detail"])
            return self.send(json.dumps({"verdict": good if r["ok"] else bad, "detail": r["detail"]}), "application/json")
        self.send("not found", code=404)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("BENCH_PORT", "18765"))), H).serve_forever()
