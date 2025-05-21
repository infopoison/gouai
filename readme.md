This project utilizes Python and requires a dedicated environment to manage dependencies. The following steps outline how to set up the environment using Anaconda (or Miniconda) on macOS.

**1. Create and Activate Conda Environment:**

First, create a new Conda environment. We recommend using Python 3.9. Replace `gouai_env` with your preferred environment name if desired.

```bash
conda create --name gouai_env python=3.10
conda activate gouai_env
```

**2. Install Dependencies:**

Once the environment is activated, install the required Python libraries:

  * **PyYAML**: For handling YAML configuration files.
    ```bash
    conda install pyyaml
    ```
  * **Google Generative AI SDK**: For interacting with Google's generative AI models.
    ```bash
    pip install google-genai
    ```

Please prepare an api key as well in the global configurations. Prepare it as 
export GEMINI_API_KEY="[key]" added to ~/.zshrc



**3. Verify Installation (Optional):**

To confirm that the key libraries are installed correctly within the activated `gouai_env`, you can run:

```python
import yaml
import google.generativeai as genai

print("PyYAML and google-generativeai SDK are successfully imported.")
```

# Example Walkthrough 


1.  **Project Initialization:** A new GOUAI project and its root task (with an initial HLG) are created using `gouai_project_init.py`.
2.  **Automated Parent Task Analysis & Decomposition (`execute_gouai_p1p2.py`):** This script takes the parent task's initial HLG. Internally, it uses LLM interactions to perform an automated GOUAI Phase 1 (to refine the HLG into a parent WSOD, eliciting necessary details if the initial meta-context is sparse) and Phase 2 (to decompose this newly formulated parent WSOD into proposed sub-tasks with their HLGs, EUs, and KIRQs). The output is a "Decomposition Document" containing the parent's HLG/WSOD and the proposed sub-tasks.
3.  **Sub-task Review, Refinement & Instantiation (`make_gouai_subtasks.py`):** The user reviews the "Decomposition Document." They have an opportunity to manually modify/combine sub-task details before `make_gouai_subtasks.py` processes each, allowing the user to decide on a handling strategy (Recursive GOUAI, Simple LLM Task, or Text Copy) and establishing output tracking.
4.  **User-Driven Sub-task Execution:** The user executes/oversees each sub-task according to its type, capturing outputs.
5.  **Final WSOD Composition for Parent Task:** A user-guided process (within the parent task's primary chat session, which can now be initiated if needed) gathers sub-task outputs and the parent's WSOD (from the Decomposition Document). An LLM synthesizes this into a "Final WSOD" for the parent task.
6.  **Parent Task Phase 3 Execution:** The user, assisted by an LLM in the parent task's chat session, proceeds with GOUAI Phase 3 for the parent task using the "Final WSOD."

### 3. Detailed Workflow with Running Example (Revised Final)

**Running Example Root HLG:** "To create a Python script that prints 'Hello World', place it in a ZIP file, and email it to myself."

---
#### **Step 1: Project Initialization (`gouai_project_init.py`)**
---
* **Action:** User initiates a new GOUAI project.
    ```bash
    python gouai_project_init.py --name HelloWorldZipEmail --root_dir ./projects
    ```
* **User Input during `gouai_project_init.py`:**
    * **HLG:** "To create a Python script that prints 'Hello World', place it in a ZIP file, and email it to myself."
    * **Meta-Context:** (User provides minimal or no meta-context initially, e.g., "Recipient email: `user@example.com`").
* **Output:**
    * Project directory: `./projects/HelloWorldZipEmail/`
    * Root `task_definition.md` containing primarily the HLG and minimal meta-context.
* **Illustrative `task_definition.md` (Root Task - Snippet after init):**
    ```yaml
    ---
    task_id: HelloWorldZipEmail_ROOT
    HLG_summary: "Create, zip, and email a 'Hello World' Python script."
    WSOD_summary: "To be defined." # Initially not defined by user
    task_type: "project_root_task"
    ---
    ## High-Level Goal(s) (HLG)

    To create a Python script that prints 'Hello World', place it in a ZIP file, and email it to myself.

    ## Meta-Context
    Recipient email: `user@example.com`
    (Further meta-context to be elicited by execute_gouai_p1p2)
    ...
    ```

    Create project level configuration or global configuration. .gouai_config.yaml to s/GOUAI/projects/HelloWorldZipEmail/ 

    Contents 
    ```
    default_model_name: "gemini-2.5-flash-preview-05-20"
    ```

---
#### **Step 2: Automated Parent Task Analysis & Decomposition (`execute_gouai_p1p2.py`)**
---
* **Action:** The user runs `execute_gouai_p1p2.py` on the root task.
    ```bash
    python execute_gouai_p1p2.py --parent_task_id HelloWorldZipEmail_ROOT --project_root_path ./projects/HelloWorldZipEmail --output_document_path ./projects/HelloWorldZipEmail/decomposition_output.md
    ```
* **Internal Process of `execute_gouai_p1p2.py`:**
    1.  Loads the parent `task_definition.md` (containing the HLG and minimal meta-context).
    2.  Constructs a prompt for a first LLM call. This prompt instructs the LLM to:
        * Act as a GOUAI analyst.
        * Review the provided HLG ("To create a Python script...").
        * Elicit (if necessary, by structuring its thoughts or asking implicit questions to be resolved in the WSOD) or infer necessary meta-context details (like Python version, email specifics, SMTP server requirements if not present) to formulate a comprehensive WSOD for the parent HLG.
        * Formulate this parent WSOD.
        * Then, decompose this formulated parent WSOD into logical sub-tasks, each with its own HLG, a preliminary list of EUs, and essential KIRQs.
    3.  Makes the LLM call(s) via `gouai_llm_api.py`.
    4.  The (potentially second) LLM call structures this analysis into the "Decomposition Document" format.
* **Output:** `decomposition_output.md`. This document now contains the LLM-formulated WSOD for the parent task, *in addition* to the proposed sub-tasks. We will use your provided `decomposition_output.md` as the example for the sub-task part, assuming `execute_gouai_p1p2.py` also formulated a parent WSOD.
* **`decomposition_output.md` (Example Snippet - Combining Formulated Parent WSOD and User's Sub-tasks):**
    ```markdown
    # PARENT TASK ANALYSIS
    ## PARENT_HLG
    to create a python script that prints hello world and then place it in a zip file and email it to myself.

    ## PARENT_WSOD 
    (Formulated by execute_gouai_p1p2's LLM call based on HLG and minimal meta-context)
    A Python 3.9+ script, `hello_world.py`, will be created that prints the exact string "Hello World!" to standard output. This script will then be compressed into a ZIP archive named `hello_world.zip`. Finally, this `hello_world.zip` archive will be emailed as an attachment to `user@example.com` from `script@example.com` (sender to be confirmed/configured) via a specified SMTP server (details like `smtp.provider.com`, port 587, STARTTLS to be confirmed/configured), with the subject 'Hello World Script Output' and body 'Attached is the Hello World script.' Credentials for SMTP will be sourced from environment variables `SMTP_USER` and `SMTP_PASS`.

    # PROPOSED SUB-TASKS 
    # (Content from user-provided decomposition_output.md follows)

    ## SUB-TASK: Clarify Python Script Details
    ### HLG
    To identify and specify the precise requirements for the "hello world" Python script...
    ### EPISTEMIC_UNCERTAINTIES
    - Exact Python version (e.g., 3.x, specific minor) to be used for script execution. (Parent WSOD suggests 3.9+)
    ...
    ### KEY_INFORMATION_REQUIREMENTS
    - User's preferred Python interpreter version. (Confirm 3.9+)
    ...

    ## SUB-TASK: Define Zip File Specifications
    ### HLG
    To determine the precise structure, naming, and content of the zip file...
    ...

    ## SUB-TASK: Specify Emailing Parameters
    ### HLG
    To delineate all necessary email parameters, including sender/recipient details...
    ...

    ## SUB-TASK: Uncover Meta-Goals and Constraints 
    ### HLG
    To identify the user's underlying motivations, values, and non-functional requirements...
    ...
    ```

---
#### **Step 3: Sub-task Review, Refinement & Instantiation (`make_gouai_subtasks.py`)**
---
* **User Action:** Before running `make_gouai_subtasks.py`, the user reviews the generated `decomposition_output.md`.
    * **User Review & Manual Refinement:** The user examines the proposed sub-tasks. They can manually edit the `decomposition_output.md` at this point to:
        * Refine the HLGs, EUs, or KIRQs of the proposed sub-tasks.
        * Combine sub-tasks (e.g., if "Clarify Python Script Details" and "Define Zip File Specifications" seem trivial enough to merge).
        * Add new sub-tasks if they identify gaps.
        * Delete sub-tasks if they deem them unnecessary.
    *(This manual editing step is a placeholder for potential future interactive features within `make_gouai_subtasks.py` itself).*
* **Action:** After review/manual refinement, the user runs `make_gouai_subtasks.py`.
    ```bash
    python make_gouai_subtasks.py --document_path ./projects/HelloWorldZipEmail/decomposition_output.md --project_root_path ./projects/HelloWorldZipEmail --parent_task_id_for_new_tasks HelloWorldZipEmail_ROOT
    ```
* **Process & User Choices during `make_gouai_subtasks.py` execution:**
    *(Assuming user proceeds with the sub-tasks as outlined in the (potentially user-edited) `decomposition_output.md`)*
    * **For "SUB-TASK: Clarify Python Script Details"**: User chooses **(S)imple LLM Task**. Name suffix: `ClarifyScript`. Output to be saved by user to `./outputs/script_spec.md` within this simple task's structure. Path recorded by the tracker.
    * **For "SUB-TASK: Define Zip File Specifications"**: User chooses **(S)imple LLM Task**. Name suffix: `ClarifyZip`. Output to `./outputs/zip_spec.md`. Path recorded.
    * **For "SUB-TASK: Specify Emailing Parameters"**: User chooses **(S)imple LLM Task**. Name suffix: `ClarifyEmail`. Output to `./outputs/email_spec.md`. Path recorded.
    * **For "SUB-TASK: Uncover Meta-Goals and Constraints"**: User chooses **(S)imple LLM Task**. Name suffix: `ClarifyMeta`. Output to `./outputs/meta_goals.md`. Path recorded.
* **Output:** `sub_task_output_tracker.md` is created/updated, similar to the previous version, listing each instantiated sub-task, its type, its path/ID, and the intended location for its output.

You've raised a crucial point, and I apologize for the continued lack of clarity and the "scope creep" feeling regarding the "gouai chat" command. It's vital that the workflow is grounded in the scripts we have and the interactions are clear.

Let's refine the workflow description (Sub-task C) *again*, focusing on making the LLM interaction for task execution (especially Step 4: User-Driven Sub-task Execution) much more explicit by detailing how the (now simplified) `gouai_context_handler.py` and the existing `gouai_llm_api.py` would work together, without relying on an undefined `gouai chat` command as a black box.

The core idea is that some script (let's call it the "interactive session manager" for now, which `gouai.py chat` would be) orchestrates calls to `gouai_context_handler.py` and `gouai_llm_api.py`.

---
### **Revised Workflow Section from Sub-task C Document (Version 1.3)**

**(Assuming Steps 1, 2, and 3: Project Initialization, Automated Parent Task Analysis & Decomposition, and Sub-task Review, Refinement & Instantiation are as described in `subtaskc.md`)**

You are absolutely right. My previous explanation for Step 4 went into far too much internal detail about how the `gouai.py chat` command *would* work, rather than focusing on what the *user actually does*. I made it much more complicated than it needs to be from a workflow perspective.

Let's simplify Step 4 dramatically to reflect your clearer vision: the user runs `gouai.py chat` for the sub-task, interacts to get the desired output, and then saves that output.

Here's a much simpler and more direct Step 4:

---
#### **Step 4: User-Driven Sub-task Execution (Simplified)**
---

* **User Action - Initiate Interactive LLM Session:**
    * To work on the sub-task, the user invokes the `gouai.py chat` command:
        ```bash
        python gouai.py chat --task_id <SubTaskID_From_Tracker> --project_root <PathToProject>
        ```
        For example, to work on the sub-task `TestProj1_ROOT_ST1-7_Simple_Struc`:
        ```bash
        python gouai.py chat --task_id HelloWorldZipEmail_ROOT_ST1-1_Simple_to_generate_a_python_script --project_root ./projects/HelloWorldZipEmail
        ```
    * This command starts an interactive session with an LLM (LLM2). The LLM is automatically primed by the system with the necessary context for this specific sub-task (including its HLG, any initial EUs/KIRQs from the decomposition, and relevant parent task information, as prepared by `gouai_context_handler.py`).

* **User Action - Interactive Dialogue & Output Generation:**
    * The user dialogues with the LLM within this chat session. The goal is to achieve the sub-task's HLG. This typically involves:
        * Clarifying requirements and reducing uncertainties for the sub-task.
        * Asking the LLM for information or to generate content (e.g., code, specifications, summaries).
        * Iterating with the LLM until the desired output for the sub-task is achieved within the chat.
    * **Example Interaction for `TestProj1_ROOT_ST1-7_Simple_Struc` (HLG: "To determine the precise structure, naming, and content of the zip file..."):**
        * User (after initial prime): "Okay, for the zip file, the name should be `HelloWorldOutput.zip`. The Python script `hello_world.py` should be at the root of the archive. No other files are needed. Standard compression is fine. Can you confirm these specifications or suggest a way to document them?"
        * LLM2: "Understood. Specifications for `HelloWorldOutput.zip`:
            * Filename: `HelloWorldOutput.zip`
            * Contents: `hello_world.py` (at archive root)
            * Additional Files: None
            * Compression: Standard
            These specifications seem clear. Would you like me to format this as a Markdown note for your records?"
        * User: "Yes, please."
        * LLM2: (Provides the Markdown formatted specifications).

* **User Action - Saving the Output:**
    * Once the desired output for the sub-task is generated within the chat (e.g., the Markdown specifications from LLM2 in the example above, or a piece of Python code, etc.), **the user copies this relevant output from the chat session.**
    * The user then **saves this copied output into the designated output file** for that sub-task. The path and filename for this output file were defined in the `_subtask_output_tracker.md` during Step 3 (e.g., for `TestProj1_ROOT_ST1-7_Simple_Struc`, if the tracker said its output was `outputs/zip_spec.md`, the user would save the Markdown there).
    * *(Future enhancement: A command like `/save_output filename.ext` within the `gouai.py chat` interface could automate saving the last LLM response or selected text to the sub-task's `outputs/` directory).*

* **User Action - Updating Tracker:**
    * After saving the output, the user manually updates the `_subtask_output_tracker.md` to mark the sub-task's status as "Complete" and verifies the `Output Location/Reference` is accurate.

* **Repeat for Other Sub-tasks:** The user repeats this process for all other sub-tasks listed in the tracker. For "Recursive GOUAI Tasks," the `gouai.py chat` session would be used to conduct their own GOUAI Phase 1, 2, and 3 processes, with their final WSOD and deliverables being their key outputs.

---
#### **Step 5: Final WSOD Composition for Parent Task (Clarified LLM Interaction)**
---
* **User Action (Pre-condition):** User verifies all sub-task outputs are finalized and accessible.
* **Initiating/Continuing Parent Task Interactive LLM Session:**
    * The user starts or continues an interactive LLM session for the **parent task** (e.g., `HelloWorldZipEmail_ROOT`) using the same mechanism described in Step 4 (i.e., the "interactive session manager" calls `gouai_context_handler.py` for the parent task, then uses `gouai_llm_api.py` for the dialogue).
    * The `gouai_context_handler.py` will provide the full context dump for the parent task to LLM2.
* **User to LLM2 (in Parent Task Session):**
    The user pastes the summaries of sub-task outputs and the parent's initial WSOD (from the `decomposition_output.md`) into the chat, and prompts LLM2 to synthesize the "Final WSOD" for the parent task.
    * Example prompt: "All sub-tasks for `HelloWorldZipEmail_ROOT` are now complete. [User pastes summaries of outputs from `_subtask_output_tracker.md` and actual content if concise]. The parent WSOD from the decomposition step was: '[Insert parent WSOD from Step 2 `decomposition_output.md` here]'. Please synthesize all this into an updated, 'Final WSOD' for the `HelloWorldZipEmail_ROOT` task..."
* LLM2 generates the Final WSOD.
* User Action: Approves and saves this Final WSOD to the parent's `task_definition.md`.

---
#### **Step 6: Parent Task Phase 3 Execution (Clarified LLM Interaction)**
---
* **Action:** Continues within the same parent task's interactive LLM session.
* **User to LLM2:** "With this 'Final WSOD', let's proceed to Phase 3 for `HelloWorldZipEmail_ROOT`."
* LLM2, using the Final WSOD and the full parent task context (including conversation history and potentially direct content from sub-task output directories if provided again by the user or referenced), assists the user through GOUAI Phase 3.
