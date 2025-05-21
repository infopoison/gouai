import yaml
from pathlib import Path
import os
from google import genai
from google.genai import types 
from google.genai.types import Content, GenerationConfig, SafetySetting, Part
from google.genai.types import HarmCategory, HarmBlockThreshold # For parsing safety_settings_params
import google.api_core.exceptions
from typing import Iterable, Union, List, Dict, Any, Optional
import sys # For _log_error_to_project placeholder
from datetime import datetime
from gouai_task_mgmt import find_task_dir_path_from_id
import json

# --- GOUAI API Configuration & Key Management (MVP_DEV_ST3.2 & MVP_DEV_ST3.3) ---

class ConfigurationError(Exception):
    """Custom exception for GOUAI configuration errors, including API key issues."""
    pass

# --- MVP_DEV_ST3.2: Configuration File Loading Logic ---

def _get_user_config_file_path() -> Path:
    """
    Determines the absolute path to the user-level global GOUAI configuration file.
    - Linux/macOS: ~/.gouai/config.yaml
    - Windows: %APPDATA%/gouai/config.yaml
    """
    if os.name == 'nt':  # Windows
        appdata_dir = os.getenv('APPDATA')
        if appdata_dir:
            return Path(appdata_dir) / "gouai" / "config.yaml"
        else:
            return Path.home() / ".gouai" / "config.yaml" # Fallback
    else:  # Linux, macOS, other POSIX
        return Path.home() / ".gouai" / "config.yaml"

def _load_single_config_file(file_path: Path) -> tuple[dict, str]:
    """
    Loads and parses a single YAML configuration file.
    Returns (config_data, loaded_path_str) or ({}, "") if not found.
    Raises ConfigurationError for parsing or severe read issues.
    """
    config_data = {}
    loaded_path_str = ""
    if file_path.is_file():
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                if data is not None:
                    if not isinstance(data, dict):
                        raise ConfigurationError(
                            f"GOUAI Configuration Error: The configuration file: {file_path} "
                            f"must contain a valid YAML mapping (dictionary)."
                        )
                    config_data = data
                    loaded_path_str = str(file_path)
        except yaml.YAMLError as e:
            raise ConfigurationError(
                f"GOUAI Configuration Error: The API configuration file: {file_path} "
                f"contains malformed YAML and could not be parsed.\n"
                f"Please check the file syntax.\nParser error: {e}"
            ) from e
        except IOError as e:
            raise ConfigurationError(
                f"GOUAI Configuration Error: Could not read configuration file: {file_path}. Error: {e}"
            ) from e
    return config_data, loaded_path_str

def load_api_config_settings(project_root_path_str: str | None = None) -> dict:
    """
    Loads API configuration from project-level and/or user-level files.
    Project-level config (<project_root>/.gouai_config.yaml) overrides user-level.

    Returns:
        A dictionary containing the 'default_model_name'.
    Raises:
        ConfigurationError: If configuration is missing, malformed, or invalid.
    """
    user_config_path = _get_user_config_file_path()
    user_config_data, loaded_user_path_str = _load_single_config_file(user_config_path)

    project_config_data = {}
    loaded_project_path_str = ""
    project_config_path_obj = None

    if project_root_path_str:
        project_config_path_obj = Path(project_root_path_str).resolve() / ".gouai_config.yaml"
        project_config_data, loaded_project_path_str = _load_single_config_file(project_config_path_obj)

    final_config = {**user_config_data, **project_config_data}

    if not loaded_user_path_str and not loaded_project_path_str:
        project_path_info = ""
        if project_root_path_str and project_config_path_obj:
            project_path_info = f"\n   1. A project-level configuration at: {project_config_path_obj}"
        elif project_root_path_str:
             project_path_info = f"\n   1. A project-level configuration at: {Path(project_root_path_str).resolve() / '.gouai_config.yaml'}"
        else:
             project_path_info = "\n   (No project_root provided to check for project-level config)"
        user_path_info = f"\n   {'2.' if project_path_info.strip().startswith('1') else '1.'} A user-level global configuration at: {user_config_path}"
        raise ConfigurationError(
            f"GOUAI Configuration Error: API configuration file not found.\n"
            f"Please create either:{project_path_info}{user_path_info}\n"
            f"The file must be in YAML format and include at least the 'default_model_name' field.\n"
            f"Example:\n"
            f"default_model_name: \"your-chosen-model-name\""
        )

    default_model_name = final_config.get('default_model_name')
    effective_config_source_for_error = "the loaded configuration"
    if loaded_project_path_str:
        effective_config_source_for_error = f"configuration file: {loaded_project_path_str}"
    elif loaded_user_path_str:
        effective_config_source_for_error = f"configuration file: {loaded_user_path_str}"

    if default_model_name is None:
        raise ConfigurationError(
            f"GOUAI Configuration Error: The mandatory field 'default_model_name' is missing in {effective_config_source_for_error} (or effective merged configuration).\n"
            f"Please add this field to your YAML file.\n"
            f"Example:\n"
            f"default_model_name: \"your-chosen-model-name\""
        )

    if not isinstance(default_model_name, str) or not default_model_name.strip():
        raise ConfigurationError(
            f"GOUAI Configuration Error: The field 'default_model_name' in {effective_config_source_for_error} "
            f"must be a non-empty string.\n"
            f"Found: '{default_model_name}' (type: {type(default_model_name).__name__})\n"
            f"Please correct the value."
        )
    return {'default_model_name': default_model_name.strip()}

# --- MVP_DEV_ST3.3: Secure API Key Access ---

_API_KEY_ENV_VAR = "GEMINI_API_KEY" # As per project decisions [cite: 28, 685]

