# MCP servers

This directory holds the shared MCP bridge conventions used inside the repo:

- `base.py`: common server / tool / resource abstractions
- `runner.py`: single entry point for starting and calling a server
- `stdio.py`: the JSON-RPC stdio server the plugin exposes
- `paperassist/`: pack tools (`harness_status`, `pack_scaffold`, `pack_plan`, `pack_task`, `pack_import`)
- `writing/`: writing pack tools (`writing_pack`, `writing_plan`, `writing_task`, `writing_import`, `writing_patch`)
- `literature/`, `bibliography/`, `file-gateway/`, `remote-runner/`, `diagram/`, `aigc-eval/`: domain bridges

## Status

- `paperassist`, `writing`: live, deterministic, model-free
- `literature`: live bridge over the existing literature search
- `bibliography`: live bridge over the minimal bibliography manager
- `file-gateway`: skeleton lock-aware workspace file gateway
- `remote-runner`: skeleton bridge over the cloud cycle / sync entry points
- `diagram`: skeleton bridge for light structural diagrams and captions
- `aigc-eval`: skeleton bridge for light text-risk checks

## Design principles

- MCP connects external capabilities; it does not own the workflow state machine.
- Every tool is model-free: no provider calls, no credentials, no prompts sent
  to a remote service.
- Write operations must take the workspace lock.
- Build an equivalent bridge first, then strengthen it.
