import unittest
from unittest.mock import patch, MagicMock, mock_open
import os
from pathlib import Path
import tempfile
from datetime import datetime
import yaml # For yaml.YAMLError and potentially for mock_safe_load if needed by type hints

# --- Import the Google API core exceptions if your code specifically catches them by type ---
# (The test code for _call_gemini_api uses google.api_core.exceptions.InvalidArgument)
import google.api_core.exceptions

# --- Now, import the components from your gouai_llm_api.py module ---
# To make this work, you typically run your tests from the `gouai_project_root` directory.
# For example: `python -m unittest tests.test_gouai_llm_api`
# This allows Python to find `gouai_llm_api` as a top-level module.

# If `gouai_llm_api.py` is directly in `gouai_project_root/`:
from gouai_llm_api import (
    # Config and API Key related
    load_api_config_settings,
    ConfigurationError,
    _get_user_config_file_path, # Used in @patch targets
    _API_KEY_ENV_VAR,
    _get_api_key_from_env,
    get_llm_provider_settings,
    _CACHED_SETTINGS, # Global variable used in one test for reset

    # Core API call related
    _call_gemini_api,
    LLMAPICallError,
    # Note: 'genai' itself is patched at the class/method level using 'gouai_llm_api.genai'
    # so a direct import here might not be needed unless you're type-hinting with genai types.

    # Logging related
    _log_error_to_project, # Mocked in one test
    _append_turn_to_llm_log,
    # _get_task_llm_log_path is used as a patch target if testing its callers directly
    # _format_prompt_content_for_log if you add tests for it

    # Public stream/aggregation functions
    generate_response_stream
    # generate_response_aggregated if you add tests for it
)

# If you need specific types from google.generativeai for your mock classes,
# you might import them here too, though often mocks can bypass strict typing.
# e.g., from google.generativeai.types import Content, Part (if your mocks need to be instances of these)
# However, your mock classes like MockGeminiPart are standalone for testing.


