#!/usr/bin/env python3
# gouai_compose_wsod.py

import argparse
from pathlib import Path
import sys
import re
import datetime
import os # For path joining if needed, though pathlib is preferred

# --- GOUAI Module Imports ---
try:
    from gouai_task_mgmt import find_task_dir_path_from_id
except ImportError:
    print("CRITICAL ERROR: gouai_task_mgmt.py not found or importable.", file=sys.stderr)
    sys.exit(1)

try:
    from gouai_decomposition_parser import parse_decomposition_document, DecompositionParsingError
except ImportError:
    print("CRITICAL ERROR: gouai_decomposition_parser.py not found or importable.", file=sys.stderr)
    sys.exit(1)

try:
    from gouai_llm_api import generate_response_aggregated, LLMAPICallError, ConfigurationError
except ImportError:
    print("CRITICAL ERROR: gouai_llm_api.py not found or importable.", file=sys.stderr)
    sys.exit(1)

# --- Constants ---
DEFAULT_OUTPUT_FILENAME = "_final_composed_wsod.md"
SUBTASK_OUTPUT_TRACKER_FILENAME = "_subtask_output_tracker.md" # As defined in make_gouai_subtasks.py

# --- Helper Functions ---

def parse_subtask_output_tracker(tracker_file_path: Path) -> list[dict]:
    """
    Parses the _subtask_output_tracker.md file.
    Returns a list of dictionaries, each representing a tracked sub-task.
    """
    tracked_subtasks = []
    if not tracker_file_path.is_file():
        print(f"Warning: Sub-task output tracker file not found: {tracker_file_path}", file=sys.stderr)
        return tracked_subtasks

    try:
        with open(tracker_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        current_subtask = None
        for line in lines:
            line = line.strip()
            
            match_header = re.match(r"^## Sub-task \(Original Temp ID: (.*?)\)", line)
            if match_header:
                if current_subtask:
                    tracked_subtasks.append(current_subtask)
                current_subtask = {"original_temp_id": match_header.group(1).strip()}
                continue

            if current_subtask is None:
                continue

            match_final_hlg = re.match(r"^\*\*Final HLG:\*\*\s*```\s*(.*?)\s*```", line, re.DOTALL) # Simple HLG grab
            if match_final_hlg: # More robust HLG parsing might be needed if HLG is truly multiline inside ```
                 current_subtask["final_hlg"] = match_final_hlg.group(1).strip()
                 # For multiline HLG inside ```, need to read until ```
                 # This simple regex might only get the first line if HLG is multiline.
                 # For now, assume HLG in tracker is concise. A better tracker parser is needed for complex HLGs.

            match_type = re.match(r"^- \*\*Type:\*\*\s*(.*)", line)
            if match_type:
                current_subtask["type"] = match_type.group(1).strip()
            
            match_path = re.match(r"^- \*\*Instantiated ID/Path \(relative to parent\):\*\*\s*`?(.*?)`?$", line)
            if match_path:
                current_subtask["instantiated_id_or_path"] = match_path.group(1).strip()

            match_output_loc = re.match(r"^- \*\*Intended Output Location:\*\*\s*`?(.*?)`?$", line)
            if match_output_loc:
                current_subtask["output_location_reference"] = match_output_loc.group(1).strip()

            match_status = re.match(r"^- \*\*Status:\*\*\s*(.*)", line)
            if match_status:
                current_subtask["status"] = match_status.group(1).strip()
        
        if current_subtask: # Add the last parsed subtask
            tracked_subtasks.append(current_subtask)

    except Exception as e:
        print(f"Error parsing tracker file {tracker_file_path}: {e}", file=sys.stderr)
    
    return tracked_subtasks


def get_subtask_output_content(
    subtask_tracker_info: dict, 
    parent_task_dir: Path, 
    project_root: Path) -> str:
    """
    Retrieves the content from a sub-task's output location.
    Handles different types of output references.
    """
    content_parts = []
    output_ref = subtask_tracker_info.get("output_location_reference")
    subtask_rel_path_str = subtask_tracker_info.get("instantiated_id_or_path") # Dir name or file path for text copy
    subtask_type = subtask_tracker_info.get("type")

    content_parts.append(f"--- Sub-task Details ---")
    content_parts.append(f"Original Temp ID: {subtask_tracker_info.get('original_temp_id', 'N/A')}")
    content_parts.append(f"Final HLG: {subtask_tracker_info.get('final_hlg', 'N/A')}")
    content_parts.append(f"Type: {subtask_type}")
    content_parts.append(f"Status: {subtask_tracker_info.get('status', 'N/A')}")

    if not output_ref or not subtask_rel_path_str:
        content_parts.append("Output Reference or Path missing in tracker.")
        return "\n".join(content_parts)

    # Determine the actual path to the sub-task's context (directory or specific file)
    # subtask_rel_path_str could be like 'ST1-1_Simple_ClarifyScript' or 'decomposed_subtasks_text/subtask_0_details.md'
    
    # The output_location_reference is often relative to the subtask's own directory.
    # The instantiated_id_or_path gives the subtask directory relative to parent.

    full_output_path = None

    if subtask_type == "Text Copy":
        # output_location_reference might be the same as instantiated_id_or_path if it's a direct file path
        # For Text Copy, instantiated_id_or_path IS the path to the .md file relative to parent_task_dir
        full_output_path = parent_task_dir / subtask_rel_path_str
    elif subtask_type == "Simple LLM Task" or subtask_type == "Recursive GOUAI Task":
        # instantiated_id_or_path is the subtask's directory name (relative to parent)
        # output_location_reference is relative to *that subtask's directory*
        # e.g., output_location_reference = "./outputs/final_spec.md"
        # e.g., instantiated_id_or_path = "ST1-1_Simple_ClarifyScript"
        # So, actual file is parent_task_dir / "ST1-1_Simple_ClarifyScript" / "outputs/final_spec.md"

        subtask_dir_abs = parent_task_dir / subtask_rel_path_str
        
        if output_ref.startswith("./"): # Path relative to subtask dir
            output_file_rel_to_subtask = output_ref[2:]
            full_output_path = subtask_dir_abs / output_file_rel_to_subtask
        elif Path(output_ref).is_absolute(): # Unlikely, but handle
            full_output_path = Path(output_ref)
        else: # Assume it's relative to subtask dir if not starting with ./
            full_output_path = subtask_dir_abs / output_ref
            
        # For Recursive GOUAI Task, we might want its task_definition.md (for WSOD)
        # AND files from its outputs/ directory.
        # The tracker's "output_location_reference" for GOUAI tasks points to its task_definition.md and outputs/
        # This simple function will just try to read the one file specified.
        # A more complex version would intelligently grab task_definition.md + files in outputs/.
        if subtask_type == "Recursive GOUAI Task":
            # Let's try to get its task_definition.md content for its WSOD
            gouai_subtask_def_path = subtask_dir_abs / "task_definition.md"
            if gouai_subtask_def_path.is_file():
                try:
                    parsed_def = parse_decomposition_document(gouai_subtask_def_path.read_text(encoding='utf-8')) # Re-use parser
                    sub_wsod = parsed_def.get("parent_task_details", {}).get("wsod", "Sub-task WSOD not found in its task_definition.md")
                    content_parts.append(f"Sub-task Final WSOD:\n```\n{sub_wsod}\n```")
                except Exception as e_parse:
                    content_parts.append(f"Could not parse sub-task WSOD from {gouai_subtask_def_path}: {e_parse}")
            else:
                 content_parts.append(f"Sub-task task_definition.md not found at {gouai_subtask_def_path}")
            
            # Now also try to read the specified output_location_reference if different or if it's an actual file
            # The current output_ref for GOUAI tasks is generic.
            # For now, we'll just focus on its WSOD from task_definition.md
            # A better approach would be for the tracker to specify key output files for GOUAI tasks.
            # Or this script could try to list and read all text files in its 'outputs/' dir.
            content_parts.append(f"Note: For full content from Recursive GOUAI task '{subtask_rel_path_str}', review its 'outputs/' directory.")
            # Fall through to try and read `full_output_path` if it resolves to a specific file.
            # If `output_ref` for GOUAI task was just like "./outputs/", `full_output_path` will be a dir.


    if full_output_path and full_output_path.is_file():
        try:
            file_content = full_output_path.read_text(encoding='utf-8', errors='replace')
            content_parts.append(f"Output Content (from {output_ref}):\n```\n{file_content.strip()}\n```")
        except Exception as e:
            content_parts.append(f"Error reading output file {full_output_path}: {e}")
    elif full_output_path and full_output_path.is_dir():
        # If the output_location_reference pointed to a directory (e.g. "./outputs/")
        content_parts.append(f"Output Location (from {output_ref}) is a directory: {full_output_path}")
        content_parts.append("  Files in this directory (first 5 .md or .txt):")
        files_read = 0
        try:
            for item in sorted(list(full_output_path.iterdir()))[:10]: # Read up to 10 items
                if item.is_file() and item.suffix.lower() in ['.md', '.txt'] and files_read < 5:
                    file_content = item.read_text(encoding='utf-8', errors='replace')
                    content_parts.append(f"  --- File: {item.name} ---")
                    content_parts.append(f"  ```\n{file_content.strip()}\n  ```")
                    files_read +=1
                elif item.is_file() and files_read < 5: # For other file types, just list them
                    content_parts.append(f"  - {item.name} (Non-text or not parsed)")
            if files_read == 0:
                 content_parts.append("   (No .md or .txt files found or read from this directory)")
        except Exception as e_dir:
            content_parts.append(f"  Error listing/reading files in directory {full_output_path}: {e_dir}")
    else:
        content_parts.append(f"Output file/directory not found or not specified clearly for path: {full_output_path if full_output_path else output_ref}")

    content_parts.append("--- End Sub-task ---\n")
    return "\n".join(content_parts)


def main():
    parser = argparse.ArgumentParser(
        description="GOUAI Final WSOD Composition Tool. "
                    "Aggregates sub-task outputs and uses an LLM to synthesize a Final WSOD for the parent task."
    )
    parser.add_argument("--parent_task_id", required=True, help="Full string ID of the parent GOUAI task.")
    parser.add_argument("--project_root", required=True, help="Path to the root directory of the GOUAI project.")
    parser.add_argument(
        "--output_filename", 
        default=DEFAULT_OUTPUT_FILENAME, 
        help=f"Filename for the composed Final WSOD. Saved in parent task's 'outputs/' directory. Default: {DEFAULT_OUTPUT_FILENAME}"
    )
    args = parser.parse_args()

    project_root_path = Path(args.project_root).resolve()
    if not project_root_path.is_dir():
        print(f"ERROR: Project root path '{project_root_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    parent_task_id = args.parent_task_id
    parent_task_dir = find_task_dir_path_from_id(project_root_path, parent_task_id, project_root_path) #
    if not parent_task_dir or not parent_task_dir.is_dir():
        print(f"ERROR: Could not find directory for parent task ID '{parent_task_id}'.", file=sys.stderr)
        sys.exit(1)
    print(f"INFO: Found parent task directory: {parent_task_dir}")

    # 1. Read Parent's Initial WSOD (from decomposition_output.md)
    decomposition_doc_path = parent_task_dir / "decomposition_output.md" # As per workflow Step 2 output
    if not decomposition_doc_path.is_file():
        print(f"ERROR: `decomposition_output.md` not found in parent task directory: {decomposition_doc_path}", file=sys.stderr)
        print(f"       This file, generated by 'execute_gouai_p1p2.py', is needed for the parent's initial WSOD.", file=sys.stderr)
        sys.exit(1)
    
    parent_initial_hlg = "Parent HLG not found in decomposition document."
    parent_initial_wsod = "Parent WSOD not found in decomposition document."
    try:
        decomp_content = decomposition_doc_path.read_text(encoding='utf-8')
        parsed_decomp = parse_decomposition_document(decomp_content) #
        parent_initial_hlg = parsed_decomp.get("parent_task_details", {}).get("hlg", parent_initial_hlg)
        parent_initial_wsod = parsed_decomp.get("parent_task_details", {}).get("wsod", parent_initial_wsod)
    except DecompositionParsingError as e:
        print(f"ERROR: Could not parse {decomposition_doc_path}: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error reading or parsing {decomposition_doc_path}: {e}", file=sys.stderr)
        sys.exit(1)
        
    print(f"INFO: Parent Initial HLG (from decomposition): '{parent_initial_hlg[:100]}...'")
    print(f"INFO: Parent Initial WSOD (from decomposition): '{parent_initial_wsod[:100]}...'")


    # 2. Read Sub-task Output Tracker
    tracker_file = parent_task_dir / SUBTASK_OUTPUT_TRACKER_FILENAME
    tracked_subtasks = parse_subtask_output_tracker(tracker_file)
    if not tracked_subtasks:
        print(f"INFO: No sub-tasks found in tracker or tracker not found. Proceeding with only parent WSOD for LLM review (if any).", file=sys.stderr)
        # Decide if to proceed or exit. For now, can proceed, LLM will get less context.
        # sys.exit(1) 

    # 3. Aggregate Sub-task Outputs
    print(f"INFO: Aggregating outputs for {len(tracked_subtasks)} tracked sub-tasks...")
    aggregated_subtask_outputs_str = ""
    completed_subtasks_count = 0
    for subtask_info in tracked_subtasks:
        if subtask_info.get("status", "").lower() == "complete" or "copied" in subtask_info.get("status", "").lower() : # Consider "Text Copied" as complete for aggregation
            print(f"  - Processing completed sub-task (Original Temp ID: {subtask_info.get('original_temp_id', 'N/A')})...")
            output_content = get_subtask_output_content(subtask_info, parent_task_dir, project_root_path)
            aggregated_subtask_outputs_str += output_content + "\n\n"
            completed_subtasks_count += 1
        else:
            print(f"  - Skipping sub-task (Original Temp ID: {subtask_info.get('original_temp_id', 'N/A')}) - Status: {subtask_info.get('status', 'N/A')}")
    
    if completed_subtasks_count == 0 and tracked_subtasks:
        print(f"WARNING: No sub-tasks were marked as 'Complete' or 'Copied' in the tracker. The composed WSOD will be based primarily on the parent's initial WSOD.")
    elif completed_subtasks_count > 0:
        print(f"INFO: Successfully aggregated outputs from {completed_subtasks_count} completed sub-task(s).")


    # 4. Construct Prompt for LLM Synthesis
    synthesis_prompt_parts = [
        "You are a GOUAI Synthesis AI. Your task is to create a 'Final Workable Stated Output Descriptor (Final WSOD)' for a parent GOUAI task.",
        "You will be provided with:",
        "1. The Parent Task's Initial HLG.",
        "2. The Parent Task's Initial WSOD (formulated after its own Phase 1 & 2, before sub-task decomposition).",
        "3. Aggregated outputs and final states/WSODs from its decomposed sub-tasks.",
        "\nYour goal is to synthesize all this information into a single, coherent, updated, and actionable Final WSOD for the PARENT task.",
        "This Final WSOD should:",
        "- Clearly restate or confirm the overarching goal.",
        "- Integrate findings and outputs from sub-tasks to provide a comprehensive picture of the achieved state or refined plan.",
        "- Resolve uncertainties mentioned in the initial parent WSOD if sub-tasks addressed them.",
        "- Be detailed enough to guide a potential GOUAI Phase 3 (Output Synthesis) for the parent task, or to stand as the definitive description of the completed work.",
        "- If sub-tasks indicate failures or unresolved critical issues, the Final WSOD should reflect this reality.",
        "\n--- START OF PROVIDED INFORMATION ---",
        f"\n**Parent Task Initial HLG:**\n{parent_initial_hlg}",
        f"\n**Parent Task Initial WSOD (from pre-decomposition analysis):**\n{parent_initial_wsod}",
        "\n**Aggregated Sub-task Outcomes & Outputs:**"
    ]
    if aggregated_subtask_outputs_str.strip():
        synthesis_prompt_parts.append(aggregated_subtask_outputs_str)
    else:
        synthesis_prompt_parts.append("No completed sub-task outputs were provided or found for aggregation.")
    
    synthesis_prompt_parts.append("\n--- END OF PROVIDED INFORMATION ---")
    synthesis_prompt_parts.append("\nPlease now generate the Final WSOD for the parent task based on all the information above.")
    
    final_synthesis_prompt = "\n".join(synthesis_prompt_parts)

    # For debugging, print the prompt
    # print("\n--- LLM Synthesis Prompt ---")
    # print(final_synthesis_prompt[:2000] + "..." if len(final_synthesis_prompt) > 2000 else final_synthesis_prompt)
    # print("--- End LLM Synthesis Prompt ---\n")

    # 5. Call LLM
    print("INFO: Calling LLM to synthesize Final WSOD...")
    session_id = f"compose_wsod_{parent_task_id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    try:
        response_data = generate_response_aggregated( #
            project_root=str(project_root_path),
            session_id=session_id,
            task_id=parent_task_id, # Log this under the parent task
            contents=final_synthesis_prompt
        )

        if response_data.get('error_info'):
            error_details = response_data['error_info']
            print(f"ERROR: LLM API call failed during WSOD synthesis: {error_details.get('type')} - {error_details.get('message')}", file=sys.stderr)
            sys.exit(1)
        
        composed_wsod_text = response_data.get('text')
        if not composed_wsod_text:
            print("ERROR: LLM returned no text content for the Final WSOD.", file=sys.stderr)
            sys.exit(1)
        
        print("INFO: Final WSOD synthesized successfully by LLM.")

    except ConfigurationError as e:
        print(f"ERROR: LLM Configuration Error: {e}", file=sys.stderr)
        sys.exit(1)
    except LLMAPICallError as e:
        print(f"ERROR: LLM API Call Error during synthesis: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error during LLM call for WSOD synthesis: {type(e).__name__} - {e}", file=sys.stderr)
        sys.exit(1)

    # 6. Save Output
    output_dir_for_wsod = parent_task_dir / "outputs"
    output_dir_for_wsod.mkdir(parents=True, exist_ok=True)
    final_wsod_filepath = output_dir_for_wsod / args.output_filename

    try:
        with open(final_wsod_filepath, 'w', encoding='utf-8') as f:
            f.write(f"# Final Composed Workable Stated Output Descriptor (WSOD)\n\n")
            f.write(f"**Parent Task ID:** {parent_task_id}\n")
            f.write(f"**Composed Date:** {datetime.datetime.now().isoformat()}\n\n")
            f.write("---\n\n")
            f.write(composed_wsod_text)
        print(f"SUCCESS: Final Composed WSOD saved to: {final_wsod_filepath}")
        print(f"INFO: Next step would be to review this Final WSOD and potentially proceed to GOUAI Phase 3 for parent task '{parent_task_id}' using this as input.")
    except IOError as e:
        print(f"ERROR: Could not write Final WSOD to file '{final_wsod_filepath}': {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()