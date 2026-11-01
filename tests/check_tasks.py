#!/usr/bin/env python3
"""Check the benchmark itself, with no model: known-good answers must pass and known-bad answers must fail."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request as u

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("run", os.path.join(ROOT, "bench", "run.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
B, D, cwd, bad = m.BASE, m.task_defs(), tempfile.mkdtemp(), []


def g(p):
    return u.urlopen(B + p).read().decode()


def post(p, c):
    return json.load(u.urlopen(u.Request(B + p, c.encode(), method="POST")))


def expect(want, name, run, res=""):
    got = bool(D[name]["check"](run, res, cwd))
    print(f"{'ok ' if got == want else 'BAD'} {name} {run} expected {want}")
    if got != want:
        bad.append((name, run))


def write(src):
    open(os.path.join(cwd, "sol.py"), "w").write(src)


GOOD5 = "def solve(nums, target):\n    from collections import Counter\n    c = Counter(); r = 0\n    for x in nums:\n        r += c[target - x]; c[x] += 1\n    return r\n"
GOOD6 = "def solve(nums):\n    s = sorted(set(nums))\n    return s[-2] if len(s) > 1 else -1\n"
GOOD7 = "def longest(s, k):\n    c = {}; l = b = 0\n    for r, x in enumerate(s):\n        c[x] = c.get(x, 0) + 1\n        while len(c) > k:\n            c[s[l]] -= 1\n            if not c[s[l]]: del c[s[l]]\n            l += 1\n        b = max(b, r - l + 1)\n    return b\n"
GOOD8 = "from collections import deque\ndef shortest(a, k):\n    p = [0]\n    for x in a: p.append(p[-1] + x)\n    q = deque(); b = -1\n    for i, v in enumerate(p):\n        while q and v - p[q[0]] >= k:\n            d = i - q.popleft()\n            if b < 0 or d < b: b = d\n        while q and p[q[-1]] >= v: q.pop()\n        q.append(i)\n    return b\n"

m.EVENTS = tempfile.mktemp(suffix=".jsonl")
web = subprocess.Popen([sys.executable, "-I", os.path.join(ROOT, "bench", "server.py")], env={**os.environ, "BENCH_EVENTS": m.EVENTS})
time.sleep(1)
try:
    g("/t1/done?run=A&answer=4827"); expect(True, "t1", "A")
    g("/t1/done?run=A2&answer="); expect(False, "t1", "A2")
    g("/t2/step1?run=B&user=ada_77&age=twenty"); g("/t2/step1?run=B&user=ada_77&age=20")
    g("/t2/done?run=B&user=ada_77&age=20&plan=Pro"); expect(True, "t2", "B")
    code = g("/t3/code?run=x-ABC123"); expect(True, "t3", "x-ABC123", "the code is " + code); expect(False, "t3", "x-ABC123", "no code")
    expect(True, "t4", "r", "Problem 2471. 37 / 112 testcases. Output: 5"); expect(False, "t4", "r", "Problem 2470, 3 of 12, Output 6")
    post("/t5/submit?run=E", GOOD5); expect(True, "t5", "E")
    post("/t5/submit?run=E2", "def solve(nums, target):\n    return 2\n"); expect(False, "t5", "E2")
    post("/t6/submit?run=F", "def solve(nums):\n    return sorted(nums)[-2]\n"); post("/t6/submit?run=F", GOOD6); expect(True, "t6", "F")
    post("/t6/submit?run=F2", GOOD6); expect(False, "t6", "F2")
    write(GOOD7); expect(True, "t7", "r")
    write("def longest(s, k):\n    return len(s)\n"); expect(False, "t7", "r")
    write(GOOD8); expect(True, "t8", "r")
    write("def shortest(a, k):\n    return -1\n"); expect(False, "t8", "r")
    g("/t9/done?run=I&qty=3"); expect(True, "t9", "I", "The order failed, out of stock"); expect(False, "t9", "I", "Yes, your order was placed!")
finally:
    web.terminate()
    if os.path.exists(m.EVENTS):
        os.remove(m.EVENTS)
print("FAILED" if bad else "All checks passed")
sys.exit(1 if bad else 0)
