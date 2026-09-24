"""The explicit, versioned Taut MCP tool manifest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from mcp import types

from ._results import DOMAIN_TOOL_NAMES, MESSAGE_ID_PATTERN

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
MAX_SAFE_JSON_INTEGER = (1 << 53) - 1

ATTACH_WORKSPACE_DESCRIPTION = "Absolute local directory of an existing Taut project; the result carries its canonical identifier."
WORKSPACE_DESCRIPTION = "Canonical workspace identifier, or the absolute local directory of an existing Taut project."
DETACH_WORKSPACE_DESCRIPTION = (
    "Canonical workspace identifier from attach_workspace or list_workspaces."
)
TOKEN_DESCRIPTION = "Existing Taut continuity token for this workspace; never returned and never invented."
CHANNEL_DESCRIPTION = "Top-level Taut channel name."
CHANNEL_PROPERTY_DESCRIPTION = "Top-level Taut channel name."
CHAT_DESCRIPTION = "Taut channel, or a `<channel>.<19-digit-message-id>` subthread."
CHAT_OR_DM_DESCRIPTION = (
    "Channel, subthread, `@name-or-alias` DM, or stable `dm.d_*` handle."
)
READ_THREAD_DESCRIPTION = "Optional channel, subthread, `@name-or-alias` DM, or stable `dm.d_*` handle; omit for every joined thread."

EXACT_MESSAGE_ID_DESCRIPTION = "Exact 19-digit Taut message id, as a string."
REACTION_DESCRIPTION = "Configured reaction slug."


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
    "description": "Maximum records per selected thread, 1 through 1000; default 100.",
    "maximum": 1000,
    "minimum": 1,
    "type": "integer",
}
_LIMIT_1000 = {
    "default": 1000,
    "description": "Maximum notifications, 1 through 1000; default 1000.",
    "maximum": 1000,
    "minimum": 1,
    "type": "integer",
}
_LIMIT_50 = {
    "default": 50,
    "description": "Maximum hits, 1 through 1000; default 50.",
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
                "Optional persona text for this member; null leaves it unchanged."
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
                "New display name for this member.",
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
        "Post a new Taut message to a channel, sub-thread, person-addressed direct message, or an existing direct-message conversation. `@name-or-alias` may create a DM; exact `dm.d_*` requires an existing actor-accessible conversation and never creates or heals one.",
        {
            "workspace": _WORKSPACE,
            "target": _string(
                "Channel, subthread, `@name-or-alias` DM (may create one), or stable `dm.d_*` handle (existing conversation only)."
            ),
            "text": _string("Nonblank message text."),
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
                "Exact 19-digit parent message id; the schema rejects any other shape, as for `message_show`.",
                pattern=MESSAGE_ID_PATTERN,
            ),
            "text": _string("Nonblank message text."),
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
        "Physically and irreversibly delete one exact ordinary message authored by this member, including after leaving its thread. It does not cascade to notifications, sub-threads, memberships, cursors, or thread registry state and is not recall. An empty result means no matching deletable own message was found; verify the full 19-digit message id and current author identity before retrying.",
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
        "Send one configured reaction to the current audience of an exact ordinary message, excluding this member. Validates against the workspace's attachment-time reaction vocabulary, advances this member's high-water cursor through the target, then attempts one atomic best-effort notification broadcast to every requested inbox. Repeating may deliver duplicates. An empty result means no reactable message with a current recipient was found; verify the full 19-digit message id, current membership, and that another current thread member exists before retrying.",
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
        "Return oldest unread messages and advance each selected cursor through its returned page. `thread` may select a channel, subthread, `@name-or-alias` DM, or stable `dm.d_*` conversation. Omit it for all joined chat threads. Cursors advance only through the returned records and no message history is deleted; use log for cursor-neutral rereads, and after an uncertain read inspect list before retrying.",
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
                    "Exclusive lower bound: ISO 8601, Unix time, or 19-digit message id; null for none."
                ),
            },
            "limit": {
                **_LIMIT_100,
                "description": "Maximum most-recent messages, 1 through 1000; default 100.",
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
        "Search actor-visible Taut history without moving chat cursors, claiming notifications, or touching member activity. The call may reconcile disposable derived index state; `reindex=true` rebuilds it. Backend tokenization and ranking may differ.",
        {
            "workspace": _WORKSPACE,
            "query": {
                "description": ("Nonblank search text."),
                "minLength": 1,
                "type": "string",
            },
            "channels": {
                "default": [],
                "description": (
                    "Channel names to search; empty means every registered channel."
                ),
                "items": {"pattern": CHANNEL_PATTERN, "type": "string"},
                "type": "array",
            },
            "direct_messages": {
                "default": [],
                "description": (
                    "`@name-or-alias` or stable `dm.d_*` DM selectors to search."
                ),
                "items": {"pattern": DM_SELECTOR_PATTERN, "type": "string"},
                "type": "array",
            },
            "all_direct_messages": {
                "default": False,
                "description": ("Search every accessible DM."),
                "type": "boolean",
            },
            "from_member": _nullable_string(
                "Author name or alias filter; null for none.",
                pattern=MEMBER_NAME_PATTERN,
            ),
            "kinds": {
                "default": [],
                "description": ("Message kinds to include; empty means all."),
                "items": {
                    "enum": ["message", "notice", "foreign"],
                    "type": "string",
                },
                "type": "array",
            },
            "before": _nullable_message_id(
                "Exclusive upper 19-digit message-id bound; null for none."
            ),
            "limit": _LIMIT_50,
            "reindex": {
                "default": False,
                "description": ("Rebuild the search index before querying."),
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
                "description": "List every registered thread; exclusive with dms.",
                "type": "boolean",
            },
            "dms": {
                "default": False,
                "description": "List every accessible DM; exclusive with all.",
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
                    "Channel topic of at most 500 characters with no line breaks, or null to clear it."
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
