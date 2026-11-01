#!/usr/bin/env bash
# Example: benchmark a local GGUF model through llama.cpp and Claude Code, with Chrome DevTools as the browser.
# Edit the paths. This only talks to local services apart from your agent's own traffic.
set -euo pipefail
MODEL=/path/to/model.gguf
MMPROJ=/path/to/mmproj.gguf
PORT=18083
CTX=32768
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# 1. Chrome with a debug port on localhost and its own profile.
google-chrome --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.cache/browser-agent-bench-chrome" --no-first-run about:blank >/dev/null 2>&1 &

# 2. llama.cpp server. -ngl 99 with --fit off fails rather than silently falling back to the CPU.
llama-server -m "$MODEL" --mmproj "$MMPROJ" --alias local -ngl 99 --fit off -c "$CTX" -np 1 --jinja \
  --image-max-tokens 512 --host 127.0.0.1 --port "$PORT" >/tmp/llama-server.log 2>&1 &
until curl -sf "http://127.0.0.1:$PORT/health" >/dev/null; do sleep 1; done

# 3. Browser tools for the agent.
MCP="$(mktemp)"
cat >"$MCP" <<JSON
{"mcpServers":{"chrome-devtools":{"command":"npx","args":["-y","chrome-devtools-mcp@1.12.0","--browserUrl","http://127.0.0.1:9222","--usageStatistics=false","--performanceCrux=false"]}}}
JSON

# 4. Run. CLAUDE_CODE_MAX_CONTEXT_TOKENS triggers compaction below the real context size.
export ANTHROPIC_BASE_URL="http://127.0.0.1:$PORT" ANTHROPIC_AUTH_TOKEN=local ANTHROPIC_API_KEY=""
export ANTHROPIC_DEFAULT_OPUS_MODEL=local ANTHROPIC_DEFAULT_SONNET_MODEL=local ANTHROPIC_DEFAULT_HAIKU_MODEL=local
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 ENABLE_TOOL_SEARCH=false API_TIMEOUT_MS=3600000
export CLAUDE_CODE_MAX_CONTEXT_TOKENS=$(( CTX * 92 / 100 )) CLAUDE_CODE_MAX_OUTPUT_TOKENS=6144
python3 "$ROOT/bench/run.py" "${1:-local-model}" \
  --health-url "http://127.0.0.1:$PORT/health" --slots-url "http://127.0.0.1:$PORT/slots" \
  --cmd "claude --model local --bare --strict-mcp-config --mcp-config $MCP --tools Bash,Read,Write,Edit,Glob,Grep -p --allowedTools {tools} --verbose --output-format stream-json {prompt}"
