"""Coding agent with configurable tools (replaces V2-V6 scripts)"""

import json
import os
import time
from dataclasses import dataclass

from core import error_codes as ec
from core.utils import (
    load_config, get_cfg, build_system_prompt, Session,
    YOU_LABEL, ASST_LABEL, CONTENT_INDENT, TOOL_LABEL, UserInputReader, is_retryable_llm_error,
)
from tools import get_tools, process_tool_call
from core.context import ContextManager
from core.model_runtime import ModelRuntime
from core.tool_result import ToolResult


@dataclass(frozen=True)
class AgentConfig:
    max_tool_iterations: int = 100
    max_tool_result_chars: int = 12000
    context_enabled: bool = True
    verbose: bool = True

    @classmethod
    def from_cfg(cls, cfg):
        return cls(
            max_tool_iterations=int(get_cfg(cfg, "runtime.max_tool_iterations", 100)),
            max_tool_result_chars=int(get_cfg(cfg, "runtime.max_tool_result_chars", 12000)),
            context_enabled=bool(get_cfg(cfg, "context.enabled", True)),
            verbose=bool(get_cfg(cfg, "runtime.verbose", True)),
        )


class Agent:
    _SLASH_COMMANDS_HELP = "/session, /session use <session_id>, /session new, /status, /compact, /model, /model use <profile>"
    _SESSION_USAGE = "  [session] usage: /session | /session new | /session use <session_id>"

    def __init__(
        self,
        model_runtime,
        session,
        tools,
        config,
        context_manager=None,
        input_reader=None,
        caller_file=None,
        system_prompt=None,
    ):
        self.model_runtime = model_runtime
        self.config = config
        self.session = session
        self.tools = tools
        self.context_manager = context_manager
        self.input_reader = input_reader
        self.caller_file = caller_file
        self.system_prompt = system_prompt or ""
        self._slash_handlers = {
            "session": self._handle_slash_session,
            "status": self._handle_slash_status,
            "compact": self._handle_slash_compact,
            "model": self._handle_slash_model,
        }

    def _current_session_id(self):
        return os.path.splitext(os.path.basename(self.session.session_file))[0]

    def _cmd_list_sessions(self):
        session_ids = Session.list_session_ids(self.caller_file)
        indent = " " * (len(YOU_LABEL) + 2)
        if not session_ids:
            print(f"{indent}[session] no saved sessions")
            return
        current = self._current_session_id()
        print(f"{indent}[session]")
        for sid in session_ids:
            marker = " [current]" if sid == current else ""
            prefix = "* " if sid == current else "  "
            print(f"{indent}{prefix}{sid}{marker}")

    def _switch_session(self, session_file, session_id):
        previous = self._current_session_id()
        self.session = Session(session_file, self.system_prompt)
        if self.context_manager:
            self.context_manager.last_actual_tokens = None
            self.context_manager.restore_memory_from_session(self.session.messages)
        self.session.append({"role": "system", "content": f"[session switched to {session_id}]"})
        print(f"  [session] switched from {previous} -> {session_id}")

    def _cmd_status(self):
        session_id = self._current_session_id()
        cwd = os.getcwd()
        home = os.path.expanduser("~")
        pretty_cwd = cwd.replace(home, "~", 1) if cwd.startswith(home) else cwd
        state = self.model_runtime.current()
        indent = " " * (len(YOU_LABEL) + 2)
        label_width = 12

        def _kv(label, value):
            print(f"{indent}  {label:<{label_width}} : {value}")

        print("")
        print(f"{indent}Runtime")
        _kv("model", state.profile)
        _kv("session", session_id)
        _kv("directory", pretty_cwd)
        print("")

        if self.context_manager:
            current_tokens = self.context_manager.estimate_session_tokens(self.session.messages)
            window = self.context_manager.context_window_tokens
            used_pct = (current_tokens / window * 100.0) if window > 0 else 0.0
            left_pct = max(0.0, 100.0 - used_pct)
            usage_line = f"{current_tokens:,} / {window:,} ({left_pct:.2f}% left)"
            trigger_line = f"{self.context_manager.trigger_tokens:,}"
            auto_compact_state = "enabled"
        else:
            usage_line = "N/A"
            trigger_line = "N/A"
            auto_compact_state = "disabled"

        print(f"{indent}Context")
        _kv("usage", usage_line)
        _kv("trigger", trigger_line)
        _kv("auto_compact", auto_compact_state)
        print("")

        print(f"{indent}Commands")
        _kv("session", "/session, /session use <session_id>, /session new")
        _kv("model", "/model, /model use <profile>")
        _kv("context", "/status, /compact")

    def _cmd_model(self, arg):
        indent = " " * (len(YOU_LABEL) + 2)
        sub = (arg or "").strip()
        current_profile = self.model_runtime.active_profile()
        if not sub:
            for name in self.model_runtime.list_profiles():
                marker = " [current]" if name == current_profile else ""
                print(f"{indent}{'*' if name == current_profile else ' '} {name}{marker}")
            return
        if sub.startswith("use "):
            profile_name = sub.split(" ", 1)[1].strip()
            if not profile_name:
                print(f"{indent}[model] usage: /model use <profile>")
                return
            try:
                state = self.model_runtime.switch(profile_name)
            except Exception as e:
                print(f"{indent}[model] error: {e}")
                return
            if self.context_manager:
                self.context_manager.last_actual_tokens = None
            self.session.append({"role": "system", "content": f"[model switched to {state.profile}]"})
            print(f"{indent}[model] switched: {state.profile} [current]")
            return
        print(f"{indent}[model] usage: /model | /model use <profile>")

    def _print_unknown_slash_command(self, raw_input):
        print(f"  [command] unknown: {raw_input}")
        print(f"  [command] available: {self._SLASH_COMMANDS_HELP}")

    def _handle_slash_session(self, args):
        sub = (args or "").strip()
        if not sub:
            self._cmd_list_sessions()
            return
        if sub == "new":
            session_file, session_id = Session.create_new_session_file(self.caller_file)
            self._switch_session(session_file, session_id)
            return
        if sub.startswith("use "):
            session_id = sub.split(" ", 1)[1].strip()
            if not session_id:
                print(self._SESSION_USAGE)
                return
            session_file = Session.resolve_session_file(self.caller_file, session_id)
            if not session_file:
                print(f"  [session] error: session not found: {session_id}")
                print("  [session] hint: run /session to view available session ids")
                return
            self._switch_session(session_file, session_id)
            return
        print(self._SESSION_USAGE)

    def _handle_slash_status(self, args):
        if (args or "").strip():
            print("  [command] usage: /status")
            return
        self._cmd_status()

    def _handle_slash_compact(self, args):
        if (args or "").strip():
            print("  [command] usage: /compact")
            return
        if self.context_manager:
            self.context_manager.maybe_compress(self.session, force=True)
        else:
            print("  [context compression is disabled]")

    def _handle_slash_model(self, args):
        self._cmd_model((args or "").strip())

    def _try_handle_slash_command(self, user_input):
        if not user_input.startswith("/"):
            return False
        body = user_input[1:].strip()
        if not body:
            self._print_unknown_slash_command(user_input)
            return True
        parts = body.split(maxsplit=1)
        command = parts[0]
        args = parts[1] if len(parts) == 2 else ""
        handler = self._slash_handlers.get(command)
        if handler is None:
            self._print_unknown_slash_command(user_input)
            return True
        handler(args)
        return True

    @staticmethod
    def _merge_tool_call_delta(tool_calls_acc, tc_delta):
        idx = tc_delta.index
        if idx not in tool_calls_acc:
            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
        if tc_delta.id:
            tool_calls_acc[idx]["id"] = tc_delta.id
        if not tc_delta.function:
            return
        if tc_delta.function.name:
            tool_calls_acc[idx]["name"] = tc_delta.function.name
        if tc_delta.function.arguments:
            tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments

    @staticmethod
    def _build_tool_calls(tool_calls_acc):
        if not tool_calls_acc:
            return None
        return [
            {
                "id": tool_calls_acc[idx]["id"],
                "type": "function",
                "function": {
                    "name": tool_calls_acc[idx]["name"],
                    "arguments": tool_calls_acc[idx]["arguments"],
                },
            }
            for idx in sorted(tool_calls_acc.keys())
        ]

    def _format_tool_result_content(self, result_obj):
        result = "" if result_obj.content is None else str(result_obj.content)
        if len(result) <= self.config.max_tool_result_chars:
            return result
        half = self.config.max_tool_result_chars // 2
        return (
            result[:half]
            + f"\n\n... [{len(result) - self.config.max_tool_result_chars:,} chars truncated] ...\n\n"
            + result[-half:]
        )

    def _append_tool_message(self, tool_call_id, content):
        self.session.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})

    def _append_error_tool_calls(self, tool_calls, code, message):
        for tc in tool_calls:
            err = ToolResult.error(code, message, tool=tc.get("function", {}).get("name"))
            self._append_tool_message(tc["id"], err.content)

    def _execute_tool_call(self, tc):
        tool_name = (tc["function"].get("name") or "").strip()
        raw_args = tc["function"].get("arguments") or ""

        if not tool_name:
            if self.config.verbose:
                print(f"\n{TOOL_LABEL}: [invalid tool call]")
                print("  ✗ Missing tool name")
            return ToolResult.error(ec.INVALID_CALL, "invalid tool call: missing tool name.")

        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError as e:
            if self.config.verbose:
                print(f"\n{TOOL_LABEL}: [{tool_name}]")
                print("  ✗ Failed to parse tool arguments")
            return ToolResult.error(
                ec.INVALID_ARGS,
                f"invalid tool arguments JSON for {tool_name}: {e}",
                tool=tool_name,
            )

        if self.config.verbose:
            print(f"\n{TOOL_LABEL}: [{tool_name}({args})]")
        start_time = time.time()
        try:
            result_obj = process_tool_call(tool_name, args)
            elapsed = time.time() - start_time
            if self.config.verbose:
                print(f"  ✓ Done ({elapsed:.1f}s)")
            return result_obj
        except Exception as e:
            elapsed = time.time() - start_time
            if self.config.verbose:
                print(f"  ✗ Tool failed ({elapsed:.1f}s)")
            return ToolResult.error(
                ec.EXEC_FAILED,
                f"tool execution failed for {tool_name}: {e}",
                tool=tool_name,
            )

    def _process_tool_calls(self, tool_calls):
        for idx, tc in enumerate(tool_calls):
            try:
                result_obj = self._execute_tool_call(tc)
                self._append_tool_message(tc["id"], self._format_tool_result_content(result_obj))
            except KeyboardInterrupt:
                print("\n  [tool execution interrupted by user]")
                self._append_error_tool_calls(
                    tool_calls[idx:],
                    ec.INTERRUPTED,
                    "tool execution interrupted by user.",
                )
                return True
        return False

    def _read_user_input(self):
        if self.input_reader is None:
            return input(f"\n{YOU_LABEL}: ").strip()
        return self.input_reader.read(f"\n{YOU_LABEL}: ").strip()

    def _run_inference_once(self, state):
        stream = state.client.chat.completions.create(
            model=state.model,
            max_completion_tokens=state.max_completion_tokens,
            messages=self.session.messages,
            tools=self.tools,
            stream=True,
            stream_options={"include_usage": True},
            timeout=state.timeout_sec,
        )
        content_parts = []
        tool_calls_acc = {}
        printed_header = False
        usage = None

        for chunk in stream:
            if hasattr(chunk, "usage") and chunk.usage:
                usage = chunk.usage
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue

            delta_content = getattr(delta, "content", None)
            if delta_content:
                if not printed_header:
                    print(f"\n{ASST_LABEL}: ", end="", flush=True)
                    printed_header = True
                print(delta_content.replace("\n", "\n" + CONTENT_INDENT), end="", flush=True)
                content_parts.append(delta_content)

            delta_tool_calls = getattr(delta, "tool_calls", None)
            if delta_tool_calls:
                for tc_delta in delta_tool_calls:
                    self._merge_tool_call_delta(tool_calls_acc, tc_delta)

        if printed_header:
            print()

        if usage:
            prompt_tokens = usage.prompt_tokens or 0
            completion_tokens = usage.completion_tokens or 0
            call_total = prompt_tokens + completion_tokens
            print(f"  [tokens] prompt: {prompt_tokens:,}, completion: {completion_tokens:,}, total: {call_total:,}")
            if self.context_manager:
                self.context_manager.last_actual_tokens = prompt_tokens

        return "".join(content_parts), self._build_tool_calls(tool_calls_acc)

    def run_inference(self):
        state = self.model_runtime.current()
        max_retries = state.max_retries
        attempts = max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                return self._run_inference_once(state)
            except Exception as e:
                retryable = is_retryable_llm_error(e)
                if attempt >= attempts or not retryable:
                    raise
                backoff = state.retry_backoff_sec * attempt
                print(f"  [llm retry {attempt}/{max_retries}] error={type(e).__name__}: {e}; backoff={backoff:.1f}s")
                time.sleep(backoff)

    def run(self):
        while True:
            try:
                user_input = self._read_user_input()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not user_input:
                continue

            if self._try_handle_slash_command(user_input):
                continue

            self.session.append({"role": "user", "content": user_input})

            tool_iterations = 0
            while True:
                if self.context_manager:
                    self.context_manager.maybe_compress(self.session)
                content, tool_calls = self.run_inference()

                assistant_msg = {"role": "assistant", "content": content}
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                self.session.append(assistant_msg)

                if not tool_calls:
                    break

                remaining = self.config.max_tool_iterations - tool_iterations
                if remaining <= 0:
                    print(f"\n  [Reached max tool iterations ({self.config.max_tool_iterations}). Stopping.]")
                    self._append_error_tool_calls(tool_calls, ec.LIMIT_REACHED, "tool call skipped because max tool iterations limit was reached.")
                    break

                executable = tool_calls[:remaining]
                skipped = tool_calls[remaining:]
                tool_iterations += len(executable)

                interrupted = self._process_tool_calls(executable)
                if interrupted:
                    break
                if skipped:
                    print(f"\n  [Reached max tool iterations ({self.config.max_tool_iterations}). Stopping.]")
                    self._append_error_tool_calls(skipped, ec.LIMIT_REACHED, "tool call skipped because max tool iterations limit was reached.")
                    break


def main():
    cfg = load_config()
    tool_names = cfg.get("tools", ["read", "list", "bash", "edit", "write", "find", "code_search", "web_search", "web_fetch"])
    try:
        tools = get_tools(tool_names)
    except ValueError as e:
        print(f"  [config error] {e}")
        return
    system_prompt = build_system_prompt(tool_names)
    agent_cfg = AgentConfig.from_cfg(cfg)
    model_runtime = ModelRuntime.from_config(cfg)

    session_file, _ = Session.create_new_session_file(__file__)
    session = Session(session_file, system_prompt)
    context_manager = None
    if agent_cfg.context_enabled:
        context_manager = ContextManager(cfg, model_runtime=model_runtime, tools=tools)
    else:
        print("  [context compression disabled]")
    input_reader = UserInputReader(__file__)
    agent = Agent(
        model_runtime,
        session,
        tools,
        config=agent_cfg,
        context_manager=context_manager,
        input_reader=input_reader,
        caller_file=__file__,
        system_prompt=system_prompt,
    )
    agent.run()


if __name__ == "__main__":
    main()
