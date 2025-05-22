# execute_gouai_p1p2.py

# --- Standard Library Imports ---
import argparse
from pathlib import Path
import sys
import yaml # For PyYAML, used for parsing YAML frontmatter
import re   # For regex operations, potentially for parsing Markdown sections
import datetime # For generating unique session IDs

# --- GOUAI Module Imports ---
# These imports leverage existing functionalities from your GOUAI toolkit.
# It's crucial these modules are accessible in the Python environment.
try:
    from gouai_task_mgmt import find_task_dir_path_from_id #
    # This function is used to locate the parent task's directory based on its ID.
except ImportError:
    print("CRITICAL ERROR: Could not import find_task_dir_path_from_id from gouai_task_mgmt.py.", file=sys.stderr)
    # Add dummy or sys.exit(1) as per your project's error handling policy for missing dependencies

try:
    from gouai_llm_api import generate_response_aggregated, ConfigurationError, LLMAPICallError #
    # generate_response_aggregated is used to make the LLM call.
    # ConfigurationError and LLMAPICallError are specific exceptions to handle.
except ImportError:
    print("CRITICAL ERROR: Could not import from gouai_llm_api.py.", file=sys.stderr)
    # Add dummy or sys.exit(1)

# Potentially, if a common Markdown parsing utility exists or is adapted:
# from gouai_common_utils import extract_md_section # (Example, if you create/use one)
# The _extract_md_section_content from gouai_context_handler.py
# provides a good pattern for this.

# --- Constants ---
# Example: Define a path or mechanism to access GOUAI.pdf if it's stored locally
# GOUAI_PROTOCOL_PDF_PATH = Path(__file__).resolve().parent / "reference_docs" / "GOUAI.pdf"

# --- Helper Functions ---

