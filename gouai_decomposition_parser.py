# gouai_decomposition_parser.py
import re
from typing import Dict, List, Any, Optional, Tuple

# --- Pre-compiled Regular Expressions ---
# Using (?m) for re.MULTILINE to have ^ and $ match start/end of each line.
# Using re.IGNORECASE for headers might be too lenient; let's assume case sensitivity for now,
# as the LLM will be instructed on the exact case.
RE_H1_PARENT_ANALYSIS = re.compile(r"^#\s*PARENT TASK ANALYSIS\s*$", re.MULTILINE)
RE_H2_PARENT_HLG = re.compile(r"^##\s*PARENT_HLG\s*$", re.MULTILINE)
RE_H2_PARENT_WSOD = re.compile(r"^##\s*PARENT_WSOD\s*$", re.MULTILINE)

RE_H1_PROPOSED_SUBTASKS = re.compile(r"^#\s*PROPOSED SUB-TASKS\s*$", re.MULTILINE)
RE_H2_SUB_TASK_BLOCK = re.compile(r"^##\s*SUB-TASK.*$", re.MULTILINE)

RE_H3_SUB_TASK_HLG = re.compile(r"^###\s*HLG\s*$", re.MULTILINE)
RE_H3_SUB_TASK_EUS = re.compile(r"^###\s*EPISTEMIC_UNCERTAINTIES\s*$", re.MULTILINE)
RE_H3_SUB_TASK_KIRQS = re.compile(r"^###\s*KEY_INFORMATION_REQUIREMENTS\s*$", re.MULTILINE)

# General regex to find any H1, H2, or H3, to help delimit sections.
RE_ANY_H1_H2_H3_HEADER = re.compile(r"^(?:#{1,3})\s+.*$", re.MULTILINE)
RE_ANY_H2_HEADER = re.compile(r"^(?:#{2})\s+.*$", re.MULTILINE)
RE_ANY_H3_HEADER = re.compile(r"^(?:#{3})\s+.*$", re.MULTILINE)

RE_BULLET_ITEM = re.compile(r"^\s*[-*+]\s+(.*)$", re.MULTILINE)

class DecompositionParsingError(Exception):
    """Custom exception for errors during decomposition document parsing."""
    pass

def _extract_content_between_delimiters(
    text_block: str,
    start_delimiter_re: re.Pattern,
    end_delimiter_res: List[re.Pattern]
) -> Optional[str]:
    """
    Extracts text content found after start_delimiter_re and before the earliest
    occurrence of any regex in end_delimiter_res within the given text_block.
    If start_delimiter_re is not found, returns None.
    If no end_delimiter_res match, extracts till the end of text_block.
    """
    match_start = start_delimiter_re.search(text_block)
    if not match_start:
        return None

    content_start_pos = match_start.end()
    content_end_pos = len(text_block) # Default to end of text_block

    for end_re in end_delimiter_res:
        match_end = end_re.search(text_block, pos=content_start_pos)
        if match_end:
            content_end_pos = min(content_end_pos, match_end.start())
            
    return text_block[content_start_pos:content_end_pos].strip()

def _parse_bullet_list_from_text(text_block: Optional[str]) -> List[str]:
    """Parses a block of text and extracts non-empty bullet list items."""
    if not text_block:
        return []
    items = RE_BULLET_ITEM.findall(text_block)
    return [item.strip() for item in items if item.strip()]

