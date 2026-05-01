"""Configurable VIGOR agent: registry, router, multi-adapter orchestration."""

from vigor_agent.agent import AgentOrchestrator
from vigor_agent.config_loader import load_agent_config
from vigor_agent.factory import FactoryLoadError, load_factory
from vigor_agent.plugin_discovery import (
    DiscoveredPlugin,
    PluginDiscoveryError,
    adapter_spec_from_plugin,
    load_plugin_directory,
)
from vigor_agent.registry import AdapterRegistry
from vigor_agent.router import Router, RoutingError

__all__ = [
    "AdapterRegistry",
    "AgentOrchestrator",
    "DiscoveredPlugin",
    "FactoryLoadError",
    "PluginDiscoveryError",
    "Router",
    "RoutingError",
    "adapter_spec_from_plugin",
    "load_agent_config",
    "load_factory",
    "load_plugin_directory",
]

__version__ = "0.1.0"
