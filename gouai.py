# gouai.py

import argparse
import subprocess # Still needed for gouai_context_handler.py and other general script calls
import sys
from pathlib import Path
import uuid
import json
import shlex

# --- Configuration for GOUAI script paths ---
SCRIPT_DIR = Path(__file__).resolve().parent
GOUAI_CONTEXT_HANDLER_SCRIPT = str(SCRIPT_DIR / "gouai_context_handler.py")
# GOUAI_LLM_API_SCRIPT is no longer needed here if we import its functions directly for chat
GOUAI_PROJECT_INIT_SCRIPT = str(SCRIPT_DIR / "gouai_project_init.py")
GOUAI_EXECUTE_P1P2_SCRIPT = str(SCRIPT_DIR / "execute_gouai_p1p2.py")
GOUAI_MAKE_SUBTASKS_SCRIPT = str(SCRIPT_DIR / "make_gouai_subtasks.py")

# --- Direct Imports from GOUAI Modules for Chat ---
try:
    from gouai_llm_api import (
        generate_response_stream,
        # We might need these if we want to handle specific errors from the API module
        # ConfigurationError as LLMConfigError, 
        # LLMAPICallError
    )
    # The imported generate_response_stream should handle its own internal dependencies like 
    # get_llm_provider_settings, _call_gemini_api, logging, etc.
except ImportError as e:
    print(f"CRITICAL ERROR: Could not import necessary functions from gouai_llm_api.py for chat. {e}", file=sys.stderr)
    print("Ensure gouai_llm_api.py is in your PYTHONPATH or the same directory.", file=sys.stderr)
    sys.exit(1)


def run_script_capture_stdout(script_path: str, args_list: list) -> tuple[str | None, str | None]:
    """
    Runs a Python script using subprocess and captures its stdout.
    Returns (stdout_str, error_message_if_any)
    """
    command = [sys.executable, script_path] + args_list
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False 
        )
        
        if process.returncode != 0:
            error_message = f"ERROR: Script '{Path(script_path).name}' exited with code {process.returncode}."
            if process.stderr and process.stderr.strip(): # Only print stderr if there's an error and stderr has content
                error_message += f"\n--- STDERR from {Path(script_path).name} ---\n{process.stderr.strip()}\n--- END STDERR ---"
            return None, error_message 
        return process.stdout.strip(), None # Return None for error message slot if successful
    except FileNotFoundError:
        err_msg = f"ERROR: Script not found at {script_path}."
        # print(err_msg, file=sys.stderr) # Keep this, it's a `gouai.py` level error
        return None, err_msg
    except Exception as e:
        err_msg = f"ERROR: An unexpected error occurred while running {Path(script_path).name}: {type(e).__name__} - {e}"
        # print(err_msg, file=sys.stderr) # Keep this
        return None, err_msg
        
# run_script_stream_stdout is NO LONGER needed for the chat loop if we import directly.
# It could be kept if other subcommands genuinely call scripts that stream simple text lines.

def format_conversation_history_for_api_direct_call(history: list) -> list:
    """
    Ensures the conversation history is in the List[Dict[str,Any]] format
    that the imported generate_response_stream (and underlying Gemini SDK) expects for its 'contents' argument.
    Each item in history: {"role": "user" or "model", "parts": [{"text": "..."}]}
    """
    # The history is already maintained in this format in handle_chat_session
    return history

