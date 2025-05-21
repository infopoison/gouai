#!/usr/bin/env python3

import argparse
import os
import sys
from pathlib import Path
from datetime import datetime

def get_multiline_input(prompt_message: str) -> str:
    """Gets multi-line input from the user."""
    print(f"\n{prompt_message}")
    print("(Enter an empty line when done, or Ctrl+D)")
    lines = []
    while True:
        try:
            line = input()
            if not line: # Empty line signifies end of input
                break
            lines.append(line)
        except EOFError: # Ctrl+D
            break
    return "\n".join(lines)

def create_project_task_definition_content(project_name_for_task_id: str, hlg_text: str, meta_context_text: str) -> str:
    """
    Creates the content for the root task_definition.md file.
    """
    task_id = f"{project_name_for_task_id}_ROOT"
    parent_task_id = "null" 
    creation_timestamp_iso = datetime.now().isoformat()
    status = "Not Started"
    version = "1.0"
    
    hlg_summary = ""
    if hlg_text and hlg_text.strip():
        hlg_summary = hlg_text.splitlines()[0].strip() # First line as summary
    
    wsod_summary = "To be defined."
    task_type = "project_root_task"

    yaml_frontmatter = f"""\
task_id: {task_id}
parent_task_id: {parent_task_id}
creation_date: {creation_timestamp_iso}
last_modified_date: {creation_timestamp_iso}
status: "{status}"
version: "{version}"
HLG_summary: "{hlg_summary}"
WSOD_summary: "{wsod_summary}"
task_type: "{task_type}"
"""

    # Standard Markdown sections based on IE 1.2 (Revised)
    # Sourced from 1.2_SystemArchitecture.txt [cite: 264]
    markdown_body = f"""\
## High-Level Goal(s) (HLG)

{hlg_text}

## Meta-Context

{meta_context_text}

## Goal Space Exploration Summary
(To be filled during GOUAI Phase 1 for this project)

## Candidate Workable Stated Output Descriptor(s) (cWSODs)
(To be filled during GOUAI Phase 1 for this project)

## Workable Stated Output Descriptor (WSOD) - Full Statement
(To be filled during GOUAI Phase 1 for this project)

## WSOD Assessment (Initial)
(To be filled during GOUAI Phase 1 for this project)
### Epistemic Uncertainties
(List identified epistemic uncertainties)
### Aleatoric Uncertainties
(List identified aleatoric uncertainties)
### HLG Alignment/Risk
(Assess alignment with HLG and any risks)
### Key Information Requirements
(List key information required to resolve uncertainties or complete WSOD)

## Phase 2: Information Requirements & Query Formulation Summary
(To be filled during GOUAI Phase 2 for this project)

## Phase 2: Information Elements (IEs) Summary/Index
(To be filled during GOUAI Phase 2 for this project)

## Phase 2: IE Uncertainty Overview
(To be filled during GOUAI Phase 2 for this project)

## Phase 2: Sufficiency Check Notes
(To be filled during GOUAI Phase 2 for this project)

## Integrated WSOD with Uncertainties and KIRQs (for Context Generation)
(This section presents the WSOD decomposed with associated EUs/KIRQs for each component, for context packaging)
""" # (referring to general structure)

    full_content = f"---\n{yaml_frontmatter}\n---\n{markdown_body}"
    return full_content

def main():
    # 1. Define Command-Line Arguments [cite: 13]
    parser = argparse.ArgumentParser(
        description="Initializes a new GOUAI project directory and root task_definition.md file."
    )
    parser.add_argument(
        "--name",
        required=True,
        help="The name of the project (e.g., 'MyCatToyProject'). This will be used for the directory name and parts of the task_id."
    )
    parser.add_argument(
        "--root_dir",
        required=True,
        help="The parent directory path where the project directory will be created (e.g., './my_gouai_projects')."
    )

    args = parser.parse_args()

    project_name_input = args.name # This is the base name for the directory
    parent_dir_path = Path(args.root_dir).resolve() # Resolve to absolute path

    # Validate project name for basic directory-safe characters (optional, OS usually handles)
    # For MVP, we might rely on OS errors if name is problematic, or add simple checks later.

    # 2. Prompt for HLG and Meta-Context (IE 3.1 Revised)
    hlg_input_text = get_multiline_input(
        f"Enter the High-Level Goal (HLG) for the project '{project_name_input}':"
    )
    if not hlg_input_text.strip():
        print("Error: HLG cannot be empty. Project initialization cancelled.")
        sys.exit(1)

    meta_context_input_text = get_multiline_input(
        f"Enter the Meta-Context (constraints, values, audience/use, etc.) for the project '{project_name_input}':"
    )
    if not meta_context_input_text.strip():
        print("Error: Meta-Context cannot be empty. Project initialization cancelled.")
        sys.exit(1)

    # 3. Define and Handle Project Directory Path (IE 2.1, 2.2 Revised)
    project_directory_to_create = parent_dir_path / project_name_input
    actual_project_directory = project_directory_to_create

    if project_directory_to_create.exists():
        print(f"Warning: Directory '{project_directory_to_create}' already exists.")
        base_name = project_name_input
        counter = 1
        
        # Find a suitable alternative name
        suggested_new_dir_name = f"{base_name}_{counter}"
        new_project_dir_candidate = parent_dir_path / suggested_new_dir_name
        while new_project_dir_candidate.exists():
            counter += 1
            suggested_new_dir_name = f"{base_name}_{counter}"
            new_project_dir_candidate = parent_dir_path / suggested_new_dir_name
        
        user_choice = input(f"Do you want to create '{new_project_dir_candidate}' instead? (y/n): ").strip().lower()
        if user_choice == 'y':
            actual_project_directory = new_project_dir_candidate
        else:
            print("Project initialization cancelled by user due to existing directory.")
            sys.exit(0)
    
    # 4. Create the project directory [cite: 13]
    try:
        actual_project_directory.mkdir(parents=True, exist_ok=False) # exist_ok=False as we prompted if it existed
        print(f"Project directory '{actual_project_directory}' created successfully.")
    except FileExistsError: 
        # This should ideally not be reached if the renaming logic is sound and user cancels for original name
        print(f"Error: Directory '{actual_project_directory}' unexpectedly already exists. Please resolve manually.")
        sys.exit(1)
    except PermissionError:
        print(f"Error: Insufficient permissions to create directory at '{actual_project_directory}'.")
        sys.exit(1)
    except OSError as e:
        print(f"An OS error occurred during directory creation for '{actual_project_directory}': {e}")
        sys.exit(1)

    # 5. Create initial task_definition.md file [cite: 14]
    # The task_id should use the name of the directory that was actually created.
    project_name_for_id = actual_project_directory.name 
    
    task_definition_content = create_project_task_definition_content(
        project_name_for_id,
        hlg_input_text,
        meta_context_input_text
    )
    task_definition_file_path = actual_project_directory / "task_definition.md"

    try:
        with open(task_definition_file_path, "w", encoding="utf-8") as f:
            f.write(task_definition_content)
        print(f"Root task_definition.md created successfully at '{task_definition_file_path}'.")
    except IOError as e:
        print(f"Error writing task_definition.md to '{task_definition_file_path}': {e}")
        # Consider cleanup: If task_definition.md fails, should the created directory be removed?
        # For MVP, leaving the directory might be acceptable.
        sys.exit(1)

    print(f"\nProject '{project_name_for_id}' initialized successfully in '{actual_project_directory}'.")
    print("Next steps: Start Phase 1 work by further editing 'task_definition.md' or by calling p1p2 script.")

if __name__ == "__main__":
    main()