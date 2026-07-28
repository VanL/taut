"""The explicit, versioned Taut MCP tool manifest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp import types

CHANNEL_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
CHAT_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}(?:\.[0-9]{19})?$"
CHAT_OR_DM_PATTERN = (
    r"^(?:[a-z0-9][a-z0-9_-]{0,63}(?:\.[0-9]{19})?"
    r"|@[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
    r"|dm\.d_[a-z2-7]{26})$"
)
MEMBER_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
REACTION_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,31}$"

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
    "Taut channel or one-level subthread. A subthread is "
    "<channel>.<19-digit-parent-message-id>."
)
CHAT_OR_DM_DESCRIPTION = (
    "Taut channel, one-level subthread, @name-or-alias, or stable "
    "dm.d_<26-lowercase-base32-chars> selector."
)
READ_THREAD_DESCRIPTION = (
    "Optional chat-or-DM selector. Null or omitted reads every joined chat "
    "thread. Explicit DM selection requires an existing accessible conversation "
    "and advances only its returned page."
)
LIMIT_DESCRIPTION = (
    "Maximum records requested from one queue, from 1 through 1,000 inclusive."
)
EXACT_MESSAGE_ID_DESCRIPTION = (
    "Exact native Taut message id as a 19-digit decimal string. Preserve it as "
    "text; suffixes, whitespace, signs, and numeric JSON values are invalid."
)
REACTION_DESCRIPTION = (
    "Configured lowercase ASCII reaction slug matching "
    "^[a-z0-9][a-z0-9_-]{0,31}$. Used only by message_react; the schema is "
    "not an enum because the attached workspace config remains authoritative."
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
    "message_show": "message",
    "message_delete": "deletion",
    "message_react": "reaction",
    "read": "message",
    "inbox": "notification",
    "log": "message",
    "list": "thread",
    "channel_show": "channel",
    "channel_topic": "channel",
    "channel_rename": "thread",
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
    "deletion": {
        "additionalProperties": False,
        "properties": {
            "deleted": {
                "const": True,
                "description": "True for a successful physical deletion.",
            },
            "thread": {
                "description": "Taut thread from which the message was deleted.",
                "type": "string",
            },
            "ts": {
                "description": "Deleted Taut message timestamp/id.",
                "type": "integer",
            },
        },
        "required": ["thread", "ts", "deleted"],
        "type": "object",
    },
    "reaction": {
        "additionalProperties": False,
        "properties": {
            "audience_count": {
                "description": (
                    "Current authorized non-actor recipient count; not a "
                    "delivery or consumption receipt."
                ),
                "minimum": 1,
                "type": "integer",
            },
            "message_ts": {
                "description": "Reacted-to Taut message timestamp/id.",
                "type": "integer",
            },
            "reaction": {
                "description": "Configured reaction slug sent by the actor.",
                "type": "string",
            },
            "thread": {
                "description": "Exact Taut thread containing the source message.",
                "type": "string",
            },
        },
        "required": ["thread", "message_ts", "reaction", "audience_count"],
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
            "reaction": {
                "description": "Reaction slug for a reaction notification.",
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
    "channel": {
        "additionalProperties": False,
        "properties": {
            "channel": {
                "description": "Registered top-level Taut channel name.",
                "type": "string",
            },
            "topic": {
                "description": "Current exact channel topic, or null.",
                **_nullable("string"),
            },
            "topic_updated_ts": {
                "description": "Topic update timestamp/id, or null.",
                **_nullable("integer"),
            },
            "topic_updated_by_id": {
                "description": "Immutable topic author member id, or null.",
                **_nullable("string"),
            },
            "topic_updated_by_name": {
                "description": "Current topic author display name, or null.",
                **_nullable("string"),
            },
        },
        "required": [
            "channel",
            "topic",
            "topic_updated_ts",
            "topic_updated_by_id",
            "topic_updated_by_name",
        ],
        "type": "object",
    },
}


def _thread_branch(
    kind: str,
    *,
    topic: bool = False,
    members: bool = False,
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "kind": {
            "const": kind,
            "description": "Taut thread kind.",
            "type": "string",
        },
        "last_ts": {
            "description": "Latest message timestamp/id when one exists.",
            **_nullable("integer"),
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
    }
    required = ["kind", "last_ts", "parent", "thread", "unread"]
    if topic:
        properties["topic"] = {
            "description": "Current exact channel topic, or null.",
            **_nullable("string"),
        }
        required.append("topic")
    if members:
        properties["members"] = {
            "description": "Immutable DM participant member ids.",
            "items": {"type": "string"},
            "type": "array",
        }
        required.append("members")
    return {
        "additionalProperties": False,
        "properties": properties,
        "required": required,
        "type": "object",
    }


_RECORD_SCHEMAS["thread"] = {
    "oneOf": [
        _thread_branch("channel", topic=True),
        _thread_branch("dm", members=True),
        _thread_branch("subthread"),
    ]
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
    schema_constraints: dict[str, Any] | None = None

    def to_mcp(self) -> types.Tool:
        schema: dict[str, Any] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "additionalProperties": False,
            "properties": self.properties,
            "type": "object",
        }
        if self.required:
            schema["required"] = list(self.required)
        if self.schema_constraints is not None:
            schema.update(self.schema_constraints)
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
_CHAT_OR_DM = _string(CHAT_OR_DM_DESCRIPTION, pattern=CHAT_OR_DM_PATTERN)
_EXACT_MESSAGE_ID = _string(
    EXACT_MESSAGE_ID_DESCRIPTION,
    pattern=r"^[0-9]{19}$",
)
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
        "message_show",
        "Return one exact full-id message from this member's current chat memberships, then advance that thread's high-water cursor through the returned id. This may mark unseen intervening history seen. It never joins a thread; use `log` for cursor-neutral known-channel or sub-thread inspection.",
        {
            "workspace": _WORKSPACE,
            "msg_id": _EXACT_MESSAGE_ID,
        },
        ("workspace", "msg_id"),
        _annotations(
            read_only=False,
            destructive=True,
            idempotent=False,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "message_delete",
        "Physically and irreversibly delete one exact ordinary message authored by this member, including after leaving its thread. It does not cascade to notifications, sub-threads, memberships, cursors, or thread registry state and is not recall.",
        {
            "workspace": _WORKSPACE,
            "msg_id": _EXACT_MESSAGE_ID,
        },
        ("workspace", "msg_id"),
        _annotations(
            read_only=False,
            destructive=True,
            idempotent=False,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "message_react",
        "Send one configured reaction to the current audience of an exact ordinary message, excluding this member. Validates against the workspace's attachment-time reaction vocabulary, advances this member's high-water cursor through the target, then attempts one atomic best-effort notification broadcast to every requested inbox. Repeating may deliver duplicates.",
        {
            "workspace": _WORKSPACE,
            "msg_id": _EXACT_MESSAGE_ID,
            "reaction": _string(
                REACTION_DESCRIPTION,
                pattern=REACTION_PATTERN,
            ),
        },
        ("workspace", "msg_id", "reaction"),
        _annotations(
            read_only=False,
            destructive=True,
            idempotent=False,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "read",
        "Return oldest unread messages and advance each selected cursor through its returned page. `thread` may select a channel, subthread, `@name-or-alias` DM, or stable `dm.d_*` conversation. Omit it for all joined chat threads.",
        {
            "workspace": _WORKSPACE,
            "thread": _nullable_string(
                READ_THREAD_DESCRIPTION,
                pattern=CHAT_OR_DM_PATTERN,
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
        "Claim and return notification pointers from this member's inbox. This consumes the pointers; source chat history is not changed by inbox but may already be author-deleted.",
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
        "Inspect cursor-neutral history for a channel, subthread, or existing actor-accessible DM selected by `@name-or-alias` or stable `dm.d_*` handle.",
        {
            "workspace": _WORKSPACE,
            "thread": _CHAT_OR_DM,
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
        "List ordinary joined/unread threads, every registered thread, or every valid actor-accessible DM. `all` and `dms` are mutually exclusive. Resolving the existing member for actor-scoped list modes may update activity.",
        {
            "workspace": _WORKSPACE,
            "all": {
                "default": False,
                "description": "When true, list every registered Taut thread. Defaults to false; mutually exclusive with dms.",
                "type": "boolean",
            },
            "dms": {
                "default": False,
                "description": "When true, list every valid actor-accessible DM, including read and empty conversations. Defaults to false; mutually exclusive with all.",
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
        {
            "not": {
                "properties": {
                    "all": {"const": True},
                    "dms": {"const": True},
                },
                "required": ["all", "dms"],
            }
        },
    ),
    ToolDefinition(
        "channel_show",
        "Return current metadata for one registered top-level Taut channel. Reads only shared registry state and does not resolve identity, touch activity, inspect a broker queue, or move a cursor.",
        {
            "workspace": _WORKSPACE,
            "channel": _CHANNEL,
        },
        ("workspace", "channel"),
        _annotations(
            read_only=True,
            destructive=False,
            idempotent=True,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "channel_topic",
        "Set or clear one registered top-level Taut channel's topic. Requires the attached member's current channel membership; a changed value replaces shared topic state and updates member activity, while an identical value is a no-op.",
        {
            "workspace": _WORKSPACE,
            "channel": _CHANNEL,
            "topic": {
                "anyOf": [
                    {
                        "maxLength": 500,
                        "not": {"pattern": r"[\r\n]"},
                        "type": "string",
                    },
                    {"type": "null"},
                ],
                "description": (
                    "Exact one-line topic of at most 500 Unicode code points, "
                    "or null to clear it. Core rejects blank text."
                ),
            },
        },
        ("workspace", "channel", "topic"),
        _annotations(
            read_only=False,
            destructive=True,
            idempotent=False,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "channel_rename",
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