# In a TestClass inheriting from unittest.TestCase
class TestConfigLoading(unittest.TestCase):
    # Assume 'load_api_config_settings' and 'ConfigurationError' are imported from gouai_llm_api

    @patch('gouai_llm_api.yaml.safe_load')
    @patch('builtins.open', new_callable=mock_open)
    @patch('pathlib.Path.is_file')
    def test_load_project_config_only(self, mock_is_file, mock_file_open, mock_safe_load):
        # Simulate only project config exists
        def is_file_side_effect(path):
            if "project_root/.gouai_config.yaml" in str(path):
                return True
            return False
        mock_is_file.side_effect = is_file_side_effect
        mock_safe_load.return_value = {'default_model_name': 'project_model'}

        config = load_api_config_settings(project_root_path_str="project_root")
        self.assertEqual(config['default_model_name'], 'project_model')
        mock_safe_load.assert_called_once() # Ensure only project was effectively loaded

    @patch('gouai_llm_api.yaml.safe_load')
    @patch('builtins.open', new_callable=mock_open)
    @patch('pathlib.Path.is_file')
    @patch('gouai_llm_api._get_user_config_file_path') # Mock this to control user path
    def test_load_user_config_only(self, mock_user_path, mock_is_file, mock_file_open, mock_safe_load):
        mock_user_path.return_value = Path("/fake/user/.gouai/config.yaml")
        # Simulate only user config exists
        def is_file_side_effect(path):
            if str(path) == "/fake/user/.gouai/config.yaml":
                return True
            return False
        mock_is_file.side_effect = is_file_side_effect
        mock_safe_load.return_value = {'default_model_name': 'user_model'}

        config = load_api_config_settings(project_root_path_str=None)
        self.assertEqual(config['default_model_name'], 'user_model')
        mock_safe_load.assert_called_once()

    @patch('gouai_llm_api.yaml.safe_load')
    @patch('builtins.open', new_callable=mock_open)
    @patch('pathlib.Path.is_file')
    @patch('gouai_llm_api._get_user_config_file_path')
    def test_project_overrides_user_config(self, mock_user_path, mock_is_file, mock_file_open, mock_safe_load):
        mock_user_path.return_value = Path("/fake/user/.gouai/config.yaml")
        # Simulate both exist
        mock_is_file.return_value = True
        # yaml.safe_load will be called twice; first for user, then for project
        mock_safe_load.side_effect = [
            {'default_model_name': 'user_model'}, # User config data
            {'default_model_name': 'project_model'}  # Project config data
        ]
        config = load_api_config_settings(project_root_path_str="project_root")
        self.assertEqual(config['default_model_name'], 'project_model') # Project should override
        self.assertEqual(mock_safe_load.call_count, 2)

    @patch('pathlib.Path.is_file', return_value=False) # No files exist
    def test_load_missing_config_files(self, mock_is_file):
        with self.assertRaisesRegex(ConfigurationError, "API configuration file not found"):
            load_api_config_settings(project_root_path_str="project_root")

    @patch('gouai_llm_api.yaml.safe_load', return_value={'other_field': 'value'}) # Missing mandatory field
    @patch('builtins.open', new_callable=mock_open)
    @patch('pathlib.Path.is_file', return_value=True)
    def test_load_config_missing_default_model(self, mock_is_file, mock_file_open, mock_safe_load):
        with self.assertRaisesRegex(ConfigurationError, "mandatory field 'default_model_name' is missing"):
            load_api_config_settings(project_root_path_str="project_root")

    @patch('gouai_llm_api.yaml.safe_load', side_effect=yaml.YAMLError("bad yaml"))
    @patch('builtins.open', new_callable=mock_open)
    @patch('pathlib.Path.is_file', return_value=True)
    def test_load_malformed_yaml(self, mock_is_file, mock_file_open, mock_safe_load):
        with self.assertRaisesRegex(ConfigurationError, "contains malformed YAML"):
            load_api_config_settings(project_root_path_str="project_root")


# In a TestClass inheriting from unittest.TestCase
class TestAPIKeyLoading(unittest.TestCase):
    # Assume '_get_api_key_from_env' and 'ConfigurationError' are imported

    def test_get_api_key_success(self):
        with patch.dict(os.environ, {_API_KEY_ENV_VAR: "test_api_key_123"}):
            key = _get_api_key_from_env()
            self.assertEqual(key, "test_api_key_123")

    def test_get_api_key_not_set(self):
        with patch.dict(os.environ, {}, clear=True): # Ensure it's not set
            with self.assertRaisesRegex(ConfigurationError, f"environment variable '{_API_KEY_ENV_VAR}' is not set or is empty"):
                _get_api_key_from_env()

    def test_get_api_key_empty(self):
        with patch.dict(os.environ, {_API_KEY_ENV_VAR: "  "}): # Empty string
            with self.assertRaisesRegex(ConfigurationError, f"environment variable '{_API_KEY_ENV_VAR}' is not set or is empty"):
                _get_api_key_from_env()

    @patch('gouai_llm_api.load_api_config_settings')
    @patch('gouai_llm_api._get_api_key_from_env')
    def test_get_llm_provider_settings_caching(self, mock_get_key, mock_load_config):
        # Reset global cache for this test
        global _CACHED_SETTINGS # Use the actual global from your module
        _CACHED_SETTINGS = None

        mock_load_config.return_value = {'default_model_name': 'cached_model'}
        mock_get_key.return_value = 'cached_key'

        settings1 = get_llm_provider_settings("proj1")
        self.assertEqual(settings1, {'default_model_name': 'cached_model', 'api_key': 'cached_key'})
        mock_load_config.assert_called_once_with("proj1")
        mock_get_key.assert_called_once()

        # Call again, should use cache
        settings2 = get_llm_provider_settings("proj1") # Same project root, or even different if cache is naive
        self.assertEqual(settings2, {'default_model_name': 'cached_model', 'api_key': 'cached_key'})
        mock_load_config.assert_called_once() # Still once
        mock_get_key.assert_called_once()   # Still once
        
        _CACHED_SETTINGS = None # Clean up

