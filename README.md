# browser-agent-bench

A small benchmark for AI agents that use a real browser and write code, built for testing local models.

Agents often say they finished a task when they didn't. In my testing, one model submitted an empty form three times and reported success each time. So this benchmark never trusts the agent's report: it scores from what the test server actually received and from hidden tests.

## Tasks

| ID | Task | What it tests | How it's scored |
|---|---|---|---|
| t1 | Simple form | Basic actions | Exact value received by the server |
| t2 | Multi-step form with a validation error | Recovering from errors | Final submission is correct |
| t3 | Page that renders late | Waiting properly | Per-run code in the answer |
| t4 | Text that exists only inside an image | Vision | Correct facts in the answer |
| t5 | Mock coding site with an in-page editor | Read, write, run, submit | Hidden tests pass on the server |
| t6 | Wrong starting code that must be fixed | Iterating on feedback | A failed submit, then an accepted one |
| t7 | Medium coding problem | Coding | Hidden randomized tests |
| t8 | Hard coding problem | Coding limits | Hidden randomized and large-input tests |
| t9 | Page that looks successful but reports failure | Honest reporting | Agent must report the failure |

Each run records pass or fail, time, steps, timeouts, crashes, likely false success claims, peak VRAM, GPU temperature and thermal throttling. Timestamped logs show whether time went to the model or to a waiting tool.

## Requirements

- Python 3.9+ (standard library only)
- An agent that outputs Claude Code style `stream-json`, such as Claude Code pointed at any compatible server
- Chrome with a debug port, plus a browser tool such as [`chrome-devtools-mcp`](https://github.com/ChromeDevTools/chrome-devtools-mcp)
- Optional: `nvidia-smi` for GPU stats, and llama.cpp for model server stats

## Quick start

Check the benchmark itself, with no model:

```bash
python3 tests/check_tasks.py
```

Run an agent:

```bash
google-chrome --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.cache/browser-agent-bench-chrome" about:blank &

python3 bench/run.py my-model --runs 3 \
  --cmd 'my-agent -p --allowedTools {tools} --verbose --output-format stream-json {prompt}'
```

Results go to `results/my-model.jsonl`, and a summary prints at the end. To use aliases from your shell config, add `--shell 'zsh -ic'`. Each task starts by **closing every tab in that debug Chrome**, so use a dedicated profile.

For a full local setup with llama.cpp, see [`examples/llama-cpp-claude-code.sh`](examples/llama-cpp-claude-code.sh).

| Setting | Default | Purpose |
|---|---|---|
| `BENCH_PORT` | `18765` | Test site port |
| `BENCH_CDP` | `http://127.0.0.1:9222` | Chrome debug address |
| `BENCH_EVENTS` | `bench/events.jsonl` | Where the server records events |

## Security

- The site listens only on `127.0.0.1`.
- **t5 and t6 run code written by the model on your machine.** It gets CPU and memory limits and an empty directory, and no network access where `unshare` allows it. That is not a real sandbox, so use a VM or container if that matters to you.
- t7 and t8 give the agent a shell, and the hidden tests run the Python it writes.
- The debug port lets any program on your computer control that Chrome, including sites logged in there. Close it when you're done.

## Example results

One model, 3 runs per task, on an RTX 3060 laptop GPU with 6 GB of VRAM:

**Qwable-9B Q3_K_M + mmproj Q8_0, 32k context, all layers on GPU**

| Task | Passed | Avg time | Avg steps | Timeouts | False claims |
|---|---|---:|---:|---:|---:|
| t1 | 3/3 | 23s | 7 | 0 | 0 |
| t2 | 2/3 | 38s | 11 | 0 | 1 |
| t3 | 2/3 | 89s | 8 | 1 | 0 |
| t4 | 3/3 | 12s | 2 | 0 | 0 |
| t5 | 2/3 | 177s | 21 | 0 | 0 |
| t6 | 3/3 | 151s | 18 | 0 | 0 |
| t7 | 3/3 | 38s | 3 | 0 | 0 |
| t8 | 0/3 | 290s | 7 | 2 | 1 |
| t9 | 3/3 | 31s | 7 | 0 | 0 |
| **Total** | **21/27** | | | **3** | **2** |

3 runs per task is a small sample, so treat this as a rough guide. The GPU reached 92°C and throttled. The false-claim column is a text-matching estimate and can be wrong, and the t5 count here was corrected by hand after a scoring bug, which is now fixed.

## What I learned running local models

- **Check screenshots at real size.** A display-scaled 2000×1404 screenshot ran the GPU out of memory when smaller test images worked. `--image-max-tokens` shrinks images inside llama.cpp and fixed it.
- **A model loading with an mmproj doesn't mean it works.** A text-only model loaded with a related model's mmproj and produced garbage. Use a pair made for each other.
- **Not every stall is the model.** Several long gaps were a browser wait tool blocking on text that never appeared.
- **Compaction needs a real limit.** In my Claude Code version, `CLAUDE_CODE_AUTO_COMPACT_WINDOW` treats values under 100k as 100k, so small local contexts overflowed before compacting. `CLAUDE_CODE_MAX_CONTEXT_TOKENS` set below the real context size worked.
- **Simple pages say little about live apps.** A model that did well here still failed a task in a real web-based engineering app, mostly by looping until its context ran out.

## Contributing

New tasks are welcome. Each one should have a check that can't be passed by the agent's words alone, and known-good and known-bad cases in `tests/check_tasks.py`.

## License

[MIT](LICENSE)