def _load_gouai_protocol_text() -> str:
    """
    Returns the GOUAI protocol definition text as a multi-line string.
    (KIRQ1.5 - Part of prompt construction)
    The content is sourced from the GOUAI.pdf document provided by the user.
    """
    gouai_protocol_string = """
    **Goal-Oriented Uncertainty-Aware LLM Interaction Protocol (GOUAI Protocol)**
    **Overarching Principles:**
    1. **Evolving Goal Clarity:** The protocol starts by acknowledging that the user's highlevel goals may initially be abstract or ambiguous and require clarification. The "true
    desired output" is co-discovered.
    2. **Explicit Uncertainty Management:** Systematic identification, characterization, and
    tracking of epistemic (reducible) and aleatoric (inherent) uncertainties are central to all
    phases.
    3. **Goal-Driven Evaluation:** The "goodness" of both intermediate descriptors and the final
    output is primarily assessed by their current and potential ability to contribute to the
    user's stated high-level goals, in light of documented uncertainties.
    4. **Iterative Refinement & Risk Assessment:** Progress occurs through iterative cycles.
    Decisions to stop refining or proceed to the next phase are based on whether the cost/benefit
    of further uncertainty reduction is justified relative to goal achievement and acceptable
    risk.
    5. **LLM as Analytical Partner:** LLMs are used not just for generation, but also for
    helping to identify uncertainties, deconstruct goals, brainstorm impacts, and articulate
    assumptions.
    6. **Transparent Living Documentation:** A "Living Document" serves as a transparent record
    of the evolving understanding of goals, descriptors, identified uncertainties, key
    information elements, decisions made, and the rationale behind them.
    ---
    **Phase 1: Goal & Descriptor Elucidation (GDE)**
    * **Objective:** To iteratively refine an initial, possibly ambiguous, high-level user goal
    into a "Workable Stated Output Descriptor (WSOD)" by exploring its facets, implications, and
    explicitly identifying associated uncertainties and its alignment with the user's overarching
    meta-goals.
    * **Stage 1.1: Articulation of Initial High-Level Goal(s) (HLG) & Meta-Context**
     * User articulates their HLG(s) (e.g., "minimize individual and human suffering,"
    "maximize specific project success," "understand complex topic X").
     * User provides initial context: constraints, values, intended audience/use of potential
    output.
     * This becomes the foundational entry in the Living Document (LD).
    * **Stage 1.2: LLM-Facilitated Exploration & Structuring of Goal Space**
     * **Action:** Employ LLM(s) to:
     * Deconstruct HLG(s): Identify underlying abstract concepts, potential sub-goals, key
    dimensions, and inherent ambiguities.
     * Brainstorm Potential Output Types: Explore various forms of outputs that could
    address the HLG(s).
     * Map to User Values/Constraints: Discuss how different interpretations or output
    types align with the stated meta-context.
     * **User Interaction:** User guides the exploration, clarifies intent, and begins to
    narrow focus towards a more specific type of desired output or understanding.
     * **LD Update:** Record of exploration paths, key insights, and emerging focus.
    * **Stage 1.3: Formulation of Candidate Workable Stated Output Descriptor (cWSOD_n)**
     * Based on Stage 1.2, the user, with LLM assistance, formulates a more concrete (though
    still potentially abstract) descriptor for a specific desired output (cWSOD_n).
    * **Stage 1.4: Uncertainty & Goal Alignment Assessment for cWSOD_n**
     * **Action (User, supported by LLM):**
     1. **Enumerate Epistemic Uncertainties within cWSOD_n:**
     * What terms are still ambiguous or underspecified?
     * What assumptions are embedded in this descriptor?
     * What knowledge gaps does this descriptor reveal regarding its own feasibility
    or scope?
     2. **Identify Potential Aleatoric Uncertainties:** What inherent randomness or
    external factors might affect the ultimate realization or utility of an output based on this
    cWSOD_n?
     3. **Assess cWSOD_n's Contribution to HLG(s):**
     * Articulate clearly how an output conforming to cWSOD_n is expected to advance
    the HLG(s).
     * Identify potential risks or ways in which cWSOD_n, if pursued, might
    inadvertently conflict with HLG(s) or lead to negative unintended consequences.
     4. **Identify Key Information Requirements implied by cWSOD_n:** What broad
    categories of information would be needed to realize an output based on this descriptor?
     * **LD Update:** Detailed record of these uncertainties, goal alignment rationale, risks, 
    and information requirements associated with cWSOD_n.
    * **Stage 1.5: Stopping Criterion Check for Descriptor Elucidation**
     * **Guiding Question:** "Is the current cWSOD_n sufficiently clear, aligned with HLGs,
    and are its inherent uncertainties sufficiently understood to guide a focused information
    acquisition phase, OR is the cost of further *descriptor* refinement likely to outweigh the
    benefits to clarity and HLG alignment *at this stage*?"
     * **Decision Factors (User-driven, LLM-informed):**
     1. **Clarity for Action:** Is cWSOD_n clear enough to define the *scope* and
    *nature* of information needed next?
     2. **HLG Alignment Confidence:** Is there sufficient confidence that pursuing this
    cWSOD_n is a productive path towards the HLG(s), and are the risks understood?
     3. **Impact of Descriptor Uncertainties:** Are the remaining epistemic uncertainties
    *within the descriptor itself* manageable, or do they prevent effective planning for the next
    phase?
     4. **Cost/Benefit of Further Descriptor Refinement:** Would more iterations on the
    descriptor likely yield significant improvements in its utility for guiding subsequent
    phases, or are we hitting diminishing returns *for descriptor clarity itself*?
     * **Decision:**
     * **If criteria NOT met:** Iterate back to Stage 1.3 (or 1.2 if more fundamental
    exploration is needed). Document reasons.
     * **If criteria ARE met:** cWSOD_n is designated the **Workable Stated Output
    Descriptor (WSOD)**. Proceed to Phase 2.
    ---
    **Phase 2: Structured Information Acquisition & Uncertainty Logging (SIAUL)**
    * **Objective:** To gather and organize the necessary Information Elements (IEs) to address
    the WSOD, explicitly logging the sources and nature of uncertainty for each IE.
    * **Stage 2.1: Decompose WSOD into Information Requirements & Query Formulation**
     * **Action:** Based on the WSOD and the "Key Information Requirements" identified in
    Stage 1.4:
     * Use LLM(s) to break down the WSOD into specific questions, definitions needed,
    hypotheses to explore, types of data required.
     * Formulate precise queries or tasks for LLMs or other information sources.
     * **LD Update:** Detailed plan for information acquisition, structured under the WSOD.
    * **Stage 2.2: Iterative Information Element (IE) Generation & Collection**
     * **Action:** Employ LLM(s), databases, user expertise, etc., to generate/collect IEs.
    * **Stage 2.3: Uncertainty Characterization for each IE**
     * **Action (User, supported by LLM for identification):** For each significant IE:
     1. **Source & Provenance:** Document the origin of the IE.
     2. **Epistemic Uncertainties:**
     * Limitations of LLM knowledge (cut-off dates, potential biases in training data
    if LLM-generated).
     * Assumptions made by the LLM during generation (if identifiable).
     * Data quality issues (if from external sources: margin of error, completeness,
    timeliness, known biases).
     * Lack of corroborating sources.
     3. **Aleatoric Uncertainties:** Note any inherent randomness or variability the IE
    describes or is subject to.
     * **LD Update:** Each IE is stored with its detailed uncertainty characterization.
    * **Stage 2.4: Sufficiency Check for Information Acquisition**
     * **Guiding Question:** "Have we gathered enough information, with sufficiently
    characterized uncertainties, to attempt a meaningful synthesis towards the WSOD, OR is the
    cost/benefit of acquiring more/better information for key IEs justified by the expected
    improvement in the final output's ability to address the HLGs?"
     * **Decision Factors (User-driven, LLM-informed):**
     1. **Coverage of WSOD:** Are there critical information gaps related to the WSOD's
    core components?
     2. **Impact of IE Uncertainties:** Are the epistemic uncertainties in key IEs so
    large that any output generated would be too unreliable to support the HLGs?
     3. **Cost/Benefit of Further IE Acquisition/Refinement:** What is the effort to
    reduce critical IE uncertainties versus the expected improvement in the final output's
    utility for HLG achievement?
     4. **Availability of Better Information:** Is it even possible to significantly
    reduce key epistemic uncertainties with available resources/methods?
     * **Decision:**
     * **If criteria NOT met:** Iterate within Stage 2.2/2.3 to acquire more/better IEs or
    refine existing ones. Document reasons.
     * **If criteria ARE met:** Proceed to Phase 3.
    ---
    **Phase 3: Output Synthesis & Integrated Uncertainty Assessment (OSIUA)**
    * **Objective:** To synthesize the collected IEs into an Approximate Output Text (AOT) that
    addresses the WSOD, and to create an integrated assessment of the AOT's uncertainties and its
    potential to achieve HLGs.
    * **Stage 3.1: LLM-Assisted Output Synthesis**
     * **Action:** Employ LLM(s) to generate the AOT, explicitly instructing them to:
     * Base the output on the IEs in the LD.
     * Reference or incorporate the documented uncertainties of the IEs used.
     * Highlight where conclusions are drawn based on IEs with significant uncertainty or
    where assumptions were made during synthesis.
     * **LD Update:** Generated AOT is added.
    * **Stage 3.2: Integrated Uncertainty & Goal Impact Assessment for AOT**
     * **Action (User, supported by LLM for analysis and articulation):**
     1. **Consolidated Uncertainty Summary:**
     * Enumerate key epistemic uncertainties from the WSOD and IEs that significantly
    impact the AOT's reliability or completeness.
     * Describe epistemic uncertainties introduced during the LLM's synthesis process
    (e.g., potential misinterpretations, logical leaps not fully supported by low-uncertainty
    IEs).
     * Enumerate key aleatoric uncertainties relevant to the AOT's implications.
     * List critical assumptions underpinning the AOT.
     2. **WSOD Fulfillment Assessment:** How well, and in what specific ways, does the
    AOT address the components of the WSOD? Where are the gaps?
     3. **HLG Impact Review:**
     * Critically evaluate the AOT's *potential to achieve the user's high-level goals
    (HLGs)*, considering its documented uncertainties and assumptions.
     * What is the range of possible outcomes if decisions are based on this AOT?
     * What are the potential risks (including unintended negative consequences) of
    using this AOT in relation to the HLGs, given its uncertainties?
     * **LD Update:** This comprehensive assessment is attached to the AOT.
    * **Stage 3.3: Final Stopping Criterion Check (Output Acceptance)**
     * **Guiding Question:** "Does the AOT, *despite its documented uncertainties and
    assumptions*, provide sufficient value towards achieving the HLGs to be considered 'good
    enough' for its intended purpose, AND is the risk associated with its use acceptable?"
     * **Decision Factors (User-driven):**
     1. **Utility for HLG Achievement:** Is the AOT actionable or informative in a way
    that meaningfully advances the HLGs?
     2. **Acceptable Risk Threshold:** Given the stakes involved and the nature of the
    HLGs, is the level of uncertainty and potential for negative outcomes documented in Stage 3.2
    acceptable? (This is highly context-dependent and defined by the user).
     3. **Cost/Benefit of Further Iteration:** Would further iterations (on IEs, or even
    the WSOD itself) likely lead to an AOT with a significantly better risk/reward profile for
    HLG achievement, and is that improvement worth the additional cost/effort?
     * **Decision:**
     * **If AOT is accepted:** Protocol concludes for this WSOD. The AOT and its full
    documentation are finalized.
     * **If AOT is NOT accepted:**
     * Identify primary reasons (e.g., unacceptable uncertainty in AOT, poor WSOD
    fulfillment, unacceptable HLG impact/risk).
     * **Iterate:**
     * Back to Stage 3.1 for refined synthesis if the issue is primarily LLM
    generation.
     * Back to Phase 2 (SIAUL) if key IEs are missing or their uncertainties are
    too high.
     * Back to Phase 1 (GDE) if the AOT reveals fundamental flaws in the WSOD
    itself or its alignment with HLGs. This acknowledges that realizing an output can clarify
    deficiencies in the initial descriptor.
    """
    return gouai_protocol_string.strip() 
    
