# make_gouai_subtasks.py

import argparse
from pathlib import Path
import sys
import datetime # Potentially for naming output files from 'Copy to Text'
# import os # If needed for path manipulations not covered by pathlib
import re
import json # For potentially saving tracker data if not markdown

# --- GOUAI Module Imports ---
try:
    from gouai_decomposition_parser import parse_decomposition_document, DecompositionParsingError
except ImportError:
    print("CRITICAL ERROR: gouai_decomposition_parser.py not found or importable.", file=sys.stderr)
    sys.exit(1) # This is a critical dependency

try:
    from gouai_task_mgmt import create_task, find_task_dir_path_from_id, FULL_GOUAI_TASK_TYPE, SIMPLE_TASK_TYPE #
except ImportError:
    print("CRITICAL ERROR: gouai_task_mgmt.py not found or importable.", file=sys.stderr)
    sys.exit(1) # Critical dependency

# --- Constants ---
OUTPUT_TRACKER_FILENAME_TEMPLATE = "_subtask_output_tracker.md"

# --- Helper Functions ---

def _get_multiline_input(prompt: str, current_text: str = "") -> str:
    """Helper to get multiline input for editing."""
    print(f"{prompt} (Current text shown below. Enter '.' on a new line to finish, or 'ABORTEDIT' to cancel):")
    if current_text:
        print("--- Current Text ---")
        print(current_text)
        print("--- End Current Text ---")
    else:
        print("(No current text. Enter '.' on a new line to finish, or 'ABORTEDIT' to cancel)")
    
    lines = []
    while True:
        try:
            line = input("> ")
            if line == ".":
                break
            if line.upper() == "ABORTEDIT":
                print("Edit aborted.")
                return current_text # Return original text
            lines.append(line)
        except EOFError:
            break
    return "\n".join(lines).strip()

def _edit_sub_task_details_interactive(sub_task_data: dict) -> dict:
    """
    Allows interactive editing of a sub-task's HLG, EUs, and KIRQs.
    Returns the modified sub_task_data.
    """
    print("\n--- Review & Edit Sub-task ---")
    edited_data = sub_task_data.copy() # Work on a copy

    while True:
        print(f"\nCurrent HLG for Temp ID {edited_data['temp_id']}:\n{edited_data['hlg']}")
        choice = input("Edit HLG? (y/N): ").strip().lower()
        if choice == 'y':
            new_hlg = _get_multiline_input("Enter new HLG:", edited_data['hlg'])
            if new_hlg != edited_data['hlg']: # Check if actually changed
                 edited_data['hlg'] = new_hlg
                 print("HLG updated.")
        
        print("\nCurrent Epistemic Uncertainties (EUs):")
        if not edited_data['eus']: print("- None")
        for i, eu in enumerate(edited_data['eus']): print(f"  {i+1}. {eu}")
        choice = input("Edit EUs? (y/N/a(dd)/r(emove)): ").strip().lower()
        if choice == 'y':
            new_eus_text = _get_multiline_input("Enter new EUs (one per line):", "\n".join(edited_data['eus']))
            edited_data['eus'] = [line.strip() for line in new_eus_text.splitlines() if line.strip()]
            print("EUs updated.")
        elif choice == 'a':
            new_eu = input("Enter new EU to add: ").strip()
            if new_eu: edited_data['eus'].append(new_eu)
        elif choice == 'r':
            if edited_data['eus']:
                try:
                    idx_to_remove = int(input(f"Enter number of EU to remove (1-{len(edited_data['eus'])}): ")) - 1
                    if 0 <= idx_to_remove < len(edited_data['eus']):
                        removed_eu = edited_data['eus'].pop(idx_to_remove)
                        print(f"Removed EU: '{removed_eu}'")
                    else:
                        print("Invalid number.")
                except ValueError:
                    print("Invalid input.")
            else:
                print("No EUs to remove.")


        print("\nCurrent Key Information Requirements (KIRQs):")
        if not edited_data['kirqs']: print("- None")
        for i, kirq in enumerate(edited_data['kirqs']): print(f"  {i+1}. {kirq}")
        choice = input("Edit KIRQs? (y/N/a(dd)/r(emove)): ").strip().lower()
        if choice == 'y':
            new_kirqs_text = _get_multiline_input("Enter new KIRQs (one per line):", "\n".join(edited_data['kirqs']))
            edited_data['kirqs'] = [line.strip() for line in new_kirqs_text.splitlines() if line.strip()]
            print("KIRQs updated.")
        elif choice == 'a':
            new_kirq = input("Enter new KIRQ to add: ").strip()
            if new_kirq: edited_data['kirqs'].append(new_kirq)
        elif choice == 'r':
            if edited_data['kirqs']:
                try:
                    idx_to_remove = int(input(f"Enter number of KIRQ to remove (1-{len(edited_data['kirqs'])}): ")) - 1
                    if 0 <= idx_to_remove < len(edited_data['kirqs']):
                        removed_kirq = edited_data['kirqs'].pop(idx_to_remove)
                        print(f"Removed KIRQ: '{removed_kirq}'")
                    else:
                        print("Invalid number.")
                except ValueError:
                    print("Invalid input.")
            else:
                print("No KIRQs to remove.")

        confirm_choice = input("Finished editing this sub-task? (Y/n): ").strip().lower()
        if confirm_choice != 'n':
            break
            
    return edited_data