def _get_api_key_from_env() -> str:
    """
    Retrieves the LLM API key from the specified environment variable.

    Returns:
        The API key string.

    Raises:
        ConfigurationError: If the environment variable is not set or is empty.
    """
    api_key = os.getenv(_API_KEY_ENV_VAR)
    if not api_key or not api_key.strip():
        raise ConfigurationError(
            f"GOUAI Configuration Error: The API key environment variable '{_API_KEY_ENV_VAR}' is not set or is empty.\n"
            f"This variable is required to authenticate with the Google Gemini API.\n\n"
            f"Please set this environment variable with your API key. For example:\n"
            f"  - On Linux/macOS (bash/zsh):\n"
            f"    export {_API_KEY_ENV_VAR}=\"YOUR_API_KEY_HERE\"\n"
            f"  - On Windows (Command Prompt):\n"
            f"    set {_API_KEY_ENV_VAR}=\"YOUR_API_KEY_HERE\"\n"
            f"  - On Windows (PowerShell):\n"
            f"    $env:{_API_KEY_ENV_VAR}=\"YOUR_API_KEY_HERE\"\n\n"
            f"Ensure the variable is available in the environment where GOUAI scripts are executed."
        )
    return api_key.strip()

# --- Cached Configuration and API Key ---
_CACHED_SETTINGS = None # Will store {'default_model_name': '...', 'api_key': '...'}

def get_llm_provider_settings(project_root: str | None = None) -> dict:
    """
    Retrieves all necessary LLM provider settings (config file settings and API key).
    Loads from file/env on first call for a given project_root context, then caches.
    """
    global _CACHED_SETTINGS
    # This simple cache assumes project_root doesn't change often in one script run.
    # For CLI tools, this is usually fine as it's per invocation.
    if _CACHED_SETTINGS is None:
        config_values = load_api_config_settings(project_root) # Handles 'default_model_name'
        api_key = _get_api_key_from_env()
        _CACHED_SETTINGS = {
            'default_model_name': config_values['default_model_name'],
            'api_key': api_key
        }
    return _CACHED_SETTINGS

def get_default_model(project_root: str | None = None) -> str:
    """Convenience function to get only the default_model_name."""
    settings = get_llm_provider_settings(project_root)
    return settings['default_model_name']

def get_api_key(project_root: str | None = None) -> str:
    """Convenience function to get only the API key."""
    settings = get_llm_provider_settings(project_root)
    return settings['api_key']

# --- End of GOUAI API Configuration & Key Management ---

# --- Custom Exception ---
class LLMAPICallError(Exception):
    """Custom exception for GOUAI LLM API call errors, wrapping the original."""
    def __init__(self, message: str, original_exception: Optional[Exception] = None):
        super().__init__(message)
        self.original_exception = original_exception

# --- Placeholder for Project-Level Error Logging ---
# In a real setup, this would write to a file like <project_root>/project_errors.log
# For now, it will just print to stderr.
def _log_error_to_project(error_message: str, exception_obj: Optional[Exception] = None):
    """Placeholder for logging errors to a project-specific log."""
    print(f"[GOUAI Project Error Log] {error_message}", file=sys.stderr)
    if exception_obj:
        print(f"[GOUAI Project Error Log] Original Exception: {type(exception_obj).__name__}: {exception_obj}", file=sys.stderr)

