# Actual pinned Codex app-server environment

Question: does the env-clearing launcher isolate the actual pinned Rust app-server, as opposed
to the earlier Python child probe? Expect exactly PATH, HOME, LANG and CODEX_HOME, with no
synthetic inherited GH_TOKEN/OPENAI_API_KEY. This follows up the inconclusive actual-process
setup in 2026-10-13-runtime-contracts.md.

## Method

Use openai-codex 0.162.1 and its bundled public codex_cli_bin runtime 0.162.1. Create a temporary
HOME and CODEX_HOME directory before start (the older probe omitted that directory). A short
exec wrapper records its PID before execing /usr/bin/env -i and the bundled app-server. The
wrapper is solely for observation; production needs no PID wrapper. It avoids private SDK
process attributes. Calls are CodexClient.start(), initialize(), close(); no authentication API,
thread or turn is called. Environment values returned by ps remain in memory; only names print.
The outer process uses the existing bounded process-group runner with a 30-second cap.

```text
$ uv run python - <<'PY'
import asyncio
from pathlib import Path
from lgcw.git.run import run_process
async def main() -> None:
 result=await run_process(('uv','run','python','spikes/2026-10-13-codex-environment/probe.py'),cwd=Path.cwd(),timeout_s=30)
 content=f'exit {result.code}\n{result.out}{result.err}'
 Path('/tmp/lgcw-codex-environment-probe-final.log').write_text(content)
 print(content)
asyncio.run(main())
PY
exit 0
{"authentication_api_calls": 0, "binary": "0.162.1", "exact_four": true, "initialized": true, "keys": ["CODEX_HOME", "HOME", "LANG", "PATH"], "llm_turns": 0, "sdk": "0.162.1"}
app-server closed: verified PID absent
```

The exact recorded invocation used uv run python to call lgcw.git.run.run_process with the probe
argv and timeout_s=30; the transcript is /tmp/lgcw-codex-environment-probe-final.log. Counters
refer to explicit probe API calls, not an OS syscall audit. The temporary home had no owner
login; no authentication file contents were read or copied. The earlier transcript called the
zero auth counter authentication_reads; it was corrected to authentication_api_calls to avoid
implying a syscall measurement, and the free probe reran.

Verdict: confirmed. CodexConfig.env alone merges the parent (pinned client.py source); the public
launch_args_override plus env -i clears it before the Rust agent server. This supplies T10's
launcher evidence without private SDK imports. Public bundled runtime resolution will need a
choosing-dependencies entry if used by product code. Remaining T10 questions still need live
turns: SkillInput + text, output_schema after resume, usage semantics/cached tokens/context,
rollout location, read-only write denial, and interruption/cancellation.