# Mock chunk and response objects for Gemini
class MockGeminiPart:
    def __init__(self, text=None):
        self.text = text

class MockGeminiCandidate:
    def __init__(self, text_parts, finish_reason_name=None, safety_ratings=None):
        self.content = MagicMock()
        self.content.parts = [MockGeminiPart(text=tp) for tp in text_parts] if text_parts else []
        self.finish_reason = MagicMock()
        self.finish_reason.name = finish_reason_name
        self.safety_ratings = []
        if safety_ratings:
            for sr_dict in safety_ratings:
                sr_mock = MagicMock()
                sr_mock.category.name = sr_dict['category']
                sr_mock.probability.name = sr_dict['probability']
                self.safety_ratings.append(sr_mock)


class MockGeminiChunk:
    def __init__(self, candidates=None):
        self.candidates = candidates if candidates else []
        # For simplicity, text and parts can be derived if needed by the code from candidates
        self.text = ""
        if candidates and candidates[0].content and candidates[0].content.parts:
            self.text = "".join(p.text for p in candidates[0].content.parts if p.text)


class MockGeminiResponseStream:
    def __init__(self, chunks_data, usage_metadata=None, prompt_feedback=None):
        self.chunks_data = chunks_data # List of candidate data for each chunk
        self.usage_metadata_val = usage_metadata
        self.prompt_feedback_val = prompt_feedback

    def __iter__(self):
        for candidate_data_for_chunk in self.chunks_data:
            candidate = MockGeminiCandidate(
                text_parts=candidate_data_for_chunk.get("text_parts"),
                finish_reason_name=candidate_data_for_chunk.get("finish_reason"),
                safety_ratings=candidate_data_for_chunk.get("safety_ratings")
            )
            yield MockGeminiChunk(candidates=[candidate])
    
    @property
    def usage_metadata(self): # This makes it accessible after iteration
        return self.usage_metadata_val
    
    @property
    def prompt_feedback(self): # This makes it accessible after iteration
        return self.prompt_feedback_val

