import re
from typing import Dict, Optional
from injester.sop.schemas import SOPDocument, CitationRef

class SOPAssembler:
    """
    Assembles a validated SOPDocument into clean, auditable Markdown
    with automated heading de-duplication and a granular Evidence Appendix.
    """
    def assemble_markdown(self, sop: SOPDocument, validation_report=None) -> str:
        lines = []

        # Document Header
        lines.append(f"# {sop.title}")
        lines.append("")
        lines.append("## Document Metadata & Scope")
        lines.append(f"- **Purpose:** {sop.purpose}")
        lines.append(f"- **Target Audience:** {sop.target_audience}")
        if validation_report is not None:
            if validation_report.is_valid:
                badge = f"PASS (100% Entailed, 0 Unsupported Claims, {int(validation_report.rule_coverage_score * 100)}% Rule Coverage)"
            else:
                badge = f"FAILED (Errors: {len(validation_report.errors)}, Unsupported Claims: {validation_report.unsupported_claims_count})"
        else:
            badge = "Pending Verification"
        lines.append(f"- **Auditable Verification:** {badge}")
        lines.append("")

        # Table of Contents
        lines.append("## Table of Contents")
        for idx, section in enumerate(sop.sections, 1):
            clean_anchor = section.section_title.lower().replace(" ", "-").replace(".", "")
            lines.append(f"{idx}. [{section.section_title}](#{clean_anchor})")
        lines.append(f"{len(sop.sections) + 1}. [Evidence & Citation Index](#evidence--citation-index)")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Sections with Heading De-Duplication
        for section in sop.sections:
            lines.append(f"## {section.section_title}")
            lines.append("")

            # Sanitize content: strip duplicate leading markdown headings and plain titles
            raw_content = section.content.strip()
            sanitized_content = self._sanitize_section_content(raw_content, section.section_title)
            lines.append(sanitized_content)
            lines.append("")

        lines.append("---")
        lines.append("")

        # Auditable Citation Index
        lines.append("## Citation Index")
        lines.append("")
        lines.append("> Every procedural instruction, rule, and threshold in this document is traced back to an immutable source evidence span.")
        lines.append("")

        citation_items = list(sop.citation_index.items())
        def sort_key(item):
            tag = item[0]
            num_part = ''.join(filter(str.isdigit, tag))
            return int(num_part) if num_part else 0

        citation_items.sort(key=sort_key)

        for tag, cit in citation_items:
            lines.append(f"### [{tag}]")
            lines.append("```text")
            lines.append(f"Source: {cit.source_doc}")
            if cit.location:
                lines.append(f"Location: {cit.location}")
            if cit.section:
                lines.append(f"Section: {cit.section}")
            lines.append(f"Chunk ID: {cit.chunk_id}")
            if cit.span_id:
                lines.append(f"Span ID: {cit.span_id}")
            status_indicator = "✓ ENTAILED" if cit.entailment_status == "entailed" else "⚠ UNSUPPORTED"
            lines.append(f"Factual Status: {status_indicator}")
            if cit.evidence_quote:
                lines.append(f"Evidence Span: \"{cit.evidence_quote.strip()}\"")
            lines.append("```")
            lines.append("")

        return "\n".join(lines)

    def _sanitize_section_content(self, content: str, title: str) -> str:
        """
        Strips redundant leading markdown headers or plain-text section titles from section body.
        """
        lines = content.splitlines()
        clean_title = title.strip().lower()
        title_words = re.sub(r'^\d+\.\s*', '', clean_title).strip()

        while lines:
            line_str = lines[0].strip()
            if not line_str:
                lines.pop(0)
                continue
            # Strip markdown headers: # Section Title, ## Section Title
            if line_str.startswith("#"):
                lines.pop(0)
                continue

            # Strip plain text matching section title or numbered section title
            line_lower = line_str.lower().rstrip(":")
            line_no_num = re.sub(r'^\d+\.\s*', '', line_lower).strip()
            line_no_cit = re.sub(r'\[(?:s\d{3,4}|c\d+(?:\.\d+)?)\]', '', line_no_num).strip()

            if line_lower == clean_title or line_no_num == title_words or line_no_cit == title_words:
                lines.pop(0)
                continue
            if title_words and (line_no_cit.startswith(title_words) or line_lower.startswith(clean_title)):
                if len(line_no_cit) <= len(title_words) + 5:
                    lines.pop(0)
                    continue
            break

        while lines and not lines[0].strip():
            lines.pop(0)
        return "\n".join(lines).strip()
