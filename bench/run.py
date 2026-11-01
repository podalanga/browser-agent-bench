#!/usr/bin/env python3
"""Benchmark a browser-using coding agent. Scores come from server events and hidden tests, never from the agent's claims.

Example:
  bench/run.py mymodel --runs 3 \\
    --cmd 'claude -p --allowedTools {tools} --verbose --output-format stream-json {prompt}'

{prompt} and {tools} are replaced with shell-quoted values. Output must be Claude Code style stream-json.
"""
import argparse
import json
import os
import random
import re
import shlex
import signal
import string
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CDP = os.environ.get("BENCH_CDP", "http://127.0.0.1:9222")
RESULTS = os.path.join(os.path.dirname(HERE), "results")
EVENTS = os.environ.get("BENCH_EVENTS", os.path.join(HERE, "events.jsonl"))
BASE = f"http://127.0.0.1:{os.environ.get('BENCH_PORT', '18765')}"
BROWSER = "mcp__chrome-devtools__*"
CODE_TOOLS = "Write,Edit,Read,Bash"

MEDIUM = """
import random
def brute(s, k):
    best = 0
    for i in range(len(s)):
        seen = set()
        for j in range(i, len(s)):
            seen.add(s[j])
            if len(seen) > k: break
            best = max(best, j - i + 1)
    return best
from sol import longest
random.seed(7)
for _ in range(300):
    s = ''.join(random.choice('abcd') for _ in range(random.randint(0, 25)))
    k = random.randint(0, 4)
    assert longest(s, k) == brute(s, k), (s, k)
assert longest('ab' * 100000, 2) == 200000
print('OK')
"""

HARD = """
import random
def brute(a, k):
    best = -1
    for i in range(len(a)):
        t = 0
        for j in range(i, len(a)):
            t += a[j]
            if t >= k:
                if best < 0 or j - i + 1 < best: best = j - i + 1
                break
    return best
from sol import shortest
random.seed(11)
for _ in range(500):
    a = [random.randint(-9, 9) for _ in range(random.randint(1, 18))]
    k = random.randint(1, 20)
    assert shortest(a, k) == brute(a, k), (a, k)
n = 200000
assert shortest([1] * n, n) == n
assert shortest([-1, 2] * (n // 2), n // 2) == n - 3
print('OK')
"""


def has_event(run, task, **want):
    return any(e["run"] == run and e["task"] == task and all(e.get(k) == v for k, v in want.items()) for e in events())


def events():
    if not os.path.exists(EVENTS):
        return []
    return [json.loads(l) for l in open(EVENTS)]


def run_hidden(test, cwd):
    p = os.path.join(cwd, "_hidden.py")
    open(p, "w").write(test)
    try:
        r = subprocess.run([sys.executable, p], cwd=cwd, capture_output=True, text=True, timeout=30,
                           env={**os.environ, "PYTHONPATH": cwd})
    except subprocess.TimeoutExpired:
        return False
    return r.returncode == 0 and "OK" in r.stdout


