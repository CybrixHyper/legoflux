"""Context management: token estimation, hysteresis-based compression, LLM structured summarization."""

import json
import time
import tiktoken
from core.utils import is_retryable_llm_error

# ── Token Estimation ──────────────────────────────────────────────────────────

_enc = tiktoken.encoding_for_model("gpt-4o")


def estimate_tools_tokens(tools):
    """Estimate token overhead introduced by tool definitions."""
    if not tools:
        return 0
    try:
        payload = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        payload = str(tools)
    return len(_enc.encode(payload))


def estimate_tokens(messages, extra_tokens=0) -> int:
    """Estimate total token count for a list of messages."""
    total = 0
    for msg in messages:
        total += 4  # per-message overhead
        total += len(_enc.encode(str(msg.get("content") or "")))
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                total += len(_enc.encode(tc["function"]["name"]))
                total += len(_enc.encode(tc["function"]["arguments"]))
    return total + 3 + max(0, int(extra_tokens))  # assistant reply priming + static overhead


def _trim_text_to_token_budget(text: str, token_budget: int) -> str:
    """Trim text to token budget, keeping the most recent portion."""
    if token_budget <= 0:
        return ""
    tokens = _enc.encode(str(text or ""))
    if len(tokens) <= token_budget:
        return str(text or "")
    return _enc.decode(tokens[-token_budget:])


# ── Round Boundary Helpers ────────────────────────────────────────────────────

def _find_round_boundaries(messages):
    """Return list of indices where each 'user' message starts a new round."""
    return [i for i, m in enumerate(messages) if m.get("role") == "user"]


def _get_compressible_range(messages, keep_recent_rounds):
    """Return (start, end) index of the compressible region.

    Returns (0, 0) if there are not enough rounds to compress.
    The compressible region starts after any leading system messages and ends
    before the most recent `keep_recent_rounds` rounds.
    """
    boundaries = _find_round_boundaries(messages)
    if len(boundaries) <= keep_recent_rounds:
        return (0, 0)

    # Start after system messages (index 0 is always system, possibly index 1 too)
    start = boundaries[0]

    # End is the start of the (total - keep_recent_rounds)-th last round
    cutoff_boundary_idx = len(boundaries) - keep_recent_rounds
    end = boundaries[cutoff_boundary_idx]
    return (start, end)


# ── Memory Schema & Validation ───────────────────────────────────────────────

MEMORY_SCHEMA = {
    "type": "object",
    "properties": {
        "completed":      {"type": "array", "items": {"type": "string", "maxLength": 200}, "maxItems": 30},
        "pending":        {"type": "array", "items": {"type": "string", "maxLength": 200}, "maxItems": 20},
        "decisions":      {"type": "array", "items": {"type": "string", "maxLength": 300}, "maxItems": 20},
        "files_modified": {"type": "array", "items": {"type": "string", "maxLength": 200}, "maxItems": 50},
        "recent_errors":  {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "error":   {"type": "string", "maxLength": 500},
                    "context": {"type": "string", "maxLength": 300},
                },
            },
            "maxItems": 5,
        },
        "open_issues":    {"type": "array", "items": {"type": "string", "maxLength": 300}, "maxItems": 10},
    },
    "required": ["completed", "pending", "decisions", "files_modified", "recent_errors", "open_issues"],
}

_REQUIRED_KEYS = MEMORY_SCHEMA["required"]
_PROPS = MEMORY_SCHEMA["properties"]


def _enforce_limits(memory: dict) -> dict:
    """Deduplicate, truncate maxLength and maxItems per schema."""
    for key in _REQUIRED_KEYS:
        prop = _PROPS[key]
        items = memory.get(key, [])

        max_items = prop.get("maxItems", 9999)
        item_schema = prop.get("items", {})

        cleaned = []
        seen = set()
        for item in items:
            if isinstance(item, dict):
                # Truncate string fields inside objects
                for fk, fv in item_schema.get("properties", {}).items():
                    if fk in item and isinstance(item[fk], str):
                        ml = fv.get("maxLength", 9999)
                        item[fk] = item[fk][:ml]
                dedup_key = json.dumps(item, sort_keys=True)
            else:
                ml = item_schema.get("maxLength", 9999)
                if isinstance(item, str):
                    item = item[:ml]
                dedup_key = str(item)

            if dedup_key not in seen:
                seen.add(dedup_key)
                cleaned.append(item)

        memory[key] = cleaned[:max_items]
    return memory