# --- Core Internal API Call Function ---
def _call_gemini_api(
    model_name: str,
    api_key: str,
    contents: Union[str, List[Content]],
    generation_config_params: Optional[Dict[str, Any]] = None,
    safety_settings_params: Optional[List[Dict[str, Any]]] = None,
    tools: Optional[List[Any]] = None  # Tools might be handled differently with the Client API
) -> Iterable[Dict[str, Any]]:
    """
    Internal generator function to make a streaming call to the Gemini API
    using the Client().models.generate_content_stream() pattern.
    """
    try:
        # Initialize the client
        # Assuming GEMINI_API_KEY environment variable is not automatically picked up by Client()
        # and api_key parameter needs to be passed. Adjust if Client() handles env var.
        client = genai.Client(api_key=api_key) # As per user's example

        sdk_safety_settings_list = []
        if safety_settings_params:
            for setting_dict in safety_settings_params:
                try:
                    category_str = setting_dict.get('category')
                    threshold_str = setting_dict.get('threshold')
                    if category_str and threshold_str:
                        harm_category = HarmCategory[category_str.upper()]
                        harm_threshold = HarmBlockThreshold[threshold_str.upper()]
                        sdk_safety_settings_list.append(
                            SafetySetting(harm_category=harm_category, threshold=harm_threshold)
                        )
                    else:
                        _log_error_to_project(f"Invalid safety setting dict (missing category/threshold): {setting_dict}")
                except KeyError as e:
                    _log_error_to_project(f"Invalid HarmCategory or HarmBlockThreshold string in safety_settings: {str(e)} for dict {setting_dict}", e)
                except Exception as e:
                    _log_error_to_project(f"Error parsing safety setting dict {setting_dict}: {str(e)}", e)

        # Prepare GenerationConfig
        # The user example uses types.GenerateContentConfig. Let's assume 'types' is google.generativeai.types
        # and GenerationConfig is an alias or compatible.
        # For clarity, let's use the full path if 'types' is imported as something else by the user.
        # Assuming 'GenerationConfig' imported at the top is what we need for 'types.GenerateContentConfig'
        
        final_gen_config = {}
        if generation_config_params:
            final_gen_config.update(generation_config_params)
        
        # Constructing the config object as per user's example structure
        generate_config_sdk = GenerationConfig(
            **final_gen_config, # Unpack temperature, top_p, top_k, max_output_tokens, candidate_count
            safety_settings=sdk_safety_settings_list if sdk_safety_settings_list else None,
            # TODO: Incorporate thinking_config if it becomes a direct parameter or via generation_config_params
            # For now, this refactor focuses on the existing parameters of _call_gemini_api
        )

        response_stream = client.models.generate_content_stream(
            model=model_name, # The model name string directly
            contents=contents,
            generation_config=generate_config_sdk, # Pass the constructed GenerationConfig object
            # tools=tools # Need to verify how tools are passed to generate_content_stream
        )

        processed_any_chunk = False
        for chunk in response_stream:
            processed_any_chunk = True
            # Default values for each chunk processing
            text_chunk_content = ""
            thought_chunk_content = ""
            parts_chunk_content = [] # Will store the raw Part objects from this chunk
            
            # Based on user example, check candidates, then content, then parts
            if not chunk.candidates:
                yield {
                    'text_chunk': '',
                    'thought_chunk': '', # Added for thoughts
                    'parts_chunk': [],
                    'candidate_finish_reason': None,
                    'candidate_safety_ratings': [],
                    'is_chunk': True,
                    'is_thought': False
                }
                continue

            candidate = chunk.candidates[0] # Typically focus on the first candidate
            chunk_finish_reason = candidate.finish_reason.name if hasattr(candidate, 'finish_reason') and candidate.finish_reason else None
            
            chunk_safety_ratings_simplified = []
            if hasattr(candidate, 'safety_ratings') and candidate.safety_ratings:
                for sr in candidate.safety_ratings:
                    chunk_safety_ratings_simplified.append({
                        'category': sr.category.name if hasattr(sr, 'category') and sr.category else 'UNKNOWN_CATEGORY',
                        'probability': sr.probability.name if hasattr(sr, 'probability') and sr.probability else 'UNKNOWN_PROBABILITY'
                    })

            if hasattr(candidate, 'content') and candidate.content and hasattr(candidate.content, 'parts') and candidate.content.parts:
                current_chunk_parts = list(candidate.content.parts) # Make a copy
                parts_chunk_content.extend(current_chunk_parts) # Store raw parts

                for part_item in current_chunk_parts:
                    is_part_thought = hasattr(part_item, 'thought') and part_item.thought
                    
                    current_part_text = ""
                    if hasattr(part_item, 'text'):
                        current_part_text = part_item.text if part_item.text else ""

                    if is_part_thought:
                        thought_chunk_content += current_part_text
                    else:
                        text_chunk_content += current_part_text
            
            yield {
                'text_chunk': text_chunk_content,
                'thought_chunk': thought_chunk_content, # Yield thoughts separately
                'parts_chunk': parts_chunk_content, # List of Part objects from this specific chunk
                'candidate_finish_reason': chunk_finish_reason,
                'candidate_safety_ratings': chunk_safety_ratings_simplified,
                'is_chunk': True,
                'is_thought': bool(thought_chunk_content) # True if this chunk contained thought parts
            }
        
        # After the stream: Try to get usage metadata and prompt feedback
        # This part is speculative as client.models.generate_content_stream might not expose these
        # directly on the stream object post-iteration like GenerativeModel().generate_content() does.
        # You may need to parse this from the last chunk or it might not be available with this method.
        usage_metadata_dict = None
        prompt_feedback_dict = None

        # For example, Gemini API sometimes includes total token count in the last streamed message's usage_metadata.
        # Or, some client methods provide a .metadata attribute or a separate method to get this.
        # For now, let's assume it might be on the 'chunk' object if it's the last one, or not available directly.
        # This part may need further adjustment based on actual behavior of generate_content_stream.

        if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata: # Check last chunk
             usage_metadata_dict = {
                'prompt_token_count': chunk.usage_metadata.prompt_token_count,
                # candidates_token_count might be named differently or part of total
                'candidates_token_count': getattr(chunk.usage_metadata, 'candidates_token_count', getattr(chunk.usage_metadata, 'generated_token_count', 0)),
                'total_token_count': chunk.usage_metadata.total_token_count
            }
        
        # Prompt feedback is often part of the initial response if the prompt itself was problematic.
        # Checking 'chunk.prompt_feedback' (last chunk) as a guess.
        if hasattr(chunk, 'prompt_feedback') and chunk.prompt_feedback:
            block_reason_str = None
            if chunk.prompt_feedback.block_reason:
                block_reason_str = chunk.prompt_feedback.block_reason.name
            
            prompt_safety_ratings_simplified = []
            if chunk.prompt_feedback.safety_ratings:
                for sr in chunk.prompt_feedback.safety_ratings:
                     prompt_safety_ratings_simplified.append({
                        'category': sr.category.name if sr.category else 'UNKNOWN_CATEGORY',
                        'probability': sr.probability.name if sr.probability else 'UNKNOWN_PROBABILITY'
                    })
            if block_reason_str or prompt_safety_ratings_simplified:
                prompt_feedback_dict = {
                    'block_reason': block_reason_str,
                    'safety_ratings': prompt_safety_ratings_simplified
                }
        
        if processed_any_chunk or usage_metadata_dict or prompt_feedback_dict:
            yield {
                'usage_metadata': usage_metadata_dict,
                'prompt_feedback': prompt_feedback_dict,
                'is_final_summary': True
            }

    except google.api_core.exceptions.GoogleAPICallError as e: # Keep this specific catch
        error_message = f"Gemini API call failed (Client method): {type(e).__name__}: {e}"
        _log_error_to_project(error_message, e)
        yield {
            'error': error_message,
            'original_exception_type': type(e).__name__,
            'original_exception_message': str(e),
            'is_error': True
        }
        raise LLMAPICallError(message=error_message, original_exception=e) from e
        
    except Exception as e: # Catch any other unexpected errors
        error_message = f"An unexpected error occurred during Gemini API call (Client method) preparation or streaming: {type(e).__name__}: {e}"
        _log_error_to_project(error_message, e)
        yield {
            'error': error_message,
            'original_exception_type': type(e).__name__,
            'original_exception_message': str(e),
            'is_error': True
        }
        raise LLMAPICallError(message=error_message, original_exception=e) from e


