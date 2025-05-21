#!/usr/bin/env python3
# gouai_report_builder.py

import argparse
import os
import sys
from datetime import datetime
import yaml # Assuming PyYAML is used as per KIRQ_Impl_3 and common Python practice
import re 

# Placeholder for actual gouai_llm_api.py import
# Ensure gouai_llm_api.py is in PYTHONPATH or same directory
try:
    import gouai_llm_api # This would be your actual module
except ImportError:
    # Mock a simple version for standalone execution if gouai_llm_api is not yet available
    # In a real scenario, this script would depend on the implemented gouai_llm_api.py
    print("WARNING: gouai_llm_api.py not found. Using mock LLM API.", file=sys.stderr)
    class MockGouaiLLMApi:
        def __init__(self):
            self.config = {"default_model": "mock_model", "temperature": 0.7} # Mock config

        def execute_llm_call(self, prompt, context_texts, task_id_for_log, session_id_for_log):
            print(f"MOCK LLM CALL for task_id: {task_id_for_log}, session_id: {session_id_for_log}", file=sys.stderr)
            print(f"MOCK LLM Prompt: {prompt}", file=sys.stderr)
            # print(f"MOCK LLM Context Texts: {context_texts}", file=sys.stderr) # Can be verbose
            return f"# Mock LLM Report\n\nThis is a mock report based on the prompt and {len(context_texts)} context documents."

        def get_api_config(self): # Added to simulate getting config for logging
             return self.config

    gouai_llm_api = MockGouaiLLMApi()


# --- Constants for GOUAI File System Structure ---
TASK_DEFINITION_MD = "task_definition.md"
LIVING_DOCUMENT_MD = "living_document.md"
LLM_CONVERSATION_LOG_MD = "llm_conversation_log.md"
PROJECT_ROOT_DIR_NAME = "." # Assuming the script is run from within the project or task path needs to be absolute/relative

# --- Report Meta-Prompts ---

PROJECT_STATUS_SUMMARY_PROMPT = """
You are an expert project management assistant. Based on the provided GOUAI task_definition.md files for a project and its direct sub-tasks, generate a concise "Project Status Summary" in Markdown format.

The context includes one or more task_definition.md file contents. The first task_definition.md provided is for the main project, and any subsequent ones are for its direct sub-tasks.

Your summary should include:
1.  **Overall Project Goal & Current Status:** From the main project's task_definition.md, briefly state its HLG (High-Level Goal) or WSOD (Workable Stated Output Descriptor) summary (look for `HLG_summary` or `WSOD_summary` in YAML frontmatter, or HLG/WSOD sections in Markdown body) and its current 'status' field from the YAML frontmatter.
2.  **Sub-Task Overview:** For each direct sub-task's task_definition.md provided in the context, list:
    * Task ID (from `task_id` in YAML frontmatter)
    * HLG/Description (from `HLG_summary` or `WSOD_summary` in YAML frontmatter, or HLG section in Markdown body)
    * Current 'status' (from YAML frontmatter)
3.  **Key Accomplishments (Optional, if discernible from status or other fields):** If status fields or other information clearly indicate recent major accomplishments, briefly note them.
4.  **Blockers or Critical Uncertainties (Optional, if discernible from status or uncertainty sections):** If status fields or uncertainty sections within the provided task definitions highlight critical blockers or new major uncertainties impacting the project, briefly note them.

Format the output clearly using Markdown headings and bullet points. If specific information (e.g., WSOD_summary) is not found in a task_definition, note that it's "not available" or "not specified" rather than failing. Structure the report logically.
"""

TASK_UNCERTAINTY_LIST_PROMPT = """
You are an expert GOUAI analyst. Based on the provided task_definition.md and potentially a living_document.md for a specific GOUAI task, generate a "Task Uncertainty List" in Markdown format.

The context includes the content of the task_definition.md and, if provided, the living_document.md for the task.

Your summary should:
1.  From the task_definition.md, examine the YAML frontmatter for any explicit uncertainty fields and the Markdown body for sections like 'WSOD Assessment (Initial)' (especially epistemic/aleatoric uncertainties sub-sections) and 'Phase 2: IE Uncertainty Overview'.
2.  If living_document.md content is provided, examine it for sections like 'Key Questions or Uncertainties'.
3.  Extract all explicitly stated epistemic and aleatoric uncertainties from these documents and sections.
4.  For each uncertainty, list its description.
5.  If available, include any noted potential impact or context for the uncertainty.
6.  Organize the list clearly, ideally grouping by source (e.g., "From task_definition.md - WSOD Assessment", "From living_document.md - Key Questions").

Format the output clearly using Markdown headings and bullet points. If no uncertainties are found in a specific section or document, state that.
"""

