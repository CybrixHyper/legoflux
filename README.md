<p align="center">
  <img src="./docs/images/legoflux_logo.png" alt="LegoFlux logo" width="400" />
</p>

<h2 align="center">LegoFlux: The Ultra-Lightweight Coding Agent.</h2>

<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-blue" />
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-green" />
</p>

A **fully-featured coding agent in ~2,000 lines of Python** — read, edit, execute, search, and browse the web, with context compression and workspace sandboxing built in.

- **Complete agent, zero magic** — 9 tools, session persistence, streaming, context management. All in readable Python you can audit in an afternoon.
- **Cost-aware context** — Hysteresis-based compression keeps you inside the token budget automatically; API-calibrated counting means no surprise overflows.
- **Drop-a-`.py` plugins** — Adding a tool is one file (`DEFINITION` + `execute()`) and one line in `config.yaml`. No framework to learn.

<table style="width: 100%; table-layout: fixed;">
  <tr>
    <td align="center" style="width: 25%;"><strong>slash commands</strong></td>
    <td align="center" style="width: 25%;"><strong>switch between models</strong></td>
    <td align="center" style="width: 25%;"><strong>search the web</strong></td>
    <td align="center" style="width: 25%;"><strong>code understanding</strong></td>
  </tr>
  <tr>
    <td align="center"><img src="./docs/images/slash.gif" style="width: 100%; height: 340px; object-fit: cover;" /></td>
    <td align="center"><img src="./docs/images/model_switch.gif" style="width: 100%; height: 340px; object-fit: cover;" /></td>
    <td align="center"><img src="./docs/images/web_search.gif" style="width: 100%; height: 340px; object-fit: cover;" /></td>
    <td align="center"><img src="./docs/images/code.gif" style="width: 100%; height: 340px; object-fit: cover;" /></td>
  </tr>
</table>

---

## Quick Start

```bash
pip install -r requirements.txt     # install dependencies
vim config.yaml                     # fill your API key/base_url
python agent.py                     # start the coding agent
```

Input: Press `Enter` to submit, and press `Ctrl+J` to insert a newline.

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
| **9 Built-in Tools** | Read, list, find, edit, write, bash, code_search, web_search, web_fetch |
| **Streaming Output** | See tokens as they arrive, not after a long wait |
| **Session** | Pick up where you left off with `/session`, `/session use`, `/session new` |
| **Context** | LLM-powered compression with hysteresis trigger; API-calibrated token counting |
| **Sandbox** | File access restricted to the project directory — no accidental writes outside |
| **Bash Safety** | Dangerous commands blocked by default; explicit confirmation required |
| **Drop-in Plugins** | One `.py` file + one config line = new tool |
| **Multi-Model** | Define multiple models in YAML, hot-switch with `/model use <profile>` |
| **Retry with Backoff** | Automatic retries on timeout, rate limit, and server errors |

---

## Comparison

```text
+--------------+-------------------+-----------------+--------------------+-----------------+
| Dimension    | LegoFlux          | Claude Code     | Codex              | OpenCode        |
+--------------+-------------------+-----------------+--------------------+-----------------+
| Tool         | 9 built-ins       | Built-ins + MCP | Built-ins + MCP    | Built-ins + MCP |
| Compaction   | Auto + /compact   | Auto + /compact | /compact + auto    | /compact        |
| Slash cmds   | Focused           | Rich            | Rich               | Medium          |
| Web          | Supported         | Supported       | Supported          | Supported       |
| Sandbox/Perm | Workspace sandbox | allow/ask/deny  | sandbox + approval | allow/ask/deny  |
+--------------+-------------------+-----------------+--------------------+-----------------+
```

---

## Architecture

```
[User]
  -> [Agent Loop] <-> [Model API]
       |-> [Tool Router] -> [read/list/find/edit/write/bash/web]
       |-> [Context Manager] (token count + compact)
       |-> [Session Store] (JSONL)
[Sandbox] guards file paths and shell commands
```

---

## Usage Examples

```bash
You: Show me the high-level structure of agent.py.
Tool: read(path='agent.py', mode='structure')
Assistant: Summarized module layout, key classes, and runtime flow.
```

More full transcripts: [`docs/examples.md`](docs/examples.md).

---
## Slash Commands

| Command | Description |
|---|---|
| `/session` | List available sessions and mark the current one |
| `/session use <id>` | Switch to an existing session |
| `/session new` | Create and switch to a new session |
| `/model` | List all model profiles and mark the active one |
| `/model use <profile>` | Hot-switch model profile in current session |
| `/status` | Show model, directory, session, and context status |
| `/compact` | Force context compression |

---

## Configuration

Core settings in `config.yaml`:

```yaml
model:
  provider: openai_compatible
  active: gpt5                          # active model profile
  max_completion_tokens: 8192           # shared defaults for all profiles
  max_retries: 2
  retry_backoff_sec: 1.0
  timeout_sec: 120
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
  - web_search
  - web_fetch
```

`web_search` uses the Alibaba Cloud IQS LiteAdvanced search engine: [Aliyun docs](https://help.aliyun.com/document_detail/2974627.html?spm=a2c4g.11186623.0.0.43434e8auGlgWu).
`web_search` and `web_fetch` share a common IQS helper module: `tools/_iqs_common.py`.

`read` supports `mode`:

- `mode: "full"` (default): return full file lines with line numbers
- `mode: "structure"`: return structural lines only (imports, class/def, decorators, and control headers)

> See [`config.yaml`](config.yaml) for the full reference with all options.

---

## Project Structure

```
legoflux/
├── agent.py              # Main coding agent (entry point)
├── chat.py               # Minimal streaming chat (no tools)
├── config.yaml           # All configuration in one file
├── docs/                 # Images and extended docs (examples, etc.)
├── core/
│   ├── utils.py          # Config, session, system prompt
│   ├── context.py        # Token counting, LLM compression
│   ├── model_runtime.py  # Model profile hot-switching
│   └── sandbox.py        # Workspace path sandboxing
├── tools/                # One file per tool
│   ├── read.py  list.py  find.py  edit.py  write.py
│   ├── bash.py  code_search.py
│   ├── web_search.py  web_fetch.py
│   └── _iqs_common.py  # Shared IQS request/validation helpers
└── sessions/             # Auto-created session storage
```

---

## Requirements

- Python 3.11+
- [ripgrep](https://github.com/BurntSushi/ripgrep) (`brew install ripgrep`) — for `code_search`
- An OpenAI-compatible API endpoint

---

## Contributing

Contributions are welcome! Fork the repo, make your changes, and open a PR.

## License

MIT