def _load_and_parse_parent_task_def(parent_task_dir: Path) -> dict:
    """
    Loads and parses the parent task's task_definition.md file.
    (KIRQ1.5 - "Load and parse parent task_definition.md")
    """
    print(f"INFO: Loading parent task definition from: {parent_task_dir}", file=sys.stderr)
    task_def_file = parent_task_dir / "task_definition.md"
    if not task_def_file.is_file():
        raise FileNotFoundError(f"Parent task_definition.md not found at {task_def_file}")

    content = task_def_file.read_text(encoding='utf-8')
    parent_task_data = {}

    # Parse YAML Frontmatter (similar to _extract_yaml_frontmatter in gouai_context_handler.py
    # or parts of _parse_parent_task_def in gouai_task_mgmt.py)
    try:
        yaml_match = re.search(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL | re.MULTILINE)
        if yaml_match:
            frontmatter_str = yaml_match.group(1)
            parent_task_data['yaml_frontmatter'] = yaml.safe_load(frontmatter_str) or {}
        else:
            parent_task_data['yaml_frontmatter'] = {} # No YAML frontmatter found
    except yaml.YAMLError as e:
        raise ValueError(f"Error parsing YAML frontmatter in {task_def_file}: {e}")

    # Extract specified Markdown Body Sections (as per EU1.6)
    # This would involve extracting text under headings like "## High-Level Goal(s) (HLG)", etc.
    # The function _extract_md_section_content in gouai_context_handler.py
    # provides a pattern for extracting content based on section headings.
    parent_task_data['markdown_body_sections'] = {}
    required_sections = [ # From EU1.6
        "High-Level Goal(s) (HLG)",
        "Meta-Context",
        "Workable Stated Output Descriptor (WSOD) - Full Statement",
        "WSOD Assessment (Initial)", # And its sub-sections
        "Goal Space Exploration Summary", # If populated
        "Candidate Workable Stated Output Descriptor(s) (cWSODs)" # If populated
    ]
    for section_title in required_sections:
        # Adapt or reuse logic similar to _extract_md_section_content from gouai_context_handler.py
        # For brevity, direct implementation of section extraction is omitted here but would be needed.
        # Placeholder for extracted content:
        # extracted_section_content = extract_specific_markdown_section(content, f"## {section_title}")
        # parent_task_data['markdown_body_sections'][section_title] = extracted_section_content
        pass # Actual extraction logic needed here

    # Example: manually simulating what might be extracted for the prompt
    parent_task_data['extracted_for_prompt'] = {
        'HLG': parent_task_data.get('yaml_frontmatter', {}).get('HLG_summary', 'Not specified in YAML.'),
        'WSOD': parent_task_data.get('yaml_frontmatter', {}).get('WSOD_summary', 'Not specified in YAML.'),
        # ... and content from Markdown sections
    }
    print("INFO: Parent task definition loaded and parsed.", file=sys.stderr)
    return parent_task_data


