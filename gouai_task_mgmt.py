#!/usr/bin/env python3

import argparse
import os
import sys
from pathlib import Path
from datetime import datetime
import re
import yaml # For parsing parent task_definition.md YAML

# --- Constants based on WSOD_TaskMgmt ---
TASK_STATUS_NOT_STARTED = "Not Started"
TASK_VERSION_DEFAULT = "1.0"
FULL_GOUAI_TASK_TYPE = "full_GOUAI_task"
SIMPLE_TASK_TYPE = "simple_task"

# --- Helper Functions ---

def _format_yaml_multiline_string(text: str, indent_prefix: str = "  ") -> str:
    """Formats a string for YAML block scalar literal style preserving newlines."""
    if not text.strip():
        return "''" # Represent empty string explicitly in YAML
    
    lines = text.splitlines()
    # The first line doesn't need the initial indent if it's short and on the same line as `key: |`
    # However, for simplicity and consistency with block scalars, we'll use the `|`
    # followed by a newline, then all lines indented.
    indented_lines = [f"{indent_prefix}{line}" for line in lines]
    return "|\n" + "\n".join(indented_lines)


def _parse_parent_task_def(parent_task_def_path: Path) -> tuple[str, str, str]:
    """
    Parses a parent task's task_definition.md to extract its task_id,
    HLG_summary, and WSOD_summary from the YAML frontmatter.

    Args:
        parent_task_def_path: Path to the parent's task_definition.md file.

    Returns:
        A tuple containing (parent_task_id, hlg_summary, wsod_summary).
        hlg_summary and wsod_summary default to "Not available" if not found.

    Raises:
        FileNotFoundError: If the parent task definition file does not exist.
        ValueError: If the file cannot be parsed, or task_id is missing.
    """
    if not parent_task_def_path.is_file():
        raise FileNotFoundError(f"Parent task definition file not found: {parent_task_def_path}")

    with open(parent_task_def_path, 'r', encoding='utf-8') as f:
        content = f.read()

    frontmatter_match = re.search(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL | re.MULTILINE)
    if not frontmatter_match:
        # Attempt to parse as full YAML if no frontmatter delimiters found (less likely for task_def)
        try:
            data = yaml.safe_load(content)
            if not isinstance(data, dict): # Ensure it's a map (dictionary)
                 raise ValueError(f"Content of {parent_task_def_path} is not a YAML map.")
        except yaml.YAMLError as e_yaml: # Catch YAML parsing errors
             raise ValueError(f"Could not parse YAML content in {parent_task_def_path}: {e_yaml}")
    else:
        try:
            data = yaml.safe_load(frontmatter_match.group(1))
        except yaml.YAMLError as e_yaml:
            raise ValueError(f"Error parsing YAML frontmatter in {parent_task_def_path}: {e_yaml}")

    if not isinstance(data, dict):
        raise ValueError(f"Parsed YAML from {parent_task_def_path} is not a dictionary.")

    parent_task_id = data.get('task_id', '')
    hlg_summary = data.get('HLG_summary', 'Not available') # Default if not found
    wsod_summary = data.get('WSOD_summary', 'Not available') # Default if not found

    if not parent_task_id: # task_id is mandatory
        raise ValueError(f"Parent task_id not found in YAML of {parent_task_def_path}")

    return parent_task_id, hlg_summary, wsod_summary