def find_task_dir_path_from_id(project_root_path: Path, target_task_id: str, search_root_path: Path) -> Optional[Path]: # Placeholder
    # This function is crucial for finding where to write the llm_conversation_log.md.
    # In a real system, this would search the file system as per gouai_task_mgmt.py.
    # For this example, let's assume a flat structure if project_root is given,
    # or that task_id itself might be a path component if project_root is complex.
    # This is a significant simplification for this standalone snippet.
    print(f"DEBUG: Called find_task_dir_path_from_id: project_root_path={project_root_path}, target_task_id={target_task_id}")
    if project_root_path and target_task_id:
        # Simplistic assumption: task_id is a dir name under project_root_path / "tasks" / target_task_id
        # Or if target_task_id is like "Project_ROOT_ST1-1", it's project_root_path / "ST1-1"
        # This needs to match your actual task directory finding logic.
        # For now, let's assume target_task_id might be a relative path from project_root or
        # the find_task_dir_path_from_id correctly resolves it.
        # Let's assume the task directory is simply project_root_path / task_id_as_folder_name
        # This is a placeholder and would need your actual robust implementation from gouai_task_mgmt.py
        parts = target_task_id.split('_')
        task_dir_name = parts[-1] if len(parts) > 1 else target_task_id
        if project_root_path.name == target_task_id : # It's the root task
             return project_root_path
        
        # Simplified search for STx-y type subdirs
        for item in project_root_path.rglob(f"*{task_dir_name}"):
            if item.is_dir() and (item / "task_definition.md").exists():
                # crude check, actual find_task_dir_path_from_id is more robust
                return item
        # Fallback: assume task_id is a direct subdirectory for placeholder
        potential_path = project_root_path / task_dir_name
        if potential_path.is_dir():
            return potential_path
        print(f"WARN: Task directory for {target_task_id} not found via placeholder logic under {project_root_path}.")
        # If the task is the root project task, its directory is the project_root_path itself.
        # This logic needs to be robust based on your task_id conventions.
        # Example: if task_id is "MyProject_ROOT", dir is project_root_path.
        # If task_id is "MyProject_ROOT_ST1-1_DoStuff", dir is project_root_path / "ST1-1_DoStuff" (or similar)
        # The `find_task_dir_path_from_id` from `gouai_task_mgmt.py` does this properly.
        # For this snippet, we'll just try a direct subfolder based on the last part of ID.
        
        # Let's try matching the full task_id as a directory relative to the project_root
        # This requires a search. For now, we'll assume a simple structure for the placeholder.
        # A more robust solution would be to actually invoke your 'find_task_dir_path_from_id'
        # If the task ID refers to the project root itself:
        if target_task_id.endswith("_ROOT") and project_root_path.name == target_task_id.replace("_ROOT", ""):
            return project_root_path

    return None # Placeholder couldn't find it easily.

class LLMAPICallError(Exception):
    def __init__(self, message: str, original_exception: Optional[Exception] = None):
        super().__init__(message)
        self.original_exception = original_exception

def _log_error_to_project(error_message: str, exception_obj: Optional[Exception] = None):
    print(f"[GOUAI Project Error Log] {error_message}", file=sys.stderr)
    if exception_obj:
        print(f"[GOUAI Project Error Log] Original Exception: {type(exception_obj).__name__}: {exception_obj}", file=sys.stderr)