def handle_chat_session(task_id: str, project_root_str: str, session_id_override: str = None):
    """Handles the interactive chat session for a GOUAI task by directly calling imported LLM API functions."""
    project_root = Path(project_root_str)
    if not project_root.is_dir():
        print(f"ERROR: Project root '{project_root}' not found or not a directory.", file=sys.stderr)
        return

    print(f"Starting GOUAI chat session for task: {task_id}...")
    print(f"Project root: {project_root}")

    # 1. Get Priming Prompt from gouai_context_handler.py (still using subprocess for this separate utility)
    print("INFO: Preparing context with gouai_context_handler.py...")
    prime_prompt_stdout, prime_prompt_stderr = run_script_capture_stdout(
        GOUAI_CONTEXT_HANDLER_SCRIPT,
        ["--task_id", task_id, "--project_root", str(project_root)]
    )

    if prime_prompt_stdout is None:
        print(f"ERROR: Failed to get priming prompt from context handler for task {task_id}.", file=sys.stderr)
        if prime_prompt_stderr: print(f"Details:\n{prime_prompt_stderr}", file=sys.stderr)
        return
    
    initial_prime_for_llm2 = prime_prompt_stdout
    
    # conversation_history is List[Dict] compatible with Gemini Content structure
    conversation_history = [
        {"role": "user", "parts": [{"text": initial_prime_for_llm2}]}
    ]

    session_id = session_id_override or str(uuid.uuid4())
    print(f"INFO: Chat session ID: {session_id}")
    print("INFO: Type '/quit' or '/exit' to end the session. Type '/history' to view conversation log.")
    print("---")

    # Optional: Send the initial prime to LLM2 and get its first response.
    print("INFO: LLM2 is processing initial context...", end="", flush=True)
    
    try:
        # Directly call the imported generate_response_stream
        # The `contents` argument for generate_response_stream (in gouai_llm_api.py)
        # should be ready to accept this List[Dict[str,Any]] structure.
        # (The modification to accept JSON string in gouai_llm_api.py's contents is still good
        # for when it's called as a script by OTHER tools, but when called as a library here,
        # we can pass the Python object directly.)
        
        full_initial_response_text = ""
        print_llm_prefix = True
        for chunk_dict in generate_response_stream(
            project_root=str(project_root),
            session_id=session_id,
            task_id=task_id,
            contents=conversation_history # Pass the Python list of dicts directly
        ):
            sys.stdout.write('\r' + ' ' * 30 + '\r') # Clear "processing" message
            if print_llm_prefix:
                print("LLM: ", end="", flush=True)
                print_llm_prefix = False
            
            if chunk_dict.get('is_error'):
                err_msg = chunk_dict.get('error', 'Unknown LLM stream error')
                print(f"\nERROR: LLM API Error: {err_msg}", file=sys.stderr)
                # Potentially log this error if generate_response_stream doesn't log it fully
                return # Abort session on initial error
            if chunk_dict.get('is_chunk'):
                text_chunk = chunk_dict.get('text_chunk', '')
                print(text_chunk, end="", flush=True)
                full_initial_response_text += text_chunk
        print() # Newline after streaming

        if full_initial_response_text.strip():
            conversation_history.append({"role": "model", "parts": [{"text": full_initial_response_text.strip()}]})
        # Logging of this turn is handled internally by generate_response_stream in gouai_llm_api.py

    except Exception as e: # Catch errors from direct call, e.g. LLMConfigError, LLMAPICallError from gouai_llm_api
        sys.stdout.write('\r' + ' ' * 30 + '\r') # Clear "processing" message
        print(f"\nERROR: During initial LLM call: {type(e).__name__} - {e}", file=sys.stderr)
        return

    # Main interactive loop
    while True:
        try:
            user_input = input("\nYou: ").strip()
        except EOFError: 
            print("\nINFO: EOF detected. Exiting chat session.")
            break
        except KeyboardInterrupt:
             print("\nINFO: Keyboard interrupt. Exiting chat session.")
             break

        if user_input.lower() in ["/quit", "/exit"]:
            print("INFO: Exiting chat session.")
            break
        if user_input.lower() == "/history":
            print("\n--- Conversation History (for this session) ---")
            for i, turn in enumerate(conversation_history):
                role = turn.get('role', 'unknown')
                text_parts = [part.get('text', '') for part in turn.get('parts', [])]
                full_text = " ".join(text_parts).strip()
                print(f"Turn {i+1} ({role}):\n  {full_text}")
            print("--- End History ---")
            continue
        if not user_input:
            continue

        conversation_history.append({"role": "user", "parts": [{"text": user_input}]})
        
        sys.stdout.write("LLM is thinking...")
        sys.stdout.flush()
        
        try:
            full_turn_response_text = ""
            print_llm_prefix_turn = True
            for chunk_dict in generate_response_stream( # DIRECTLY CALLING
                project_root=str(project_root),
                session_id=session_id,
                task_id=task_id,
                contents=conversation_history # Pass full history
            ):
                # Clear "LLM is thinking..." only once meaningful output starts
                if print_llm_prefix_turn and (chunk_dict.get('is_chunk') or chunk_dict.get('is_error')):
                    sys.stdout.write('\r' + ' ' * 30 + '\r') 
                    sys.stdout.flush()
                    print("LLM: ", end="", flush=True)
                    print_llm_prefix_turn = False

                if chunk_dict.get('is_error'):
                    err_msg = chunk_dict.get('error', 'Unknown LLM stream error during turn')
                    print(f"\nERROR: LLM API Error: {err_msg}", file=sys.stderr)
                    conversation_history.pop() # Remove last user message from history
                    full_turn_response_text = None # Signal error for history addition
                    break 
                if chunk_dict.get('is_chunk'):
                    text_chunk = chunk_dict.get('text_chunk', '')
                    print(text_chunk, end="", flush=True)
                    full_turn_response_text += text_chunk
            
            # Ensure "LLM is thinking..." is cleared if loop finishes (e.g. empty stream)
            if print_llm_prefix_turn: # If "LLM:" was never printed
                 sys.stdout.write('\r' + ' ' * 30 + '\r')
                 sys.stdout.flush()
            print() # Newline after streaming

            if full_turn_response_text is not None and full_turn_response_text.strip():
                conversation_history.append({"role": "model", "parts": [{"text": full_turn_response_text.strip()}]})
            elif full_turn_response_text is None: # Error occurred and was handled
                pass

        except Exception as e: # Catch errors from direct call
            sys.stdout.write('\r' + ' ' * 30 + '\r') # Clear "thinking" message
            print(f"\nERROR: During LLM turn: {type(e).__name__} - {e}", file=sys.stderr)
            if conversation_history and conversation_history[-1]["role"] == "user":
                conversation_history.pop() # Remove last user message if LLM call failed entirely
    
