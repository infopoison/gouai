#!/usr/bin/env python3
# gouai_context_handler.py

import argparse
from pathlib import Path
import sys
import yaml # For task_definition.md frontmatter
from datetime import datetime
import re
import os # For path operations and reading file content

# --- GOUAI Module Imports ---
# Note: The LLM1-related imports from gouai_llm_api (generate_response_aggregated for packaging) are no longer needed here.
# We only need find_task_dir_path_from_id.
# The `gouai chat` command will handle calls to `gouai_llm_api.py` for LLM2 interaction.

try:
    from gouai_task_mgmt import find_task_dir_path_from_id, FULL_GOUAI_TASK_TYPE, SIMPLE_TASK_TYPE # Import task types
except ImportError as e:
    print("CRITICAL ERROR: gouai_task_mgmt.py or one of its dependencies could not be imported.", file=sys.stderr)
    print(f"--- Specific Import Error Details ---", file=sys.stderr)
    print(f"{type(e).__name__}: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    print(f"--- End of Traceback ---", file=sys.stderr)
    # Dummy implementation for find_task_dir_path_from_id if import fails
    def find_task_dir_path_from_id(current_search_path: Path, target_task_id: str, project_root_path: Path) -> Path | None:
        print("Warning: Using DUMMY find_task_dir_path_from_id from gouai_context_handler.py", file=sys.stderr)
        if project_root_path and project_root_path.is_dir():
            parts = target_task_id.split('_')
            potential_dir_name = parts[-1] if parts else target_task_id
            dummy_path = project_root_path / potential_dir_name
            if dummy_path.is_dir() and (dummy_path / "task_definition.md").exists():
                return dummy_path
            if project_root_path.name == target_task_id.replace("_ROOT", "") and (project_root_path / "task_definition.md").exists():
                return project_root_path
        return None
    FULL_GOUAI_TASK_TYPE = "full_GOUAI_task" # Define if import fails
    SIMPLE_TASK_TYPE = "simple_task"         # Define if import fails
    # sys.exit(1) # In a real scenario, exit

# --- Constants ---

DIRECT_LLM2_PRIMING_INSTRUCTION_TEMPLATE_V1_0 = """
You are an expert AI assistant (LLM2) operating within the GOUAI (Goal-Oriented Uncertainty-Aware LLM Interaction) protocol.
The user requires your assistance with GOUAI Task ID: `[TASK_ID_PLACEHOLDER]`.

**Task Type:** `[TASK_TYPE_PLACEHOLDER]`
**HLG Summary:** `[HLG_SUMMARY_PLACEHOLDER]`
**WSOD Summary:** `[WSOD_SUMMARY_PLACEHOLDER]`
**Current Status:** `[STATUS_PLACEHOLDER]`
**Parent Task ID (if applicable):** `[PARENT_TASK_ID_PLACEHOLDER]`

Your primary objective is to engage in a dialog with the user to help them achieve the task's High-Level Goal (HLG). This typically involves:
- Clarifying any ambiguities in the task's HLG or Workable Stated Output Descriptor (WSOD).
- Identifying and helping to resolve Epistemic Uncertainties (EUs).
- Gathering necessary Key Information Requirements (KIRQs).
- Assisting in the generation of the task's desired output (e.g., code, documentation, analysis, specifications).
- Ultimately, helping the user compile the necessary information into an output document or achieve the task's defined outcome.

Review the comprehensive context provided below, which includes details from the task's `task_definition.md`, `living_document.md` (if available), and any relevant files from `context_packages/`.

After reviewing the context, please:
1. Briefly confirm your understanding of the task's main HLG.
2. Ask the user how you can best assist them with their immediate objective for this task, or suggest 1-2 initial actionable steps you can take together to move the task forward.

--- START OF GOUAI TASK CONTEXT DUMP ---

**TASK ID:** `[TASK_ID_PLACEHOLDER]`

**1. From `task_definition.md`:**
   - **Task Type:** `[TASK_TYPE_PLACEHOLDER]`
   - **HLG Summary:** `[HLG_SUMMARY_PLACEHOLDER]`
   - **WSOD Summary:** `[WSOD_SUMMARY_PLACEHOLDER]`
   - **Status:** `[STATUS_PLACEHOLDER]`
   - **Parent Task ID:** `[PARENT_TASK_ID_PLACEHOLDER]`
   - **Full HLG / Description Text (may include initial EUs/KIRQs from decomposition):**
     ```
[TASK_HLG_FULL_TEXT_PLACEHOLDER]
     ```
   - **WSOD Assessment (Initial) (for Full GOUAI Tasks):**
     ```
[WSOD_ASSESSMENT_PLACEHOLDER]
     ```
   - **IE Uncertainty Overview (Phase 2) (for Full GOUAI Tasks):**
     ```
[IE_UNCERTAINTY_PLACEHOLDER]
     ```

**2. From `living_document.md` (if available and relevant):**
   - **Key Questions or Uncertainties (User's current focus):**
     ```
[LIVING_DOC_QUESTIONS_PLACEHOLDER]
     ```
   - **Recent Chronological Log Entries (approx. last few):**
     ```
[LIVING_DOC_LOG_PLACEHOLDER]
     ```

**3. From `context_packages/` (if available and relevant):**
   **Text-Based Context Files:**
[FILES_CONTEXT_STR_PLACEHOLDER]

   **Non-Text Context Files Referenced:**
[NON_TEXT_FILES_LIST_PLACEHOLDER]

--- END OF GOUAI TASK CONTEXT DUMP ---
"""

LIVING_DOC_LOG_LINES_TO_EXTRACT = 15 # Reduced for conciseness in direct dump

def _debug_print(*args):
    print("DEBUG_CONTEXT_HANDLER:", *args, file=sys.stderr, flush=True)

def _extract_yaml_frontmatter(file_path: Path) -> dict:
    _debug_print(f"_extract_yaml_frontmatter: Attempting to read {file_path}")
    try:
        if not file_path.is_file():
            _debug_print(f"_extract_yaml_frontmatter: File not found at {file_path}")
            return {}
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        _debug_print(f"_extract_yaml_frontmatter: Read {len(content)} chars from {file_path}")

        # Remove potential BOM and leading whitespace
        if content.startswith('\ufeff'):
            content = content[1:]
            _debug_print("_extract_yaml_frontmatter: Removed BOM")
        content_stripped = content.lstrip()
        
        if not content_stripped.startswith("---"):
            _debug_print(f"_extract_yaml_frontmatter: No '---' at the start of stripped content for {file_path}")
            return {}
        _debug_print(f"_extract_yaml_frontmatter: Found '---' at start of stripped content for {file_path}")

        parts = content_stripped.split("---", 2)
        _debug_print(f"_extract_yaml_frontmatter: Split into {len(parts)} parts for {file_path}")

        if len(parts) >= 3: 
            frontmatter_str = parts[1]
            _debug_print(f"_extract_yaml_frontmatter: Extracted frontmatter_str (first 100 chars): '{frontmatter_str.strip()[:100]}...' for {file_path}")
            
            if not frontmatter_str.strip():
                _debug_print(f"_extract_yaml_frontmatter: Extracted frontmatter string is EMPTY for {file_path}")
                return {}

            try:
                loaded_yaml = yaml.safe_load(frontmatter_str)
                _debug_print(f"_extract_yaml_frontmatter: yaml.safe_load result type: {type(loaded_yaml)} for {file_path}")
                if isinstance(loaded_yaml, dict):
                    _debug_print(f"_extract_yaml_frontmatter: Successfully parsed YAML dict with keys: {list(loaded_yaml.keys())} from {file_path}")
                    return loaded_yaml
                else:
                    _debug_print(f"_extract_yaml_frontmatter: YAML in {file_path} did not parse as a dictionary. Parsed type: {type(loaded_yaml)}")
                    return {}
            except yaml.YAMLError as e:
                _debug_print(f"_extract_yaml_frontmatter: YAML PARSING ERROR in {file_path}. Error: {e}")
                _debug_print(f"                         Problematic frontmatter string snippet:\n---\n{frontmatter_str.strip()[:300]}\n---")
                return {}
        else:
            _debug_print(f"_extract_yaml_frontmatter: Not enough '---' delimiters found (expected 3 parts from split). Parts found: {len(parts)} for {file_path}")
            return {}

    except FileNotFoundError: # Should be redundant due to is_file() check above, but good practice
        _debug_print(f"_extract_yaml_frontmatter: FileNotFoundError (should have been caught by is_file): {file_path}")
        return {}
    except Exception as e:
        _debug_print(f"_extract_yaml_frontmatter: UNEXPECTED ERROR extracting frontmatter from {file_path}: {type(e).__name__} - {e}")
    return {}


def _extract_md_section_content(file_path: Path, section_heading_text: str, exact_heading_level: str = "##") -> str:
    _debug_print(f"_extract_md_section_content: Reading section '{section_heading_text}' from {file_path} (level: {exact_heading_level})")
    content_lines = []
    try:
        if not file_path.is_file():
            _debug_print(f"_extract_md_section_content: File not found: {file_path}")
            return ""
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        in_section = False
        normalized_heading_text = section_heading_text.strip()
        start_re = re.compile(rf"^{re.escape(exact_heading_level)}\s*{re.escape(normalized_heading_text)}\s*$", re.IGNORECASE)
        
        level_num = len(exact_heading_level)
        higher_or_same_markers = [f"^{re.escape('#'*i)}\\s+" for i in range(1, level_num + 1)]
        end_re = re.compile(r"^(?:" + "|".join(higher_or_same_markers) + r")")

        for i, line_text in enumerate(lines):
            stripped_line_text = line_text.strip()
            if not in_section:
                if start_re.match(stripped_line_text):
                    in_section = True
                    _debug_print(f"_extract_md_section_content: Found start of section '{section_heading_text}' at line {i+1}")
                    continue
            if in_section:
                is_another_target_start = start_re.match(stripped_line_text)
                is_different_terminating_header = end_re.match(line_text) and not is_another_target_start

                if is_another_target_start and content_lines: # Stop if same heading re-appears and we have content
                    _debug_print(f"_extract_md_section_content: Found another start of '{section_heading_text}' at line {i+1}, stopping previous section.")
                    break
                if is_different_terminating_header:
                    _debug_print(f"_extract_md_section_content: Found terminating header at line {i+1}, stopping section '{section_heading_text}'.")
                    break
                content_lines.append(line_text)
        
        final_content = "".join(content_lines).strip()
        _debug_print(f"_extract_md_section_content: Extracted for '{section_heading_text}' (len {len(final_content)}): '{final_content[:100]}...'")
        return final_content
    except Exception as e:
        _debug_print(f"_extract_md_section_content: UNEXPECTED ERROR extracting section '{section_heading_text}' from {file_path}: {type(e).__name__} - {e}")
    return "".join(content_lines).strip()


def _get_task_hlg_full_text(task_def_path: Path, task_type: str) -> str:
    _debug_print(f"_get_task_hlg_full_text: task_type='{task_type}' for path {task_def_path}")
    if task_type == SIMPLE_TASK_TYPE:
        return _extract_md_section_content(task_def_path, "Task Description", exact_heading_level="##")
    return _extract_md_section_content(task_def_path, "High-Level Goal(s) (HLG)", exact_heading_level="##")


def _parse_task_definition_md(task_def_path: Path) -> dict:
    _debug_print(f"_parse_task_definition_md: Called with path: {task_def_path}")
    if not task_def_path.is_file():
        _debug_print(f"_parse_task_definition_md: File NOT FOUND at {task_def_path}")
        return {"error": f"task_definition.md not found at {task_def_path}", "task_type": "ERROR_NO_FILE"}

    _debug_print(f"_parse_task_definition_md: File FOUND. Attempting to extract frontmatter.")
    frontmatter = _extract_yaml_frontmatter(task_def_path)
    _debug_print(f"_parse_task_definition_md: Extracted frontmatter: {frontmatter}")

    data = {}
    data['task_type'] = frontmatter.get('task_type', FULL_GOUAI_TASK_TYPE) # Default to full if not found
    data['hlg_summary'] = frontmatter.get('HLG_summary', frontmatter.get('one_line_description', "Default HLG Summary - Not in YAML"))
    data['wsod_summary'] = frontmatter.get('WSOD_summary', "Default WSOD Summary - Not in YAML" if data['task_type'] != SIMPLE_TASK_TYPE else "N/A for Simple Task")
    data['status'] = frontmatter.get('status', "Default Status - Not in YAML")
    data['parent_task_id'] = frontmatter.get('parent_task_id', "Default Parent ID - Not in YAML") # Keep as string
    
    _debug_print(f"_parse_task_definition_md: Parsed from YAML - task_type='{data['task_type']}', hlg_summary='{data['hlg_summary']}', parent_task_id='{data['parent_task_id']}'")

    data['task_hlg_full_text'] = _get_task_hlg_full_text(task_def_path, data['task_type'])
    if not data['task_hlg_full_text'] and data['hlg_summary'] != "Default HLG Summary - Not in YAML":
        data['task_hlg_full_text'] = data['hlg_summary'] # Fallback if section empty but summary exists
    _debug_print(f"_parse_task_definition_md: task_hlg_full_text (len {len(data['task_hlg_full_text'])}): '{data['task_hlg_full_text'][:100]}...'")
    
    if data['task_type'] != SIMPLE_TASK_TYPE:
        data['wsod_assessment_initial'] = _extract_md_section_content(task_def_path, "WSOD Assessment (Initial)", "##")
        data['ie_uncertainty_overview'] = _extract_md_section_content(task_def_path, "Phase 2: IE Uncertainty Overview", "##")
    else:
        data['wsod_assessment_initial'] = "N/A for Simple Task"
        data['ie_uncertainty_overview'] = "N/A for Simple Task"
    
    _debug_print(f"_parse_task_definition_md: Returning data: { {k: (v[:50] + '...' if isinstance(v, str) and len(v) > 50 else v) for k,v in data.items()} }")
    return data


def _parse_living_document_md(living_doc_path: Path) -> dict:
    _debug_print(f"_parse_living_document_md: Attempting to parse {living_doc_path}")
    data = {"key_questions_uncertainties": "Not specified (living_document.md)", "recent_chrono_log": "Not specified (living_document.md)"}
    if not living_doc_path.is_file():
        _debug_print(f"_parse_living_document_md: File not found: {living_doc_path}")
        return data

    data['key_questions_uncertainties'] = _extract_md_section_content(living_doc_path, "Key Questions or Uncertainties", "##") or "Not specified (section empty or not found)"
    chrono_log_full = _extract_md_section_content(living_doc_path, "Chronological Log of Tasking Completed (and when)", "##")
    if chrono_log_full:
        log_lines = chrono_log_full.strip().splitlines()
        data['recent_chrono_log'] = "\n".join(log_lines[-LIVING_DOC_LOG_LINES_TO_EXTRACT:])
    else:
        data['recent_chrono_log'] = "Not specified (section empty or not found)"
    _debug_print(f"_parse_living_document_md: Returning: {data}")
    return data


def _gather_context_from_files(context_packages_path: Path) -> tuple[str, str]:
    _debug_print(f"_gather_context_from_files: Scanning {context_packages_path}")
    all_text_content_parts = []
    non_text_files_paths = []
    if not context_packages_path.is_dir():
        _debug_print(f"_gather_context_from_files: Directory not found: {context_packages_path}")
        return "No `context_packages/` directory found.", "None."
    
    paths_to_scan = [context_packages_path] + [item for item in context_packages_path.iterdir() if item.is_dir()]
    
    found_text_files = False
    for scan_dir in paths_to_scan:
        _debug_print(f"_gather_context_from_files: Scanning dir {scan_dir}")
        for item_path in scan_dir.iterdir():
            if item_path.is_file():
                relative_item_path = item_path.relative_to(context_packages_path)
                _debug_print(f"_gather_context_from_files: Found file {relative_item_path}")
                if item_path.suffix.lower() in ['.txt', '.md', '.py', '.json', '.yaml', '.xml', '.csv', '.log', '.sh', '.ini', '.cfg', '.html', '.css', '.js']:
                    try:
                        content = item_path.read_text(encoding='utf-8', errors='replace')
                        all_text_content_parts.append(f"--- START File: {relative_item_path} ---\n{content.strip()}\n--- END File: {relative_item_path} ---\n")
                        found_text_files = True
                        _debug_print(f"_gather_context_from_files: Added text content from {relative_item_path}")
                    except Exception as e:
                        all_text_content_parts.append(f"--- File: {relative_item_path} ---\nError reading file: {e}\n--- END File: {relative_item_path} ---\n")
                        _debug_print(f"_gather_context_from_files: Error reading {relative_item_path}: {e}")
                else:
                    non_text_files_paths.append(str(relative_item_path))
                    _debug_print(f"_gather_context_from_files: Added non-text file {relative_item_path}")
    
    text_content_output = "\n\n".join(all_text_content_parts) if found_text_files else "No text files found in `context_packages/`."
    non_text_files_list_str_formatted = "\n".join([f"- `{p}`" for p in non_text_files_paths]) if non_text_files_paths else "None."
    
    _debug_print(f"_gather_context_from_files: Returning text content (len {len(text_content_output)}), non-text list string: '{non_text_files_list_str_formatted}'")
    return text_content_output, non_text_files_list_str_formatted


def _construct_direct_llm2_prime(
    task_id: str, 
    task_def_data: dict, 
    living_doc_data: dict, 
    files_context_str: str, 
    non_text_files_list_str_param: str # Renamed to avoid conflict with any global
    ) -> str:
    _debug_print(f"_construct_direct_llm2_prime: Building prime for task_id '{task_id}'")
    _debug_print(f"  task_def_data used: { {k: (v[:50] + '...' if isinstance(v, str) and len(v) > 50 else v) for k,v in task_def_data.items()} }")
    _debug_print(f"  living_doc_data used: {living_doc_data}")
    _debug_print(f"  files_context_str (len {len(files_context_str)}): '{files_context_str[:100]}...'")
    _debug_print(f"  non_text_files_list_str_param: '{non_text_files_list_str_param}'")

    prompt = DIRECT_LLM2_PRIMING_INSTRUCTION_TEMPLATE_V1_0

    prompt = prompt.replace("[TASK_ID_PLACEHOLDER]", task_id)
    prompt = prompt.replace("[TASK_TYPE_PLACEHOLDER]", task_def_data.get('task_type', 'ERROR_TYPE_UNSET'))
    prompt = prompt.replace("[HLG_SUMMARY_PLACEHOLDER]", task_def_data.get('hlg_summary', 'ERROR_HLG_SUM_UNSET'))
    prompt = prompt.replace("[WSOD_SUMMARY_PLACEHOLDER]", task_def_data.get('wsod_summary', 'ERROR_WSOD_SUM_UNSET'))
    prompt = prompt.replace("[STATUS_PLACEHOLDER]", task_def_data.get('status', 'ERROR_STATUS_UNSET'))
    
    parent_task_id_value = task_def_data.get('parent_task_id')
    parent_task_id_for_prompt = str(parent_task_id_value) if parent_task_id_value is not None else "N/A_IN_PRIME"
    prompt = prompt.replace("[PARENT_TASK_ID_PLACEHOLDER]", parent_task_id_for_prompt)
    
    prompt = prompt.replace("[TASK_HLG_FULL_TEXT_PLACEHOLDER]", task_def_data.get('task_hlg_full_text', 'ERROR_HLG_FULL_TEXT_UNSET'))
    prompt = prompt.replace("[WSOD_ASSESSMENT_PLACEHOLDER]", task_def_data.get('wsod_assessment_initial', 'ERROR_WSOD_ASSESS_UNSET'))
    prompt = prompt.replace("[IE_UNCERTAINTY_PLACEHOLDER]", task_def_data.get('ie_uncertainty_overview', 'ERROR_IE_UNCERT_UNSET'))
    
    prompt = prompt.replace("[LIVING_DOC_QUESTIONS_PLACEHOLDER]", living_doc_data.get('key_questions_uncertainties', 'ERROR_LD_QUEST_UNSET'))
    prompt = prompt.replace("[LIVING_DOC_LOG_PLACEHOLDER]", living_doc_data.get('recent_chrono_log', 'ERROR_LD_LOG_UNSET'))
    
    prompt = prompt.replace("[FILES_CONTEXT_STR_PLACEHOLDER]", files_context_str if files_context_str.strip() else "No text-based context files provided or found.")
    
    non_text_files_display_value = "None."
    if isinstance(non_text_files_list_str_param, list): # Should be string from _gather_context_from_files now
        if non_text_files_list_str_param: 
            non_text_files_display_value = "\n".join([f"- `{p}`" for p in non_text_files_list_str_param])
    elif isinstance(non_text_files_list_str_param, str):
        if non_text_files_list_str_param.strip() and non_text_files_list_str_param.lower() != "none.":
            non_text_files_display_value = non_text_files_list_str_param
    prompt = prompt.replace("[NON_TEXT_FILES_LIST_PLACEHOLDER]", non_text_files_display_value)
    
    _debug_print(f"_construct_direct_llm2_prime: Final prompt (first 300 chars): '{prompt[:300]}...'")
    return prompt

# --- Main Execution ---
def main():
    parser = argparse.ArgumentParser(description="GOUAI Context Handler (DEBUG VERSION)")
    parser.add_argument("--task_id", required=True, help="Target GOUAI task ID.")
    parser.add_argument("--project_root", required=True, help="GOUAI project root path.")
    args = parser.parse_args()

    _debug_print(f"main: Script started. task_id='{args.task_id}', project_root='{args.project_root}'")

    project_root_path = Path(args.project_root).resolve()
    if not project_root_path.is_dir():
        _debug_print(f"main: ERROR - Project root path '{project_root_path}' not found or not a directory.")
        # Print to stdout as well for gouai.py to capture if it expects stdout
        print(f"Error: Project root path '{project_root_path}' does not exist or is not a directory.", file=sys.stdout)
        sys.exit(1)

    task_id = args.task_id
    task_dir_path = find_task_dir_path_from_id(project_root_path, task_id, project_root_path)
    
    _debug_print(f"main: find_task_dir_path_from_id for '{task_id}' returned: {task_dir_path}")
    if task_dir_path:
        _debug_print(f"main: Resolved task_dir_path exists: {task_dir_path.exists()}")
        potential_td_path = task_dir_path / "task_definition.md"
        _debug_print(f"main: Expected task_definition.md path: {potential_td_path}")
        _debug_print(f"main: Does task_definition.md exist at this path? {potential_td_path.exists()}")
    else:
        _debug_print(f"main: task_dir_path is None. Cannot proceed.")
        print(f"Error: Could not find task directory for ID '{task_id}' (task_dir_path is None).", file=sys.stdout)
        sys.exit(1)

    if not task_dir_path.is_dir(): # Should be caught by above, but for safety
        _debug_print(f"main: ERROR - Resolved task_dir_path '{task_dir_path}' is not a directory.")
        print(f"Error: Resolved task_dir_path '{task_dir_path}' is not a directory.", file=sys.stdout)
        sys.exit(1)
    
    _debug_print(f"main: Confirmed task directory: {task_dir_path}")

    task_def_file_path = task_dir_path / "task_definition.md"
    current_task_def_data = _parse_task_definition_md(task_def_file_path)
    if current_task_def_data.get("error"): # Check if _parse_task_definition_md reported an error (e.g. file not found by it)
        _debug_print(f"main: CRITICAL Error processing task_definition.md: {current_task_def_data['error']}")
        print(f"CRITICAL Error processing task_definition.md: {current_task_def_data['error']}", file=sys.stdout)
        sys.exit(1) 
    
    living_doc_data = _parse_living_document_md(task_dir_path / "living_document.md")
    files_context_str, non_text_files_list_str = _gather_context_from_files(task_dir_path / "context_packages")
    
    priming_prompt_for_llm2 = _construct_direct_llm2_prime(
        task_id, current_task_def_data, living_doc_data,
        files_context_str, non_text_files_list_str
    )
    
    # The final output of this script is the priming prompt to stdout
    # All debug prints go to stderr.
    print(priming_prompt_for_llm2)
    
    _debug_print("main: Script finished. Priming prompt sent to stdout.")

if __name__ == "__main__":
    main()