def _call_gemini_api(
    model_name: str,
    api_key: str,
    contents: Union[str, List[Content]],
    generation_config_params: Optional[Dict[str, Any]] = None,
    safety_settings_params: Optional[List[Dict[str, Any]]] = None,
    tools: Optional[List[Any]] = None
) -> Iterable[Dict[str, Any]]:
    try:

        client = genai.Client(api_key=api_key)
        model = model_name # Add system_instruction here if needed

        response_stream = client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                  thinking_config=types.ThinkingConfig(
                    include_thoughts=True
                )
            )
        )
        processed_any_chunk = False
        for chunk in response_stream:
            processed_any_chunk = True
            text_chunk_content = ""
            parts_chunk_content = []
            chunk_finish_reason = None
            chunk_safety_ratings_simplified = []

            if chunk.candidates:
                candidate = chunk.candidates[0] # Focus on the first candidate
                chunk_finish_reason = candidate.finish_reason.name if candidate.finish_reason else None
                if candidate.safety_ratings:
                    for sr in candidate.safety_ratings:
                        chunk_safety_ratings_simplified.append({
                            'category': sr.category.name if sr.category else 'UNKNOWN_CATEGORY',
                            'probability': sr.probability.name if sr.probability else 'UNKNOWN_PROBABILITY'
                        })
                if candidate.content and candidate.content.parts:
                    parts_chunk_content = list(candidate.content.parts)
                    for part_item in candidate.content.parts: # Changed 'part' to 'part_item' to avoid conflict
                        if hasattr(part_item, 'text'):
                            text_chunk_content += part_item.text
            
            yield {
                'text_chunk': text_chunk_content,
                'parts_chunk': parts_chunk_content,
                'candidate_finish_reason': chunk_finish_reason,
                'candidate_safety_ratings': chunk_safety_ratings_simplified,
                'is_chunk': True
            }
        
        # This part executes after the loop successfully completes or if the stream was empty.
        usage_metadata_dict = None
        if hasattr(response_stream, 'usage_metadata') and response_stream.usage_metadata:
            usage_metadata_dict = {
                'prompt_token_count': response_stream.usage_metadata.prompt_token_count,
                'candidates_token_count': response_stream.usage_metadata.candidates_token_count,
                'total_token_count': response_stream.usage_metadata.total_token_count
            }

        prompt_feedback_dict = None
        if hasattr(response_stream, 'prompt_feedback') and response_stream.prompt_feedback:
            block_reason_str = None
            if response_stream.prompt_feedback.block_reason: # Check if it's not BlockReason.BLOCK_REASON_UNSPECIFIED or None
                block_reason_str = response_stream.prompt_feedback.block_reason.name
            
            prompt_safety_ratings_simplified = []
            if response_stream.prompt_feedback.safety_ratings:
                for sr in response_stream.prompt_feedback.safety_ratings:
                     prompt_safety_ratings_simplified.append({
                        'category': sr.category.name if sr.category else 'UNKNOWN_CATEGORY',
                        'probability': sr.probability.name if sr.probability else 'UNKNOWN_PROBABILITY'
                    })
            # Only include prompt_feedback_dict if there's meaningful feedback
            if block_reason_str or prompt_safety_ratings_simplified:
                prompt_feedback_dict = {
                    'block_reason': block_reason_str,
                    'safety_ratings': prompt_safety_ratings_simplified
                }
        
        # Yield final summary only if we processed any chunk or if there's metadata
        if processed_any_chunk or usage_metadata_dict or prompt_feedback_dict:
            yield {
                'usage_metadata': usage_metadata_dict,
                'prompt_feedback': prompt_feedback_dict,
                'is_final_summary': True
            }

    except google.api_core.exceptions.GoogleAPICallError as e:
        error_message = f"Gemini API call failed: {type(e).__name__}: {e}"
        _log_error_to_project(error_message, e)
        yield {
            'error': error_message,
            'original_exception_type': type(e).__name__,
            'original_exception_message': str(e),
            'is_error': True
        }
        # Re-raise the wrapped exception to signal failure to the caller
        raise LLMAPICallError(message=error_message, original_exception=e) from e
        
    except Exception as e:
        error_message = f"An unexpected error occurred during Gemini API call preparation or streaming: {type(e).__name__}: {e}"
        _log_error_to_project(error_message, e)
        yield {
            'error': error_message,
            'original_exception_type': type(e).__name__,
            'original_exception_message': str(e),
            'is_error': True
        }
        raise LLMAPICallError(message=error_message, original_exception=e) from e

# --- End of copied _call_gemini_api ---


# --- LLM Conversation Logging Helper (Simplified for MVP) ---
def _get_task_llm_log_path(project_root_str: Optional[str], task_id: str) -> Optional[Path]:
    """
    Placeholder: Gets the path to llm_conversation_log.md for a given task.
    In a real system, this would use robust task directory discovery.
    """
    if not project_root_str: # Cannot resolve if project_root is not given
        _log_error_to_project(f"Cannot determine log path: project_root_str is None for task_id {task_id}")
        return None
        
    project_root_path = Path(project_root_str).resolve()
    
    # Use the more robust find_task_dir_path_from_id (placeholder used here for now)
    # The actual find_task_dir_path_from_id needs the project_root_path as the search root as well.
    task_dir = find_task_dir_path_from_id(project_root_path, task_id, project_root_path) # search_root_path is project_root_path

    if task_dir and task_dir.is_dir():
        return task_dir / "llm_conversation_log.md"
    else:
        _log_error_to_project(f"Task directory for task_id '{task_id}' not found under project '{project_root_str}'. Cannot write LLM log.")
        return None

def _format_prompt_content_for_log(contents: Union[str, List[Content]]) -> str:
    """Formats the prompt contents for logging."""
    if isinstance(contents, str):
        return contents
    
    log_str_parts = []
    for content_item in contents: # Assuming contents is List[Content]
        if isinstance(content_item, Content):
            role_prefix = f"Role: {content_item.role}\n" if content_item.role else ""
            log_str_parts.append(role_prefix)
            for part_item in content_item.parts:
                if hasattr(part_item, 'text') and part_item.text:
                    log_str_parts.append(part_item.text)
                elif hasattr(part_item, 'inline_data') and part_item.inline_data:
                    log_str_parts.append(f"[Inline Data: {part_item.inline_data.mime_type}]")
                elif hasattr(part_item, 'file_data') and part_item.file_data:
                    log_str_parts.append(f"[File Data: {part_item.file_data.mime_type}, URI: {part_item.file_data.file_uri}]")
                # Add more specific part handling if needed
    return "\n".join(log_str_parts)


