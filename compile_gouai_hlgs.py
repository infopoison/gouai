# compile_gouai_hlgs.py (Modified to exclude 'Completed' tasks)

import argparse
from pathlib import Path
import re
import yaml # To parse YAML frontmatter for HLG_summary and task_id
import datetime
import sys

# --- GOUAI Module Imports ---
try:
    from gouai_llm_api import generate_response_aggregated, LLMAPICallError, ConfigurationError
except ImportError:
    print("CRITICAL ERROR: gouai_llm_api.py not found or importable.", file=sys.stderr)
    sys.exit(1)

# --- Helper Functions ---

def _extract_yaml_and_content(file_path: Path) -> tuple[dict, str]:
    """
    Extracts YAML frontmatter and remaining Markdown content.
    Returns (yaml_data_dict, markdown_body_str).
    If no valid YAML frontmatter, returns ({}, full_file_content).
    """
    if not file_path.is_file():
        return {}, ""
    
    content = file_path.read_text(encoding='utf-8')
    
    # Remove potential BOM and leading whitespace
    if content.startswith('\ufeff'):
        content = content[1:]
    content_stripped = content.lstrip()

    frontmatter_match = re.search(r"^(---)\s*\n(.*?)\n(---)\s*\n(.*)", content_stripped, re.DOTALL | re.MULTILINE)
    
    yaml_data = {}
    markdown_body = content_stripped # Default to full content if no frontmatter

    if frontmatter_match:
        try:
            yaml_data = yaml.safe_load(frontmatter_match.group(2))
            markdown_body = frontmatter_match.group(4).strip() # The content after the second '---'
        except yaml.YAMLError:
            # If YAML is malformed, treat the whole file as markdown body
            pass
    return yaml_data, markdown_body

def _get_hlg_from_task_definition(task_def_path: Path) -> str:
    """
    Extracts the most comprehensive HLG from a task_definition.md file.
    Prioritizes the full HLG section content if available, falling back to 
    HLG_summary/one_line_description from YAML.
    """
    yaml_data, markdown_body = _extract_yaml_and_content(task_def_path)
    
    extracted_hlg_text = ""

    # Try to extract the full HLG text from the markdown section
    # This regex now captures content until the next '##' header or end of document
    hlg_section_match = re.search(
        r"##\s*High-Level Goal\(s\)\s*\(HLG\)\s*\n+(.*?)(?=\n##\s*|$)", # Added \n+ to ensure it matches newlines after header
        markdown_body, 
        re.DOTALL | re.IGNORECASE # Use IGNORECASE for robustness against minor header variations
    )
    if hlg_section_match:
        extracted_hlg_text = hlg_section_match.group(1).strip()
        # If the extracted HLG section text contains EUs/KIRQs headers, it's the comprehensive one.
        # Check for initial EUs/KIRQs within this block (as seen in your example `task_definition.md`).
        if "### Initial Epistemic Uncertainties" in extracted_hlg_text or \
           "### Initial Key Information Requirements" in extracted_hlg_text:
            return extracted_hlg_text

    # If the comprehensive HLG section wasn't found or didn't contain EUs/KIRQs,
    # fall back to the HLG_summary from YAML.
    hlg_summary = yaml_data.get('HLG_summary')
    if hlg_summary and hlg_summary.strip() and hlg_summary.lower() != "to be defined.":
        return hlg_summary.strip()

    # If it's a simple task, check for 'one_line_description' in YAML
    if yaml_data.get('task_type') == "simple_task":
        one_line_desc = yaml_data.get('one_line_description')
        if one_line_desc and one_line_desc.strip():
            return one_line_desc.strip()
        # Also check for 'Task Description' section in simple tasks
        task_desc_match = re.search(
            r"##\s*Task Description\s*\n+(.*?)(?=\n##\s*|$)",
            markdown_body,
            re.DOTALL | re.IGNORECASE
        )
        if task_desc_match:
            return task_desc_match.group(1).strip()

    # If all else fails, return the best effort extracted HLG text (could be empty or a generic statement)
    if extracted_hlg_text:
        return extracted_hlg_text
    
    return "HLG not found or not explicitly defined."
    
