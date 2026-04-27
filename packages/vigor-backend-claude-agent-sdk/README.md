# vigor-backend-claude-agent-sdk

Thin VIGOR `AgentBackend` adapter built on the [Claude Agent SDK](https://docs.anthropic.com/en/api/agent-sdk/python).

Claude Agent SDK is an optional dependency. Install with:

```bash
uv add 'vigor-backend-claude-agent-sdk[claude]'
```

Key design points:

1. Uses `claude_agent_sdk.query(...)` for stateless calls.
2. Runs in hermetic mode by default (`setting_sources=[]`) so local `.claude/` configs do not leak in.
3. Uses `permission_mode="dontAsk"` and pre-approves only read-only tools by default.
4. Persists the VIGOR canonical archive independent from Claude Code sessions and checkpoints.
5. Success is detected via `ResultMessage.subtype == "success"` and `not is_error`.