def parse_decomposition_document(doc_content: str) -> Dict[str, Any]:
    """
    Parses the Markdown "Decomposition Document" into a structured dictionary.

    Args:
        doc_content: The full Markdown content of the decomposition document.

    Returns:
        A dictionary:
        {
            "parent_task_details": {"hlg": "...", "wsod": "..."},
            "sub_tasks": [
                {"temp_id": 0, "hlg": "...", "eus": [...], "kirqs": [...]}, ...
            ]
        }
    Raises:
        DecompositionParsingError: If essential sections are missing or misformatted.
    """
    output: Dict[str, Any] = {
        "parent_task_details": {},
        "sub_tasks": []
    }

    # --- 1. Parse Parent Task Analysis ---
    parent_analysis_match = RE_H1_PARENT_ANALYSIS.search(doc_content)
    if not parent_analysis_match:
        raise DecompositionParsingError("Mandatory section '# PARENT TASK ANALYSIS' not found.")
    
    # Define the scope for parent analysis: from its header to the next H1 (e.g., # PROPOSED SUB-TASKS) or EOF
    parent_analysis_start_pos = parent_analysis_match.end()
    next_h1_after_parent_analysis = RE_H1_PROPOSED_SUBTASKS.search(doc_content, pos=parent_analysis_start_pos)
    parent_analysis_end_pos = next_h1_after_parent_analysis.start() if next_h1_after_parent_analysis else len(doc_content)
    parent_analysis_block = doc_content[parent_analysis_start_pos:parent_analysis_end_pos]

    parent_hlg = _extract_content_between_delimiters(parent_analysis_block, RE_H2_PARENT_HLG, [RE_H2_PARENT_WSOD, RE_ANY_H2_HEADER])
    if parent_hlg is None:
        raise DecompositionParsingError("Mandatory section '## PARENT_HLG' not found within '# PARENT TASK ANALYSIS'.")
    output["parent_task_details"]["hlg"] = parent_hlg

    parent_wsod = _extract_content_between_delimiters(parent_analysis_block, RE_H2_PARENT_WSOD, [RE_ANY_H2_HEADER]) # Ends at next H2 or end of block
    if parent_wsod is None:
        raise DecompositionParsingError("Mandatory section '## PARENT_WSOD' not found within '# PARENT TASK ANALYSIS'.")
    output["parent_task_details"]["wsod"] = parent_wsod

    # --- 2. Parse Proposed Sub-Tasks ---
    subtasks_section_match = RE_H1_PROPOSED_SUBTASKS.search(doc_content, pos=parent_analysis_start_pos) # Search after parent analysis
    if not subtasks_section_match:
        # If this section is optional (e.g., a decomposition might yield no sub-tasks),
        # then we can return here with an empty sub_tasks list.
        # For now, let's assume if the section is missing, it's an issue or means no sub-tasks.
        # However, the schema implies it should be present if sub-tasks are proposed.
        # If the document can be valid without this section, this check needs adjustment.
        # Let's make it mandatory as per the defined schema from KIRQ2.1.
        raise DecompositionParsingError("Mandatory section '# PROPOSED SUB-TASKS' not found.")

    # Content from "PROPOSED SUB-TASKS" header to the end of the document (or next major H1 if any)
    subtasks_overall_block_start = subtasks_section_match.end()
    # Assuming no other H1 follows PROPOSED SUB-TASKS in this document type.
    subtasks_overall_block = doc_content[subtasks_overall_block_start:]

    current_pos_in_subtasks_block = 0
    sub_task_idx = 0
    while True:
        # Find the start of the next "## SUB-TASK" block
        sub_task_block_match = RE_H2_SUB_TASK_BLOCK.search(subtasks_overall_block, pos=current_pos_in_subtasks_block)
        if not sub_task_block_match:
            break # No more "## SUB-TASK" headers found

        # Determine the content of this specific sub-task block
        current_sub_task_content_start = sub_task_block_match.end()
        
        # Find the start of the *next* "## SUB-TASK" to delimit the current one
        next_sub_task_block_match = RE_H2_SUB_TASK_BLOCK.search(subtasks_overall_block, pos=current_sub_task_content_start)
        
        if next_sub_task_block_match:
            current_sub_task_content_end = next_sub_task_block_match.start()
        else:
            current_sub_task_content_end = len(subtasks_overall_block) # Goes to the end of the subtasks_overall_block
            
        sub_task_text_block = subtasks_overall_block[current_sub_task_content_start:current_sub_task_content_end]

        # Parse HLG, EUs, KIRQs from this sub_task_text_block
        sub_task_hlg = _extract_content_between_delimiters(sub_task_text_block, RE_H3_SUB_TASK_HLG, [RE_H3_SUB_TASK_EUS, RE_H3_SUB_TASK_KIRQS, RE_ANY_H3_HEADER])
        if sub_task_hlg is None:
            raise DecompositionParsingError(f"Sub-task (index {sub_task_idx}): Missing '### HLG' section.")

        sub_task_eus_text = _extract_content_between_delimiters(sub_task_text_block, RE_H3_SUB_TASK_EUS, [RE_H3_SUB_TASK_KIRQS, RE_ANY_H3_HEADER])
        sub_task_eus_list = _parse_bullet_list_from_text(sub_task_eus_text)
        # It's okay if EUs/KIRQs lists are empty, but the section headers should be there.
        if sub_task_eus_text is None: # Check if header itself was missing
             raise DecompositionParsingError(f"Sub-task (index {sub_task_idx}): Missing '### EPISTEMIC_UNCERTAINTIES' section header.")


        sub_task_kirqs_text = _extract_content_between_delimiters(sub_task_text_block, RE_H3_SUB_TASK_KIRQS, [RE_ANY_H3_HEADER]) # Ends at next H3 or end of sub-task block
        sub_task_kirqs_list = _parse_bullet_list_from_text(sub_task_kirqs_text)
        if sub_task_kirqs_text is None: # Check if header itself was missing
            raise DecompositionParsingError(f"Sub-task (index {sub_task_idx}): Missing '### KEY_INFORMATION_REQUIREMENTS' section header.")

        output["sub_tasks"].append({
            "temp_id": sub_task_idx,
            "hlg": sub_task_hlg,
            "eus": sub_task_eus_list,
            "kirqs": sub_task_kirqs_list
        })

        sub_task_idx += 1
        current_pos_in_subtasks_block = current_sub_task_content_end # Move to the end of the processed block

    # If "# PROPOSED SUB-TASKS" was found but no "## SUB-TASK" blocks, output["sub_tasks"] will be empty.
    # This is acceptable based on the logic allowing zero sub-tasks if the main header exists.
    return output

if __name__ == '__main__':
    # Path to your sample decomposition document
    sample_file_path = "./projects/TestProj1/decomposition_output.md" # Adjust path if needed

    print(f"Attempting to parse: {sample_file_path}")
    try:
        with open(sample_file_path, 'r', encoding='utf-8') as f:
            doc_content = f.read()

        parsed_data = parse_decomposition_document(doc_content)

        # Pretty print the JSON output for verification
        import json
        print("\n--- Parsed Output ---")
        print(json.dumps(parsed_data, indent=2))
        print("\n--- Parsing Successful ---")

    except FileNotFoundError:
        print(f"ERROR: Sample file not found at '{sample_file_path}'")
    except DecompositionParsingError as e:
        print(f"PARSING ERROR: {e}")
    except Exception as e:
        print(f"UNEXPECTED ERROR during test: {type(e).__name__} - {e}")
        import traceback
        traceback.print_exc()