def validate_memory(memory: dict) -> dict:
    """Validate and enforce limits on a memory dict. Returns cleaned memory."""
    # Ensure all required keys exist with correct types
    for key in _REQUIRED_KEYS:
        if key not in memory or not isinstance(memory[key], list):
            memory[key] = []
    return _enforce_limits(memory)


# ── Summarization Prompt ──────────────────────────────────────────────────────

_SUMMARY_SYSTEM_PROMPT = """You are a context compressor for a coding assistant session.

You will receive:
1. An existing session memory (JSON) — may be empty on first compression.
2. A block of conversation history that is about to be discarded.

Your job: MERGE the new information into the existing memory and return the updated JSON.

Rules:
- Output ONLY valid JSON — no markdown fences, no explanation.
- Keep entries concise (< 200 chars each where possible).
- Deduplicate: if an item already exists in memory, do not add it again.
- Move completed tasks from "pending" to "completed".
- Keep only the 5 most recent errors in "recent_errors".
- For "files_modified", record path and brief change description.

Required JSON schema:
{
  "completed":      ["<task description>", ...],
  "pending":        ["<task description>", ...],
  "decisions":      ["<key decision made>", ...],
  "files_modified": ["<path: brief change>", ...],
  "recent_errors":  [{"error": "<msg>", "context": "<what was being done>"}, ...],
  "open_issues":    ["<unresolved issue>", ...]
}"""


def _build_summary_user_prompt(existing_memory, conversation_text):
    parts = []
    if existing_memory:
        parts.append(f"## Existing memory\n```json\n{json.dumps(existing_memory, ensure_ascii=False, indent=2)}\n```")
    else:
        parts.append("## Existing memory\n(empty — first compression)")
    parts.append(f"## Conversation to compress\n{conversation_text}")
    return "\n\n".join(parts)


def _format_messages_as_text(messages):
    """Convert a list of messages to readable text for the summarizer."""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = str(msg.get("content") or "")
        if role == "tool":
            # Truncate long tool results
            if len(content) > 1000:
                content = content[:500] + "\n...[truncated]...\n" + content[-300:]
            lines.append(f"[tool result] {content}")
        elif role == "assistant":
            if content:
                lines.append(f"[assistant] {content}")
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    name = tc["function"]["name"]
                    args = tc["function"]["arguments"]
                    if len(args) > 500:
                        args = args[:400] + "..."
                    lines.append(f"[tool call: {name}] {args}")
        elif role == "user":
            lines.append(f"[user] {content}")
    return "\n".join(lines)


# ── Session Memory Tag ────────────────────────────────────────────────────────

_MEMORY_TAG = "[session_memory]"


def _make_memory_message(memory: dict) -> dict:
    return {
        "role": "system",
        "content": f"{_MEMORY_TAG}\n```json\n{json.dumps(memory, ensure_ascii=False, indent=2)}\n```",
    }


def _parse_memory_from_message(msg: dict):
    """Try to parse memory JSON from a system message with [session_memory] tag."""
    content = msg.get("content", "")
    if _MEMORY_TAG not in content:
        return None
    # Extract JSON from ```json ... ``` block
    start = content.find("```json")
    end = content.find("```", start + 7)
    if start == -1 or end == -1:
        return None
    json_str = content[start + 7:end].strip()
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


# ── ContextManager ────────────────────────────────────────────────────────────

