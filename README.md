# LegoFlux Agent

![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)

> *"The coding agent scaffold that fits in your head — complete enough to use, simple enough to own."*

A **fully-featured coding agent in ~2,200 lines of Python** — read, edit, execute, search, and browse the web, with context compression and workspace sandboxing built in.

- **Complete agent, zero magic** — 9 tools, session persistence, streaming, context management. All in readable Python you can audit in an afternoon.
- **Cost-aware context** — Hysteresis-based compression keeps you inside the token budget automatically; API-calibrated counting means no surprise overflows.
- **Drop-a-`.py` plugins** — Adding a tool is one file (`DEFINITION` + `execute()`) and one line in `config.yaml`. No framework to learn.

<!-- TODO: add terminal screenshot or GIF here -->

---

## Quick Start

```bash
pip install -r requirements.txt     # openai pyyaml requests tiktoken prompt_toolkit
cp config.yaml.example config.yaml  # add your API key
python agent.py                     # start the coding agent
```

> **Tip:** `python chat.py` launches a minimal streaming chat (no tools) for quick Q&A.

---

## Why LegoFlux?

Most open-source agents are either **toy demos** that fall apart on real tasks, or **sprawling frameworks** that need a week to understand.

LegoFlux occupies the middle ground on purpose:

- **Constraints as features.** Single-file entry point, flat tool directory, YAML-only config. You can `grep -r` the entire project and get answers.
- **Own the code.** No plugin SDK, no abstract base classes, no dependency injection. Fork it, change it, ship it.
- **Production patterns included.** Retry with backoff, workspace sandboxing, bash safety checks, context compression — the boring stuff that matters is already here.

---

## Features

| Feature | What it does for you |
|---|---|
| **9 Built-in Tools** | Read, list, find, edit, write, bash, code_search, web_search, web_fetch — covers the full dev loop |
| **Streaming Output** | See tokens as they arrive, not after a long wait |
| **Session Persistence** | Pick up where you left off — JSONL sessions with `/list`, `/resume`, `/new` |
| **Cost-Aware Context** | LLM-powered compression with hysteresis trigger; API-calibrated token counting |
| **Workspace Sandbox** | File access restricted to the project directory — no accidental writes outside |
| **Bash Safety** | Dangerous commands blocked by default; explicit confirmation required |
| **Drop-in Plugins** | One `.py` file + one config line = new tool |
| **Multi-Model Profiles** | Define multiple model profiles in YAML, hot-switch with `/model use <profile>` |
| **Retry with Backoff** | Automatic retries on timeout, rate limit, and server errors |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  agent.py                                                        │
│                                                                  │
│  ┌──────────┐   ┌────────────────────────────────────────────┐   │
│  │  User    │   │  Agent Loop                                │   │
│  │  Input   │──>│                                            │   │
│  │          │   │  1. Slash commands (/list /resume /new ...)│   │
│  │          │   │  2. Append user message to session         │   │
│  │          │   │  3. Check context → compress if needed     │   │
│  │          │   │  4. Stream LLM response                    │   │
│  │          │<──│  5. Execute tool calls → loop until done   │   │
│  └──────────┘   └──────┬──────────────┬──────────────┬───────┘   │
│                        │              │              │           │
│     ┌──────────────────▼──┐   ┌───────▼────────┐ ┌──—▼─────────┐ │
│     │  Tool Layer         │   │  Context Mgr   │ │  Session    │ │
│     │  (tools/*.py)       │   │  (core/)       │ │  (core/)    │ │
│     │                     │   │                │ │             │ │
│     │  read  list  find   │   │  Token count   │ │  JSONL      │ │
│     │  edit  write bash   │   │  LLM compress  │ │  /resume    │ │
│     │  code_search        │   │  Calibration   │ │  /list      │ │
│     │  web_search/fetch   │   │                │ │             │ │
│     └──────────┬──────────┘   └────────────────┘ └─────────────┘ │
│                │                                                 │
│     ┌──────────▼──────────┐                                      │
│     │  Sandbox            │  Path resolution + workspace fence   │
│     └─────────────────────┘                                      │
└──────────────────────────────────────────────────────────────────┘
```

---

## Usage Examples

### Read & understand a codebase

```
You: Find all Python files in this project and tell me what each one does.

 AI: [calls find(pattern="*.py")] [calls read() on each file]

     Here's the project structure:
     - agent.py: Main coding agent with tool execution loop
     - chat.py: Minimal streaming chat without tools
     - core/utils.py: Config loading, session management ...
```

### Create, edit, and run code

```
You: Create a Fibonacci script, save it as fib.py, then run it.

 AI: [calls write(path="fib.py", content="...")]
     [calls bash(command="python fib.py")]

     0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, ...
```

---

## Slash Commands

| Command | Description |
|---|---|
| `/list` | List available sessions and mark the current one |
| `/resume <id>` | Switch to an existing session |
| `/new` | Create and switch to a new session |
| `/status` | Show model, directory, session, and context status |
| `/model` | List all model profiles and mark the active one |
| `/model use <profile>` | Hot-switch model profile in current session |
| `/compact` | Force context compression |

---

## Configuration

Core settings in `config.yaml`:

```yaml
model:
  active: gpt5                          # which profile to use
  profiles:
    gpt5:
      name: gpt-5
      api_key: ${OPENAI_API_KEY}        # env vars resolved automatically
      base_url: https://api.openai.com/v1/

context:
  compress_trigger_tokens: 90000        # auto-compress above this

tools:
  - read
  - list
  - bash
  - edit
  - write
  - find
  - code_search
```

> See [`config.yaml`](config.yaml) for the full reference with all options.

---

## Project Structure

```
legoflux_agent/
├── agent.py              # Main coding agent (entry point)
├── chat.py               # Minimal streaming chat (no tools)
├── config.yaml           # All configuration in one file
├── core/
│   ├── utils.py          # Config, session, system prompt
│   ├── context.py        # Token counting, LLM compression
│   ├── model_runtime.py  # Model profile hot-switching
│   └── sandbox.py        # Workspace path sandboxing
├── tools/                # One file per tool
│   ├── read.py  list.py  find.py  edit.py  write.py
│   ├── bash.py  code_search.py
│   └── web_search.py  web_fetch.py
└── sessions/             # Auto-created session storage
```

---

## Requirements

- Python 3.8+
- [ripgrep](https://github.com/BurntSushi/ripgrep) (`brew install ripgrep`) — for `code_search`
- An OpenAI-compatible API endpoint

---

## Contributing

Contributions are welcome! Fork the repo, make your changes, and open a PR.

## License

MIT
