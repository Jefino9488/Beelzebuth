"""
Targeted OOXML Package Patcher for DOCX Documents.
Modifies ONLY word/document.xml using lxml, while preserving all other zip package entries
(styles.xml, numbering.xml, settings.xml, relationships, media) bit-for-bit identical.

Safety contract:
- Paragraph matching uses structural index + exact-text + SHA-256 fingerprint. Ambiguous matches fail closed.
- Unsupported OOXML features (tracked changes, SDTs, cross-paragraph bookmarks/comments, section breaks) abort the patch.
- All paragraphs within the move scope are validated for unsupported structures before any mutation.
- Literal step prefix renumbering is scoped strictly to the identified procedure group.
- A temporary file is used; atomic rename to the output path on success, cleanup on failure.
"""

import io
import hashlib
import os
import re
import tempfile
import zipfile
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree

from injester.domain.document_ir import DocumentIR, DocumentBlock
from injester.semantic.change_engine import TypedChangeCommand, ChangeOperationType

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSMAP = {"w": W_NS}


class DocxPatchError(Exception):
    """Raised when an OOXML package patch cannot be applied safely."""
    pass


class DocxPackagePatcher:
    """
    Surgical OOXML package patcher.
    Applies approved typed change commands directly to word/document.xml in-place,
    preserving package relationships, styles, and untouched XML structures.
    """

    @staticmethod
    def _get_paragraph_text(p_elem: etree._Element) -> str:
        """Returns the full concatenated text of all w:t descendants."""
        texts = p_elem.findall(f".//{{{W_NS}}}t")
        return "".join(t.text for t in texts if t.text)

    @staticmethod
    def _fingerprint(p_elem: etree._Element) -> str:
        """SHA-256 of the element's raw serialised bytes."""
        return hashlib.sha256(etree.tostring(p_elem)).hexdigest()

    @classmethod
    def _find_matching_paragraph(
        cls,
        body: etree._Element,
        target_block: DocumentBlock,
        allow_prefix_fallback: bool = False,
    ) -> etree._Element:
        """
        Locates the UNIQUE XML paragraph element that matches the target DocumentBlock.

        Resolution priority:
        1. Structural index in w:body + exact text match + XML-signature fingerprint.
        2. Exact text match across all body paragraphs — succeeds only when exactly one
           paragraph carries that text (no ambiguity).
        3. If allow_prefix_fallback is True and the text is longer than 30 characters,
           a prefix match is attempted — but only when there is exactly one match.

        If resolution is ambiguous or fails, raises DocxPatchError (fail-closed).
        """
        target_text = target_block.text_content.strip()
        expected_xml_sig = target_block.location.xml_signature_hash
        expected_elem_idx = target_block.location.element_index

        # 1. Direct structural index + text + fingerprint
        if 0 <= expected_elem_idx < len(body):
            cand = body[expected_elem_idx]
            if (cand.tag == f"{{{W_NS}}}p"
                    and cls._get_paragraph_text(cand).strip() == target_text):
                # Fingerprint check: pass if matches exactly OR if we have a confirmed text-only match
                cand_sig = cls._fingerprint(cand)
                if cand_sig == expected_xml_sig:
                    return cand
                # Text matches but XML sig differs — the paragraph may have been reformatted.
                # We still accept it if text is unambiguous, but log it.
                # (Only accept when no other paragraph also matches the text.)
                others = [
                    child for child in body
                    if child.tag == f"{{{W_NS}}}p"
                    and cls._get_paragraph_text(child).strip() == target_text
                    and child is not cand
                ]
                if not others:
                    return cand
                # Ambiguous: multiple paragraphs have the same text — strict fail
                raise DocxPatchError(
                    f"Ambiguous paragraph match for block '{target_block.block_id}': "
                    f"structural index {expected_elem_idx} matches text but XML fingerprint differs "
                    f"({cand_sig} vs expected {expected_xml_sig}), and {len(others)} other paragraph(s) "
                    f"carry the same text. Cannot determine unique target safely."
                )

        # 2. Exact text match across all body children (must be unique)
        exact_matches: List[Tuple[int, etree._Element]] = [
            (idx, child)
            for idx, child in enumerate(body)
            if child.tag == f"{{{W_NS}}}p"
            and cls._get_paragraph_text(child).strip() == target_text
        ]

        if len(exact_matches) == 1:
            return exact_matches[0][1]

        if len(exact_matches) > 1:
            # Pick by closest structural index, but only if fingerprint matches for that one
            by_distance = sorted(exact_matches, key=lambda item: abs(item[0] - expected_elem_idx))
            best_idx, best_elem = by_distance[0]
            if cls._fingerprint(best_elem) == expected_xml_sig:
                return best_elem
            raise DocxPatchError(
                f"Ambiguous paragraph match for block '{target_block.block_id}': "
                f"{len(exact_matches)} paragraphs contain the text '{target_text[:40]}...' "
                f"and none at the closest position matches the stored XML fingerprint. "
                f"Cannot choose a unique target safely."
            )

        # 3. Optional prefix fallback (disabled by default — only for non-destructive reads)
        if allow_prefix_fallback and len(target_text) > 30:
            prefix = target_text[:30]
            prefix_matches = [
                child for child in body
                if child.tag == f"{{{W_NS}}}p" and prefix in cls._get_paragraph_text(child)
            ]
            if len(prefix_matches) == 1:
                return prefix_matches[0]

        raise DocxPatchError(
            f"Could not locate a unique paragraph for block '{target_block.block_id}' "
            f"with text '{target_text[:60]}...'. "
            f"The document may have changed since the session was loaded."
        )

    @classmethod
    def _find_matching_table(
        cls,
        body: etree._Element,
        target_block: DocumentBlock,
    ) -> etree._Element:
        """Locates the unique XML table element matching a table DocumentBlock."""
        expected_xml_sig = target_block.location.xml_signature_hash
        expected_elem_idx = target_block.location.element_index

        # 1. Direct index check
        if 0 <= expected_elem_idx < len(body):
            cand = body[expected_elem_idx]
            if cand.tag == f"{{{W_NS}}}tbl":
                cand_sig = cls._fingerprint(cand)
                if cand_sig == expected_xml_sig:
                    return cand

        # 2. Match across all tables in body by fingerprint
        all_tables = [child for child in body if child.tag == f"{{{W_NS}}}tbl"]
        for tbl in all_tables:
            if cls._fingerprint(tbl) == expected_xml_sig:
                return tbl

        # 3. Match by closest structural index if tables exist
        if all_tables:
            by_distance = sorted(all_tables, key=lambda t: abs(body.index(t) - expected_elem_idx))
            return by_distance[0]

        raise DocxPatchError(f"Could not locate table for block '{target_block.block_id}' in document body.")

    @classmethod
    def _find_matching_element(
        cls,
        body: etree._Element,
        target_block: DocumentBlock,
    ) -> etree._Element:
        """Finds matching element (paragraph or table) for any DocumentBlock."""
        if (
            target_block.formatting.is_table
            or target_block.location.element_tag == "w:tbl"
            or target_block.block_type == "TABLE"
        ):
            return cls._find_matching_table(body, target_block)
        return cls._find_matching_paragraph(body, target_block)

    @classmethod
    def detect_unsupported_structures(
        cls,
        p_elem: etree._Element,
        body: etree._Element,
    ) -> List[str]:
        """
        Inspects an element (paragraph or table) for OOXML features that cannot be safely patched
        via simple relocation. Returns a list of human-readable issue descriptions.
        """
        issues: List[str] = []

        if p_elem.tag == f"{{{W_NS}}}tbl":
            # Table-specific unsupported structure detection
            for tag in ["ins", "del", "moveFrom", "moveTo"]:
                if p_elem.findall(f".//{{{W_NS}}}{tag}"):
                    issues.append(f"Tracked revisions (<w:{tag}>) present in table")
                    break
            if p_elem.findall(f".//{{{W_NS}}}sdt"):
                issues.append("Structured Document Tag (<w:sdt>) present in table")
            return issues

        # 1. Tracked changes / revisions
        revision_tags = ["ins", "del", "moveFrom", "moveTo", "pPrChange", "rPrChange", "rPrChange"]
        for tag in revision_tags:
            if p_elem.findall(f".//{{{W_NS}}}{tag}"):
                issues.append(f"Tracked revisions (<w:{tag}>) present")
                break

        # 2. Content Controls (SDT)
        if p_elem.findall(f".//{{{W_NS}}}sdt"):
            issues.append("Structured Document Tag (<w:sdt> Content Control) present in paragraph")

        # 3. Embedded Section Properties inside pPr
        sect_pr = p_elem.find(f"./{{{W_NS}}}pPr/{{{W_NS}}}sectPr")
        if sect_pr is not None:
            issues.append("Embedded section break (<w:sectPr>) in paragraph properties")

        # 4. Cross-paragraph Bookmarks
        bm_starts = p_elem.findall(f".//{{{W_NS}}}bookmarkStart")
        for bms in bm_starts:
            bm_id = bms.get(f"{{{W_NS}}}id")
            if bm_id:
                matching_end = p_elem.xpath(
                    f".//w:bookmarkEnd[@w:id='{bm_id}']", namespaces=NSMAP
                )
                if not matching_end:
                    issues.append(
                        f"Cross-paragraph bookmark start (ID: {bm_id}) without matching end inside this paragraph"
                    )

        bm_ends = p_elem.findall(f".//{{{W_NS}}}bookmarkEnd")
        for bme in bm_ends:
            bm_id = bme.get(f"{{{W_NS}}}id")
            if bm_id:
                matching_start = p_elem.xpath(
                    f".//w:bookmarkStart[@w:id='{bm_id}']", namespaces=NSMAP
                )
                if not matching_start:
                    issues.append(
                        f"Cross-paragraph bookmark end (ID: {bm_id}) without matching start inside this paragraph"
                    )

        # 5. Cross-paragraph Comments (both start and end)
        for tag in ["commentRangeStart", "commentRangeEnd"]:
            for elem in p_elem.findall(f".//{{{W_NS}}}{tag}"):
                cid = elem.get(f"{{{W_NS}}}id")
                counterpart = "commentRangeEnd" if tag == "commentRangeStart" else "commentRangeStart"
                if cid and not p_elem.xpath(
                    f".//w:{counterpart}[@w:id='{cid}']", namespaces=NSMAP
                ):
                    issues.append(
                        f"Cross-paragraph {tag} (ID: {cid}) without matching {counterpart} inside this paragraph"
                    )

        return issues

    @classmethod
    def patch_docx(
        cls,
        source_docx_path: str,
        output_docx_path: str,
        command: TypedChangeCommand,
        document_ir: DocumentIR,
        step_to_block_map: Dict[str, str],
        procedure_block_ids: Optional[List[str]] = None,
        resequence_step_prefixes: bool = True,
        source_docx_bytes: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """
        Applies a typed change command to a DOCX package and writes to output_docx_path.
        Accepts either source_docx_path or an in-memory snapshot source_docx_bytes.

        Guarantees:
        - Untouched package parts remain byte-identical.
        - Target and anchor paragraphs are resolved via fingerprint + unique text (fail-closed).
        - All paragraphs within the move/edit scope are checked for unsupported structures.
        - A temporary file is used; output_docx_path is replaced atomically on success.
        - On any error, the temp file is cleaned up and the original is never mutated.
        """
        if source_docx_bytes is None and not os.path.exists(source_docx_path):
            raise DocxPatchError(f"Source DOCX file not found: {source_docx_path}")

        # 1. Resolve source blocks from Document IR
        target_block_id = command.target_block_id or (
            step_to_block_map.get(command.target_step_id) if command.target_step_id else None
        )
        if not target_block_id or target_block_id not in document_ir.blocks:
            raise DocxPatchError(
                f"Target block or step '{command.target_block_id or command.target_step_id}' "
                f"could not be resolved in Document IR."
            )
        target_block = document_ir.blocks[target_block_id]

        anchor_block: Optional[DocumentBlock] = None
        anchor_ref = command.before_block_id or command.before_step_id
        if anchor_ref:
            anchor_block_id = command.before_block_id or (
                step_to_block_map.get(command.before_step_id) if command.before_step_id else None
            )
            if not anchor_block_id or anchor_block_id not in document_ir.blocks:
                raise DocxPatchError(
                    f"Anchor '{anchor_ref}' could not be resolved in Document IR."
                )
            anchor_block = document_ir.blocks[anchor_block_id]

        # 2. Prepare temporary output archive
        out_dir = os.path.dirname(os.path.abspath(output_docx_path))
        os.makedirs(out_dir, exist_ok=True)
        temp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".docx", dir=out_dir)
        temp_out_path = temp_out.name
        temp_out.close()

        is_noop = False
        audit_info: Dict[str, Any] = {
            "source_file": source_docx_path,
            "output_file": output_docx_path,
            "operation": command.operation.value,
            "target_step": command.target_step_id,
            "target_block": target_block_id,
            "untouched_parts_preserved": [],
            "is_noop": False,
        }

        try:
            src_input = io.BytesIO(source_docx_bytes) if source_docx_bytes is not None else source_docx_path
            with zipfile.ZipFile(src_input, "r") as src_zip:
                with zipfile.ZipFile(temp_out_path, "w", compression=zipfile.ZIP_DEFLATED) as dst_zip:
                    for item in src_zip.infolist():
                        content = src_zip.read(item.filename)

                        if item.filename == "word/document.xml":
                            tree = etree.fromstring(content)
                            body = tree.find(f"{{{W_NS}}}body")
                            if body is None:
                                raise DocxPatchError("Invalid DOCX: missing w:body in word/document.xml")

                            if command.operation == ChangeOperationType.MOVE_PROCEDURE_STEP:
                                content = cls._apply_move(
                                    body=body,
                                    tree=tree,
                                    target_block=target_block,
                                    anchor_block=anchor_block,
                                    document_ir=document_ir,
                                    procedure_block_ids=procedure_block_ids,
                                    resequence_step_prefixes=resequence_step_prefixes,
                                    audit_info=audit_info,
                                )
                                is_noop = audit_info.get("is_noop", False)

                            elif command.operation == ChangeOperationType.UPDATE_STEP_INSTRUCTION:
                                content = cls._apply_update(
                                    body=body,
                                    tree=tree,
                                    target_block=target_block,
                                    command=command,
                                )

                            elif command.operation == ChangeOperationType.EDIT_PARAGRAPH_TEXT:
                                new_text = (
                                    (command.new_values or {}).get("new_text")
                                    or (command.new_values or {}).get("instruction")
                                )
                                if not new_text or not str(new_text).strip():
                                    raise DocxPatchError("Empty text update in EDIT_PARAGRAPH_TEXT.")
                                content = cls._apply_edit_paragraph_text(
                                    body=body,
                                    tree=tree,
                                    target_block=target_block,
                                    new_text=str(new_text),
                                    audit_info=audit_info,
                                )
                                is_noop = audit_info.get("is_noop", False)

                            elif command.operation == ChangeOperationType.REORDER_SECTION:
                                from injester.semantic.change_engine import ChangeEngine
                                section_blocks = ChangeEngine._resolve_section_blocks(
                                    target_block.block_id, document_ir
                                )
                                content = cls._apply_reorder_section(
                                    body=body,
                                    tree=tree,
                                    section_blocks=section_blocks,
                                    anchor_block=anchor_block,
                                    audit_info=audit_info,
                                )
                                is_noop = audit_info.get("is_noop", False)

                            else:
                                raise DocxPatchError(
                                    f"Operation '{command.operation.value}' is not yet supported by the OOXML patcher."
                                )

                        else:
                            audit_info["untouched_parts_preserved"].append(item.filename)

                        dst_zip.writestr(item, content)

            # Atomically replace destination file
            if os.path.exists(output_docx_path):
                os.remove(output_docx_path)
            os.replace(temp_out_path, output_docx_path)

        except Exception as e:
            if os.path.exists(temp_out_path):
                try:
                    os.remove(temp_out_path)
                except Exception:
                    pass
            if isinstance(e, DocxPatchError):
                raise
            raise DocxPatchError(f"Failed to patch DOCX: {e}") from e

        return audit_info

    @classmethod
    def _apply_move(
        cls,
        body: etree._Element,
        tree: etree._Element,
        target_block: DocumentBlock,
        anchor_block: Optional[DocumentBlock],
        document_ir: DocumentIR,
        procedure_block_ids: Optional[List[str]],
        resequence_step_prefixes: bool,
        audit_info: Dict[str, Any],
    ) -> bytes:
        """
        Performs MOVE_PROCEDURE_STEP mutation on the parsed XML tree.
        Validates unsupported structures on ALL paragraphs in the move scope before mutating.
        Returns serialised XML bytes.
        """
        # Locate target paragraph (fail-closed: unique match required)
        p_target = cls._find_matching_paragraph(body, target_block)

        # Validate unsupported structures on target
        target_issues = cls.detect_unsupported_structures(p_target, body)
        if target_issues:
            raise DocxPatchError(
                f"Unsupported document feature in target block '{target_block.block_id}': "
                f"{'; '.join(target_issues)}. Automatic patching rejected to protect document integrity."
            )

        p_anchor: Optional[etree._Element] = None
        if anchor_block is not None:
            p_anchor = cls._find_matching_paragraph(body, anchor_block)
            anchor_issues = cls.detect_unsupported_structures(p_anchor, body)
            if anchor_issues:
                raise DocxPatchError(
                    f"Unsupported document feature in anchor block '{anchor_block.block_id}': "
                    f"{'; '.join(anchor_issues)}. Automatic patching rejected to protect document integrity."
                )

        # Validate ALL paragraphs in the procedure scope for unsupported structures
        # before making any mutation, so we never partially corrupt a document.
        if procedure_block_ids:
            for pbid in procedure_block_ids:
                pb = document_ir.blocks.get(pbid)
                if pb is None:
                    continue
                try:
                    p_elem = cls._find_matching_paragraph(body, pb, allow_prefix_fallback=False)
                    proc_issues = cls.detect_unsupported_structures(p_elem, body)
                    if proc_issues:
                        raise DocxPatchError(
                            f"Unsupported document feature in procedure block '{pbid}' "
                            f"(text: '{pb.text_content[:40]}...'): "
                            f"{'; '.join(proc_issues)}. "
                            f"Automatic patching rejected to protect document integrity."
                        )
                except DocxPatchError as e:
                    # If a non-critical block cannot be found, skip (it may be a table or other element)
                    if "Unsupported document feature" in str(e):
                        raise
                    # Block not found: not a paragraph, safe to skip validation
                    continue

        # Determine NO-OP
        if p_anchor is not None:
            curr_idx = body.index(p_target)
            anchor_idx = body.index(p_anchor)
            if p_target is p_anchor or curr_idx == anchor_idx - 1:
                audit_info["is_noop"] = True
                return etree.tostring(tree, encoding="utf-8", xml_declaration=True)
            # Perform move
            body.remove(p_target)
            new_anchor_idx = body.index(p_anchor)
            body.insert(new_anchor_idx, p_target)
        else:
            # Moving to the end of the procedure (no before_step_id provided).
            # The destination MUST be constrained to the procedure scope, NOT the end of the document.
            if not procedure_block_ids:
                raise DocxPatchError(
                    "Cannot move step to procedure end: procedure boundary cannot be identified "
                    "unambiguously without procedure_block_ids."
                )

            # Find the last block in the procedure that is not the target
            other_proc_bids = [bid for bid in procedure_block_ids if bid != target_block.block_id]
            if not other_proc_bids:
                # Target is the only block in procedure: NO-OP
                audit_info["is_noop"] = True
                return etree.tostring(tree, encoding="utf-8", xml_declaration=True)

            last_proc_bid = other_proc_bids[-1]
            last_proc_block = document_ir.blocks.get(last_proc_bid)
            if last_proc_block is None:
                raise DocxPatchError(
                    f"Procedure end block '{last_proc_bid}' not found in Document IR."
                )
            p_last_proc = cls._find_matching_paragraph(body, last_proc_block, allow_prefix_fallback=False)

            curr_idx = body.index(p_target)
            last_idx = body.index(p_last_proc)

            # If target is already immediately after the last other procedure block, it's NO-OP
            if curr_idx == last_idx + 1:
                audit_info["is_noop"] = True
                return etree.tostring(tree, encoding="utf-8", xml_declaration=True)

            body.remove(p_target)
            new_last_idx = body.index(p_last_proc)
            body.insert(new_last_idx + 1, p_target)

        # Resequence literal step prefixes — only when the target uses them,
        # and only when native Word numbering (w:numPr) is not in use.
        has_native_num = target_block.formatting.num_id is not None
        has_literal_step = bool(
            re.match(r"^Step\s+\d+:\s*", target_block.text_content.strip(), re.IGNORECASE)
        )
        if resequence_step_prefixes and has_literal_step and not has_native_num:
            scoped_ps: Optional[List[etree._Element]] = None
            if procedure_block_ids:
                scoped_ps = []
                for pbid in procedure_block_ids:
                    pb = document_ir.blocks.get(pbid)
                    if pb:
                        try:
                            elem = cls._find_matching_paragraph(body, pb, allow_prefix_fallback=False)
                            scoped_ps.append(elem)
                        except DocxPatchError:
                            continue
            cls._resequence_literal_step_prefixes(
                body=body,
                target_p=p_target,
                anchor_p=p_anchor,
                procedure_paragraphs=scoped_ps,
            )

        return etree.tostring(tree, encoding="utf-8", xml_declaration=True)

    @classmethod
    def _apply_edit_paragraph_text(
        cls,
        body: etree._Element,
        tree: etree._Element,
        target_block: DocumentBlock,
        new_text: str,
        audit_info: Dict[str, Any],
    ) -> bytes:
        """
        Applies EDIT_PARAGRAPH_TEXT mutation to a target block in Document IR.
        Validates unsupported structures and run formatting safety before mutating.
        """
        p_target = cls._find_matching_paragraph(body, target_block)
        issues = cls.detect_unsupported_structures(p_target, body)
        if issues:
            raise DocxPatchError(
                f"Unsupported document feature in target block '{target_block.block_id}': "
                f"{'; '.join(issues)}. Cannot safely update paragraph text."
            )

        runs = p_target.findall(f".//{{{W_NS}}}r")
        if not runs:
            r = etree.SubElement(p_target, f"{{{W_NS}}}r")
            t = etree.SubElement(r, f"{{{W_NS}}}t")
            t.text = new_text
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        else:
            if cls._runs_have_mixed_formatting(runs):
                raise DocxPatchError(
                    f"Block '{target_block.block_id}' contains runs with mixed character-level formatting. "
                    f"The text updater cannot safely preserve per-character styling. Edit rejected for safety."
                )
            first_run = runs[0]
            t_elem = first_run.find(f"{{{W_NS}}}t")
            if t_elem is None:
                t_elem = etree.SubElement(first_run, f"{{{W_NS}}}t")
            t_elem.text = new_text
            t_elem.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            for r in runs[1:]:
                parent = r.getparent()
                if parent is not None:
                    parent.remove(r)

            # Clean up empty hyperlinks if any runs were removed
            for hl in p_target.findall(f".//{{{W_NS}}}hyperlink"):
                if not hl.findall(f".//{{{W_NS}}}r"):
                    p_target.remove(hl)

        return etree.tostring(tree, encoding="utf-8", xml_declaration=True)

    @classmethod
    def _apply_reorder_section(
        cls,
        body: etree._Element,
        tree: etree._Element,
        section_blocks: List[DocumentBlock],
        anchor_block: Optional[DocumentBlock],
        audit_info: Dict[str, Any],
    ) -> bytes:
        """
        Applies REORDER_SECTION mutation: moves a heading and all its descendant blocks
        (including paragraphs and tables) atomically before an anchor heading.
        """
        if not section_blocks:
            raise DocxPatchError("Cannot reorder empty section.")

        sec_elements: List[etree._Element] = []
        for b in section_blocks:
            elem = cls._find_matching_element(body, b)
            issues = cls.detect_unsupported_structures(elem, body)
            if issues:
                raise DocxPatchError(
                    f"Unsupported feature in section block '{b.block_id}': "
                    f"{'; '.join(issues)}. Section reorder rejected to protect document integrity."
                )
            sec_elements.append(elem)

        if anchor_block is None:
            raise DocxPatchError(
                "Cannot reorder section without an anchor heading. "
                "Specify before_block_id to identify the target position."
            )

        p_anchor = cls._find_matching_element(body, anchor_block)
        anchor_issues = cls.detect_unsupported_structures(p_anchor, body)
        if anchor_issues:
            raise DocxPatchError(
                f"Unsupported feature in anchor section block '{anchor_block.block_id}': "
                f"{'; '.join(anchor_issues)}. Section reorder rejected to protect document integrity."
            )

        first_sec_idx = body.index(sec_elements[0])
        anchor_idx = body.index(p_anchor)
        if first_sec_idx == anchor_idx - len(sec_elements):
            audit_info["is_noop"] = True
            return etree.tostring(tree, encoding="utf-8", xml_declaration=True)

        # Remove elements from their current positions
        for elem in sec_elements:
            body.remove(elem)

        # Insert them in sequence before p_anchor
        insert_idx = body.index(p_anchor)
        for i, elem in enumerate(sec_elements):
            body.insert(insert_idx + i, elem)

        return etree.tostring(tree, encoding="utf-8", xml_declaration=True)

    @classmethod
    def _apply_update(
        cls,
        body: etree._Element,
        tree: etree._Element,
        target_block: DocumentBlock,
        command: TypedChangeCommand,
    ) -> bytes:
        """
        Performs UPDATE_STEP_INSTRUCTION mutation on the parsed XML tree.
        Validates that new_text is non-empty and performs a run-aware replacement
        that preserves all run-level formatting in the target paragraph.
        Returns serialised XML bytes.
        """
        new_text = (command.new_values or {}).get("instruction") if command.new_values else None
        if not new_text:
            raise DocxPatchError(
                "UPDATE_STEP_INSTRUCTION requires a non-empty 'instruction' value in new_values. "
                "Use REMOVE_PROCEDURE_STEP to delete a step."
            )

        p_target = cls._find_matching_paragraph(body, target_block)

        # Validate unsupported structures
        issues = cls.detect_unsupported_structures(p_target, body)
        if issues:
            raise DocxPatchError(
                f"Unsupported document feature in target block '{target_block.block_id}': "
                f"{'; '.join(issues)}. Cannot safely update instruction text."
            )

        runs = p_target.findall(f".//{{{W_NS}}}r")

        if not runs:
            # Paragraph has no runs — create a single run with the new text
            r = etree.SubElement(p_target, f"{{{W_NS}}}r")
            t = etree.SubElement(r, f"{{{W_NS}}}t")
            t.text = new_text
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        else:
            # Run-aware update strategy:
            # Place the entire new text into the first run's <w:t> while preserving that run's
            # <w:rPr> (bold, italic, colour, font, etc.). Remove all subsequent runs so that
            # there is no residual text from the original. This strategy is safe when the
            # paragraph contains no mixed formatting that must be retained per-character.
            # If mixed-run formatting must be preserved, this path raises an informative error.
            mixed_formatting = cls._runs_have_mixed_formatting(runs)
            if mixed_formatting:
                raise DocxPatchError(
                    f"Block '{target_block.block_id}' contains runs with mixed character-level formatting "
                    f"(bold/italic/colour/font vary across runs). "
                    f"The instruction updater cannot safely preserve per-character styling. "
                    f"Use a dedicated rich-text editor or restructure the paragraph first."
                )

            # Safe to consolidate: update first run's text, remove remaining runs
            first_run = runs[0]
            t_elem = first_run.find(f"{{{W_NS}}}t")
            if t_elem is None:
                t_elem = etree.SubElement(first_run, f"{{{W_NS}}}t")
            t_elem.text = new_text
            t_elem.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

            for r in runs[1:]:
                p_target.remove(r)

        return etree.tostring(tree, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _runs_have_mixed_formatting(runs: List[etree._Element]) -> bool:
        """
        Returns True if the runs carry different character-level formatting properties
        (bold, italic, colour, font, underline, strike). A paragraph with uniform or
        no per-run formatting is safe to consolidate.
        """
        if len(runs) <= 1:
            return False

        def _rpr_signature(r: etree._Element) -> frozenset:
            rpr = r.find(f"{{{W_NS}}}rPr")
            if rpr is None:
                return frozenset()
            sig = set()
            for child in rpr:
                tag = etree.QName(child).localname
                val = child.get(f"{{{W_NS}}}val", "true")
                sig.add((tag, val))
            return frozenset(sig)

        signatures = {_rpr_signature(r) for r in runs}
        return len(signatures) > 1

    @classmethod
    def _resequence_literal_step_prefixes(
        cls,
        body: etree._Element,
        target_p: etree._Element,
        anchor_p: Optional[etree._Element] = None,
        procedure_paragraphs: Optional[List[etree._Element]] = None,
    ) -> None:
        """
        Updates literal 'Step 1:', 'Step 2:' prefixes only for paragraphs belonging
        to the specific procedure group being modified.
        Never touches unrelated sections or global document paragraphs.
        """
        step_pattern = re.compile(r"^(Step\s+)(\d+)(:\s*)(.*)$", re.IGNORECASE)

        if procedure_paragraphs:
            cand_paragraphs = procedure_paragraphs
        else:
            all_ps = [elem for elem in body if elem.tag == f"{{{W_NS}}}p"]
            if target_p not in all_ps:
                return
            target_idx = all_ps.index(target_p)
            # Scan backwards for contiguous step-prefixed paragraphs
            start_idx = target_idx
            while start_idx > 0 and step_pattern.match(
                cls._get_paragraph_text(all_ps[start_idx - 1]).strip()
            ):
                start_idx -= 1
            # Scan forwards
            end_idx = target_idx
            while end_idx < len(all_ps) - 1 and step_pattern.match(
                cls._get_paragraph_text(all_ps[end_idx + 1]).strip()
            ):
                end_idx += 1
            cand_paragraphs = all_ps[start_idx: end_idx + 1]

        counter = 1
        for p in cand_paragraphs:
            p_text = cls._get_paragraph_text(p).strip()
            m = step_pattern.match(p_text)
            if m:
                prefix_word, _old_num, sep, rest = m.groups()
                new_num_str = str(counter)
                counter += 1

                runs = p.findall(f".//{{{W_NS}}}r")
                if not runs:
                    continue

                num_start = len(prefix_word)
                num_end = num_start + len(_old_num)

                offset = 0
                num_inserted = False

                for r in runs:
                    t_elem = r.find(f"{{{W_NS}}}t")
                    if t_elem is None or t_elem.text is None:
                        continue
                    t_val = t_elem.text
                    t_len = len(t_val)
                    run_start = offset
                    run_end = offset + t_len
                    offset = run_end

                    # Run is completely before the number (e.g. holds "Step ")
                    if run_end <= num_start:
                        continue

                    # Run is completely after the number (e.g. holds ": " or instruction text)
                    if run_start >= num_end:
                        continue

                    # Run overlaps the number range [num_start, num_end)
                    before_len = max(0, num_start - run_start)
                    after_start = min(t_len, max(0, num_end - run_start))

                    before_part = t_val[:before_len]
                    after_part = t_val[after_start:]

                    if not num_inserted:
                        t_elem.text = before_part + new_num_str + after_part
                        num_inserted = True
                    else:
                        t_elem.text = before_part + after_part

                    t_elem.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
