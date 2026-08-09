# ADR-003: Replay matching and divergence

**Status:** Accepted
**Date:** 2026-08-09
**Supersedes:** none
**Superseded by:** none

---

## Context

The replay engine must decide, for every incoming tool call, whether it can answer faithfully. The failure mode to avoid is **fabrication**: returning a plausible response the recorded world does not support. Fabrication produces confident wrong answers, which in a verification product is worse than no answer at all.

The architecture review of ARCH-001 identified the merge function as the component most likely to kill the project, on the grounds that a narrow capability failing opaquely outside its range is experienced by users as arbitrary.

---

## Decision

**Match on `(server, tool, canonical(arguments))` with exact equality. Never fuzzy-match. Every call is first checked against its tool's declared fidelity contract; a call outside the contract produces a classified divergence and no response.**

### Canonicalization

Deterministic and specified:

1. Sort object keys.
2. Normalize numeric representation.
3. Drop paths listed in `canonicalization.volatile_paths`.
4. Substitute minted ids back to their recorded counterparts where a mapping exists.
5. Normalize Unicode to NFC.

### Matching order

```
1. tool unknown                              -> UNKNOWN_TOOL (FATAL)
2. call outside declared fidelity contract   -> OUT_OF_CONTRACT (ERROR)
3. exact recorded match                      -> serve, provenance RECORDED
4. L2-Core write                             -> mutate overlay, serve recorded or synthesized
5. L2-Core read                              -> merge(recorded, overlay), provenance OVERLAY
6. no match, no overlay coverage             -> NO_RECORDED_INTERACTION (ERROR)
```

### Divergence taxonomy

| Class | Severity | Verdict effect |
|---|---|---|
| `UNKNOWN_TOOL` | FATAL | Execution UNKNOWN, always |
| `UNKNOWN_SERVER` | FATAL | Execution UNKNOWN, always |
| `WORLD_SCHEMA_UNSUPPORTED` | FATAL | Execution UNKNOWN, always |
| `OUT_OF_CONTRACT` | ERROR | Execution UNKNOWN by default; FAIL under `strict` |
| `NO_RECORDED_INTERACTION` | ERROR | Execution UNKNOWN by default; FAIL under `strict` |
| `UNDECLARED_OPERATION` | WARN | Safety-sensitive assertions UNKNOWN |
| `SYNTHESIZED_WRITE_RESPONSE` | WARN | Response-content assertions on it UNKNOWN |
| `UNMERGEABLE_OVERLAY` | WARN | Dependent assertions UNKNOWN |
| `PAGINATION_OVERLAY_SKIPPED` | WARN | Dependent assertions UNKNOWN |
| `STALE_DERIVED_FIELD` | WARN | Assertions touching the stale path UNKNOWN |
| `ARGUMENT_DRIFT` | INFO | None |
| `ORDER_DRIFT` | INFO | None |
| `EXTRA_CALL` | INFO | None |

### Strictness policy

`strict`, `standard` (default), `lenient` control which severities terminate an execution. **No policy can convert a divergence into PASS.** CI defaults to `strict`.

### The invariant

**No divergence at any severity may result in PASS for an assertion that depended on the diverged interaction.** The mapping from divergence to dependent assertions is computed by the engine from trajectory evidence references, never left to assertion authors.

---

## Rationale

- **Fuzzy matching is fabrication with extra steps.** A near-match served as an exact match is precisely the failure this product exists to prevent.
- **The contract check must precede the match**, otherwise the fidelity promise is aspirational rather than enforceable.
- **Divergence as a first-class domain object** follows from the product promise: telling the user when we cannot answer *is* the product, not an error path within it.

---

## Consequences

### Accepted

- Higher divergence rates than a lenient engine would produce. This is the intended trade, and it makes World Maintenance load-bearing rather than optional, which is why it was promoted to v0.1.
- Users encounter divergence early and often. Divergence message quality ([NFR-105](../../requirements/non-functional-requirements.md#developer-experience)) is a primary UX surface, not an error path.

### Gained

- The engine can never silently produce a wrong answer.
- Divergence rate becomes a measurable product health signal ([NFR-092](../../requirements/non-functional-requirements.md#observability)) visible to users and to us.

### Open, deliberately

Whether real-world divergence rates are tolerable across ordinary prompt iteration. This is measured in [Milestone 0](../../development/milestone-0.md) step 8 and again in M2.5.

---

## Related

- Requirements: FR-040, FR-044, FR-048, FR-049, FR-050, FR-188, FR-189, FR-190
- Invariants: [INV-004](../invariants.md#inv-004--never-fabricate), [INV-005](../invariants.md#inv-005--divergence-is-first-class-and-always-visible), [INV-003](../invariants.md#inv-003--fidelity-contract)
- Components: C6 Replay Engine