def _generate_task_id_and_dir_name(
    parent_task_id_str: str,
    parent_task_dir_path: Path,
    task_type_str: str,
    name_suffix_str: str | None
) -> tuple[str, str]:
    """
    Generates the new task_id and its corresponding directory_name.
    Based on WSOD_TaskMgmt Section 3.B.ii.
    """
    # 1. Determine NewLevel for ST<Level>-<Index>
    new_level = 1
    st_matches = list(re.finditer(r"_ST(\d+)-(\d+)", parent_task_id_str))
    if st_matches:
        last_st_match = st_matches[-1]
        parent_level = int(last_st_match.group(1))
        new_level = parent_level + 1

    # 2. Determine NewIndex for ST<Level>-<Index>
    new_index = 1
    existing_indices_for_level = []
    if parent_task_dir_path.exists() and parent_task_dir_path.is_dir():
        for item in parent_task_dir_path.iterdir():
            if item.is_dir():
                # Match directory names like ST<NewLevel>-<Index> or ST<NewLevel>-<Index>_Suffix...
                dir_name_match = re.match(rf"ST{new_level}-(\d+)(?:_.*)?", item.name)
                if dir_name_match:
                    existing_indices_for_level.append(int(dir_name_match.group(1)))
    
    if existing_indices_for_level:
        new_index = max(existing_indices_for_level) + 1
    
    base_name_segment = f"ST{new_level}-{new_index}"

    # 3. Construct DirectoryName
    directory_name = base_name_segment
    if task_type_str == SIMPLE_TASK_TYPE:
        directory_name += "_Simple"
    
    if name_suffix_str:
        # Sanitize suffix: replace spaces/multiple underscores with single underscore, remove other problematic chars
        safe_suffix = re.sub(r'\s+', '_', name_suffix_str.strip()) # Trim and replace spaces
        safe_suffix = re.sub(r'_+', '_', safe_suffix) # Consolidate multiple underscores
        safe_suffix = re.sub(r'[^\w\-_]', '', safe_suffix) # Keep word chars, hyphen, underscore
        if safe_suffix: # Ensure suffix is not empty after sanitization
             directory_name += f"_{safe_suffix}"

    # 4. Construct Full New Task ID
    new_task_id = f"{parent_task_id_str}_{directory_name}"
    
    return new_task_id, directory_name


def _create_task_definition_md(
    task_dir_path: Path,
    task_id: str,
    parent_task_id: str,
    task_type: str,
    input_text: str,
    parent_hlg_summary: str,
    parent_wsod_summary: str
):
    """Creates the task_definition.md file based on WSOD_TaskMgmt Section 3.B.iv."""
    timestamp = datetime.now().isoformat()
    
    yaml_frontmatter_parts = [
        f"task_id: {task_id}",
        f"parent_task_id: {parent_task_id}",
        f"creation_date: \"{timestamp}\"", # Enclose timestamps in quotes for YAML safety
        f"last_modified_date: \"{timestamp}\"",
        f"status: \"{TASK_STATUS_NOT_STARTED}\"",
        f"version: \"{TASK_VERSION_DEFAULT}\"",
        f"task_type: \"{task_type}\"",
    ]
    markdown_body = ""

    if task_type == FULL_GOUAI_TASK_TYPE:
        hlg_summary = input_text.splitlines()[0].strip() if input_text.strip() else "To be defined."
        yaml_frontmatter_parts.extend([
            f"HLG_summary: \"{hlg_summary}\"", # Ensure summaries are quoted
            f"WSOD_summary: \"To be defined.\"",
        ])
        
        meta_context_content = (
            f"This task ({task_id}) is a sub-task of {parent_task_id}.\n\n"
            f"- Parent Task Definition: `../task_definition.md`\n"
            f"- Parent HLG Summary: \"{parent_hlg_summary}\"\n"
            f"- Parent WSOD Summary: \"{parent_wsod_summary}\"\n\n"
            "It is recommended to review the full parent task documentation for relevant constraints, "
            "values, audience/use context, and any overarching goals or uncertainties that may "
            "influence this sub-task. Explicitly define any meta-context specific to this sub-task below."
        )
        
        # Content based on WSOD_TaskMgmt (derived from gouai_project_init.py and GOUAI doc structure [cite: 264])
        markdown_body_parts = [
            f"## High-Level Goal(s) (HLG)\n\n{input_text}\n",
            f"## Meta-Context\n\n{meta_context_content}\n",
            "## Goal Space Exploration Summary\n(To be filled during GOUAI Phase 1 for this task)\n",
            "## Candidate Workable Stated Output Descriptor(s) (cWSODs)\n(To be filled during GOUAI Phase 1 for this task)\n",
            "## Workable Stated Output Descriptor (WSOD) - Full Statement\n(To be filled during GOUAI Phase 1 for this task)\n",
            "## WSOD Assessment (Initial)\n(To be filled during GOUAI Phase 1 for this task)", # [cite: 265]
            "### Epistemic Uncertainties\n(List identified epistemic uncertainties related to achieving the WSOD for this sub-task. Consider any uncertainties inherited or implied by the parent task's context or the nature of this sub-task's HLG.)",
            "### Aleatoric Uncertainties\n(List identified aleatoric uncertainties related to this sub-task.)",
            "### HLG Alignment/Risk\n(Assess alignment with this sub-task's HLG and any risks.)",
            "### Key Information Requirements\n(List key information required to resolve uncertainties or complete the WSOD for this sub-task.)\n", # [cite: 265]
            "## Phase 2: Information Requirements & Query Formulation Summary\n(To be filled during GOUAI Phase 2 for this task)\n", # [cite: 265]
            "## Phase 2: Information Elements (IEs) Summary/Index\n(To be filled during GOUAI Phase 2 for this task)\n", # [cite: 265]
            "## Phase 2: IE Uncertainty Overview\n(To be filled during GOUAI Phase 2 for this task)\n", # [cite: 265]
            "## Phase 2: Sufficiency Check Notes\n(To be filled during GOUAI Phase 2 for this task)\n", # [cite: 265]
            "## Integrated WSOD with Uncertainties and KIRQs (for Context Generation)\n(This section presents the WSOD decomposed with associated EUs/KIRQs for each component, for context packaging)\n" # [cite: 266]
        ]
        markdown_body = "\n".join(markdown_body_parts)

    elif task_type == SIMPLE_TASK_TYPE:
        # Based on 1.2_SystemArchitecture.txt
        first_meaningful_line = input_text.strip().splitlines()[0].strip() if input_text.strip() else "Simple task description"
        clean_one_line_desc = first_meaningful_line.replace('"', '') # Escape double quotes
        yaml_frontmatter_parts.append(f"one_line_description: \"{clean_one_line_desc}\"")
        markdown_task_description_content = input_text # Keep this for the body

        markdown_body = (
            f"## Task Description\n\n{markdown_task_description_content}\n\n"
            "(This is a simple task. Formal GOUAI sections are not applicable. "
            "Outputs should be stored in the 'outputs/' directory, and LLM interactions "
            "logged in 'llm_conversation_log.md'.)\n"
        )

    yaml_frontmatter_str = "\n".join(yaml_frontmatter_parts)
    full_content = f"---\n{yaml_frontmatter_str}\n---\n{markdown_body}"
    
    file_path = task_dir_path / "task_definition.md"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(full_content)
    print(f"Created: {file_path.relative_to(task_dir_path.parent.parent) if task_dir_path.parent.parent else file_path}")