# In a TestClass inheriting from unittest.TestCase
@patch('gouai_llm_api.genai') # Patch the whole genai module
class TestGeminiAPICall(unittest.TestCase):
    # Assume _call_gemini_api, LLMAPICallError are imported

    def test_call_gemini_api_success_stream(self, mock_genai_module):
        mock_model_instance = MagicMock()
        
        # Define what the stream will yield
        mock_stream_chunks_data = [
            {"text_parts": ["Hello "], "finish_reason": None},
            {"text_parts": ["World!"], "finish_reason": "STOP"}
        ]
        mock_usage = MagicMock()
        mock_usage.prompt_token_count = 5
        mock_usage.candidates_token_count = 2
        mock_usage.total_token_count = 7

        mock_response_stream_obj = MockGeminiResponseStream(mock_stream_chunks_data, usage_metadata=mock_usage)
        mock_model_instance.generate_content.return_value = mock_response_stream_obj
        
        mock_genai_module.GenerativeModel.return_value = mock_model_instance

        results = list(_call_gemini_api(
            model_name="gemini-test",
            api_key="fake_key",
            contents="A prompt"
        ))

        mock_genai_module.configure.assert_called_once_with(api_key="fake_key")
        mock_genai_module.GenerativeModel.assert_called_once_with("gemini-test")
        mock_model_instance.generate_content.assert_called_once()
        
        self.assertEqual(len(results), 3) # 2 chunks + 1 final summary
        self.assertTrue(results[0]['is_chunk'])
        self.assertEqual(results[0]['text_chunk'], "Hello ")
        self.assertTrue(results[1]['is_chunk'])
        self.assertEqual(results[1]['text_chunk'], "World!")
        self.assertEqual(results[1]['candidate_finish_reason'], "STOP")
        
        self.assertTrue(results[2]['is_final_summary'])
        self.assertEqual(results[2]['usage_metadata']['total_token_count'], 7)

    @patch('gouai_llm_api._log_error_to_project') # Mock our logger
    def test_call_gemini_api_handles_api_error(self, mock_log_error, mock_genai_module_outer):
        # This inner mock_genai_module is from the class-level patch
        mock_model_instance = MagicMock()
        # Simulate an API error
        api_error = google.api_core.exceptions.InvalidArgument("Bad request")
        mock_model_instance.generate_content.side_effect = api_error
        
        mock_genai_module_outer.GenerativeModel.return_value = mock_model_instance

        with self.assertRaises(LLMAPICallError) as cm:
            # Consume the generator to trigger the error
            list(_call_gemini_api(model_name="gemini-test", api_key="fake_key", contents="A prompt"))

        self.assertIs(cm.exception.original_exception, api_error)
        mock_log_error.assert_called_once()
        # Check that an error dictionary was also yielded before raising (if that's the design)
        # For this, we'd iterate one step:
        gen = _call_gemini_api(model_name="gemini-test", api_key="fake_key", contents="A prompt")
        error_yield = next(gen)
        self.assertTrue(error_yield.get('is_error'))
        self.assertEqual(error_yield.get('original_exception_type'), "InvalidArgument")

    # Add more tests for safety_settings parsing, different error types, empty stream etc.


    # In a TestClass inheriting from unittest.TestCase
class TestInteractionLogging(unittest.TestCase):
    # Assume _append_turn_to_llm_log is imported

    def setUp(self):
        self.temp_dir_context = tempfile.TemporaryDirectory()
        self.temp_dir = self.temp_dir_context.name
        self.log_file_path = Path(self.temp_dir) / "test_llm_conversation_log.md"

    def tearDown(self):
        self.temp_dir_context.cleanup()

    @patch('gouai_llm_api.datetime') # Assuming _append_turn_to_llm_log uses datetime.now()
    def test_append_turn_new_file_user(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2025, 5, 20, 12, 0, 0)
        
        _append_turn_to_llm_log(
            self.log_file_path, "User", "Test user prompt",
            model_name_for_session="gemini-test",
            session_id_for_session="sess123",
            task_id_for_session="taskABC"
        )
        self.assertTrue(self.log_file_path.exists())
        content = self.log_file_path.read_text()
        
        self.assertIn("session_id: sess123", content)
        self.assertIn("task_id: taskABC", content)
        self.assertIn("llm_model_used: gemini-test", content)
        self.assertIn("session_start_timestamp: \"2025-05-20 12:00:00\"", content)
        self.assertIn("## LLM Conversation Log", content)
        self.assertIn("### User", content)
        self.assertIn("**Timestamp:** 2025-05-20 12:00:00", content)
        self.assertIn("Test user prompt", content)
        self.assertIn("---", content)

    @patch('gouai_llm_api.datetime')
    def test_append_turn_existing_file_assistant_with_metadata(self, mock_datetime):
        # First, create the file with a user turn
        mock_datetime.now.return_value = datetime(2025, 5, 20, 12, 0, 0)
        _append_turn_to_llm_log(self.log_file_path, "User", "Initial prompt")

        # Now, append an assistant turn
        mock_datetime.now.return_value = datetime(2025, 5, 20, 12, 5, 0)
        assistant_metadata = {
            'usage_metadata': {'total_token_count': 150},
            'finish_reason': 'STOP',
            'safety_ratings': [{'category': 'HARM_CATEGORY_SEXUAL', 'probability': 'NEGLIGIBLE'}]
        }
        _append_turn_to_llm_log(
            self.log_file_path, "Assistant", "Test assistant response.",
            turn_metadata=assistant_metadata
        )
        content = self.log_file_path.read_text()
        self.assertIn("### Assistant", content)
        self.assertIn("**Timestamp:** 2025-05-20 12:05:00", content)
        self.assertIn("Test assistant response.", content)
        self.assertIn("**Turn Metadata:**", content)
        self.assertIn("- **Usage Metadata:** {'total_token_count': 150}", content)
        self.assertIn("- **Finish Reason:** STOP", content)
        # ... and so on for other metadata

    # Add tests for _format_prompt_content_for_log for complex Content objects.
    # Test _get_task_llm_log_path by mocking find_task_dir_path_from_id

    # In a TestClass inheriting from unittest.TestCase
