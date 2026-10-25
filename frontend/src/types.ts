export interface SourceSpan {
  id: string; // e.g. "S001"
  text: string;
  page?: number;
  section?: string;
  start_char?: number;
  end_char?: number;
}

export interface WorkflowNode {
  id: string;
  label: string;
  type: 'start' | 'task' | 'gateway' | 'end';
  role?: string;
  cited_spans: string[];
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  condition?: string;
  justification?: string;
  cited_spans: string[];
  status: 'VERIFIED' | 'AMBIGUOUS' | 'UNSUPPORTED';
  confidence: number;
}

export interface ProcessGraphData {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  bpmn_xml?: string;
  mermaid_code?: string;
}

export interface ExtractedField {
  key: string;
  value: any;
  type: string;
  cited_spans: string[];
  confidence: number;
  status: 'ENTAILED' | 'CONTRADICTED' | 'UNCERTAIN';
}

export interface DefectItem {
  id: string;
  type: 'MODALITY_ESCALATION' | 'NEGATIVE_RECORD_INVERSION' | 'AMBIGUOUS_TRANSITION' | 'NUMERICAL_DISCREPANCY' | 'UNGROUNDED_CLAIM';
  description: string;
  element_id: string;
  cited_spans: string[];
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  recommended_fix?: string;
}

export interface DocumentDigest {
  id: string;
  filename: string;
  file_hash: string;
  file_type: string;
  page_count: number;
  raw_tokens: number;
  clean_tokens: number;
  compression_ratio: number;
  raw_content: string;
  spans: SourceSpan[];
  process_graph: ProcessGraphData;
  extracted_schema: Record<string, ExtractedField>;
  digital_markdown: string;
  defects: DefectItem[];
}

export interface InquisitorVerification {
  hypothesis: string;
  verdict: 'ENTAILED' | 'CONTRADICTED' | 'UNCERTAIN';
  confidence: number;
  justification: string;
  cited_spans: string[];
}