def _append_turn_to_llm_log(
    log_file_path: Path,
    role: str, # "User" or "Assistant"
    content_to_log: str,
    model_name_for_session: Optional[str] = None, # For initial YAML if file is new, not for updating
    session_id_for_session: Optional[str] = None, # For initial YAML
    task_id_for_session: Optional[str] = None, # For initial YAML
    turn_metadata: Optional[Dict[str, Any]] = None # For assistant: usage, finish_reason, safety
):
    """
    Appends a turn to the llm_conversation_log.md.
    Simplified for MVP: Does NOT update YAML frontmatter for existing files.
    It will create the file with basic YAML if it doesn't exist.
    """
    try:
        timestamp = datetime.now().isoformat(sep=" ", timespec="seconds")
        turn_entry = f"### {role}\n**Timestamp:** {timestamp}\n\n{content_to_log}\n"

        if turn_metadata:
            turn_entry += "\n**Turn Metadata:**\n"
            for key, value in turn_metadata.items():
                if value is not None:
                    turn_entry += f"  - **{key.replace('_', ' ').title()}:** {value}\n"
        
        turn_entry += "\n---\n"

        if not log_file_path.exists():
            # Create file with initial YAML frontmatter
            # Based on 1.2_SystemArchitecture.txt
            # and gouai_task_mgmt.py's _create_llm_conversation_log_md
            initial_yaml = (
                f"session_id: {session_id_for_session or 'null'}\n"
                f"task_id: {task_id_for_session or 'null'}\n"
                f"llm_model_used: {model_name_for_session or 'null'}\n" # Log model used for this session start
                f"session_start_timestamp: \"{timestamp}\"\n"
                f"api_request_id_initial: null\n" # Not easily available/relevant for all calls
                f"total_tokens_used: 0\n" # MVP: Not updated dynamically here
                f"total_cost_estimate: 0.0\n" # MVP: Not updated dynamically here
            )
            header = "## LLM Conversation Log\n\n"
            log_file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file_path, "w", encoding="utf-8") as f:
                f.write(f"---\n{initial_yaml}---\n{header}")
        
        with open(log_file_path, "a", encoding="utf-8") as f:
            f.write(turn_entry)

    except IOError as e:
        _log_error_to_project(f"IOError appending to LLM log '{log_file_path}': {e}", e)
    except Exception as e: # Catch any other unexpected error during logging
        _log_error_to_project(f"Unexpected error appending to LLM log '{log_file_path}': {e}", e)


