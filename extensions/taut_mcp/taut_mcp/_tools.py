"""The explicit, versioned Taut MCP tool manifest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp import types

CHANNEL_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
CHAT_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}(?:\.[0-9]{19})?$"
MEMBER_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"

ATTACH_WORKSPACE_DESCRIPTION = (
    "Absolute local directory containing an existing Taut project. Attachment "
    "resolves it once and returns the canonical workspace identifier for later "
    "calls. No relative path or file URI."
)
WORKSPACE_DESCRIPTION = (
    "Exact canonical workspace identifier returned by attach_workspace or "
    "list_workspaces. Do not re-resolve, shorten, or substitute an alias path."
)
TOKEN_DESCRIPTION = (
    "Sensitive existing Taut continuity token for this workspace. It selects "
    "one member and is never returned. Valid only on attach_workspace; do not "
    "invent or repeat it in chat."
)
CHANNEL_DESCRIPTION = (
    "Taut channel matching ^[a-z0-9][a-z0-9_-]{0,63}$; dm, notify, sys, and "
    "taut are reserved."
)
CHAT_DESCRIPTION = (
    "Taut channel or one-level sub-thread. A sub-thread is "
    "<channel>.<19-digit-parent-message-id>. An opaque dm.* queue and an @name "
    "target are not explicit thread values."
)
READ_THREAD_DESCRIPTION = (
    "Optional Taut channel or one-level sub-thread. Null or omitted reads every "
    "joined thread, including direct messages, and is the only public direct-"
    "message read path. For a bare read, the result contains at most limit × N "
    "records, where N is the number of joined non-notification chat threads "
    "selected by the call; every thread returning rows advances its own cursor. "
    "Explicit dm.* and @name values are rejected."
)
LIMIT_DESCRIPTION = (
    "Maximum records requested from one queue, from 1 through 1,000 inclusive."
)

RECORD_TYPE_BY_TOOL = {
    "attach_workspace": "workspace",
    "detach_workspace": "workspace",
    "list_workspaces": "workspace",
    "join": "message",
    "leave": "message",
    "set_name": "member",
    "say": "message",
    "reply": "message",
    "read": "message",
    "inbox": "notification",
    "log": "message",
    "list": "thread",
    "rename": "thread",
    "who": "member",
    "whoami": "member",
}


def _nullable(kind: str) -> dict[str, Any]:
    return {"anyOf": [{"type": kind}, {"type": "null"}]}


_RECORD_SCHEMAS: dict[str, dict[str, Any]] = {
    "workspace": {
        "additionalProperties": False,
        "properties": {
            "backend": {
                "description": "Resolved Taut backend name for this attachment.",
                "type": "string",
            },
            "member_id": {
                "description": "Immutable attached Taut member id, or null before identity is available.",
                **_nullable("string"),
            },
            "name": {
                "description": "Current attached member display name, or null before identity is available.",
                **_nullable("string"),
            },
            "status": {
                "description": "Connection-local workspace lifecycle status.",
                "enum": [
                    "ready",
                    "detaching",
                    "identity_lost",
                    "reactor_failed",
                    "detached",
                ],
                "type": "string",
            },
            "workspace": {
                "description": "Canonical workspace identifier for later calls.",
                "type": "string",
            },
        },
        "required": ["backend", "member_id", "name", "status", "workspace"],
        "type": "object",
    },
    "message": {
        "additionalProperties": False,
        "properties": {
            "from": {"description": "Author display name.", "type": "string"},
            "from_id": {
                "description": "Immutable author member id when available.",
                **_nullable("string"),
            },
            "kind": {"description": "Taut message kind.", "type": "string"},
            "text": {"description": "Message body.", "type": "string"},
            "thread": {
                "description": "Taut channel, sub-thread, or direct-message queue.",
                "type": "string",
            },
            "ts": {"description": "Taut message timestamp/id.", "type": "integer"},
        },
        "required": ["from", "from_id", "kind", "text", "thread", "ts"],
        "type": "object",
    },
    "notification": {
        "additionalProperties": False,
        "properties": {
            "actor_id": {
                "description": "Immutable actor member id when available.",
                **_nullable("string"),
            },
            "actor_name": {
                "description": "Actor display name when available.",
                **_nullable("string"),
            },
            "matched": {
                "description": "Mention text that matched, when supplied.",
                "type": "string",
            },
            "message_ts": {
                "description": "Related message timestamp/id when available.",
                **_nullable("integer"),
            },
            "thread": {
                "description": "Related Taut thread when available.",
                **_nullable("string"),
            },
            "to_id": {
                "description": "Notification recipient member id when available.",
                **_nullable("string"),
            },
            "type": {"description": "Notification type.", "type": "string"},
        },
        "required": [
            "actor_id",
            "actor_name",
            "message_ts",
            "thread",
            "to_id",
            "type",
        ],
        "type": "object",
    },
    "member": {
        "additionalProperties": False,
        "properties": {
            "aliases": {
                "description": "Known display-name aliases for this member.",
                "items": {"type": "string"},
                "type": "array",
            },
            "kind": {"description": "Taut member record kind.", "type": "string"},
            "last_active_ts": {
                "description": "Most recent recorded member activity timestamp.",
                "type": "integer",
            },
            "member_id": {
                "description": "Immutable Taut member id.",
                "type": "string",
            },
            "name": {"description": "Current member display name.", "type": "string"},
            "persona": {
                "description": "Current member persona text when set.",
                **_nullable("string"),
            },
            "presence": {
                "description": "Computed Taut presence state.",
                "type": "string",
            },
        },
        "required": [
            "aliases",
            "kind",
            "last_active_ts",
            "member_id",
            "name",
            "persona",
            "presence",
        ],
        "type": "object",
    },
    "thread": {
        "additionalProperties": False,
        "properties": {
            "kind": {"description": "Taut thread kind.", "type": "string"},
            "last_ts": {
                "description": "Latest message timestamp/id when one exists.",
                **_nullable("integer"),
            },
            "members": {
                "description": "Member names when returned by the selected operation.",
                "items": {"type": "string"},
                "type": "array",
            },
            "parent": {
                "description": "Parent message id for a sub-thread, otherwise null.",
                **_nullable("string"),
            },
            "thread": {"description": "Taut thread name.", "type": "string"},
            "unread": {
                "description": "Whether this member has unread messages in the thread.",
                "type": "boolean",
            },
        },
        "required": ["kind", "last_ts", "parent", "thread", "unread"],
        "type": "object",
    },
}


def _result_schema(record_type: str) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "properties": {
            "empty": {
                "description": "True when records is empty.",
                "type": "boolean",
            },
            "guidance": {
                "description": "Action-bearing guidance associated with this result.",
                "items": {
                    "additionalProperties": False,
                    "properties": {
                        "action": {
                            "description": "Recommended follow-up action.",
                            "type": "string",
                        },
                        "code": {
                            "description": "Stable guidance classification.",
                            "type": "string",
                        },
                        "message": {
                            "description": "Human-readable effect explanation.",
                            "type": "string",
                        },
                    },
                    "required": ["action", "code", "message"],
                    "type": "object",
                },
                "type": "array",
            },
            "record_type": {
                "const": record_type,
                "description": "Domain record type contained in records.",
                "type": "string",
            },
            "records": {
                "description": "Canonical domain records returned by the operation.",
                "items": _RECORD_SCHEMAS[record_type],
                "type": "array",
            },
            "warnings": {
                "description": "Content-free operational warnings.",
                "items": {"type": "string"},
                "type": "array",
            },
            "workspace": {
                "description": "Canonical selected workspace, or null for connection-wide results.",
                **_nullable("string"),
            },
        },
        "required": [
            "empty",
            "guidance",
            "record_type",
            "records",
            "warnings",
            "workspace",
        ],
        "type": "object",
    }


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    properties: dict[str, dict[str, Any]]
    required: tuple[str, ...]
    annotations: types.ToolAnnotations

    def to_mcp(self) -> types.Tool:
        schema: dict[str, Any] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "additionalProperties": False,
            "properties": self.properties,
            "type": "object",
        }
        if self.required:
            schema["required"] = list(self.required)
        return types.Tool(
            name=self.name,
            description=self.description,
            inputSchema=schema,
            outputSchema=_result_schema(RECORD_TYPE_BY_TOOL[self.name]),
            annotations=self.annotations,
        )


def _string(description: str, *, pattern: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"description": description, "type": "string"}
    if pattern is not None:
        schema["pattern"] = pattern
    return schema


def _nullable_string(
    description: str,
    *,
    pattern: str | None = None,
    default: str | None = None,
) -> dict[str, Any]:
    string = _string(description, pattern=pattern)
    return {
        "anyOf": [string, {"type": "null"}],
        "default": default,
        "description": description,
    }


def _annotations(
    *,
    read_only: bool,
    destructive: bool,
    idempotent: bool,
    open_world: bool,
) -> types.ToolAnnotations:
    return types.ToolAnnotations(
        readOnlyHint=read_only,
        destructiveHint=destructive,
        idempotentHint=idempotent,
        openWorldHint=open_world,
    )


_WORKSPACE = _string(WORKSPACE_DESCRIPTION)
_CHANNEL = _string(CHANNEL_DESCRIPTION, pattern=CHANNEL_PATTERN)
_CHAT = _string(CHAT_DESCRIPTION, pattern=CHAT_PATTERN)
_LIMIT_100 = {
    "default": 100,
    "description": LIMIT_DESCRIPTION + " Defaults to 100 per selected thread.",
    "maximum": 1000,
    "minimum": 1,
    "type": "integer",
}
_LIMIT_1000 = {
    "default": 1000,
    "description": LIMIT_DESCRIPTION + " Defaults to 1,000.",
    "maximum": 1000,
    "minimum": 1,
    "type": "integer",
}

TOOL_DEFINITIONS = (
    ToolDefinition(
        "attach_workspace",
        "Validate and attach one local Taut workspace with an existing continuity token. Reads project and member identity without touching member activity; creates connection-local state and no Taut project or member.",
        {
            "workspace": _string(ATTACH_WORKSPACE_DESCRIPTION),
            "token": _string(TOKEN_DESCRIPTION),
        },
        ("workspace", "token"),
        _annotations(
            read_only=False,
            destructive=False,
            idempotent=True,
            open_world=False,
        ),
    ),
    ToolDefinition(
        "detach_workspace",
        "Destroy this session's attachment and stop its notification observation. Deletes no Taut project, member, or message data.",
        {"workspace": _WORKSPACE},
        ("workspace",),
        _annotations(
            read_only=False,
            destructive=True,
            idempotent=True,
            open_world=False,
        ),
    ),
    ToolDefinition(
        "list_workspaces",
        "List the canonical workspaces and statuses currently attached to this MCP session. Reads only connection-local cached state.",
        {},
        (),
        _annotations(
            read_only=True,
            destructive=False,
            idempotent=True,
            open_world=False,
        ),
    ),
    ToolDefinition(
        "join",
        "Join or create a Taut channel. Writes membership state and a channel notice.",
        {
            "workspace": _WORKSPACE,
            "thread": _CHANNEL,
            "persona": _nullable_string(
                "Optional persona text stored for the attached member while joining. Null leaves the current persona unchanged."
            ),
        },
        ("workspace", "thread"),
        _annotations(
            read_only=False,
            destructive=False,
            idempotent=False,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "leave",
        "Leave a Taut channel or sub-thread. Removes membership and writes a notice.",
        {"workspace": _WORKSPACE, "thread": _CHAT},
        ("workspace", "thread"),
        _annotations(
            read_only=False,
            destructive=True,
            idempotent=False,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "set_name",
        "Change the attached member's Taut display name. Replaces identity-routing state for that member.",
        {
            "workspace": _WORKSPACE,
            "name": _string(
                "Case-preserving Taut member name matching ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$; routing uniqueness is case-insensitive. Used only by set_name.",
                pattern=MEMBER_NAME_PATTERN,
            ),
        },
        ("workspace", "name"),
        _annotations(
            read_only=False,
            destructive=True,
            idempotent=False,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "say",
        "Post a new Taut message to a channel, sub-thread, or direct-message target.",
        {
            "workspace": _WORKSPACE,
            "target": _string(
                "Message destination: a channel such as general, a sub-thread such as general.<19-digit-parent-message-id>, or a direct message such as @claude. Used only by say; no stdin sentinel."
            ),
            "text": _string(
                "Nonblank message text written as participant content under Taut's core size and validation rules. Used by say and reply."
            ),
        },
        ("workspace", "target", "text"),
        _annotations(
            read_only=False,
            destructive=False,
            idempotent=False,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "reply",
        "Post a new reply under a top-level channel message. May create the reply sub-thread and membership.",
        {
            "workspace": _WORKSPACE,
            "thread": _CHANNEL,
            "msg_id": _string(
                "Parent message id: the full 19-digit id, or a unique suffix of at least 4 digits among the most recent 1,000 ids in the channel. Used only by reply; ambiguity is an error.",
                pattern=r"^[0-9]{4,19}$",
            ),
            "text": _string(
                "Nonblank message text written as participant content under Taut's core size and validation rules. Used by say and reply."
            ),
        },
        ("workspace", "thread", "msg_id", "text"),
        _annotations(
            read_only=False,
            destructive=False,
            idempotent=False,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "read",
        "Return oldest unread messages and advance each selected read cursor through its own returned page. No message history is deleted. Use `log` to inspect channel or sub-thread history without moving a cursor. Omit `thread` only for all joined threads, including direct messages; this may return up to `limit × N` rows, where `N` is the number of selected joined non-notification chat threads. Prefer an explicit channel or sub-thread when direct messages are not needed.",
        {
            "workspace": _WORKSPACE,
            "thread": _nullable_string(
                READ_THREAD_DESCRIPTION,
                pattern=CHAT_PATTERN,
            ),
            "limit": _LIMIT_100,
        },
        ("workspace",),
        _annotations(
            read_only=False,
            destructive=True,
            idempotent=False,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "inbox",
        "Claim and return notification pointers from this member's inbox. This consumes the pointers; source chat history remains.",
        {"workspace": _WORKSPACE, "limit": _LIMIT_1000},
        ("workspace",),
        _annotations(
            read_only=False,
            destructive=True,
            idempotent=False,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "log",
        "Inspect bounded channel or sub-thread history without moving read cursors or claiming notifications. Direct-message queues are not valid log targets.",
        {
            "workspace": _WORKSPACE,
            "thread": _CHAT,
            "since": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "integer"},
                    {"type": "null"},
                ],
                "default": None,
                "description": "Exclusive history lower bound: ISO 8601, Unix seconds/milliseconds/nanoseconds, or a native 19-digit message id. Null means no lower bound; used only by log.",
            },
            "limit": {
                **_LIMIT_100,
                "description": LIMIT_DESCRIPTION
                + " Defaults to 100 most-recent matches.",
            },
        },
        ("workspace", "thread"),
        _annotations(
            read_only=True,
            destructive=False,
            idempotent=True,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "list",
        "List joined or visible threads and unread counts. Resolving the existing member updates this member's activity timestamp; it does not change the member anchor, token fingerprint, or computed presence. Direct-message bodies are unavailable through `log` or an explicit `read.thread`; omit `thread` from `read` to retrieve unread direct messages.",
        {
            "workspace": _WORKSPACE,
            "all": {
                "default": False,
                "description": "When true, list every registered visible Taut thread; when false, use ordinary joined/unread list behavior. Defaults to false.",
                "type": "boolean",
            },
        },
        ("workspace",),
        _annotations(
            read_only=False,
            destructive=False,
            idempotent=False,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "rename",
        "Rename a Taut channel and its sub-threads. Replaces existing thread addresses.",
        {
            "workspace": _WORKSPACE,
            "old_name": _CHANNEL,
            "new_name": _CHANNEL,
        },
        ("workspace", "old_name", "new_name"),
        _annotations(
            read_only=False,
            destructive=True,
            idempotent=False,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "who",
        "List Taut members or members of one thread. Resolving the existing member updates the caller's activity timestamp; it does not change the member anchor, token fingerprint, or computed presence.",
        {
            "workspace": _WORKSPACE,
            "thread": _nullable_string(CHAT_DESCRIPTION, pattern=CHAT_PATTERN),
        },
        ("workspace",),
        _annotations(
            read_only=False,
            destructive=False,
            idempotent=False,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "whoami",
        "Return the member bound to this workspace attachment. Resolving the existing member updates its activity timestamp; it does not change the member anchor, token fingerprint, or computed presence.",
        {"workspace": _WORKSPACE},
        ("workspace",),
        _annotations(
            read_only=False,
            destructive=False,
            idempotent=False,
            open_world=True,
        ),
    ),
)

TOOLS = tuple(definition.to_mcp() for definition in TOOL_DEFINITIONS)