def _construct_llm_prompt(parent_task_info: dict, gouai_protocol_text: str) -> str:
    """
    Constructs the full prompt to be sent to the LLM.
    (KIRQ1.5 - "Construct and send the first prompt...")
    """
    print("INFO: Constructing LLM prompt.", file=sys.stderr)
    # Part 1: GOUAI Protocol Definition
    part1_protocol = gouai_protocol_text

    # Part 2: Parent Task Information (Format as per KIRQ1.1)
    # This needs to carefully assemble the extracted YAML and Markdown content.
    parent_yaml = parent_task_info.get('yaml_frontmatter', {})
    # parent_md_sections = parent_task_info.get('markdown_body_sections', {})

    # Simplified example of constructing this part:
    parent_content_for_prompt = f"""PARENT_TASK_DEFINITION_CONTENT:
---
task_id: {parent_yaml.get('task_id', 'N/A')}
HLG_summary: "{parent_yaml.get('HLG_summary', 'N/A')}"
WSOD_summary: "{parent_yaml.get('WSOD_summary', 'N/A')}"
status: "{parent_yaml.get('status', 'N/A')}"
task_type: "{parent_yaml.get('task_type', 'N/A')}"
# ... other relevant YAML fields from EU1.6 ...
---
## High-Level Goal(s) (HLG)
{parent_task_info.get('extracted_for_prompt', {}).get('HLG_content', 'Content not extracted.')} 
# ... content from other required Markdown sections (Meta-Context, WSOD Full, WSOD Assessment etc.) ...
"""

    llm_instructions = f"""
**Role Definition:** You are an AI assistant specialized in applying the Goal-Oriented Uncertainty-Aware LLM Interaction (GOUAI) Protocol...
**Core Task:**
    1. Thoroughly review the GOUAI Protocol Definition...
    2. Carefully review the PARENT_TASK_DEFINITION_CONTENT...
    3. Parent Task WSOD Formulation (GOUAI Phase 1):
    Your FIRST and MOST CRITICAL task is to analyze the PARENT_HLG and any available meta-context to complete the phase one stages.
    4. Sub-task Decomposition (GOUAI Phase 2):
    Based on phase 1 and phase 2.1, decompose the high level goal into a set of granular, actionable sub-tasks. The crucial requirement for the decomposition is that it is not merely a conceptual decomposition grouping similar ideas into a sub-task, but instead each the sub-task breakdown can be conceptualized as a series of executable processes that proceed chronologically and can be run on a one-off or ongoing basis.
    For each proposed sub-task, you must define:
    * A clear High-Level Goal (HLG) for the sub-task.
    * A preliminary list of key Epistemic Uncertainties (EUs) related to achieving the sub-task's HLG. Previous subtask outputs might be epistemic uncertainties. 
    * A list of Key Information Requirements (KIRQs) needed to resolve those EUs or define the sub-task's output.
    This will all help us formulate a WSOD after the KIRQ information is retrieved and the uncertainties resolved
    5. Output Formatting Instructions:
    Present your full analysis in the structured Markdown format specified below.
    The ## PARENT_WSOD section in your output must contain the complete WSOD you formulated in step 3.
    Adhere strictly to this structure:
    ```markdown
    # PARENT TASK ANALYSIS
    ## PARENT_HLG
    [Restated Parent HLG from its task_definition.md]

    ## PARENT_WSOD
    [Restated Parent WSOD from its task_definition.md, if available]

    # PROPOSED SUB-TASKS

    ## SUB-TASK
    ### HLG
    [HLG for Sub-task 1]
    ### EPISTEMIC_UNCERTAINTIES
    - [EU 1 for Sub-task 1]
    ### KEY_INFORMATION_REQUIREMENTS
    - [KIRQ 1 for Sub-task 1]

    # ... (structure continues) ...
    ```
    This output format *must* align with the Schema above
"""
    full_prompt = f"{part1_protocol}\n\n{parent_content_for_prompt}\n\n{llm_instructions}"
    print("INFO: LLM prompt constructed.", file=sys.stderr)
    return full_prompt