def load_file_content(file_path):
    """Loads content from a file. Returns content as string or None if error."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"Error: File not found at {file_path}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error reading file {file_path}: {e}", file=sys.stderr)
        return None

def get_direct_child_task_dirs(parent_task_path):
    """Finds direct child task directories (heuristic: starts with ST, T, or similar GOUAI task patterns)."""
    child_dirs = []
    if not os.path.isdir(parent_task_path):
        return child_dirs
    for item in os.listdir(parent_task_path):
        item_path = os.path.join(parent_task_path, item)
        # Basic heuristic: GOUAI task directories might have a recognizable pattern
        # This might need refinement based on actual GOUAI task ID/directory naming conventions
        if os.path.isdir(item_path) and (item.startswith("ST") or item.startswith("T") or "_ST" in item or "_TASK" in item):
            child_dirs.append(item_path)
    return child_dirs


def generate_project_status_summary(project_id_path_str: str, llm_api_module): # llm_api_module is the imported gouai_llm_api
    """Generates the Project Status Summary report."""
    print(f"Generating Project Status Summary for project at: {project_id_path_str}", file=sys.stderr)
    project_root_for_api = project_id_path_str # Used for LLM API config path

    # 1. Load root project's task_definition.md
    root_td_path = os.path.join(project_id_path_str, TASK_DEFINITION_MD)
    root_td_content = load_file_content(root_td_path)
    if not root_td_content:
        print(f"Error: Could not load root task definition from {root_td_path}", file=sys.stderr)
        return None

    # Prepare the full content for the LLM
    full_prompt_parts = [PROJECT_STATUS_SUMMARY_PROMPT] # The main instruction prompt
    full_prompt_parts.append("\n\n--- Context from Task Definition Files ---")
    
    full_prompt_parts.append(f"\n\n## Content from: {root_td_path}\n")
    full_prompt_parts.append(root_td_content)

    # 2. Load direct child tasks' task_definition.md
    child_task_dirs = get_direct_child_task_dirs(project_id_path_str)
    loaded_child_td_count = 0
    for child_dir_path in child_task_dirs:
        child_td_path = os.path.join(child_dir_path, TASK_DEFINITION_MD)
        child_td_content = load_file_content(child_td_path)
        if child_td_content:
            full_prompt_parts.append(f"\n\n## Content from: {child_td_path}\n")
            full_prompt_parts.append(child_td_content)
            loaded_child_td_count +=1
        else:
            print(f"Warning: Could not load task definition from child task at {child_td_path}", file=sys.stderr)

    final_llm_content_input = "\n".join(full_prompt_parts)
    
    print(f"Invoking LLM for Project Status Summary. Root context + {loaded_child_td_count} child contexts.", file=sys.stderr)
    
    session_id = f"report_pss_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    
    # Determine task_id for logging (usually the project root task_id from its YAML)
    project_task_id_for_log = os.path.basename(os.path.normpath(project_id_path_str)) # Fallback
    try:
        # Extract task_id from YAML frontmatter of the root task_definition.md
        # Assuming '---' delimiters for YAML frontmatter
        yaml_match = re.search(r"^---\s*\n(.*?)\n---\s*\n", root_td_content, re.DOTALL | re.MULTILINE)
        if yaml_match:
            root_yaml_frontmatter = yaml.safe_load(yaml_match.group(1))
            if isinstance(root_yaml_frontmatter, dict):
                 project_task_id_for_log = root_yaml_frontmatter.get('task_id', project_task_id_for_log)
    except Exception as e:
        print(f"Warning: Could not parse task_id from root task_definition.md YAML: {e}", file=sys.stderr)
        pass

    # Call the actual function from gouai_llm_api module
    response_data = llm_api_module.generate_response_aggregated(
        project_root=project_root_for_api,    # For API config loading
        session_id=session_id,
        task_id=project_task_id_for_log,      # For LLM conversation logging
        contents=final_llm_content_input      # The full prompt including context
    )

    if response_data and response_data.get('error_info'):
        error_detail = response_data['error_info']
        print(f"LLM call failed: {error_detail.get('type')} - {error_detail.get('message')}", file=sys.stderr)
        return f"# Report Generation Failed\n\nLLM Error: {error_detail.get('message', 'Unknown error')}"
    
    report_text = response_data.get('text') if response_data else None
    if not report_text:
        print("LLM call did not return any text content.", file=sys.stderr)
        return "# Report Generation Failed\n\nLLM did not return text content."
        
    return report_text


def generate_task_uncertainty_list(task_id_path, llm_api_instance):
    """Generates the Task Uncertainty List report."""
    print(f"Generating Task Uncertainty List for task at: {task_id_path}", file=sys.stderr)
    context_texts = []

    # 1. Load target task's task_definition.md
    td_path = os.path.join(task_id_path, TASK_DEFINITION_MD)
    td_content = load_file_content(td_path)
    if not td_content:
        print(f"Error: Could not load task definition from {td_path}", file=sys.stderr)
        return None
    context_texts.append({"source": td_path, "content": td_content})

    # 2. Load target task's living_document.md (optional)
    ld_path = os.path.join(task_id_path, LIVING_DOCUMENT_MD)
    ld_content = load_file_content(ld_path)
    if ld_content:
        context_texts.append({"source": ld_path, "content": ld_content})
    else:
        print(f"Info: living_document.md not found or empty at {ld_path}. Proceeding without it.", file=sys.stderr)

    # Create a unique session ID
    session_id = f"report_tul_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    target_task_id_for_log = os.path.basename(os.path.normpath(task_id_path))

    # Attempt to parse task_id from td_content YAML frontmatter
    try:
        yaml_frontmatter = yaml.safe_load(td_content.split("---")[1])
        target_task_id_for_log = yaml_frontmatter.get('task_id', target_task_id_for_log)
    except Exception:
        pass # Stick with directory name if parsing fails

    print(f"Invoking LLM for Task Uncertainty List. Context items: {len(context_texts)}", file=sys.stderr)
    report_content = llm_api_instance.execute_llm_call(
        prompt=TASK_UNCERTAINTY_LIST_PROMPT,
        context_texts=[item['content'] for item in context_texts],
        task_id_for_log=target_task_id_for_log,
        session_id_for_log=session_id
    )
    return report_content


def main():
    parser = argparse.ArgumentParser(description="GOUAI Report Builder Script (MVP-P1)")
    parser.add_argument("--report_type", choices=["ProjectStatusSummary", "TaskUncertaintyList"],
                        required=True, help="The type of report to generate.")
    parser.add_argument("--id", required=True,
                        help="The path to the GOUAI project root directory (for ProjectStatusSummary) "
                             "or the specific GOUAI task directory (for TaskUncertaintyList).")
    parser.add_argument("--output_file", help="Optional. Path to save the Markdown report. "
                                             "If not provided, prints to standard output.")

    args = parser.parse_args()

    # Validate --id path
    if not os.path.isdir(args.id):
        print(f"Error: Provided ID path '{args.id}' is not a valid directory or does not exist.", file=sys.stderr)
        sys.exit(1)

    # Instantiate the actual LLM API handler
    # For now, it uses the global `gouai_llm_api` which might be the mock or the real one.
    # In a more structured app, this might be initialized and passed around.
    llm_api = gouai_llm_api # Using the globally available instance

    report_content = None
    if args.report_type == "ProjectStatusSummary":
        report_content = generate_project_status_summary(args.id, llm_api)
    elif args.report_type == "TaskUncertaintyList":
        report_content = generate_task_uncertainty_list(args.id, llm_api)
    else:
        # Should be caught by argparse choices, but as a fallback:
        print(f"Error: Unknown report type '{args.report_type}'", file=sys.stderr)
        sys.exit(1)

    if report_content:
        if args.output_file:
            try:
                with open(args.output_file, 'w', encoding='utf-8') as f:
                    f.write(report_content)
                print(f"Report successfully generated and saved to: {args.output_file}", file=sys.stderr)
            except Exception as e:
                print(f"Error writing report to file {args.output_file}: {e}", file=sys.stderr)
                print("\n--- Report Content ---\n", file=sys.stderr) # Print to stderr if file write fails
                print(report_content, file=sys.stderr)
                sys.exit(1)
        else:
            print(report_content)
    else:
        print(f"Report generation failed for type '{args.report_type}' and id '{args.id}'.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()