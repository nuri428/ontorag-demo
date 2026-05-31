"""Compose the case manager, registry, executor, and domain actions; drive a case end-to-end.

Mirrors the structure of ``vendor/ontorag-flow/examples/supply_chain_rca/run_demo.py``:
RuleEngine drives until the case suspends (human approval gate), the
runner simulates the operator signing off, then explicitly executes the
write-back action with the suspect lot URI from case state.
"""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ontorag.stores.base import GraphStore
from ontorag_flow.core.case import CaseStatus
from ontorag_flow.core.case_manager import CaseManager
from ontorag_flow.core.executor import ActionExecutor
from ontorag_flow.core.process import load_process
from ontorag_flow.core.provenance import render
from ontorag_flow.core.registry import default_registry
from ontorag_flow.engines.selection import EngineResolver
from ontorag_flow.stores.sqlite import SqliteStore
from rich.console import Console
from rich.table import Table

from ontorag_demo.flow.actions import (
    QUARANTINED_KEY,
    SUSPECT_LOT_KEY,
    build_domain_actions,
    lot_uri_for,
)

PROCESS_YAML = Path(__file__).resolve().parent / "process.yaml"
QUARANTINE_ACTION = "urn:demo:manufacturing:QuarantineLot"


@dataclass(frozen=True)
class FlowResult:
    case_uri: str
    final_status: str
    audit_ttl_path: Path
    state_snapshot: dict[str, Any]


async def run_flow(
    store: GraphStore,
    *,
    initial_defect_rate_percent: int = 25,
    output_dir: Path | None = None,
    console: Console | None = None,
) -> FlowResult:
    """Drive one RCA case end-to-end and return the audit artefacts.

    ``store`` is ontorag's loaded GraphStore — the Pinpoint action SPARQLs
    against it, the Quarantine action SPARQL-UPDATEs against it.
    """
    console = console or Console()
    logging.getLogger("ontorag_flow").setLevel(logging.WARNING)

    process = load_process(PROCESS_YAML)
    actions = build_domain_actions(store)
    output_dir = output_dir or Path(tempfile.mkdtemp(prefix="ontorag-demo-flow-"))
    output_dir.mkdir(parents=True, exist_ok=True)

    console.rule(f"[bold]Process[/] {process.process_uri}")
    console.print(
        f"goal:        {process.goal}\n"
        f"actions:     {len(process.allowed_actions)}\n"
        f"rules:       {len(process.rules)}\n"
        f"requires:    {process.constraints.get('requires', {})}\n"
    )

    case_store = SqliteStore(str(output_dir / "case.db"))
    await case_store.connect()
    try:
        registry = default_registry()
        for action in actions:
            registry.register(action)

        manager = CaseManager(
            case_store=case_store,
            process_store=case_store,
            executor=ActionExecutor(audit_store=case_store, agent="urn:demo:ops"),
            registry=registry,
            engine_factory=EngineResolver(registry=registry).for_process,
        )
        await manager.register_process(process)

        incident_state = {"defect_rate_percent": initial_defect_rate_percent}
        case = await manager.create_case(process.process_uri, initial_state=incident_state)
        console.print(
            f"opened [cyan]{case.case_uri}[/] with defect rate "
            f"{initial_defect_rate_percent}%\n"
        )

        # Phase 1 — let the RuleEngine drive until human handoff (or terminal).
        console.rule("Phase 1 — automatic (RuleEngine until suspend)")
        case = await _drive_until_terminal(manager, case.case_uri, console)

        # Phase 2 — human approval simulation + explicit write-back.
        if case.status is CaseStatus.SUSPENDED:
            console.rule("[yellow]Phase 2 — human approval gate[/]")
            console.print(
                f"  reason: {case.state.properties.get('approval_reason')!r}\n"
                "  ...simulating the operator clicking 'approve' ..."
            )
            case = await manager.resume(case.case_uri)

            suspect_lot_id = case.state.properties.get(SUSPECT_LOT_KEY)
            if not suspect_lot_id:
                raise RuntimeError(
                    "Suspect lot missing from case state — PinpointSuspectLot did not fire."
                )

            console.rule("Phase 3 — ABox write-back (QuarantineLot)")
            case, _ = await manager.execute_action(
                case.case_uri,
                QUARANTINE_ACTION,
                {"lot_uri": lot_uri_for(suspect_lot_id)},
            )
            console.print(
                f"  wrote: mfg:quarantined = true on {suspect_lot_id} "
                f"({lot_uri_for(suspect_lot_id)})\n"
            )

            # Phase 4 — let the RuleEngine run the CF replay rule to close.
            console.rule("Phase 4 — counterfactual replay (closes the case)")
            case = await _drive_until_terminal(manager, case.case_uri, console)

        # Audit export.
        console.rule("Audit trail")
        activities = await case_store.list_by_case(case.case_uri)
        _print_history(activities, console)
        ttl_path = output_dir / "audit.ttl"
        ttl_path.write_text(render(activities, "ttl"), encoding="utf-8")
        console.print(f"\nPROV-O Turtle export: {ttl_path} ({ttl_path.stat().st_size} bytes)")
        state_path = output_dir / "case_state.json"
        state_path.write_text(
            json.dumps(case.state.properties, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        console.print(f"Final case state: {state_path}")

        return FlowResult(
            case_uri=case.case_uri,
            final_status=case.status.value,
            audit_ttl_path=ttl_path,
            state_snapshot=dict(case.state.properties),
        )
    finally:
        await case_store.close()


async def _drive_until_terminal(manager: CaseManager, case_uri: str, console: Console):  # type: ignore[no-untyped-def]
    case = await manager.get_case(case_uri)
    assert case is not None
    step = 0
    while case.status is CaseStatus.OPEN:
        step += 1
        proposals = await manager.propose_next(case_uri)
        if not proposals:
            console.print("[yellow]engine yielded nothing — stopping.[/]")
            break
        top = proposals[0]
        short = top.action_uri.rsplit(":", 1)[-1]
        console.print(
            f"  [bold]#{step}[/] picks [magenta]{short}[/] (conf {top.confidence:.2f}) — {top.rationale}"
        )
        case, _ = await manager.execute_action(case_uri, top.action_uri, top.params)
    console.print(f"  status after phase: [bold]{case.status.value}[/]\n")
    return case


def _print_history(activities, console: Console) -> None:  # type: ignore[no-untyped-def]
    table = Table(title="PROV-O activities")
    table.add_column("#", justify="right")
    table.add_column("Action")
    table.add_column("Agent")
    table.add_column("Status")
    for i, a in enumerate(activities, start=1):
        short = a.action_uri.rsplit(":", 1)[-1]
        status = getattr(a, "status", "completed") or "completed"
        table.add_row(str(i), short, a.agent or "—", status)
    console.print(table)
