# Server C: deterministic MCP fixture server

**This is the only Milestone 0 artifact intended to survive.** It becomes the permanent
conformance fixture referenced by [testing-strategy.md](../../docs/testing/testing-strategy.md).

## Why it exists

It is the only environment where correct semantics are known with certainty, which makes
it the debugging substrate for the replay engine and the generator of the conformance corpus.

## Protocol

MCP stdio: newline-delimited JSON-RPC 2.0. Implements `initialize`, `tools/list`, `tools/call`.

## Tools

| Tool | Shape | Purpose in the spike |
|---|---|---|
| `create_issue(project, title)` | write, entity `issue` | L2-Core create |
| `get_issue(id)` | read by id | L2-Core get-by-id |
| `update_issue(id, title?, status?)` | write | L2-Core update |
| `delete_issue(id)` | write | L2-Core delete |
| `list_issues(project, limit?, offset?)` | read collection | L2-Core list + pagination |
| `search_issues(query)` | read, **query language** | Must stay L1. Proves the contract boundary |

`list_issues` returns `{issues: [...], total: N}`. The `total` sibling is deliberate: after an
overlay create, `total` is a derived field the engine cannot recompute and must mark STALE.

`search_issues` takes a `field=value AND field=value` expression. It exists to be
**refused** by L2-Core, not supported.

## Determinism

Timestamps come from a virtual clock (epoch `2026-01-01T00:00:00Z`, 1 second per operation),
never the wall clock. Ids are sequential (`FX-001`, ...). The server is reproducible across
runs and machines.

## Controlled errors

`FIXTURE_FAIL_ON=<tool_name>` forces that tool to return an MCP error result. Used to record
error interactions without needing a real failure.

## Run

```bash
python spike/fixture_server/server.py
```

Reads JSON-RPC from stdin, writes to stdout. Intended to be spawned by an MCP client.
