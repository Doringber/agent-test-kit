"""M0 spike domain models. Dataclasses only, exactly as specified in milestone-0.md.

No pydantic. No production schema abstractions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Mode = Literal["record", "replay", "hybrid"]
Operation = Literal["read", "write", "unknown"]
CapState = Literal["confirmed", "proposed", "unknown"]
Fidelity = Literal["l1", "l2_core"]
Provenance = Literal["recorded", "overlay", "synthesized"]

Severity = Literal["fatal", "error", "warn", "info"]
DivergenceCls = Literal[
    "UNKNOWN_TOOL", "OUT_OF_CONTRACT", "NO_RECORDED_INTERACTION",
    "SYNTHESIZED_WRITE_RESPONSE", "UNMERGEABLE_OVERLAY",
    "PAGINATION_OVERLAY_SKIPPED", "STALE_DERIVED_FIELD", "EXTRA_CALL",
    "ENTITY_CONSTRUCTION_FAILED",                      # ADR-006 s4
]

SEVERITY_OF: dict[str, Severity] = {
    "UNKNOWN_TOOL": "fatal",
    "OUT_OF_CONTRACT": "error",
    "NO_RECORDED_INTERACTION": "error",
    "ENTITY_CONSTRUCTION_FAILED": "error",             # ADR-006 s4
    "SYNTHESIZED_WRITE_RESPONSE": "warn",
    "UNMERGEABLE_OVERLAY": "warn",
    "PAGINATION_OVERLAY_SKIPPED": "warn",
    "STALE_DERIVED_FIELD": "warn",
    "EXTRA_CALL": "info",
}

# ADR-006 s5. Exactly two values. No UNKNOWN_ENTITY (INV-017 makes it unreachable),
# no VERIFIED_SYNTHESIZED_ENTITY (validation makes it redundant).
EntityProvenance = Literal["RECORDED_ENTITY", "SYNTHESIZED_ENTITY"]


@dataclass(frozen=True)
class EntityConstructionContract:
    """ADR-006 s1. Minimum information to turn a write request into overlay state.

    Authority is OBSERVED DATA, not human declaration.
    """
    entity_template: tuple[str, ...] = ()          # authoritative key set
    required_fields: tuple[str, ...] = ()          # present on every observed entity
    field_bindings: dict[str, str] = field(default_factory=dict)   # entity_key <- request_key
    generated_fields: dict[str, str] = field(default_factory=dict)  # key -> "mint" | "clock"
    constant_defaults: dict[str, Any] = field(default_factory=dict)
    cardinality: str = "one"                       # "many" is reserved, never implemented

    def unresolved(self) -> tuple[str, ...]:
        """Required fields that are neither bound, generated, nor constant (V4)."""
        known = set(self.field_bindings) | set(self.generated_fields) | set(self.constant_defaults)
        return tuple(sorted(f for f in self.required_fields if f not in known))

    def construct(self, request: dict, mint, clock) -> tuple[dict | None, str | None]:
        """ADR-006 s1 step 2. Build an entity from a request. Returns (entity, failure).

        Lives on the contract, not in compile/, so replay/ can use it without importing
        inference (FR-165). Construction is mechanical; deriving the contract is not.
        """
        entity: dict = {}
        for key in self.entity_template:
            if key in self.field_bindings:
                src = self.field_bindings[key]
                if src in request:
                    entity[key] = request[src]
                elif key in self.required_fields:
                    return None, f"required field {key!r} has no value at request path {src!r}"
            elif key in self.generated_fields:
                entity[key] = mint() if self.generated_fields[key] == "mint" else clock()
            elif key in self.constant_defaults:
                entity[key] = self.constant_defaults[key]
            elif key in self.required_fields:
                return None, f"required field {key!r} is unresolved by the contract"
        missing = [f for f in self.required_fields if f not in entity]
        if missing:
            return None, f"constructed entity is missing required field(s) {missing}"
        return entity, None


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of ADR-006 s3 validations V1-V6."""
    passed: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    reasons: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failed

    def first_failure(self) -> str | None:
        return self.failed[0] if self.failed else None


@dataclass(frozen=True)
class Interaction:
    seq: int
    server: str
    tool: str
    request: dict          # canonical
    response: dict
    status: Literal["success", "error"]


@dataclass(frozen=True)
class Capability:
    operation: Operation
    state: CapState
    fidelity: Fidelity
    entity_type: str | None = None
    id_request_path: str | None = None
    id_response_path: str | None = None
    body_request_path: str | None = None
    collection_response_path: str | None = None
    predicate: dict | None = None            # grammar per ADR-004
    ignored_request_paths: tuple[str, ...] = ()
    pagination_paths: tuple[str, ...] = ()
    # L2-Core mutation kind: create | update | delete | get (reads use collection/get)
    mutation: str | None = None
    derived_paths: tuple[str, ...] = ()
    ecc: EntityConstructionContract | None = None   # ADR-006 s1, write tools
    validation: ValidationResult | None = None      # ADR-006 s3


@dataclass
class Entity:
    entity_type: str
    entity_id: str
    body: dict
    deleted: bool = False
    provenance: EntityProvenance = "RECORDED_ENTITY"   # ADR-006 s5


@dataclass(frozen=True)
class Divergence:
    cls: DivergenceCls
    severity: Severity
    seq: int
    server: str
    tool: str
    detail: str


@dataclass(frozen=True)
class CallOutcome:
    served: bool
    response: dict | None
    provenance: Provenance | None
    stale_paths: tuple[str, ...]
    divergence: Divergence | None
    # ADR-006 s5. Ids of SYNTHESIZED_ENTITY entities present in this response.
    # NEVER cleared by a downstream read.
    synthesized_entity_ids: tuple[str, ...] = ()


@dataclass
class World:
    world_id: str
    seed_epoch: str                       # virtual clock epoch
    volatile_paths: tuple[str, ...]
    tools: dict[tuple[str, str], Capability]
    interactions: list[Interaction]
    entities: dict[str, list[Entity]]
    id_minting: dict[str, str]            # entity_type -> template
    tools_list_hash: str
    tools_list: dict[str, list] = field(default_factory=dict)  # server -> raw tools/list


@dataclass
class ReplayStats:
    calls: int = 0
    served_recorded: int = 0
    served_overlay: int = 0
    served_synthesized: int = 0
    refused: int = 0
    divergences: list[Divergence] = field(default_factory=list)


@dataclass
class SessionSummary:
    session_id: str
    seq: int
    stats: ReplayStats
    interactions: list[Interaction]


@dataclass
class CapabilityProposal:
    """Compiler output. `questions` counts the manual decisions required (M4)."""
    capability: Capability
    questions: list[str] = field(default_factory=list)
    auto_derived: list[str] = field(default_factory=list)


@dataclass
class CompileReport:
    decisions_per_tool: dict[str, int] = field(default_factory=dict)
    proposals: dict[str, CapabilityProposal] = field(default_factory=dict)

    def median_decisions(self) -> float:
        vals = sorted(self.decisions_per_tool.values())
        if not vals:
            return 0.0
        mid = len(vals) // 2
        return float(vals[mid]) if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0

    def max_decisions(self) -> int:
        return max(self.decisions_per_tool.values(), default=0)
