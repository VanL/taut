"""Lightweight installed server identity shared by launch adapters."""

from importlib.metadata import version

SERVER_NAME = "taut_mcp"
SERVER_VERSION = version("taut-mcp")

__all__ = ["SERVER_NAME", "SERVER_VERSION"]
