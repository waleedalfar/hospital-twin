"""Stands in for `python -m twin.ml.fed_cli --json` in API tests: prints progress lines like the real one."""

import json
import sys

mode = sys.argv[1] if len(sys.argv) > 1 else "ok"
print("some library log line that is not JSON", flush=True)
for r in range(1, 4):
    print(json.dumps({"event": "round", "round": r, "rounds": 3, "auroc": 0.8 + r / 100}), flush=True)
if mode == "error":
    print(json.dumps({"event": "error", "message": "boom"}), flush=True)
    sys.exit(1)
if mode == "crash":
    sys.stderr.write("Traceback: it crashed")
    sys.exit(2)
print("{broken json", flush=True)
print(
    json.dumps({"event": "done", "gates_ok": mode == "ok", "problems": [] if mode == "ok" else ["federated below centralized"], "summary": "x"}),
    flush=True,
)
sys.exit(0 if mode == "ok" else 1)
