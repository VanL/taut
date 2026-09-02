"""Test-side oracle for the fixed Taut MCP result envelope and record shapes.

The manifest carries input schemas only; these schemas pin the shape of
``structuredContent`` returned by every tool and are used to validate real
results in the suite.
"""

from __future__ import annotations

from typing import Any

from taut_mcp._tools import MESSAGE_ID_PATTERN, RECORD_TYPE_BY_TOOL


def _nullable(kind: str) -> dict[str, Any]:
    return {"anyOf": [{"type": kind}, {"type": "null"}]}


def _message_id(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "pattern": MESSAGE_ID_PATTERN,
        "type": "string",
    }


def _nullable_message_id(description: str) -> dict[str, Any]:
    return {
        "anyOf": [
            {"pattern": MESSAGE_ID_PATTERN, "type": "string"},
            {"type": "null"},
        ],
        "description": description,
    }


RECORD_SCHEMAS: dict[str, dict[str, Any]] = {
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
                "description": "Process-local workspace lifecycle status.",
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
            "ts": _message_id("Taut message timestamp/id."),
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
            "ts": _message_id("Deleted Taut message timestamp/id."),
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
            "message_ts": _message_id("Reacted-to Taut message timestamp/id."),
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
            "message_ts": _nullable_message_id(
                "Related message timestamp/id when available."
            ),
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
            "last_active_ts": _message_id(
                "Most recent recorded member activity timestamp."
            ),
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
            "topic_updated_ts": _nullable_message_id(
                "Topic update timestamp/id, or null."
            ),
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
        "last_ts": _nullable_message_id("Latest message timestamp/id when one exists."),
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


RECORD_SCHEMAS["thread"] = {
    "oneOf": [
        _thread_branch("channel", topic=True),
        _thread_branch("dm", members=True),
        _thread_branch("subthread"),
    ]
}


def _search_hit_branch(thread_kind: str) -> dict[str, Any]:
    channel: dict[str, Any]
    parent: dict[str, Any]
    members: dict[str, Any]
    if thread_kind == "channel":
        channel = {
            "description": "Top-level channel containing the hit.",
            "type": "string",
        }
        parent = {
            "description": "Top-level channel name for sub-thread hits only.",
            "type": "null",
        }
        members = {
            "description": "Sorted stable member-id pair for direct-message hits only.",
            "type": "null",
        }
    elif thread_kind == "subthread":
        channel = {
            "description": "Top-level channel containing the hit.",
            "type": "string",
        }
        parent = {
            "description": "Top-level channel name containing the sub-thread hit.",
            "type": "string",
        }
        members = {
            "description": "Sorted stable member-id pair for direct-message hits only.",
            "type": "null",
        }
    else:
        channel = {
            "description": "Top-level channel containing channel or sub-thread hits only.",
            "type": "null",
        }
        parent = {
            "description": "Top-level channel name for sub-thread hits only.",
            "type": "null",
        }
        members = {
            "description": "Sorted stable member-id pair for this direct-message hit.",
            "items": {"type": "string"},
            "maxItems": 2,
            "minItems": 2,
            "type": "array",
        }
    properties: dict[str, Any] = {
        "thread": {
            "description": "Canonical Taut thread containing the hit.",
            "type": "string",
        },
        "ts": _message_id("Taut message timestamp/id."),
        "from_id": {
            "description": "Immutable author member id when available.",
            **_nullable("string"),
        },
        "from": {"description": "Write-time author display name.", "type": "string"},
        "kind": {
            "description": "Taut message kind.",
            "enum": ["message", "notice", "foreign"],
            "type": "string",
        },
        "text": {"description": "Exact hydrated message body.", "type": "string"},
        "thread_kind": {
            "const": thread_kind,
            "description": "Taut thread facet for this hit.",
            "type": "string",
        },
        "channel": channel,
        "parent": parent,
        "members": members,
    }
    return {
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
        "type": "object",
    }


RECORD_SCHEMAS["search_hit"] = {
    "oneOf": [
        _search_hit_branch("channel"),
        _search_hit_branch("subthread"),
        _search_hit_branch("dm"),
    ]
}


def result_schema(record_type: str) -> dict[str, Any]:
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
                "items": RECORD_SCHEMAS[record_type],
                "type": "array",
            },
            "warnings": {
                "description": "Content-free operational warnings.",
                "items": {"type": "string"},
                "type": "array",
            },
            "workspace": {
                "description": "Canonical selected workspace, or null for process-wide results.",
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


def result_schema_for_tool(tool_name: str) -> dict[str, Any]:
    return result_schema(RECORD_TYPE_BY_TOOL[tool_name])