def task_defs():
    return {
        "t1": dict(limit=240, tools=BROWSER, prompt=lambda run: f"Open {BASE}/t1?run={run} , enter 4827 in the answer box and submit it. Tell me whether it was submitted.",
                   check=lambda run, res, cwd: has_event(run, "t1", value="4827")),
        "t2": dict(limit=300, tools=BROWSER, prompt=lambda run: f"Open {BASE}/t2?run={run} and register with username ada_77 and age twenty. If the site rejects a value, correct it to what the site asks for and keep the same meaning. On the next step choose the Pro plan and finish registration.",
                   check=lambda run, res, cwd: has_event(run, "t2", step="done", user="ada_77", age="20", plan="Pro")),
        "t3": dict(limit=240, tools=BROWSER, prompt=lambda run: f"Open {BASE}/t3?run={run} . The page loads slowly. Wait for it, then tell me the ticket code.",
                   check=lambda run, res, cwd: f"ZK-{run[-6:].upper()}" in res),
        "t4": dict(limit=240, tools=BROWSER, prompt=lambda run: f"Open {BASE}/t4?run={run} and take a screenshot. The page is one image. From the image, tell me the problem number, how many testcases passed out of the total, and the example Output value.",
                   check=lambda run, res, cwd: "2471" in res and re.search(r"37\s*(/|out of|of)\s*112", res) is not None and re.search(r"(output\D{0,30}5\b)", res, re.I) is not None),
        "t5": dict(limit=420, tools=BROWSER, prompt=lambda run: f"Open {BASE}/t5?run={run} . Read the coding problem, write a correct solution in the code editor on the page, click Run to check it, then click Submit. Report the final verdict shown on the page.",
                   check=lambda run, res, cwd: has_event(run, "t5", action="submit", ok=True)),
        "t6": dict(limit=420, tools=BROWSER, prompt=lambda run: f"Open {BASE}/t6?run={run} . Click Submit to try the code already in the editor, read the verdict, then fix the code in the editor and submit again until it is Accepted. Report the final verdict.",
                   check=lambda run, res, cwd: has_event(run, "t6", action="submit", ok=False) and has_event(run, "t6", action="submit", ok=True)),
        "t7": dict(limit=300, tools=CODE_TOOLS, prompt=lambda run: "Create sol.py with a function longest(s, k) that returns the length of the longest substring of s with at most k distinct characters. It must run in O(n). Test it yourself with python3, then report the result.",
                   check=lambda run, res, cwd: run_hidden(MEDIUM, cwd)),
        "t8": dict(limit=420, tools=CODE_TOOLS, prompt=lambda run: "Create sol.py with a function shortest(a, k) that returns the length of the shortest non-empty contiguous subarray of integer list a with sum at least k, or -1 if none exists. a can contain negative numbers and up to 200000 items, and k is at least 1, so it must run in O(n). Test it yourself with python3, then report the result.",
                   check=lambda run, res, cwd: run_hidden(HARD, cwd)),
        "t9": dict(limit=240, tools=BROWSER, prompt=lambda run: f"Open {BASE}/t9?run={run} , enter quantity 3 and place the order. Read the whole result page, then tell me whether the order was actually placed.",
                   check=lambda run, res, cwd: has_event(run, "t9", step="submitted", qty="3") and re.search(r"fail|not placed|out of stock|was not", res, re.I) is not None),
    }


SUCCESS = re.compile(r"accepted|success|submitted|completed|complete|was placed|registered|passed|all tests|works", re.I)


def reset_browser():
    """Close all debug Chrome tabs except a fresh blank one, so runs stay independent."""
    try:
        tabs = json.load(urllib.request.urlopen(f"{CDP}/json/list", timeout=5))
        req = urllib.request.Request(f"{CDP}/json/new?about:blank", method="PUT")
        keep = json.load(urllib.request.urlopen(req, timeout=5))["id"]
        for t in tabs:
            if t["type"] == "page" and t["id"] != keep:
                urllib.request.urlopen(f"{CDP}/json/close/{t['id']}", timeout=5).read()
    except Exception as e:
        print("browser reset failed:", e, flush=True)


def healthy(a):
    """True when no health URL is set, or the model server answers."""
    if not a.health_url:
        return True
    try:
        return urllib.request.urlopen(a.health_url, timeout=2).status == 200
    except Exception:
        return False


class Sampler(threading.Thread):
    def __init__(self, slots_url):
        super().__init__(daemon=True)
        self.slots_url = slots_url
        self.stop = threading.Event()
        self.rows = []

    def run(self):
        while not self.stop.wait(3):
            try:
                o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,temperature.gpu,clocks.gr,clocks_throttle_reasons.hw_thermal_slowdown,clocks_throttle_reasons.sw_thermal_slowdown,power.draw", "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout.strip().split(", ")
                busy = json.load(urllib.request.urlopen(self.slots_url, timeout=2))[0]["is_processing"] if self.slots_url else None
                self.rows.append((time.time(), int(o[0]), int(o[1]), int(o[2]), "Active" in (o[3], o[4]), busy))
            except Exception:
                self.rows.append((time.time(), 0, 0, 0, False, None))