def _create_living_document_md(task_dir_path: Path, task_id: str, task_type: str):
    """Creates the living_document.md file based on WSOD_TaskMgmt."""
    content = ""
    if task_type == FULL_GOUAI_TASK_TYPE:
        content = f"""\
# Living Document for Task: {task_id}

## Formal link to task_definition.md
- ./task_definition.md

## Link to full LLM Chat Log(s)
- ./llm_conversation_log.md

## Chronological Log of Tasking Completed (and when)
(Record key actions, decisions, and dates here as the task progresses)

## Key Questions or Uncertainties
(Log questions, evolving uncertainties, and insights here)

## Definitions and Terminology
(Define key terms, concepts, and acronyms specific to this task)

## Resources & References
(List any important external resources, documents, or links)

## Notes & Scratchpad
(General notes, ideas, or intermediate findings)
"""
    elif task_type == SIMPLE_TASK_TYPE:
        content = f"""\
# Living Document for Simple Task: {task_id}

## Formal link to task_definition.md
- ./task_definition.md

## Link to full LLM Chat Log(s)
- ./llm_conversation_log.md

## Notes
(Brief notes, context, or reminders related to this simple task, if any. The primary record of interaction should be in llm_conversation_log.md and outputs in the outputs/ directory.)
"""
    file_path = task_dir_path / "living_document.md"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Created: {file_path.relative_to(task_dir_path.parent.parent) if task_dir_path.parent.parent else file_path}")