class ContextManager:
    def __init__(self, cfg, model_runtime, tools=None):
        ctx_cfg = cfg.get("context", {})
        self.context_window_tokens = max(1, int(ctx_cfg.get("context_window_tokens", 128000)))
        self.trigger_tokens = int(ctx_cfg.get("compress_trigger_tokens", 90000))
        self.summary_output_tokens = int(ctx_cfg.get("summary_output_tokens", 1000))
        self.keep_recent_rounds = int(ctx_cfg.get("keep_recent_rounds", 2))
        # Derived budgets (fixed logic, not separately configured)
        self.target_tokens = int(self.trigger_tokens * 0.75)
        self.summary_input_tokens = min(
            int(self.context_window_tokens * 0.25),
            max(1, self.trigger_tokens // 2),
        )

        self.model_runtime = model_runtime
        self._tools_overhead_tokens = estimate_tools_tokens(tools or [])
        self._memory = None
        self.last_actual_tokens = None

    def estimate_session_tokens(self, messages):
        return estimate_tokens(messages, extra_tokens=self._tools_overhead_tokens)

    def maybe_compress(self, session, force=False) -> bool:
        """Check context size and compress if needed. Returns True if compression happened."""
        if self.last_actual_tokens is not None:
            current = self.last_actual_tokens
            self.last_actual_tokens = None
        else:
            current = self.estimate_session_tokens(session.messages)
        pct = current / self.context_window_tokens * 100

        if not force and current <= self.trigger_tokens:
            return False

        print(f"  [context: {current:,} / {self.context_window_tokens:,} tokens ({pct:.2f}%) → compressing...]")

        keep = self.keep_recent_rounds
        compressed = False

        while (force or current > self.target_tokens) and keep >= 1:
            success = self._compress_once(session, keep)
            if not success:
                if not compressed:
                    print("  [nothing to compress: not enough conversation rounds]")
                break
            compressed = True
            current = self.estimate_session_tokens(session.messages)
            pct_after = current / self.context_window_tokens * 100
            if current > self.target_tokens and keep > 1:
                keep -= 1
                print(f"  [still {pct_after:.2f}%, reducing protected rounds to {keep}...]")
            else:
                break

        if compressed:
            pct_after = current / self.context_window_tokens * 100
            print(f"  [context: {current:,} / {self.context_window_tokens:,} tokens ({pct_after:.2f}%) ✓ compressed]")

        return compressed

    def _compress_once(self, session, keep_recent_rounds) -> bool:
        """Execute one round of LLM-based compression. Returns True on success."""
        messages = session.messages
        start, end = _get_compressible_range(messages, keep_recent_rounds)
        if start >= end:
            return False

        # Extract compressible messages
        compressible = messages[start:end]
        conversation_text = _format_messages_as_text(compressible)
        conversation_text = _trim_text_to_token_budget(
            conversation_text,
            self.summary_input_tokens,
        )

        # Call LLM for structured summary
        new_memory = self._call_summary_llm(conversation_text)
        if new_memory is None:
            return False

        new_memory = validate_memory(new_memory)
        self._memory = new_memory

        # Build new message list: system_base + memory_system + protected_rounds
        system_base = messages[0]  # original system prompt
        memory_msg = _make_memory_message(new_memory)
        protected = messages[end:]  # recent rounds to keep

        new_messages = [system_base, memory_msg] + protected
        session.replace_messages(new_messages)
        return True

    def _call_summary_llm(self, conversation_text):
        """Call LLM to generate/update structured memory. Returns dict or None."""
        user_prompt = _build_summary_user_prompt(self._memory, conversation_text)
        state = self.model_runtime.current()
        attempts = state.max_retries + 1
        last_err = None
        for attempt in range(1, attempts + 1):
            try:
                response = state.client.chat.completions.create(
                    model=state.model,
                    temperature=0.0,
                    max_completion_tokens=self.summary_output_tokens,
                    messages=[
                        {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    timeout=state.timeout_sec,
                )
                raw = (response.choices[0].message.content or "").strip()
                # Strip markdown fences if LLM included them despite instructions.
                # This handles ```json / ```JSON / ``` with or without language labels.
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1] if "\n" in raw else ""
                if raw.endswith("```"):
                    raw = raw.rsplit("```", 1)[0]
                raw = raw.strip()
                return json.loads(raw)
            except Exception as e:
                last_err = e
                retryable = is_retryable_llm_error(e)
                if attempt >= attempts or not retryable:
                    break
                backoff = state.retry_backoff_sec * attempt
                print(
                    f"  [context llm retry {attempt}/{state.max_retries}] "
                    f"error={type(e).__name__}: {e}; backoff={backoff:.1f}s"
                )
                if backoff > 0:
                    time.sleep(backoff)
        print(f"  [context compression failed: {last_err}]")
        return None

    def restore_memory_from_session(self, messages):
        """Restore memory state from a resumed session's messages."""
        for msg in messages[:5]:
            if msg.get("role") != "system":
                continue
            mem = _parse_memory_from_message(msg)
            if mem:
                self._memory = validate_memory(mem)
                print(f"  [session memory restored: {sum(len(v) for v in self._memory.values())} entries]")
                return
