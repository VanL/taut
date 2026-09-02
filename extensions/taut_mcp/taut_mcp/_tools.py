"""The explicit, versioned Taut MCP tool manifest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from mcp import types

CHANNEL_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
CHAT_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}(?:\.[0-9]{19})?$"
CHAT_OR_DM_PATTERN = (
    r"^(?:[a-z0-9][a-z0-9_-]{0,63}(?:\.[0-9]{19})?"
    r"|@[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
    r"|dm\.d_[a-z2-7]{26})$"
)
DM_SELECTOR_PATTERN = r"^(?:@[A-Za-z0-9][A-Za-z0-9_-]{0,63}|dm\.d_[a-z2-7]{26})$"
MEMBER_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
REACTION_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,31}$"
MESSAGE_ID_PATTERN = r"^[0-9]{19}$"
MAX_SAFE_JSON_INTEGER = (1 << 53) - 1

ATTACH_WORKSPACE_DESCRIPTION = (
    "Absolute local directory containing an existing Taut project. The server "
    "resolves it to a canonical workspace identifier; reuse the returned "
    "canonical value to avoid repeated resolution. No relative path or file URI; "
    "used by attach_workspace and the 18 CLI-shaped tools."
)
WORKSPACE_DESCRIPTION = ATTACH_WORKSPACE_DESCRIPTION
DETACH_WORKSPACE_DESCRIPTION = (
    "Exact canonical workspace identifier returned by a successful ensure or "
    "list_workspaces. Detach removes only this process's resident state. No "
    "filesystem re-resolution and no identity token; an exact active "
    "hidden-candidate string reports busy but is never removed."
)
TOKEN_DESCRIPTION = (
    "Existing Taut continuity token for this workspace. It selects one member "
    "and is never returned. Required on attach_workspace and every CLI-shaped "
    "tool; do not invent it or repeat it in chat."
)
CHANNEL_DESCRIPTION = (
    "Taut channel matching ^[a-z0-9][a-z0-9_-]{0,63}$; dm, notify, sys, and "
    "taut are reserved. join, reply, channel_rename.old_name, and "
    "channel_rename.new_name require a top-level channel."
)
CHANNEL_PROPERTY_DESCRIPTION = (
    "Taut channel matching ^[a-z0-9][a-z0-9_-]{0,63}$; dm, notify, sys, and "
    "taut are reserved. Used by channel_show and channel_topic; no subthread or "
    "DM form."
)
CHAT_DESCRIPTION = (
    "Taut channel or one-level subthread. A subthread is "
    "<channel>.<19-digit-parent-message-id>. leave and who accept only this narrow "
    "form."
)
CHAT_OR_DM_DESCRIPTION = (
    "Taut channel, one-level subthread, @name-or-alias, or stable "
    "dm.d_<26-lowercase-base32-chars> selector. log accepts all forms and applies "
    "actor access checks to DMs."
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
    "text; suffixes, whitespace, signs, and numeric JSON values are invalid. Used "
    "by message_show, message_delete, and message_react; all three schemas set "
    "pattern: ^[0-9]{19}$, and core additionally rejects values outside the public "
    "signed-64-bit native timestamp range before identity or lookup."
)
REACTION_DESCRIPTION = (
    "Configured lowercase ASCII reaction slug matching "
    "^[a-z0-9][a-z0-9_-]{0,31}$. Used only by message_react; the schema is not an "
    "enum because the attached workspace config remains authoritative."
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
    "search": "search_hit",
    "list": "thread",
    "channel_show": "channel",
    "channel_topic": "channel",
    "channel_rename": "thread",
    "who": "member",
    "whoami": "member",
}
DOMAIN_TOOL_NAMES = frozenset(RECORD_TYPE_BY_TOOL) - {
    "attach_workspace",
    "detach_workspace",
    "list_workspaces",
}


def _nullable_message_id(description: str) -> dict[str, Any]:
    return {
        "anyOf": [
            {"pattern": MESSAGE_ID_PATTERN, "type": "string"},
            {"type": "null"},
        ],
        "description": description,
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
        properties: dict[str, dict[str, Any]] = {}
        for name, property_schema in self.properties.items():
            properties[name] = property_schema
            if name == "workspace" and self.name in DOMAIN_TOOL_NAMES:
                properties["token"] = _TOKEN
        required = list(self.required)
        if self.name in DOMAIN_TOOL_NAMES:
            required.insert(required.index("workspace") + 1, "token")
        schema: dict[str, Any] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "additionalProperties": False,
            "properties": properties,
            "type": "object",
        }
        if required:
            schema["required"] = required
        if self.schema_constraints is not None:
            schema.update(self.schema_constraints)
        return types.Tool(
            name=self.name,
            description=self.description,
            input_schema=schema,
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
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=open_world,
    )


_WORKSPACE = _string(WORKSPACE_DESCRIPTION)
_TOKEN = _string(TOKEN_DESCRIPTION)
_CHANNEL = _string(CHANNEL_DESCRIPTION, pattern=CHANNEL_PATTERN)
_CHANNEL_PROPERTY = _string(
    CHANNEL_PROPERTY_DESCRIPTION,
    pattern=CHANNEL_PATTERN,
)
_CHAT = _string(CHAT_DESCRIPTION, pattern=CHAT_PATTERN)
_CHAT_OR_DM = _string(CHAT_OR_DM_DESCRIPTION, pattern=CHAT_OR_DM_PATTERN)
_EXACT_MESSAGE_ID = _string(
    EXACT_MESSAGE_ID_DESCRIPTION,
    pattern=MESSAGE_ID_PATTERN,
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
_LIMIT_50 = {
    "default": 50,
    "description": LIMIT_DESCRIPTION + " Defaults to 50.",
    "maximum": 1000,
    "minimum": 1,
    "type": "integer",
}

TOOL_DEFINITIONS = (
    ToolDefinition(
        "attach_workspace",
        "Eagerly validate and retain one local Taut workspace with an existing continuity token. Reads project and member identity without touching member activity; starts notification observation and creates no Taut project or member.",
        {
            "workspace": _string(ATTACH_WORKSPACE_DESCRIPTION),
            "token": _TOKEN,
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
        "Stop and remove this process's resident workspace owner. Deletes no Taut project, member, message, or identity data.",
        {"workspace": _string(DETACH_WORKSPACE_DESCRIPTION)},
        ("workspace",),
        _annotations(
            read_only=False,
            destructive=False,
            idempotent=True,
            open_world=False,
        ),
    ),
    ToolDefinition(
        "list_workspaces",
        "List canonical workspaces and statuses currently resident in this server process. Reads only process-local cached state.",
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
            destructive=False,
            idempotent=False,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "say",
        "Post a new Taut message to a channel, sub-thread, person-addressed direct message, or an existing direct-message conversation. @name-or-alias may create a DM; exact dm.d_* requires an existing actor-accessible conversation and never creates or heals one.",
        {
            "workspace": _WORKSPACE,
            "target": _string(
                "Message destination: a channel such as general, a sub-thread such as general.<19-digit-parent-message-id>, a person-addressed direct message such as @claude, or an exact stable handle dm.d_<26-lowercase-base32-chars>. @name-or-alias may create a DM; an exact stable handle requires an existing actor-accessible conversation and never creates or heals one. Used only by say; no stdin sentinel."
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
            destructive=False,
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
            destructive=False,
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
            destructive=False,
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
            destructive=False,
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
                    {
                        "maximum": MAX_SAFE_JSON_INTEGER,
                        "minimum": -MAX_SAFE_JSON_INTEGER,
                        "type": "integer",
                    },
                    {"type": "null"},
                ],
                "default": None,
                "description": (
                    "Exclusive history lower bound: ISO 8601, Unix "
                    "seconds/milliseconds/nanoseconds, or a native 19-digit message "
                    "id. Null means no lower bound; used only by log. String forms "
                    "preserve the existing core grammar. Bare JSON integers are "
                    "accepted only in JavaScript's safe range [-(2**53-1), "
                    "2**53-1]; larger numeric values must be strings."
                ),
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
        "search",
        "Search actor-visible Taut history without moving chat cursors, claiming notifications, or touching member activity. The call may reconcile disposable derived index state; reindex=true rebuilds it. Backend tokenization and ranking may differ.",
        {
            "workspace": _WORKSPACE,
            "query": {
                "description": (
                    "Required nonblank Unicode search query; core [SRCH-3] remains "
                    "authoritative for normalization, length, and token rules. Used "
                    "only by search; schema rejects an empty string and core rejects "
                    "queries with no alphanumeric chunk."
                ),
                "minLength": 1,
                "type": "string",
            },
            "channels": {
                "default": [],
                "description": (
                    "Optional array of channel names; default []; each element uses "
                    "the canonical channel pattern. Used only by search; duplicates "
                    "are accepted and collapse in core."
                ),
                "items": {"pattern": CHANNEL_PATTERN, "type": "string"},
                "type": "array",
            },
            "direct_messages": {
                "default": [],
                "description": (
                    "Optional array of @name-or-alias routes or stable dm.d_* "
                    "handles; default []; each element uses [SRCH-4.1]'s exact "
                    "chat-DM selector grammar. Used only by search; duplicates are "
                    "accepted and collapse in core."
                ),
                "items": {"pattern": DM_SELECTOR_PATTERN, "type": "string"},
                "type": "array",
            },
            "all_direct_messages": {
                "default": False,
                "description": (
                    "Optional boolean selecting every actor-accessible DM. Used only "
                    "by search; defaults to false and may coexist with explicit DM "
                    "selectors."
                ),
                "type": "boolean",
            },
            "from_member": _nullable_string(
                "Optional current member name or alias used as an author filter. Used "
                "only by search; null means no author filter.",
                pattern=MEMBER_NAME_PATTERN,
            ),
            "kinds": {
                "default": [],
                "description": (
                    "Optional array of message kinds drawn from message, notice, and "
                    "foreign. Used only by search; defaults to []; duplicates are "
                    "accepted and collapse in core."
                ),
                "items": {
                    "enum": ["message", "notice", "foreign"],
                    "type": "string",
                },
                "type": "array",
            },
            "before": _nullable_message_id(
                "Optional exclusive upper message-id bound as a canonical 19-digit "
                "decimal string. Used only by search; null means no upper bound and "
                "numeric JSON values are invalid."
            ),
            "limit": _LIMIT_50,
            "reindex": {
                "default": False,
                "description": (
                    "Whether to rebuild disposable search index state before "
                    "querying. Used only by search; defaults to false."
                ),
                "type": "boolean",
            },
        },
        ("workspace", "query"),
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
            read_only=True,
            destructive=False,
            idempotent=True,
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
            "channel": _CHANNEL_PROPERTY,
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
            "channel": _CHANNEL_PROPERTY,
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
                    "Current channel topic as a string of at most 500 Unicode code "
                    "points with no CR or LF, or null to clear it. Core rejects "
                    "blank/Cf-only strings. Required by channel_topic; the string "
                    'branch uses maxLength: 500 and not: { "pattern": "[\\r\\n]" }.'
                ),
            },
        },
        ("workspace", "channel", "topic"),
        _annotations(
            read_only=False,
            destructive=False,
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
            destructive=False,
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
            read_only=True,
            destructive=False,
            idempotent=True,
            open_world=True,
        ),
    ),
    ToolDefinition(
        "whoami",
        "Return the member bound to this workspace attachment. Resolving the existing member updates its activity timestamp; it does not change the member anchor, token fingerprint, or computed presence.",
        {"workspace": _WORKSPACE},
        ("workspace",),
        _annotations(
            read_only=True,
            destructive=False,
            idempotent=True,
            open_world=True,
        ),
    ),
)

TOOLS = tuple(definition.to_mcp() for definition in TOOL_DEFINITIONS)
TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


class ToolValidationError(ValueError):
    """A known tool call does not match its advertised input schema."""


_TOOL_VALIDATORS: dict[str, Draft202012Validator] = {}
for _tool in TOOLS:
    Draft202012Validator.check_schema(_tool.input_schema)
    _TOOL_VALIDATORS[_tool.name] = Draft202012Validator(_tool.input_schema)


def validate_tool_call(
    name: str,
    arguments: dict[str, object] | None,
) -> dict[str, object]:
    """Validate one known tool call without coercion or diagnostic leakage."""

    try:
        validator = _TOOL_VALIDATORS[name]
    except KeyError:
        raise KeyError(name) from None
    normalized: object = {} if arguments is None else arguments
    if not isinstance(normalized, dict) or not all(
        isinstance(key, str) for key in normalized
    ):
        raise ToolValidationError from None
    if next(validator.iter_errors(normalized), None) is not None:
        raise ToolValidationError from None
    return normalized