def _derive_name_suffix(hlg: str, existing_suffixes: list) -> str:
    """
    Derives a safe and unique name_suffix for a new task from its HLG.
    """
    words = re.sub(r'[^\w\s-]', '', hlg.lower()).split() # Keep hyphens as they are often meaningful
    # Sanitize individual words further by replacing multiple underscores/hyphens with single
    sanitized_words = []
    for word in words:
        word = re.sub(r'[_]+', '_', word) # Consolidate underscores
        word = re.sub(r'[-]+', '-', word) # Consolidate hyphens
        sanitized_words.append(word)

    base_suffix_candidate = "_".join(sanitized_words[:5]) # Max 5 words, join with underscore
    base_suffix_candidate = base_suffix_candidate[:50] # Truncate to avoid excessively long names

    if not base_suffix_candidate:
        base_suffix_candidate = "sub_task"
    
    # Final check to remove trailing/leading underscores/hyphens that might result from truncation or empty words
    base_suffix = base_suffix_candidate.strip('_-')

    suffix = base_suffix
    counter = 1
    while suffix in existing_suffixes:
        suffix = f"{base_suffix}_{counter}"
        counter += 1
    return suffix

def _handle_copy_to_text(sub_task_data: dict, parent_task_dir: Path, parent_task_id: str, tracker_entry: dict):
    """
    Handles the 'Copy to Text' action and updates tracker_entry.
    """
    try:
        output_dir = parent_task_dir / "decomposed_subtasks_text"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        safe_hlg_part = re.sub(r'[^\w-]', '', sub_task_data['hlg'][:30].replace(" ", "_")).strip('_-')
        filename = f"subtask_{sub_task_data['temp_id']}_{safe_hlg_part if safe_hlg_part else 'details'}.md" # Save as markdown
        filepath = output_dir / filename

        content = f"# Sub-task (Original Temp ID: {sub_task_data['temp_id']})\n\n"
        content += f"**Parent Task ID:** {parent_task_id}\n\n"
        content += "---\n"
        content += f"## HLG:\n{sub_task_data['hlg']}\n\n"
        content += "## Epistemic Uncertainties:\n"
        if sub_task_data['eus']:
            for eu in sub_task_data['eus']: content += f"- {eu}\n"
        else:
            content += "_None specified._\n"
        content += "\n## Key Information Requirements:\n"
        if sub_task_data['kirqs']:
            for kirq in sub_task_data['kirqs']: content += f"- {kirq}\n"
        else:
            content += "_None specified._\n"
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"INFO: Sub-task details copied to: {filepath.relative_to(parent_task_dir.parent) if parent_task_dir.parent else filepath}")
        
        tracker_entry["instantiated_id_or_path"] = str(filepath.relative_to(parent_task_dir))
        tracker_entry["status"] = "Text Copied"

    except Exception as e:
        print(f"ERROR: Could not copy sub-task {sub_task_data['temp_id']} to text: {e}", file=sys.stderr)
        tracker_entry["status"] = "Error copying to text"


