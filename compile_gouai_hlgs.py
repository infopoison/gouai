# compile_gouai_hlgs.py (Modified to exclude 'Completed' tasks and include recent outputs appending, with LLM analysis removed)

import argparse
from pathlib import Path
import re
import yaml
import datetime
import sys
import os

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
        r"##\s*High-Level Goal\(s\)\s*\(HLG\)\s*\n+(.*?)(?=\n##\s*|$)",
        markdown_body, 
        re.DOTALL | re.IGNORECASE
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

def _gather_recent_output_files(project_root_path: Path, days: int) -> str:
    """
    Gathers content from .md and .txt files in 'outputs/' folders
    modified within the last 'days' from project_root_path.
    """
    recent_outputs_content = []
    time_threshold = datetime.datetime.now() - datetime.timedelta(days=days)
    
    # Traverse all subdirectories, looking for 'outputs' folders
    for dirpath, dirnames, filenames in os.walk(project_root_path):
        if "outputs" in dirnames:
            outputs_path = Path(dirpath) / "outputs"
            for item in outputs_path.iterdir():
                if item.is_file() and item.suffix.lower() in ['.md', '.txt']:
                    try:
                        mod_timestamp = datetime.datetime.fromtimestamp(os.path.getmtime(item))
                        if mod_timestamp >= time_threshold:
                            relative_path = item.relative_to(project_root_path)
                            content = item.read_text(encoding='utf-8', errors='replace')
                            recent_outputs_content.append(
                                f"\n--- Recently Modified Output File: {relative_path} (Last Modified: {mod_timestamp.isoformat(timespec='seconds')}) ---\n"
                                f"```\n{content.strip()}\n```\n"
                            )
                    except Exception as e:
                        recent_outputs_content.append(f"\n--- Error reading file {item.relative_to(project_root_path)}: {e} ---\n")
    
    if recent_outputs_content:
        return "\n".join(recent_outputs_content)
    return "No recently modified .md or .txt files found in any 'outputs/' folders within the specified time period."


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
                continue
            
            task_id = _get_task_id_from_task_definition(task_def_path)
            hlg = _get_hlg_from_task_definition(task_def_path)
            
            compiled_report_lines.append(f"{prefix}- **Directory:** `{current_path.name}/`")
            compiled_report_lines.append(f"{prefix}  **Task ID:** `{task_id}`")
            compiled_report_lines.append(f"{prefix}  **HLG:** {hlg}")
            compiled_report_lines.append(f"{prefix}  **Status:** {task_status}")

            outputs_path = current_path / "outputs"
            output_summary = _summarize_outputs_folder(outputs_path)
            if output_summary:
                compiled_report_lines.append(f"{prefix}  **Outputs Summary:**")
                for line in output_summary:
                    compiled_report_lines.append(f"{prefix}    {line}")
            compiled_report_lines.append("")
        else:
            # If not a task directory, still list it but without HLG/outputs
            if current_path != project_root_path:
                compiled_report_lines.append(f"{prefix}- **Directory:** `{current_path.name}/` (Not a GOUAI Task Directory)")
                compiled_report_lines.append("")

        # Add subdirectories to the stack for further processing
        # Iterate in reverse to maintain alphabetical order when popping
        sub_dirs = sorted([d for d in current_path.iterdir() if d.is_dir() and d not in processed_dirs], reverse=True)
        for sub_dir in sub_dirs:
            stack.append((sub_dir, depth + 1))

    return "\n".join(compiled_report_lines)


# --- Main function for CLI execution ---
def main():
    parser = argparse.ArgumentParser(
        description="Compile High-Level Goals (HLGs) and Output Summaries from a GOUAI project hierarchy, "
                    "with optional inclusion of recently modified output files."
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
        "--days_since_modified",
        type=int,
        help="Optional: Include .md and .txt files from 'outputs/' folders modified within this many days in the report."
    )

    args = parser.parse_args()

    project_root_path = Path(args.project_root).resolve()

    if not project_root_path.is_dir():
        print(f"Error: Project root path '{project_root_path}' does not exist or is not a directory.", file=sys.stderr)
        sys.exit(1)

    print(f"Compiling HLGs and output summaries from: {project_root_path}")
    report_content = compile_hlgs_and_outputs(project_root_path)

    recent_outputs_for_report = ""
    if args.days_since_modified is not None and args.days_since_modified > 0:
        print(f"INFO: Gathering .md and .txt files from 'outputs/' folders modified in the last {args.days_since_modified} days for the report...")
        recent_outputs_for_report = _gather_recent_output_files(project_root_path, args.days_since_modified)
        if recent_outputs_for_report.strip() != "No recently modified .md or .txt files found in any 'outputs/' folders within the specified time period.":
            print(f"INFO: Appending recent output files to the main report.")
            report_content += "\n\n# Recently Modified Output Files in Project\n"
            report_content += f"*(Files modified in the last {args.days_since_modified} days)*\n"
            report_content += recent_outputs_for_report
        else:
            print(f"INFO: {recent_outputs_for_report.strip()}")

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

if __name__ == "__main__":
    main()