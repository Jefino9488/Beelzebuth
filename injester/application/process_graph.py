from pathlib import Path
from typing import Optional, Union, Dict, Any
from pydantic import BaseModel, Field

from injester.application.manager import manager
from injester.semantic.schemas import DualOutputResult
from injester.semantic.projections import (
    render_bpmn_20_xml,
    render_flowchart_mermaid,
    render_swimlane_mermaid,
)

class ProcessGraphResult(BaseModel):
    process_name: str
    objective: str
    activities_count: int
    gateways_count: int
    transitions_count: int
    actors_count: int
    defects_count: int
    bpmn_xml: str
    flowchart_mermaid: str
    swimlane_mermaid: str
    defect_markdown: str
    total_latency_sec: float
    output_dir: Optional[str] = None
    snapshot_id: Optional[str] = None
    generation_run_id: Optional[str] = None

class ProcessGraphService:
    def __init__(self):
        self.mgr = manager

    def generate(
        self,
        file_path_or_id: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None,
    ) -> ProcessGraphResult:
        """Generates an evidence-grounded process graph and projections."""
        pipeline = self.mgr.get_pipeline()
        sec_ctx = self.mgr.sec_ctx()

        target_out_dir = Path(output_dir).resolve() if output_dir else None
        if target_out_dir:
            target_out_dir.mkdir(parents=True, exist_ok=True)

        dual_result: DualOutputResult = pipeline.generate_process_graph(
            sec_ctx=sec_ctx,
            file_path_or_id=file_path_or_id,
            output_dir=target_out_dir,
        )

        bpmn_xml = getattr(dual_result, "bpmn_xml", "") or render_bpmn_20_xml(dual_result.graph)
        flowchart = getattr(dual_result, "mermaid_diagram", "") or render_flowchart_mermaid(dual_result.graph)
        swimlane = render_swimlane_mermaid(dual_result.graph)
        defect_md = getattr(dual_result, "defect_markdown", "") or ""

        return ProcessGraphResult(
            process_name=dual_result.graph.process_name,
            objective=dual_result.graph.objective or "",
            activities_count=len(dual_result.graph.activities),
            gateways_count=len(dual_result.graph.gateways),
            transitions_count=len(dual_result.graph.transitions),
            actors_count=len(dual_result.graph.actors),
            defects_count=len(dual_result.defect_register.defects),
            bpmn_xml=bpmn_xml,
            flowchart_mermaid=flowchart,
            swimlane_mermaid=swimlane,
            defect_markdown=defect_md,
            total_latency_sec=round(dual_result.total_latency_sec, 2),
            output_dir=str(target_out_dir) if target_out_dir else None,
            snapshot_id=dual_result.snapshot_id,
            generation_run_id=dual_result.generation_run_id,
        )