def _handle_create_new_task(
    sub_task_data: dict, 
    project_root_path: Path, 
    parent_task_id_for_new_tasks: str, 
    task_type: str, 
    existing_name_suffixes: list,
    tracker_entry: dict # To update with new task ID and output location
):
    """
    Handles creation of a new GOUAI or Simple task, including structured input_text.
    Updates tracker_entry.
    """
    print(f"INFO: Preparing to create a new '{task_type}' for sub-task (Original Temp ID: {sub_task_data['temp_id']})")
    
    default_name_suffix = _derive_name_suffix(sub_task_data['hlg'], existing_name_suffixes)
    name_suffix = input(f"Proposed name suffix for new task: '{default_name_suffix}'. Press Enter to accept or type a new one: ").strip()
    if not name_suffix: # User pressed Enter
        name_suffix = default_name_suffix
    
    # Ensure unique suffix for this session if user provides one that might already exist
    final_name_suffix = name_suffix
    counter = 1
    while final_name_suffix in existing_name_suffixes:
        final_name_suffix = f"{name_suffix}_{counter}"
        counter += 1
    existing_name_suffixes.append(final_name_suffix)
    name_suffix = final_name_suffix


    # Prepare input_text_str with HLG and descriptive EUs/KIRQs
    # This text will go into the main HLG description section of the new task's task_definition.md
    input_text_for_new_task = f"{sub_task_data['hlg']}\n" 

    if sub_task_data.get('eus'):
        input_text_for_new_task += "\n### Initial Epistemic Uncertainties (from parent decomposition):\n"
        for eu in sub_task_data['eus']:
            input_text_for_new_task += f"- {eu}\n"
    
    if sub_task_data.get('kirqs'):
        input_text_for_new_task += "\n### Initial Key Information Requirements (from parent decomposition):\n"
        for kirq in sub_task_data['kirqs']:
            input_text_for_new_task += f"- {kirq}\n"
    
    input_text_str_for_create_task = input_text_for_new_task.strip()
    
    # For SIMPLE_TASK_TYPE, gouai_task_mgmt.py uses the input_text for both 
    # 'one_line_description' (from first line) and the body text.
    # For FULL_GOUAI_TASK_TYPE, it uses it for the HLG body text.
    # This formatted input_text_str_for_create_task should work for both.

    parent_task_dir_path = find_task_dir_path_from_id(project_root_path, parent_task_id_for_new_tasks, project_root_path) #
    if not parent_task_dir_path:
        print(f"ERROR: Could not find directory for parent task ID '{parent_task_id_for_new_tasks}'. Cannot create sub-task.", file=sys.stderr)
        tracker_entry["status"] = f"Error finding parent task dir"
        return

    # Define conventional output location for tracking
    # This is a placeholder; user will manage actual output file creation within the sub-task.
    # The tracker just notes where it's *expected* or where key summaries might be.
    conventional_output_ref = ""
    if task_type == FULL_GOUAI_TASK_TYPE:
        conventional_output_ref = f"./<NewTaskDir>/task_definition.md (for WSOD) and ./<NewTaskDir>/outputs/"
    elif task_type == SIMPLE_TASK_TYPE:
        user_defined_output_filename = input(f"Enter a conventional primary output filename for this simple task (e.g., result.txt, spec.md - will be under ./<NewTaskDir>/outputs/): ").strip()
        if not user_defined_output_filename:
            user_defined_output_filename = "primary_output.md"
        conventional_output_ref = f"./<NewTaskDir>/outputs/{user_defined_output_filename}"


    try:
        # Note: If gouai_task_mgmt.create_task is modified to accept structured EUs/KIRQs,
        # this call would change to pass sub_task_data['eus'] and sub_task_data['kirqs'] as lists.
        # For now, they are embedded in input_text_str_for_create_task.
        new_task_id, new_task_path = create_task( #
            parent_dir_path_str=str(parent_task_dir_path),
            task_type_str=task_type,
            input_text_str=input_text_str_for_create_task,
            name_suffix_str=name_suffix
        )
        relative_new_task_path = new_task_path.relative_to(parent_task_dir_path)
        print(f"SUCCESS: Created new {task_type} '{new_task_id}' at {relative_new_task_path}")
        
        tracker_entry["instantiated_id_or_path"] = str(relative_new_task_path) # Store relative path
        tracker_entry["status"] = "Not Started"
        tracker_entry["output_location_reference"] = conventional_output_ref.replace("<NewTaskDir>", str(relative_new_task_path.name))

        print("INFO: Next step for this new task would be context priming (if applicable via `gouai chat`).")

    except Exception as e:
        print(f"ERROR: Failed to create new {task_type} for sub-task (Original Temp ID {sub_task_data['temp_id']}): {e}", file=sys.stderr)
        tracker_entry["status"] = f"Error creating task: {e}"

