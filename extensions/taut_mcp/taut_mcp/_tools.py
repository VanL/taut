"""The explicit, versioned Taut MCP tool manifest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from mcp import types

from ._results import DOMAIN_TOOL_NAMES, MESSAGE_ID_PATTERN
from .cli import McpLaunchDefaults

CHANNEL_PATTERN = r"^#?[a-z0-9][a-z0-9_-]{0,63}$"
CHAT_PATTERN = r"^#?[a-z0-9][a-z0-9_-]{0,63}(?:\.[0-9]{19})?$"
CHAT_OR_DM_PATTERN = (
    r"^(?:#?[a-z0-9][a-z0-9_-]{0,63}(?:\.[0-9]{19})?"
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

    def to_mcp(self, defaults: McpLaunchDefaults | None = None) -> types.Tool:
        effective = McpLaunchDefaults() if defaults is None else defaults
        token_schema = (
            _optional_nullable_string(TOKEN_DESCRIPTION)
            if effective.has_identity_default
            else _TOKEN
        )
        properties: dict[str, dict[str, Any]] = {}
        for name, property_schema in self.properties.items():
            if name == "workspace" and effective.workspace is not None:
                properties[name] = _optional_nullable_string(
                    str(property_schema["description"])
                )
            elif name == "token":
                properties[name] = token_schema
            else:
                properties[name] = property_schema
            if name == "workspace" and self.name in DOMAIN_TOOL_NAMES:
                properties["token"] = token_schema
        required = list(self.required)
        if self.name in DOMAIN_TOOL_NAMES:
            required.insert(required.index("workspace") + 1, "token")
        if effective.workspace is not None:
            required = [item for item in required if item != "workspace"]
        if effective.has_identity_default:
            required = [item for item in required if item != "token"]
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


def _optional_nullable_string(description: str) -> dict[str, Any]:
    return {"description": description, "type": ["string", "null"]}


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
        "List ordinary joined/unread threads, every registered thread, or every valid actor-accessible DM. `all` and `dms` are mutually exclusive. The operation does not update member activity or heal identity claims.",
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
        "List Taut members or members of one thread without updating member activity or healing identity claims.",
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
        "Return the member bound to this workspace attachment without updating member activity or healing identity claims.",
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


@dataclass(frozen=True, slots=True)
class _CompiledPropertyValidator:
    name: str
    validator: Draft202012Validator
    item_validator: Draft202012Validator | None = None


@dataclass(frozen=True, slots=True)
class _CompiledToolValidator:
    validator: Draft202012Validator
    required: tuple[str, ...]
    property_names: frozenset[str]
    properties: tuple[_CompiledPropertyValidator, ...]


_VALIDATOR_CACHE: dict[tuple[bool, bool], dict[str, _CompiledToolValidator]] = {}


def build_tools(defaults: McpLaunchDefaults | None = None) -> tuple[types.Tool, ...]:
    """Return the advertised 21-tool manifest for the given launch defaults."""

    if defaults is None or not defaults.has_any_default:
        return TOOLS
    return tuple(definition.to_mcp(defaults) for definition in TOOL_DEFINITIONS)


def _compile_tool_validator(tool: types.Tool) -> _CompiledToolValidator:
    schema = tool.input_schema
    Draft202012Validator.check_schema(schema)
    raw_props: dict[str, dict[str, Any]] = schema.get("properties", {})
    compiled_props: list[_CompiledPropertyValidator] = []
    for prop_name, prop_schema in raw_props.items():
        item_schema = prop_schema.get("items")
        item_val = (
            Draft202012Validator(item_schema) if isinstance(item_schema, dict) else None
        )
        compiled_props.append(
            _CompiledPropertyValidator(
                name=prop_name,
                validator=Draft202012Validator(prop_schema),
                item_validator=item_val,
            )
        )
    return _CompiledToolValidator(
        validator=Draft202012Validator(schema),
        required=tuple(schema.get("required", ())),
        property_names=frozenset(raw_props),
        properties=tuple(compiled_props),
    )


def _validators_for_defaults(
    defaults: McpLaunchDefaults | None,
) -> dict[str, _CompiledToolValidator]:
    effective = McpLaunchDefaults() if defaults is None else defaults
    cache_key = (effective.workspace is not None, effective.has_identity_default)
    cached = _VALIDATOR_CACHE.get(cache_key)
    if cached is not None:
        return cached
    built = {
        tool.name: _compile_tool_validator(tool) for tool in build_tools(effective)
    }
    _VALIDATOR_CACHE[cache_key] = built
    return built


_TOOL_VALIDATORS = _validators_for_defaults(None)


def _check_array_items(
    prop_name: str,
    item_validator: Draft202012Validator,
    items: list[object],
) -> None:
    for index, item in enumerate(items):
        if next(item_validator.iter_errors(item), None) is not None:
            raise ToolValidationError(
                f"invalid tool arguments: invalid field '{prop_name}[{index}]'; "
                "inspect the tool schema and retry"
            )


def _check_compiled_properties(
    properties: tuple[_CompiledPropertyValidator, ...],
    normalized: dict[str, object],
) -> None:
    for prop in properties:
        if prop.name not in normalized:
            continue
        value = normalized[prop.name]
        if prop.item_validator is not None and isinstance(value, list):
            _check_array_items(prop.name, prop.item_validator, value)
            continue
        if next(prop.validator.iter_errors(value), None) is not None:
            raise ToolValidationError(
                f"invalid tool arguments: invalid field '{prop.name}'; "
                "inspect the tool schema and retry"
            )


def _raise_for_schema_mismatch(
    name: str,
    compiled: _CompiledToolValidator,
    normalized: dict[str, object],
) -> None:
    for req in compiled.required:
        if req not in normalized:
            raise ToolValidationError(
                f"invalid tool arguments: missing required field '{req}'; "
                "inspect the tool schema and retry"
            )
    if any(key not in compiled.property_names for key in normalized):
        raise ToolValidationError(
            "invalid tool arguments (unexpected property); "
            "inspect the tool schema and retry"
        )
    _check_compiled_properties(compiled.properties, normalized)
    if (
        name == "list"
        and normalized.get("all") is True
        and normalized.get("dms") is True
    ):
        raise ToolValidationError(
            "invalid tool arguments: conflicting fields 'all' and 'dms'; "
            "inspect the tool schema and retry"
        )
    if next(compiled.validator.iter_errors(normalized), None) is not None:
        raise ToolValidationError(
            "invalid tool arguments; inspect the tool schema and retry"
        )


def validate_tool_call(
    name: str,
    arguments: dict[str, object] | None,
    *,
    defaults: McpLaunchDefaults | None = None,
) -> dict[str, object]:
    """Validate one known tool call without coercion or diagnostic leakage."""

    validators = _validators_for_defaults(defaults)
    try:
        compiled = validators[name]
    except KeyError:
        raise KeyError(name) from None
    normalized: object = {} if arguments is None else arguments
    if not isinstance(normalized, dict) or not all(
        isinstance(key, str) for key in normalized
    ):
        raise ToolValidationError(
            "invalid tool arguments (expected JSON object); "
            "inspect the tool schema and retry"
        )
    _raise_for_schema_mismatch(name, compiled, normalized)
    return normalized