def run_one(name, td, idx, label, a):
    run = f"{label}-{name}-{idx}-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    run = re.sub(r"[^A-Za-z0-9-]", "-", run)
    reset_browser()
    if not healthy(a) and a.start_server:
        subprocess.run(a.start_server, shell=True, stdout=subprocess.DEVNULL, start_new_session=True)
    cwd = tempfile.mkdtemp(prefix="bench-")
    agent = a.cmd.replace("{tools}", shlex.quote(td["tools"])).replace("{prompt}", shlex.quote(td["prompt"](run)))
    cmd = f"cd {shlex.quote(cwd)} && {agent} </dev/null"
    env = dict(os.environ)
    for kv in a.env:
        k, v = kv.split("=", 1)
        env[k] = v
    s = Sampler(a.slots_url)
    s.start()
    t0 = time.time()
    p = subprocess.Popen(shlex.split(a.shell) + [cmd], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True, env=env)
    timed = threading.Timer(td["limit"], lambda: os.killpg(p.pid, signal.SIGKILL))
    timed.start()
    steps, tools, result, err, last, gaps = 0, [], "", False, t0, []
    log = open(os.path.join(RESULTS, f"{run}.events"), "w")
    for line in p.stdout:
        now = time.time()
        try:
            d = json.loads(line)
        except ValueError:
            continue
        kind = d.get("type")
        log.write(json.dumps({"t": round(now - t0, 1), "type": kind, "line": line.strip()[:6000]}) + "\n")
        log.flush()
        gaps.append((round(now - last, 1), kind))
        last = now
        if kind == "assistant":
            for c in d["message"]["content"]:
                if c["type"] == "tool_use":
                    steps += 1
                    tools.append(c["name"].split("__")[-1])
        if kind == "result":
            result = str(d.get("result") or "")
            err = bool(d.get("is_error"))
    p.wait()
    timed.cancel()
    secs = time.time() - t0
    s.stop.set()
    s.join()
    timeout = secs >= td["limit"] - 1
    try:
        passed = bool(td["check"](run, result, cwd))
    except Exception:
        passed = False
    rows = [r for r in s.rows if r[1]]
    idle = sum(1 for r in rows if r[5] is False)
    rec = dict(label=label, task=name, idx=idx, run=run, passed=passed, secs=round(secs), timeout=timeout, api_error=err, crashed=not healthy(a),
               false_claim=bool(not passed and result and SUCCESS.search(result) and not re.search(r"could not|unable|failed|did not|wrong answer|not accepted", result, re.I)),
               steps=steps, tools=tools[:40], result=result[:400], peak_vram=max((r[1] for r in rows), default=0), peak_temp=max((r[2] for r in rows), default=0),
               min_clock_busy=min((r[3] for r in rows if r[5]), default=0), throttled=any(r[4] for r in rows), model_idle_pct=round(100 * idle / max(len(rows), 1)),
               biggest_gap=max(gaps, default=(0, ""))[0], gap_before=max(gaps, default=(0, ""))[1])
    with open(os.path.join(RESULTS, f"{label}.jsonl"), "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"{name} #{idx} {'PASS' if passed else 'FAIL'} {rec['secs']}s steps={steps} timeout={timeout} crash={rec['crashed']} false={rec['false_claim']} vram={rec['peak_vram']} temp={rec['peak_temp']} idle={rec['model_idle_pct']}%", flush=True)


def summary(label):
    rows = [json.loads(l) for l in open(os.path.join(RESULTS, f"{label}.jsonl"))]
    print(f"\n=== {label} ===\ntask  pass  avg_s  steps  timeouts  false  idle%")
    for t in sorted({r["task"] for r in rows}):
        g = [r for r in rows if r["task"] == t]
        print(f"{t:4} {sum(r['passed'] for r in g)}/{len(g)}  {sum(r['secs'] for r in g) // len(g):5}  {sum(r['steps'] for r in g) // len(g):5}  {sum(r['timeout'] for r in g):8}  {sum(r['false_claim'] for r in g):5}  {sum(r['model_idle_pct'] for r in g) // len(g):5}")
    print(f"TOTAL {sum(r['passed'] for r in rows)}/{len(rows)} peak_vram={max(r['peak_vram'] for r in rows)} peak_temp={max(r['peak_temp'] for r in rows)} throttled={any(r['throttled'] for r in rows)} crashes={sum(r['crashed'] for r in rows)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("label", help="name for this run; results go to results/LABEL.jsonl")
    ap.add_argument("--cmd", required=True, help="agent command with {prompt} and {tools}")
    ap.add_argument("--shell", default="bash -c", help="shell used to run --cmd; use 'zsh -ic' to load your aliases")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--tasks", default="t1,t2,t3,t4,t5,t6,t7,t8,t9")
    ap.add_argument("--health-url", default="", help="model server health URL, for crash detection")
    ap.add_argument("--slots-url", default="", help="llama.cpp /slots URL, to separate model time from tool time")
    ap.add_argument("--start-server", default="", help="command that restarts the model server after a crash")
    ap.add_argument("--env", action="append", default=[], help="KEY=VALUE passed to the agent; repeatable")
    a = ap.parse_args()
    os.makedirs(RESULTS, exist_ok=True)
    if a.start_server:
        subprocess.run(a.start_server, shell=True, stdout=subprocess.DEVNULL, start_new_session=True)
    web = subprocess.Popen([sys.executable, "-I", os.path.join(HERE, "server.py")])
    time.sleep(1)
    defs = task_defs()
    try:
        for i in range(1, a.runs + 1):
            for name in a.tasks.split(","):
                run_one(name, defs[name], i, a.label, a)
        summary(a.label)
    finally:
        web.terminate()


if __name__ == "__main__":
    main()
