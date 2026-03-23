from datetime import datetime
import copy
import glob
import json
import yaml
import os
import re
import tempfile

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings


YOU_LABEL = f"{'You':>9}"
ASST_LABEL = f"{'Assistant':>9}"
TOOL_LABEL = f"{'Tool':>9}"
CONTENT_INDENT = " " * 11


_CONFIG_CACHE = None
_ENV_VAR_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def _resolve_env_vars(value):
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(v) for v in value]
    if isinstance(value, str):
        match = _ENV_VAR_PATTERN.match(value.strip())
        if match:
            var_name = match.group(1)
            return os.environ.get(var_name, value)
    return value


def load_config(force_reload=False):
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None and not force_reload:
        return copy.deepcopy(_CONFIG_CACHE)

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(project_root, "config.yaml")
    with open(config_path, "r") as f:
        data = yaml.safe_load(f) or {}
    _CONFIG_CACHE = _resolve_env_vars(data)
    return copy.deepcopy(_CONFIG_CACHE)


def get_cfg(cfg, path, default=None):
    """Safely read nested config values by dotted path."""
    cur = cfg
    for part in str(path).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def is_retryable_llm_error(err) -> bool:
    """Best-effort classifier for retryable LLM/API errors."""
    name = type(err).__name__
    if name in {"APITimeoutError", "APIConnectionError", "RateLimitError", "InternalServerError", "TimeoutError"}:
        return True
    status = getattr(err, "status_code", None)
    if isinstance(status, int) and (status == 429 or status >= 500):
        return True
    message = str(err).lower()
    retryable_markers = ["timed out", "timeout", "connection", "rate limit", "temporarily unavailable", "server error"]
    return any(marker in message for marker in retryable_markers)


def _atomic_replace_file(path, write_fn):
    """Atomically rewrite `path` by writing to a temp file and os.replace()."""
    target = os.path.abspath(path)
    parent = os.path.dirname(target) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp.", dir=parent)
    try:
        with os.fdopen(fd, "w") as f:
            write_fn(f)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(target):
            try:
                os.chmod(tmp_path, os.stat(target).st_mode)
            except OSError:
                pass
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_text(path, content):
    """Atomically write text content to file."""
    def _writer(f):
        f.write(content)
    _atomic_replace_file(path, _writer)


def atomic_write_lines(path, lines):
    """Atomically write an iterable of lines to file."""
    def _writer(f):
        for line in lines:
            f.write(line)
    _atomic_replace_file(path, _writer)


def build_system_prompt(tool_names):
    """Auto-generate a system prompt from the list of tool names."""
    if not tool_names:
        return "You are a helpful assistant."

    tool_list = ", ".join(tool_names)
    cwd = os.getcwd()
    date = datetime.now().strftime("%Y-%m-%d")

    return f"""You are an expert coding assistant. You help users by reading, searching, editing, and creating code files. You can also execute commands and search the web.

Available tools: {tool_list}

## Tool Usage

- ALWAYS read a file before editing it. Never guess file contents.
- Use `find` or `code_search` to locate files before reading. Never assume file paths.
- Use `read` instead of `bash cat`. Use `list` instead of `bash ls`. Use `code_search` instead of `bash grep`. Prefer specialized tools over bash.
- Use `edit` for surgical changes to existing files. Use `write` only for creating new files or complete rewrites.
- Use `web_search` + `web_fetch` for questions about external libraries, APIs, or current information.
- When a tool returns an error, read the error message carefully and adjust your approach. Do not retry the same call.

## Workflow

1. Understand: Ask clarifying questions if the task is ambiguous.
2. Locate: Use `find` or `code_search` to find relevant files.
3. Read: Use `read` to examine the code before making changes.
4. Plan: Explain what you will change and why, before changing it.
5. Edit: Make precise, minimal changes. Only modify what is necessary.
6. Verify: After editing, use `read` to confirm the change is correct.

## Safety

- Never delete files or directories without explicit user confirmation.
- Never run destructive bash commands (rm -rf, git reset --hard, etc.) without asking first.
- Do not modify files outside the project directory unless asked.
- Do not execute commands that could expose secrets or credentials.

## Response Style

- Be concise. Lead with the answer, not the reasoning.
- When you make changes, briefly explain what you changed and why.
- Do not add unnecessary comments, docstrings, or type annotations to code you didn't change.
- Do not over-engineer. Only make changes that are directly requested.

Current working directory: {cwd}
Current date: {date}"""


class Session:
    def __init__(self, session_file, system_prompt):
        self.session_file = session_file
        self.messages = []

        if os.path.exists(session_file):
            self._load()
            print(f"  Resumed session ({len(self.messages)} messages): {session_file}")
        else:
            self.append({"role": "system", "content": system_prompt})

    def append(self, msg):
        payload = json.dumps(msg, ensure_ascii=False) + "\n"
        with open(self.session_file, "a") as f:
            f.write(payload)
        self.messages.append(msg)

    def replace_messages(self, new_messages):
        """Replace in-memory messages and rewrite the JSONL file."""
        self.messages = new_messages
        self._rewrite()

    def _rewrite(self):
        """Overwrite the JSONL file with current messages."""
        atomic_write_lines(
            self.session_file,
            (json.dumps(msg, ensure_ascii=False) + "\n" for msg in self.messages),
        )

    def _load(self):
        with open(self.session_file, "r") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if line:
                    try:
                        self.messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        print(f"  [session] warning: skipped corrupted JSONL line {line_no}")

    @staticmethod
    def get_session_dir(caller_file):
        cfg = load_config()
        script_name = os.path.splitext(os.path.basename(caller_file))[0]
        base_dir = os.path.dirname(os.path.abspath(caller_file))
        session_dir = os.path.join(
            base_dir,
            get_cfg(cfg, "runtime.session_dir", "sessions"),
            script_name,
        )
        os.makedirs(session_dir, exist_ok=True)
        return session_dir

    @staticmethod
    def create_new_session_file(caller_file):
        session_dir = Session.get_session_dir(caller_file)
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        session_file = os.path.join(session_dir, f"{session_id}.jsonl")
        return session_file, session_id

    @staticmethod
    def list_session_ids(caller_file):
        session_dir = Session.get_session_dir(caller_file)
        files = sorted(glob.glob(os.path.join(session_dir, "*.jsonl")), reverse=True)
        return [os.path.splitext(os.path.basename(f))[0] for f in files]

    @staticmethod
    def resolve_session_file(caller_file, session_id):
        session_dir = Session.get_session_dir(caller_file)
        session_file = os.path.join(session_dir, f"{session_id}.jsonl")
        if os.path.exists(session_file):
            return session_file
        return None


class UserInputReader:
    def __init__(self, caller_file):
        script_name = os.path.splitext(os.path.basename(caller_file))[0]
        session_root = os.path.dirname(Session.get_session_dir(caller_file))
        history_dir = os.path.join(session_root, "_history")
        os.makedirs(history_dir, exist_ok=True)
        history_path = os.path.join(history_dir, f"{script_name}.txt")

        kb = KeyBindings()

        @kb.add("c-j")
        def _submit(event):
            event.current_buffer.validate_and_handle()

        self._prompt_session = PromptSession(
            history=FileHistory(history_path),
            multiline=True,
            key_bindings=kb,
        )

    def read(self, prompt_text):
        continuation = " " * len(prompt_text)
        return self._prompt_session.prompt(
            prompt_text,
            prompt_continuation=lambda _width, _line, _is_soft_wrap: continuation,
        )