def _write_output_tracker(parent_task_dir: Path, parent_task_id: str, tracker_data: list):
    """Writes the tracker data to a Markdown file."""
    tracker_filename = OUTPUT_TRACKER_FILENAME_TEMPLATE
    tracker_filepath = parent_task_dir / tracker_filename
    
    content = f"# Sub-task Output Tracker\n\n"
    content += f"**Parent Task ID:** `{parent_task_id}`\n"
    content += f"**Last Updated:** {datetime.datetime.now().isoformat()}\n\n"
    
    if not tracker_data:
        content += "No sub-tasks processed or tracked in this session.\n"
    else:
        for entry in tracker_data:
            content += f"---\n"
            content += f"## Sub-task (Original Temp ID: {entry['original_temp_id']})\n\n"
            content += f"**Final HLG:**\n```\n{entry['final_hlg']}\n```\n\n"
            if entry.get('final_eus'):
                content += f"**Final EUs:**\n"
                for eu in entry['final_eus']: content += f"- {eu}\n"
                content += "\n"
            if entry.get('final_kirqs'):
                content += f"**Final KIRQs:**\n"
                for kirq in entry['final_kirqs']: content += f"- {kirq}\n"
                content += "\n"
            content += f"- **Type:** {entry['type']}\n"
            content += f"- **Instantiated ID/Path (relative to parent):** `{entry['instantiated_id_or_path']}`\n"
            if entry.get('output_location_reference'):
                content += f"- **Intended Output Location:** `{entry['output_location_reference']}`\n"
            content += f"- **Status:** {entry['status']}\n\n"
            
    try:
        with open(tracker_filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"\nINFO: Sub-task output tracker saved to: {tracker_filepath.relative_to(parent_task_dir.parent) if parent_task_dir.parent else tracker_filepath}")
    except IOError as e:
        print(f"ERROR: Could not write output tracker file at '{tracker_filepath}': {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="GOUAI Sub-task Instantiation Tool with Interactive Review and Output Tracking.")
    parser.add_argument("--document_path", required=True, help="Path to the Decomposition Document.")
    parser.add_argument("--project_root_path", required=True, help="Path to the GOUAI project root.")
    parser.add_argument("--parent_task_id_for_new_tasks", required=True, help="Task ID of the original parent task for new sub-tasks.")
    args = parser.parse_args()

    project_root = Path(args.project_root_path).resolve()
    doc_path = Path(args.document_path).resolve()

    if not project_root.is_dir():
        print(f"ERROR: Project root path does not exist or is not a directory: {project_root}", file=sys.stderr)
        sys.exit(1)
    if not doc_path.is_file():
        print(f"ERROR: Decomposition document not found at: {doc_path}", file=sys.stderr)
        sys.exit(1)
    
    parent_task_dir = find_task_dir_path_from_id(project_root, args.parent_task_id_for_new_tasks, project_root)
    if not parent_task_dir:
        print(f"ERROR: Could not find directory for parent task ID '{args.parent_task_id_for_new_tasks}'. This script needs it for saving tracker and text copies.", file=sys.stderr)
        sys.exit(1)

    try:
        print(f"INFO: Parsing decomposition document: {doc_path}")
        with open(doc_path, 'r', encoding='utf-8') as f:
            doc_content = f.read()
        parsed_data = parse_decomposition_document(doc_content) #
    except DecompositionParsingError as e:
        print(f"ERROR: Could not parse the decomposition document: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: An unexpected error occurred during document parsing: {e}", file=sys.stderr)
        sys.exit(1)

    parent_details = parsed_data.get("parent_task_details", {})
    sub_tasks_list_from_parser = parsed_data.get("sub_tasks", [])

    print("\n--- Original Parent Task ---")
    print(f"HLG: {parent_details.get('hlg', 'N/A')}")
    print(f"WSOD: {parent_details.get('wsod', 'N/A')}")
    print(f"Found {len(sub_tasks_list_from_parser)} sub-tasks to process from decomposition document.\n")

    if not sub_tasks_list_from_parser:
        print("INFO: No sub-tasks found in the document to process.")
        _write_output_tracker(parent_task_dir, args.parent_task_id_for_new_tasks, []) # Write empty tracker
        sys.exit(0)

    created_task_name_suffixes_in_session = [] 
    sub_task_tracker_data = []

    for original_sub_task_data in sub_tasks_list_from_parser:
        print("========================================")
        print(f"Processing Sub-task (Original Temp ID: {original_sub_task_data['temp_id']})")
        print("----------------------------------------")
        
        # Allow user to edit details before choosing action
        current_sub_task_data = _edit_sub_task_details_interactive(original_sub_task_data.copy()) # Edit a copy

        # Initialize tracker entry for this sub-task
        tracker_entry = {
            "original_temp_id": original_sub_task_data['temp_id'],
            "original_hlg": original_sub_task_data['hlg'], # Keep original for reference
            "final_hlg": current_sub_task_data['hlg'],
            "final_eus": current_sub_task_data['eus'],
            "final_kirqs": current_sub_task_data['kirqs'],
            "type": "Skipped", # Default type
            "instantiated_id_or_path": "N/A",
            "output_location_reference": "N/A",
            "status": "Skipped by user"
        }

        while True:
            print("\n--- Choose Action for Sub-task ---")
            print(f"HLG (after potential edits):\n{current_sub_task_data['hlg']}")
            print("----------------------------------------")
            choice = input(
                "Choose action: (A)ccept and Instantiate | (E)dit Again | (C)opy to Text File | (S)kip this sub-task | (Q)uit all : "
            ).strip().upper()
            
            if choice == 'E':
                current_sub_task_data = _edit_sub_task_details_interactive(current_sub_task_data)
                # Update tracker entry with potentially new final HLG/EUs/KIRQs
                tracker_entry["final_hlg"] = current_sub_task_data['hlg']
                tracker_entry["final_eus"] = current_sub_task_data['eus']
                tracker_entry["final_kirqs"] = current_sub_task_data['kirqs']
                continue # Re-loop to action choice

            elif choice == 'A':
                print("\n--- Instantiate Sub-task ---")
                instantiation_type_choice = input("Instantiate as (G)OUAI Task or (S)imple Task? : ").strip().upper()
                if instantiation_type_choice == 'G':
                    tracker_entry["type"] = FULL_GOUAI_TASK_TYPE
                    _handle_create_new_task(current_sub_task_data, project_root, args.parent_task_id_for_new_tasks, FULL_GOUAI_TASK_TYPE, created_task_name_suffixes_in_session, tracker_entry)
                    break 
                elif instantiation_type_choice == 'S':
                    tracker_entry["type"] = SIMPLE_TASK_TYPE
                    _handle_create_new_task(current_sub_task_data, project_root, args.parent_task_id_for_new_tasks, SIMPLE_TASK_TYPE, created_task_name_suffixes_in_session, tracker_entry)
                    break
                else:
                    print("Invalid instantiation type. Please choose 'G' or 'S'.")
                    continue # Re-ask (A)ccept and Instantiate options

            elif choice == 'C':
                tracker_entry["type"] = "Text Copy"
                _handle_copy_to_text(current_sub_task_data, parent_task_dir, args.parent_task_id_for_new_tasks, tracker_entry)
                break 
            
            elif choice == 'S': # Skip
                print(f"INFO: Skipping sub-task (Original Temp ID {original_sub_task_data['temp_id']}). Details logged in tracker.")
                # Tracker entry already defaults to Skipped
                break
            elif choice == 'Q':
                print("INFO: Quitting sub-task processing by user request.")
                # Append the current (skipped) tracker entry before exiting loop
                sub_task_tracker_data.append(tracker_entry) 
                # Write out what has been tracked so far
                _write_output_tracker(parent_task_dir, args.parent_task_id_for_new_tasks, sub_task_tracker_data)
                sys.exit(0)
            else:
                print("Invalid choice. Please try again.")
        
        sub_task_tracker_data.append(tracker_entry)
            
    print("\n========================================")
    print("INFO: Finished processing all sub-tasks from the document.")
    _write_output_tracker(parent_task_dir, args.parent_task_id_for_new_tasks, sub_task_tracker_data)

if __name__ == "__main__":
    main()