def _create_llm_conversation_log_md(task_dir_path: Path, task_id: str):
    """Creates the llm_conversation_log.md file with YAML frontmatter based on WSOD_TaskMgmt / 1.2_SystemArchitecture.txt."""
    yaml_frontmatter = f"""\
session_id: null
task_id: {task_id}
llm_model_used: null
session_start_timestamp: null
api_request_id_initial: null
total_tokens_used: 0
total_cost_estimate: 0.0
"""
    markdown_body = "## LLM Conversation Log\n"
    full_content = f"---\n{yaml_frontmatter}---\n{markdown_body}"
    
    file_path = task_dir_path / "llm_conversation_log.md"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(full_content)
    print(f"Created: {file_path.relative_to(task_dir_path.parent.parent) if task_dir_path.parent.parent else file_path}")


def _create_empty_dirs(task_dir_path: Path):
    """Creates empty outputs/ and context_packages/ directories."""
    outputs_path = task_dir_path / "outputs"
    context_packages_path = task_dir_path / "context_packages"
    
    outputs_path.mkdir(exist_ok=True)
    context_packages_path.mkdir(exist_ok=True)
    print(f"Created: {outputs_path.relative_to(task_dir_path.parent.parent) if task_dir_path.parent.parent else outputs_path}/")
    print(f"Created: {context_packages_path.relative_to(task_dir_path.parent.parent) if task_dir_path.parent.parent else context_packages_path}/")


# --- Core Function ---
def create_task(
    parent_dir_path_str: str,
    task_type_str: str,
    input_text_str: str,
    name_suffix_str: str | None = None
):
    """
    Creates a new GOUAI sub-task directory and initial files.
    This function implements the core logic defined in WSOD_TaskMgmt.
    """
    parent_dir_path = Path(parent_dir_path_str).resolve()
    if not parent_dir_path.is_dir():
        print(f"Error: Parent directory '{parent_dir_path}' does not exist or is not a directory.")
        sys.exit(1)

    parent_task_def_path = parent_dir_path / "task_definition.md"
    try:
        parent_task_id_str, parent_hlg_summary, parent_wsod_summary = _parse_parent_task_def(parent_task_def_path)
    except Exception as e:
        print(f"Error parsing parent task definition '{parent_task_def_path}': {e}")
        sys.exit(1)

    if task_type_str not in [FULL_GOUAI_TASK_TYPE, SIMPLE_TASK_TYPE]:
        print(f"Error: Invalid task type '{task_type_str}'. Must be '{FULL_GOUAI_TASK_TYPE}' or '{SIMPLE_TASK_TYPE}'.")
        sys.exit(1)
    if not input_text_str.strip():
        print(f"Error: --input_text cannot be empty.")
        sys.exit(1)


    new_task_id, new_task_dir_name = _generate_task_id_and_dir_name(
        parent_task_id_str, parent_dir_path, task_type_str, name_suffix_str
    )
    
    new_task_path = parent_dir_path / new_task_dir_name

    try:
        new_task_path.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        print(f"Error: Task directory '{new_task_path}' already exists. Possible indexing issue or manual conflict.")
        sys.exit(1)
    except OSError as e:
        print(f"Error creating task directory '{new_task_path}': {e}")
        sys.exit(1)
    print(f"\nCreated task directory: {new_task_path}")

    # Create stub files
    try:
        _create_task_definition_md(
            new_task_path, new_task_id, parent_task_id_str, task_type_str,
            input_text_str, parent_hlg_summary, parent_wsod_summary
        )
        _create_living_document_md(new_task_path, new_task_id, task_type_str)
        _create_llm_conversation_log_md(new_task_path, new_task_id)
        _create_empty_dirs(new_task_path)
    except Exception as e:
        print(f"Error creating stub files for task '{new_task_id}' in '{new_task_path}': {e}")
        # Consider cleanup logic here for a more robust script
        sys.exit(1)

    print(f"\nSuccessfully created GOUAI task '{new_task_id}'.")
    print(f"Location: {new_task_path.resolve()}")
    print("\nNext steps: Navigate to the new task directory and begin your GOUAI work by editing its 'task_definition.md'.")
    
    return new_task_id, new_task_path


# --- Main CLI Logic ---

