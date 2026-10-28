"""Stand-in for `qloo exec` in the executor tests. The request's `query` picks the behavior.

Invoked as: python fake_qloo.py exec <workflow> --input-file <path>. Standard library only,
because the executor gives child processes a minimal environment.
"""

import json
import os
import sys
import time

args = sys.argv[1:]
workflow = args[1]
with open(args[args.index("--input-file") + 1], encoding="utf-8") as handle:
    behavior = json.load(handle).get("query", "ok")


def envelope(**fields: object) -> str:
    value = {
        "schema_version": "1.0-preview.1",
        "operation": workflow,
        "status": "ok",
        "results": [],
        "result_count": 0,
        "execution": {"transport": "direct", "transport_name": "Qloo API", "correlation_id": "exec-test", "duration_ms": 1},
    }
    value.update(fields)
    return json.dumps(value)


def failure(code: str, retryable: bool, exit_code: int) -> None:
    error = {"code": code, "layer": "qloo", "retryable": retryable, "recovery": "Test recovery text."}
    print(json.dumps({"error": error, "operation": workflow, "correlation_id": "exec-test"}))
    sys.exit(exit_code)


if behavior == "ok":
    hiking = {"id": "urn:tag:keyword:qloo:hiking", "name": "Hiking", "type": "urn:tag:keyword:qloo"}
    print(
        envelope(
            results=[hiking],
            result_count=1,
            seen_env=sorted(os.environ),  # names only, never values
            argv=args,
            cwd=os.getcwd(),
            qloo_home=os.environ.get("QLOO_HOME"),
        )
    )
elif behavior == "sleep":
    time.sleep(30)
elif behavior == "badjson":
    print("this is not json")
elif behavior == "crash":
    print("boom: internal failure details", file=sys.stderr)
    sys.exit(3)
elif behavior == "auth":
    failure("QLOO_AUTH", False, 4)
elif behavior == "ratelimit":
    failure("QLOO_RATE_LIMIT", True, 1)
elif behavior == "big":
    sys.stdout.write("x" * (3 * 1024 * 1024))
elif behavior == "error envelope":
    print(envelope(status="error", error={"code": "QLOO_UPSTREAM", "layer": "qloo", "retryable": True, "recovery": "Retry later."}))
elif behavior == "wrong operation":
    print(envelope(operation="rank"))
elif behavior == "old schema":
    print(envelope(schema_version="0.9"))
elif behavior == "leak":
    key = os.environ.get("QLOO_API_KEY", "")
    print(f"debug: key={key}", file=sys.stderr)
    print(envelope(results=[{"id": key, "name": "Leaky"}], result_count=1))