def _get_task_id_from_task_definition(task_def_path: Path) -> str:
    """Extracts the task_id from the YAML frontmatter of a task_definition.md file."""
    yaml_data, _ = _extract_yaml_and_content(task_def_path)
    return yaml_data.get('task_id', 'UNKNOWN_TASK_ID')

def _get_task_status_from_task_definition(task_def_path: Path) -> str:
    """Extracts the status from the YAML frontmatter of a task_definition.md file."""
    yaml_data, _ = _extract_yaml_and_content(task_def_path)
    return yaml_data.get('status', 'Unknown Status')


def _summarize_outputs_folder(outputs_path: Path) -> list[str]:
    """
    Summarizes the contents of an 'outputs/' folder.
    Lists up to 5 files and mentions if more exist.
    """
    summary_lines = []
    if outputs_path.is_dir():
        all_files = [item for item in outputs_path.iterdir() if item.is_file()]
        if all_files:
            summary_lines.append("Contains the following files:")
            for i, file_path in enumerate(sorted(all_files)):
                if i >= 5:
                    summary_lines.append(f"    ... and {len(all_files) - 5} more files.")
                    break
                summary_lines.append(f"    - {file_path.name}")
        else:
            summary_lines.append("Outputs folder is empty.")
    else:
        summary_lines.append("No 'outputs/' folder found.")
    return summary_lines

def compile_hlgs_and_outputs(project_root_path: Path) -> str:
    """
    Traverses the project directory, extracts HLGs and output summaries,
    and compiles them into a hierarchical Markdown string.
    """
    compiled_report_lines = []
    
    # Use a stack for depth-first traversal to maintain hierarchy
    # Stack items: (path, current_depth)
    stack = [(project_root_path, 0)]
    
    # Keep track of directories already processed to avoid infinite loops if symlinks create cycles
    processed_dirs = set()

    while stack:
        current_path, depth = stack.pop()

        if current_path in processed_dirs:
            continue
        processed_dirs.add(current_path)

        # Skip common non-task directories
        if current_path.name in ["context_packages", "outputs", ".git", ".venv", "__pycache__"] or current_path.name.startswith('.'):
            continue
        
        # Check if current_path is a task directory (contains task_definition.md)
        task_def_path = current_path / "task_definition.md"
        is_task_dir = task_def_path.is_file()

        prefix = "  " * depth
        
        if is_task_dir:
            task_status = _get_task_status_from_task_definition(task_def_path)
            if task_status.lower() == "completed":
                # If the task is completed, skip it and all its subdirectories
                print(f"INFO: Skipping completed task and its subtasks: {current_path.name}/ (Status: {task_status})", file=sys.stderr)
                continue # Skip processing this directory and don't add its subdirectories to stack
            
            task_id = _get_task_id_from_task_definition(task_def_path)
            hlg = _get_hlg_from_task_definition(task_def_path)
            
            compiled_report_lines.append(f"{prefix}- **Directory:** `{current_path.name}/`")
            compiled_report_lines.append(f"{prefix}  **Task ID:** `{task_id}`")
            compiled_report_lines.append(f"{prefix}  **HLG:** {hlg}")
            compiled_report_lines.append(f"{prefix}  **Status:** {task_status}") # Include status in report

            outputs_path = current_path / "outputs"
            output_summary = _summarize_outputs_folder(outputs_path)
            if output_summary:
                compiled_report_lines.append(f"{prefix}  **Outputs Summary:**")
                for line in output_summary:
                    compiled_report_lines.append(f"{prefix}    {line}")
            compiled_report_lines.append("") # Empty line for spacing
        else:
            # If not a task directory, still list it but without HLG/outputs
            if current_path != project_root_path: # Don't re-list root if it's not a task itself
                compiled_report_lines.append(f"{prefix}- **Directory:** `{current_path.name}/` (Not a GOUAI Task Directory)")
                compiled_report_lines.append("") # Empty line for spacing

        # Add subdirectories to the stack for further processing
        # Iterate in reverse to maintain alphabetical order when popping
        sub_dirs = sorted([d for d in current_path.iterdir() if d.is_dir() and d not in processed_dirs], reverse=True)
        for sub_dir in sub_dirs:
            stack.append((sub_dir, depth + 1))

    return "\n".join(compiled_report_lines)