# --- Public API Functions ---
def generate_response_stream(
    project_root: Optional[str], # Needed for config and potentially log path finding
    session_id: str,
    task_id: str,
    prompt_text: Optional[str] = None,
    contents: Optional[Union[str, List[Content]]] = None,
    override_model_name: Optional[str] = None,
    override_generation_config: Optional[Dict[str, Any]] = None,
    override_safety_settings: Optional[List[Dict[str, Any]]] = None,
    override_tools: Optional[List[Any]] = None
) -> Iterable[Dict[str, Any]]:
    """
    Public function to get a streaming response from the configured LLM (Gemini for MVP).
    Handles configuration, API key, logging, and calls the core API function.
    Logs user prompt before call, and assistant response after stream completion.
    """
    if not project_root and "~" not in str(Path().home()): # Check if we can even resolve user config without project root
        # This check is a bit simplistic; load_api_config_settings handles None project_root
        # by only trying user-level. But for logging path, project_root is more critical.
        # If user-level config is the only source, and task_id implies a non-project specific context,
        # logging path becomes ambiguous.
        # For now, we'll proceed, but _get_task_llm_log_path might return None.
        pass

    log_file_path = _get_task_llm_log_path(project_root, task_id)

    try:
        settings = get_llm_provider_settings(project_root) #
        api_key = settings.get('api_key')
        if not api_key:
            # This case should be handled by get_llm_provider_settings raising ConfigurationError
            # for empty GEMINI_API_KEY
            raise MockConfigurationError("API key not found in settings.") 

        actual_model_name = override_model_name or settings.get('default_model_name')
        if not actual_model_name:
            # This case should be handled by get_llm_provider_settings (via load_api_config_settings)
            # raising ConfigurationError if default_model_name is missing
            raise MockConfigurationError("LLM model name not configured.")

        actual_contents: Union[str, List[Content]] # type: ignore # For linters if Content not fully defined here
        if contents is not None:
            if isinstance(contents, str):
                try:
                    # Attempt to parse as JSON representing List[Content-like dicts]
                    # The dict structure should be like: {"role": "user", "parts": [{"text": "Hello"}]}
                    parsed_json_contents = json.loads(contents)
                    if isinstance(parsed_json_contents, list):
                        # The Gemini SDK can often take a list of dicts directly for `contents`
                        # if they match the expected structure.
                        actual_contents = parsed_json_contents 
                    else:
                        # Not a list, treat as a single string prompt.
                        actual_contents = contents 
                except json.JSONDecodeError:
                    # Not a valid JSON string, treat as a single string prompt.
                    actual_contents = contents
            else:
                # `contents` is already not a string (e.g., perhaps List[Content] if called internally)
                actual_contents = contents # type: ignore
        elif prompt_text is not None:
            actual_contents = prompt_text
        else:
            raise ValueError("Either 'prompt_text' or 'contents' must be provided.")

                
        # Log User Prompt
        if log_file_path:
            content_for_this_user_log_entry = ""
            if isinstance(actual_contents, list) and actual_contents:
                # The last item in the history is the current user's input (or the initial prime)
                last_message = actual_contents[-1]
                if isinstance(last_message, dict) and last_message.get("role") == "user":
                    parts_data = last_message.get("parts", [])
                    text_from_parts = []
                    for part in parts_data:
                        if isinstance(part, dict) and "text" in part:
                            text_from_parts.append(part["text"])
                        elif isinstance(part, str): # If parts can be just strings (less likely for Gemini standard)
                            text_from_parts.append(part)
                    content_for_this_user_log_entry = "\n".join(text_from_parts)
                else:
                    # Fallback: Should not happen if history is built correctly by gouai.py chat
                    content_for_this_user_log_entry = "[Error: Could not extract last user message for log]"
            elif isinstance(actual_contents, str):
                # If actual_contents is just a string (e.g., first prime before being wrapped in dict)
                content_for_this_user_log_entry = actual_contents
            else:
                content_for_this_user_log_entry = "[Error: Invalid format for actual_contents_for_api for logging]"

            _append_turn_to_llm_log(
                log_file_path, 
                "User", 
                content_for_this_user_log_entry, # Log only the current user/system message
                model_name_for_session=actual_model_name,
                session_id_for_session=session_id,
                task_id_for_session=task_id
            )

        response_iterator = _call_gemini_api(
            model_name=actual_model_name,
            api_key=api_key,
            contents=actual_contents, # LLM gets full history
            # ... other params
        )
        # ... rest of the function (iterating response_iterator, logging Assistant turn) ...

        # --- Call the internal API function ---
        response_iterator = _call_gemini_api(
            model_name=actual_model_name,
            api_key=api_key,
            contents=actual_contents,
            generation_config_params=override_generation_config,
            safety_settings_params=override_safety_settings,
            tools=override_tools
        )

        # --- Process and yield stream, then log assistant response ---
        accumulated_text_response = ""
        accumulated_parts_response: List[Part] = []
        
        final_summary_data: Optional[Dict[str, Any]] = None
        error_data: Optional[Dict[str, Any]] = None
        
        assistant_turn_metadata = {}

        for chunk_dict in response_iterator:
            if chunk_dict.get('is_error'):
                error_data = chunk_dict # Store error and stop processing normal chunks
                # Error is already logged by _call_gemini_api before yielding this
                yield chunk_dict # Forward the error chunk
                break 
            elif chunk_dict.get('is_final_summary'):
                final_summary_data = chunk_dict # Store final summary
                # Don't yield this immediately, it's for post-stream logging and aggregation
                # but we need to make sure this doesn't get missed if no chunks were processed.
                if final_summary_data.get('usage_metadata'):
                    assistant_turn_metadata['usage_metadata'] = final_summary_data['usage_metadata']
                if final_summary_data.get('prompt_feedback'):
                     assistant_turn_metadata['prompt_feedback'] = final_summary_data['prompt_feedback']
                continue # Don't yield the summary itself, the loop ends, then we log.
            elif chunk_dict.get('is_chunk'):
                yield chunk_dict # Yield the actual content chunk
                accumulated_text_response += chunk_dict.get('text_chunk', '')
                if chunk_dict.get('parts_chunk'):
                    # This simple accumulation might not be ideal for all Part types,
                    # but for text it's okay. For multimodal, caller might need raw parts_chunk.
                    accumulated_parts_response.extend(chunk_dict.get('parts_chunk', []))
                
                # Capture finish_reason and safety_ratings from the last chunk processed,
                # as these might be updated progressively by some models.
                if chunk_dict.get('candidate_finish_reason'):
                    assistant_turn_metadata['finish_reason'] = chunk_dict['candidate_finish_reason']
                if chunk_dict.get('candidate_safety_ratings'):
                    assistant_turn_metadata['safety_ratings'] = chunk_dict['candidate_safety_ratings']


        # Log Assistant Response or Error
        if log_file_path:
            if error_data:
                _append_turn_to_llm_log(
                    log_file_path, "Assistant",
                    f"Error during API call: {error_data.get('error')}\n"
                    f"Original Exception: {error_data.get('original_exception_type')} - {error_data.get('original_exception_message')}"
                )
            elif accumulated_text_response or accumulated_parts_response or final_summary_data : # Log if there was any response
                # For logging, use accumulated_text_response.
                # If more complex content, one might choose to log a summary of accumulated_parts_response.
                _append_turn_to_llm_log(
                    log_file_path, "Assistant",
                    accumulated_text_response if accumulated_text_response else "[No text content in response parts]",
                    turn_metadata=assistant_turn_metadata
                )
            # If stream was empty and no error, and no final_summary_data with content, nothing may be logged for assistant.

    except ConfigurationError as e: # Or your actual ConfigurationError
        _log_error_to_project(f"Configuration error in generate_response_stream for task {task_id}: {e}", e)
        # Yield an error structure if the function is expected to always yield
        yield {'error': str(e), 'is_error': True, 'is_configuration_error': True}
        # And/or re-raise
        raise
    except LLMAPICallError: # Already logged by _call_gemini_api if it raised this
        # This function might have yielded an error dict already from _call_gemini_api
        # Re-raise to indicate failure to the caller of generate_response_stream
        raise
    except ValueError as e: # e.g. if prompt_text and contents are both None
        _log_error_to_project(f"ValueError in generate_response_stream for task {task_id}: {e}", e)
        yield {'error': str(e), 'is_error': True, 'is_value_error': True}
        raise
    except Exception as e: # Catch-all for other unexpected issues in this function
        _log_error_to_project(f"Unexpected error in generate_response_stream for task {task_id}: {e}", e)
        yield {'error': str(e), 'is_error': True, 'is_unexpected_error': True}
        raise