# --- Main Script Logic ---
def main():
    parser = argparse.ArgumentParser(description="GOUAI Phase 1 & 2 Task Decomposer.")
    parser.add_argument("--parent_task_id", required=True, help="Full string ID of the parent GOUAI task.")
    parser.add_argument("--project_root_path", required=True, help="Path to the root directory of the GOUAI project.")
    parser.add_argument("--output_document_path", required=True, help="Full file path to save the generated Decomposition Document.")
    args = parser.parse_args()

    try:
        project_root = Path(args.project_root_path).resolve()
        output_doc_path = Path(args.output_document_path).resolve()

        if not project_root.is_dir():
            raise FileNotFoundError(f"Project root path does not exist or is not a directory: {project_root}")

        # 1. Resolve Parent Task Directory
        print(f"INFO: Finding parent task directory for ID: {args.parent_task_id}", file=sys.stderr)
        parent_task_dir = find_task_dir_path_from_id(project_root, args.parent_task_id, project_root) #
        if not parent_task_dir:
            raise FileNotFoundError(f"Parent task directory not found for ID '{args.parent_task_id}' in project '{project_root}'.")

        # 2. Load and Parse Parent task_definition.md
        parent_task_data = _load_and_parse_parent_task_def(parent_task_dir)

        # 3. Load GOUAI Protocol Definition
        gouai_protocol_text = _load_gouai_protocol_text()
        if "[Placeholder for full content of GOUAI.pdf" in gouai_protocol_text and "not loaded" in gouai_protocol_text.lower():
             print("WARNING: GOUAI.pdf content is a placeholder or failed to load. LLM results may be suboptimal.", file=sys.stderr)


        # 4. Construct LLM Prompt
        llm_prompt = _construct_llm_prompt(parent_task_data, gouai_protocol_text)

        # 5. Execute LLM Call
        # (KIRQ1.5 - "...send the first prompt via gouai_llm_api.py", "...Receive and process the first response.")
        print(f"INFO: Executing LLM call for task: {args.parent_task_id}", file=sys.stderr)
        session_id = f"exec_p1p2_{args.parent_task_id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        
        response_data = generate_response_aggregated(
            project_root=str(project_root),
            session_id=session_id,
            task_id=args.parent_task_id, # Used for logging context within gouai_llm_api.py
            contents=llm_prompt
        ) #

        # 6. Process LLM Response
        if response_data.get('error_info'):
            error_details = response_data['error_info']
            raise LLMAPICallError(f"LLM API call failed: {error_details.get('type')} - {error_details.get('message')}")
        
        decomposition_document_text = response_data.get('text')
        if not decomposition_document_text:
            raise ValueError("LLM call returned no text content for the Decomposition Document.")
        print("INFO: LLM response received successfully.", file=sys.stderr)

        # 7. Save the Decomposition Document
        # (KIRQ1.5 - "...save it as the 'Decomposition Document'.")
        print(f"INFO: Saving Decomposition Document to: {output_doc_path}", file=sys.stderr)
        output_doc_path.parent.mkdir(parents=True, exist_ok=True) # Ensure parent directory exists
        with open(output_doc_path, 'w', encoding='utf-8') as f:
            f.write(decomposition_document_text)
        print(f"SUCCESS: Decomposition Document generated and saved to {output_doc_path}")

    # 8. Error Handling
    # (KIRQ1.5 - "Implement error handling for LLM calls and file operations.")
    except FileNotFoundError as e:
        print(f"ERROR (FileNotFound): {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e: # Includes YAML parsing errors if raised as ValueError
        print(f"ERROR (ValueError): {e}", file=sys.stderr)
        sys.exit(1)
    except ConfigurationError as e: # From gouai_llm_api.py
        print(f"ERROR (ConfigurationError): {e}", file=sys.stderr)
        sys.exit(1)
    except LLMAPICallError as e: # From gouai_llm_api.py or raised above
        print(f"ERROR (LLMAPICallError): {e}", file=sys.stderr)
        sys.exit(1)
    except IOError as e: # For file writing errors
        print(f"ERROR (IOError): Could not write to output file. {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e: # Catch-all for any other unexpected errors
        print(f"UNEXPECTED ERROR: {type(e).__name__} - {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()