@patch('gouai_llm_api._call_gemini_api')
@patch('gouai_llm_api._append_turn_to_llm_log')
@patch('gouai_llm_api._get_task_llm_log_path')
@patch('gouai_llm_api.get_llm_provider_settings')
class TestGenerateResponseStream(unittest.TestCase):

    def test_successful_stream_and_logging(
        self, mock_get_settings, mock_get_log_path, 
        mock_append_log, mock_internal_call
    ):
        mock_get_settings.return_value = {'default_model_name': 'test_model', 'api_key': 'test_key'}
        mock_log_file = Path(self.temp_dir) / "llm_conversation_log.md" # Assuming temp_dir setup
        mock_get_log_path.return_value = mock_log_file

        # Define what _call_gemini_api will yield
        mock_internal_call.return_value = iter([
            {'is_chunk': True, 'text_chunk': 'Chunk1 text', 'candidate_finish_reason': None, 'candidate_safety_ratings': []},
            {'is_chunk': True, 'text_chunk': 'Chunk2 text', 'candidate_finish_reason': 'STOP', 'candidate_safety_ratings': []},
            {'is_final_summary': True, 'usage_metadata': {'total_token_count': 42}, 'prompt_feedback': None}
        ])

        # Call the function under test
        result_chunks = list(generate_response_stream(
            project_root=self.temp_dir, session_id="s1", task_id="t1", prompt_text="User prompt"
        ))

        # Assertions
        mock_get_settings.assert_called_once_with(self.temp_dir)
        mock_get_log_path.assert_called_once_with(self.temp_dir, "t1")
        
        # Check logging calls
        # Call 1: User prompt
        # Call 2: Assistant response
        self.assertEqual(mock_append_log.call_count, 2)
        
        # User log call
        args_user_log, _ = mock_append_log.call_args_list[0]
        self.assertEqual(args_user_log[0], mock_log_file)
        self.assertEqual(args_user_log[1], "User")
        self.assertIn("User prompt", args_user_log[2])
        self.assertEqual(args_user_log[3], 'test_model') # model_name_for_session

        # Assistant log call
        args_assistant_log, _ = mock_append_log.call_args_list[1]
        self.assertEqual(args_assistant_log[0], mock_log_file)
        self.assertEqual(args_assistant_log[1], "Assistant")
        self.assertEqual(args_assistant_log[2], "Chunk1 textChunk2 text") # Accumulated text
        self.assertIn('usage_metadata', args_assistant_log[4]) # turn_metadata
        self.assertEqual(args_assistant_log[4]['usage_metadata']['total_token_count'], 42)
        self.assertEqual(args_assistant_log[4]['finish_reason'], 'STOP')

        # Check yielded chunks from generate_response_stream
        self.assertEqual(len(result_chunks), 2) # Only 'is_chunk' items are yielded by generate_response_stream
        self.assertEqual(result_chunks[0]['text_chunk'], 'Chunk1 text')
        self.assertEqual(result_chunks[1]['text_chunk'], 'Chunk2 text')

        # Add tests for error handling within generate_response_stream (e.g., ConfigurationError)