# --- New function for LLM-based analysis and suggestions ---
def analyze_and_suggest_hierarchy_updates(
    project_root_path: Path, 
    compiled_hlgs_and_outputs: str, 
    review_material: str
) -> str:
    """
    Constructs a prompt for the LLM to analyze the project hierarchy and review material,
    then calls the LLM to get suggestions for updates or refactoring.
    """
    prompt_parts = [
        "You are an expert GOUAI process analyst. Your task is to analyze a GOUAI project's current task hierarchy and its outputs, alongside new review material. Based on this analysis, you should suggest potential updates to the existing context for tasks or (much more rarely) refactoring of the subtask breakdown to better integrate the new context. Provide your suggestions in a clear, actionable Markdown format, categorized by type of suggestion.",
        "Consider the following aspects in your analysis, but only suggest any of them if there is clear justification for doing so. These should be rare events, and it is more likely that the reflections merely provide additional context rather than a genuine restructuring of goals and objectives. ", # Final prompt from user
        "-   Are there new high-level goals emerging from the review material that are not adequately covered by the existing project or its tasks?", 
        "-   Does the review material suggest that existing tasks or subtasks need their HLGs, EUs, or KIRQs updated?",
        "-   Are there opportunities to combine or split existing subtasks to better align with the new context?",
        "-   Does the review material suggest a re-prioritization or re-ordering of tasks?",
        "-   Are there any gaps in the existing project structure that the review material highlights?",
        "-   Suggest any changes to the `task_definition.md` structure or content of specific tasks.",
        "\n--- Current GOUAI Project Hierarchy & Outputs ---",
        compiled_hlgs_and_outputs,
        "\n--- New Review Material ---",
        review_material,
        "\n--- Your Analysis and Suggestions ---",
        "\nPlease provide your suggestions using the following Markdown structure:",
        "## Suggested Hierarchy Updates",
        "### High-Level Goal / Project Scope Adjustments",
        "- [Suggestion 1]",
        "- [Suggestion 2]",
        "### Task/Subtask Refactoring Suggestions",
        "- **Task ID / Directory Name:** [ID/Name]",
        "  - **Suggestion:** [Detail of refactoring, e.g., 'Update HLG to better reflect X', 'Split into two subtasks: A and B']",
        "- **Task ID / Directory Name:** [ID/Name]",
        "  - **Suggestion:** [Detail]",
        "### New Task/Subtask Proposals",
        "- **HLG:** [Proposed HLG for new task]",
        "  - **Justification:** [Why this new task is needed based on review material]",
        "  - **Parent Suggestion (Optional):** [e.g., 'Under ROOT', 'Under ST1-X']",
        "### Other Recommendations",
        "- [General recommendation 1]",
        "- [General recommendation 2]",
    ]
    llm_prompt = "\n".join(prompt_parts)

    print("INFO: Calling LLM to analyze and suggest hierarchy updates...")
    session_id = f"hierarchy_analysis_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    try:
        response_data = generate_response_aggregated(
            project_root=str(project_root_path),
            session_id=session_id,
            task_id="system_review", # A special task ID for logging system-level LLM calls
            contents=llm_prompt
        )

        if response_data.get('error_info'):
            error_details = response_data['error_info']
            print(f"ERROR: LLM API call failed during hierarchy analysis: {error_details.get('type')} - {error_details.get('message')}", file=sys.stderr)
            return "ERROR: LLM analysis failed."
        
        llm_suggestions = response_data.get('text')
        if not llm_suggestions:
            print("ERROR: LLM returned no text content for hierarchy suggestions.", file=sys.stderr)
            return "No suggestions returned by LLM."
        
        print("INFO: LLM analysis and suggestions received.")
        return llm_suggestions

    except ConfigurationError as e:
        print(f"ERROR: LLM Configuration Error during hierarchy analysis: {e}", file=sys.stderr)
        return "ERROR: LLM Configuration Error."
    except LLMAPICallError as e:
        print(f"ERROR: LLM API Call Error during hierarchy analysis: {e}", file=sys.stderr)
        return "ERROR: LLM API Call Error."
    except Exception as e:
        print(f"ERROR: Unexpected error during LLM call for hierarchy analysis: {type(e).__name__} - {e}", file=sys.stderr)
        return "ERROR: Unexpected error during LLM analysis."