def find_task_dir_path_from_id(current_search_path: Path, target_task_id: str, project_root_path: Path) -> Path | None:
    """
    Recursively searches for a task directory by its task_id.
    It checks task_definition.md in `current_search_path` and its subdirectories (excluding common non-task dirs).
    """
    # Check current directory
    task_def_path = current_search_path / "task_definition.md"
    if task_def_path.is_file():
        try:
            # Only read the task_id from YAML to speed up search
            with open(task_def_path, 'r', encoding='utf-8') as f:
                # Quick check for task_id in the first few lines to avoid full parse if not necessary
                # This is an optimization; full parse is safer if YAML is complex
                file_content_head = "".join(f.readline() for _ in range(15)) # Read first 15 lines
            
            id_match = re.search(r"task_id:\s*([^\s]+)", file_content_head)
            if id_match and id_match.group(1).strip().strip('"').strip("'") == target_task_id:
                return current_search_path
        except Exception:
            # If parsing fails for any reason, this directory doesn't match.
            print('parsing failed')
            pass # Continue search

    # Recursively check subdirectories, only if current_search_path is a directory
    if current_search_path.is_dir():
        for item in current_search_path.iterdir():
            if item.is_dir():
                # Avoid recursing into known non-task or output directories
                if item.name in ["outputs", "context_packages", ".git", ".venv", "__pycache__"] or item.name.startswith('.'):
                    continue
                
                # Prevent going "up" or outside project boundaries for safety, though Pathlib handles '.' and '..'
                # Ensure we are still within the project_root_path
                try:
                    item.relative_to(project_root_path)
                except ValueError: # Item is outside project_root_path
                    continue

                found_path = find_task_dir_path_from_id(item, target_task_id, project_root_path)
                if found_path:
                    return found_path
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Creates a new GOUAI sub-task (full GOUAI or simple) within a parent task, inside a GOUAI project.",
        formatter_class=argparse.RawTextHelpFormatter # Allows for better help text formatting
    )
    parser.add_argument(
        "--parent_id",
        required=True,
        help="The full string ID of the parent task (e.g., 'MyProject_ROOT' or 'MyProject_ROOT_ST1-1_Research').\n"
             "The script will search for this parent task directory starting from the --project_path."
    )
    parser.add_argument(
        "--project_path",
        required=True,
        help="The path to the root directory of the GOUAI project (e.g., './my_gouai_projects/MyProjectName')."
    )
    parser.add_argument(
        "--type",
        required=True,
        choices=[FULL_GOUAI_TASK_TYPE, SIMPLE_TASK_TYPE],
        help=f"The type of task to create: '{FULL_GOUAI_TASK_TYPE}' or '{SIMPLE_TASK_TYPE}'."
    )
    parser.add_argument(
        "--input_text",
        required=True,
        help="For 'full_GOUAI_task': The High-Level Goal (HLG) for the new task.\n"
             "For 'simple_task': A concise description of the task."
    )
    parser.add_argument(
        "--name_suffix",
        default=None,
        help="Optional suffix to append to the auto-generated task directory name and ID for better readability\n"
             "(e.g., 'Research', 'DataAnalysis'). Spaces will be replaced by underscores. "
             "Allowed characters: alphanumeric, underscore, hyphen."
    )

    args = parser.parse_args()

    project_root_path = Path(args.project_path).resolve()
    if not project_root_path.is_dir():
        print(f"Error: Project path '{project_root_path}' does not exist or is not a directory.")
        sys.exit(1)
    
    # Verify project_root_path itself is a GOUAI project root (contains a task_definition.md)
    if not (project_root_path / "task_definition.md").is_file():
        print(f"Error: '{project_root_path}' does not appear to be a GOUAI project root (missing task_definition.md).")
        sys.exit(1)

    print(f"Searching for parent task ID '{args.parent_id}' within project '{project_root_path}'...")
    parent_task_dir = find_task_dir_path_from_id(project_root_path, args.parent_id, project_root_path)

    if not parent_task_dir:
        print(f"Error: Could not find parent task directory for ID '{args.parent_id}' within project '{project_root_path}'.")
        print("Please ensure the parent_id is correct and the task exists within the specified project structure.")
        sys.exit(1)
    
    print(f"Found parent task directory at: {parent_task_dir.resolve()}")

    try:
        create_task(
            parent_dir_path_str=str(parent_task_dir),
            task_type_str=args.type,
            input_text_str=args.input_text,
            name_suffix_str=args.name_suffix
        )
    except SystemExit: # Allow SystemExit from create_task to pass through
        raise
    except Exception as e:
        print(f"An unexpected error occurred in main execution: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()