def generate_response_aggregated(
    project_root: Optional[str],
    session_id: str,
    task_id: str,
    prompt_text: Optional[str] = None,
    contents: Optional[Union[str, List[Content]]] = None,
    override_model_name: Optional[str] = None,
    override_generation_config: Optional[Dict[str, Any]] = None,
    override_safety_settings: Optional[List[Dict[str, Any]]] = None,
    override_tools: Optional[List[Any]] = None
) -> Dict[str, Any]:
    """
    Public function that calls generate_response_stream and aggregates the
    chunks into a single response dictionary.
    """
    full_text_response = []
    # For simplicity, we'll just aggregate text. A more complex aggregation
    # might reconstruct a List[Part] or handle multimodal outputs differently.
    # The last seen 'parts_chunk' from the stream could be returned, or all parts aggregated.
    
    final_response_data = {
        'text': "",
        'usage_metadata': None,
        'prompt_feedback': None,
        'finish_reason': None,
        'safety_ratings': None,
        'error_info': None # To store any error encountered
    }

    try:
        stream_iterator = generate_response_stream(
            project_root=project_root,
            session_id=session_id,
            task_id=task_id,
            prompt_text=prompt_text,
            contents=contents,
            override_model_name=override_model_name,
            override_generation_config=override_generation_config,
            override_safety_settings=override_safety_settings,
            override_tools=override_tools
        )

        for chunk in stream_iterator:
            if chunk.get('is_error'):
                final_response_data['error_info'] = {
                    'message': chunk.get('error'),
                    'type': chunk.get('original_exception_type') or ('ConfigurationError' if chunk.get('is_configuration_error') else 'ValueError' if chunk.get('is_value_error') else 'LLMProcessingError'),
                    'details': chunk.get('original_exception_message')
                }
                # If an error occurs, we might not get further valid data or summary.
                # The error would have been logged by generate_response_stream or _call_gemini_api.
                break # Stop aggregation on error

            if chunk.get('is_chunk'):
                full_text_response.append(chunk.get('text_chunk', ''))
                # These might be overwritten by later chunks, which is usually fine for streaming
                if chunk.get('candidate_finish_reason'):
                    final_response_data['finish_reason'] = chunk.get('candidate_finish_reason')
                if chunk.get('candidate_safety_ratings'):
                    final_response_data['safety_ratings'] = chunk.get('candidate_safety_ratings')
            
            # The final summary from _call_gemini_api (usage_metadata, prompt_feedback)
            # is handled by generate_response_stream for logging purposes.
            # Here we just reconstruct the main parts for the aggregated response.
            # The internal _call_gemini_api yields 'is_final_summary' which generate_response_stream consumes.
            # For generate_response_aggregated, the key is the accumulated content and final state.
            # The final_summary_data is captured by generate_response_stream for logging the assistant turn.
            # We need to get that info here too.
            # Let's assume the last non-error, non-chunk item from _call_gemini_api's structure if it was yielded.
            # However, `generate_response_stream` consumes the final_summary for logging.
            # This means `generate_response_aggregated` needs to reconstruct it from the assistant log turn,
            # or `generate_response_stream` needs to return it.
            # For simplicity, we'll rely on the last chunk's info for finish_reason/safety and
            # acknowledge that usage_metadata and prompt_feedback are logged but might be harder
            # to pass cleanly to this aggregated function without changing generate_response_stream's yield.

            # Simpler: generate_response_stream's logging helper captures the usage_metadata.
            # If this aggregated function needs it, it should be part of the contract of what
            # generate_response_stream yields, OR this function needs to re-parse the log (bad).

            # Let's refine: generate_response_stream should also yield the final_summary_data if available.
            # (generate_response_stream was modified to capture final_summary_data in assistant_turn_metadata)
            # For the aggregated response, we need to get this assistant_turn_metadata.
            # This is tricky as generate_response_stream is a generator.
            #
            # The simplest path for generate_response_aggregated is to call the internal
            # _call_gemini_api directly again for aggregation if strict separation is hard.
            # OR, generate_response_stream can be designed to return a tuple: (iterator, function_to_get_summary_after_iteration)
            # For now, let's assume that the *last values* of finish_reason and safety_ratings are sufficient
            # and usage_metadata/prompt_feedback will be available in the log.
            # This is a simplification for the aggregated return.
            # A more robust solution might involve generate_response_stream returning more comprehensive final data.

        final_response_data['text'] = "".join(full_text_response)
        
        # If no specific error was caught and yielded by the stream,
        # but the text is empty and there was no clear finish reason,
        # it might indicate a silent block or empty response.
        if not final_response_data['error_info'] and not final_response_data['text'] and not final_response_data['finish_reason']:
            # Check if prompt was blocked (this info is in final_summary_data, which is tricky to get here)
            # For now, this is a basic check.
            # If prompt_feedback had a block_reason, that would be the real cause.
            # This aggregated function is simplified regarding final metadata.
            pass


    except LLMAPICallError as e:
        final_response_data['error_info'] = {
            'message': str(e),
            'type': type(e.original_exception).__name__ if e.original_exception else "LLMAPICallError",
            'details': str(e.original_exception) if e.original_exception else str(e)
        }
    except MockConfigurationError as e: # Or your actual ConfigurationError
         final_response_data['error_info'] = {
            'message': str(e),
            'type': "ConfigurationError"
        }
    except ValueError as e:
         final_response_data['error_info'] = {
            'message': str(e),
            'type': "ValueError"
        }
    except Exception as e: # Catch-all
        final_response_data['error_info'] = {
            'message': str(e),
            'type': type(e).__name__
        }
        _log_error_to_project(f"Unexpected error in generate_response_aggregated for task {task_id}: {e}", e)

    # How to get usage_metadata and prompt_feedback here reliably after stream consumption?
    # The `assistant_turn_metadata` in `generate_response_stream` holds it before logging.
    # `generate_response_stream` would need to return this info *after* the stream is done.
    # This is a structural challenge for generators.
    # For MVP, `generate_response_aggregated` might not include rich `usage_metadata` or `prompt_feedback`
    # in its direct return, and users would refer to the log file for that detail.
    # Or, the primary use case is streaming, and aggregation is a simple utility.

    # To improve: One could pass a list to generate_response_stream to populate with final metadata.
    # e.g., final_metadata_capture = []
    # for chunk in generate_response_stream(..., final_metadata_out=final_metadata_capture):
    # if final_metadata_capture: update final_response_data

    return final_response_data