def main_cli():
    parser = argparse.ArgumentParser(
        description="GOUAI Command Line Interface (CLI) dispatcher.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="Available GOUAI commands", required=True)

    # ... (init, decompose, make-subtasks parsers remain the same, using run_script_capture_stdout) ...
    # --- init subcommand ---
    init_parser = subparsers.add_parser("init", help="Initialize a new GOUAI project.")
    init_parser.add_argument("--name", required=True, help="The name of the project.")
    init_parser.add_argument("--root_dir", required=True, help="Parent directory for the new project.")
    init_parser.set_defaults(func=lambda args_ns: run_script_capture_stdout(GOUAI_PROJECT_INIT_SCRIPT, ["--name", args_ns.name, "--root_dir", args_ns.root_dir]))

    # --- decompose subcommand ---
    decompose_parser = subparsers.add_parser("decompose", help="Automated Parent Task Analysis & Decomposition (execute_gouai_p1p2.py).")
    decompose_parser.add_argument("--parent_task_id", required=True, help="Full string ID of the parent GOUAI task.")
    decompose_parser.add_argument("--project_root_path", required=True, help="Path to the root directory of the GOUAI project.")
    decompose_parser.add_argument("--output_document_path", required=True, help="Full file path to save the generated Decomposition Document.")
    decompose_parser.set_defaults(func=lambda args_ns: run_script_capture_stdout(GOUAI_EXECUTE_P1P2_SCRIPT, ["--parent_task_id", args_ns.parent_task_id, "--project_root_path", args_ns.project_root_path, "--output_document_path", args_ns.output_document_path]))

    # --- make-subtasks subcommand ---
    make_subtasks_parser = subparsers.add_parser("make-subtasks", help="Sub-task Review, Refinement & Instantiation (make_gouai_subtasks.py).")
    make_subtasks_parser.add_argument("--document_path", required=True, help="Path to the Decomposition Document.")
    make_subtasks_parser.add_argument("--project_root_path", required=True, help="Path to the GOUAI project root.")
    make_subtasks_parser.add_argument("--parent_task_id_for_new_tasks", required=True, help="Task ID of the original parent task for new sub-tasks.")
    make_subtasks_parser.set_defaults(func=lambda args_ns: run_script_capture_stdout(GOUAI_MAKE_SUBTASKS_SCRIPT, ["--document_path", args_ns.document_path, "--project_root_path", args_ns.project_root_path, "--parent_task_id_for_new_tasks", args_ns.parent_task_id_for_new_tasks]))
    
    # --- chat subcommand ---
    chat_parser = subparsers.add_parser("chat", help="Start an interactive GOUAI chat session for a task.")
    chat_parser.add_argument("--task_id", required=True, help="The GOUAI task ID.")
    chat_parser.add_argument("--project_root", required=True, help="Path to the GOUAI project root.")
    chat_parser.add_argument("--session_id", help="Optional: specify a session ID to resume or use for the chat.")
    chat_parser.set_defaults(func=lambda args_ns: handle_chat_session(args_ns.task_id, args_ns.project_root, args_ns.session_id))

    args = parser.parse_args()
    
    if args.command != "chat": # Non-chat commands use the simple stdout/stderr print
        stdout, stderr = args.func(args)
        if stdout is not None: print(stdout)
        if stderr is not None: print(stderr, file=sys.stderr)
    else:
        args.func(args) # chat command handles its own interactive printing

if __name__ == "__main__":
    main_cli()