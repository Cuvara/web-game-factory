"""The init module: create a game's repository from web-game-template.

    game-design -> project metadata -> gh repository from the template -> local project
                -> scaffold-record

Registered from workspace/config/factory.yaml (`factory.steps.modules: [wgf_init]`) and
configured by `factory.init` there. See docs/init-module.md.
"""

from .infrastructure import TEMPLATE_INFRASTRUCTURE, missing_infrastructure, read_game_config
from .project import DesignError, ProjectMetadata
from .step import InitSettings, InitStep, SettingsError
from .tooling import GhCli, GitCli, Git, GitHub, Repository, ToolError

__all__ = [
    "DesignError",
    "GhCli",
    "Git",
    "GitCli",
    "GitHub",
    "InitSettings",
    "InitStep",
    "ProjectMetadata",
    "Repository",
    "SettingsError",
    "TEMPLATE_INFRASTRUCTURE",
    "ToolError",
    "missing_infrastructure",
    "read_game_config",
    "register",
]


def register(registry):
    registry.register(InitStep.type, InitStep)