# --- Main function for CLI execution ---
def main():
    parser = argparse.ArgumentParser(
        description="Compile High-Level Goals (HLGs) and Output Summaries from a GOUAI project hierarchy, "
                    "with optional LLM-based analysis and suggestions for updates."
    )
    parser.add_argument(
        "--project_root",
        required=True,
        help="The path to the root directory of the GOUAI project (e.g., './projects')."
    )
    parser.add_argument(
        "--output_file",
        default="gouai_hlg_report.md",
        help="The name of the output Markdown file (e.g., 'report.md'). "
             "This file will be created in the project_root directory."
    )
    parser.add_argument(
        "--review_material_path",
        help="Optional: Path to a text file containing review material for LLM analysis."
    )
    parser.add_argument(
        "--suggestions_output_file",
        default="gouai_review_suggestions.md",
        help="Filename for LLM-generated suggestions if review material is provided. "
             "Saved in the project_root directory. Default: 'gouai_review_suggestions.md'."
    )

    args = parser.parse_args()

    project_root_path = Path(args.project_root).resolve()

    if not project_root_path.is_dir():
        print(f"Error: Project root path '{project_root_path}' does not exist or is not a directory.", file=sys.stderr)
        sys.exit(1)

    print(f"Compiling HLGs and output summaries from: {project_root_path}")
    report_content = compile_hlgs_and_outputs(project_root_path)

    output_file_path = project_root_path / args.output_file

    try:
        with open(output_file_path, "w", encoding='utf-8') as f:
            f.write(f"# GOUAI Project HLG and Output Summary Report\n\n")
            f.write(f"**Generated On:** {datetime.datetime.now().isoformat(timespec='seconds')}\n")
            f.write(f"**Project Root:** `{project_root_path}`\n\n")
            f.write("---\n\n")
            f.write(report_content)
        print(f"Report successfully generated and saved to: {output_file_path}")
    except IOError as e:
        print(f"Error writing report to '{output_file_path}': {e}", file=sys.stderr)
        sys.exit(1)

    # New feature integration: LLM analysis of review material
    if args.review_material_path:
        review_material_path = Path(args.review_material_path).resolve()
        if not review_material_path.is_file():
            print(f"Error: Review material file not found at '{review_material_path}'. Skipping LLM analysis.", file=sys.stderr)
        else:
            try:
                review_material_content = review_material_path.read_text(encoding='utf-8')
                print(f"INFO: Review material loaded from: {review_material_path}")

                llm_suggestions_content = analyze_and_suggest_hierarchy_updates(
                    project_root_path,
                    report_content, # Pass the compiled report content
                    review_material_content
                )

                suggestions_output_path = project_root_path / args.suggestions_output_file
                with open(suggestions_output_path, "w", encoding='utf-8') as f:
                    f.write(f"# GOUAI Project Hierarchy Review Suggestions\n\n")
                    f.write(f"**Generated On:** {datetime.datetime.now().isoformat(timespec='seconds')}\n")
                    f.write(f"**Project Root:** `{project_root_path}`\n")
                    f.write(f"**Review Material Source:** `{review_material_path.name}`\n\n")
                    f.write("---\n\n")
                    f.write(llm_suggestions_content)
                print(f"INFO: LLM suggestions saved to: {suggestions_output_path}")

            except Exception as e:
                print(f"ERROR: Failed to perform LLM analysis and save suggestions: {type(e).__name__} - {e}", file=sys.stderr)

if __name__ == "__main__":
    main()