"""The init module: create a game's repository from web-game-template.

    game-design + tech-plan -> project metadata -> repository from the template (gh, or a
                local template checkout) -> local project -> game.config.yaml from the plan,
                committed locally -> scaffold-record

Registered from workspace/config/factory.yaml (`factory.steps.modules: [wgf_init]`) and
configured by `factory.init` there. See docs/init-module.md.
"""

from .gameconfig import GameConfigError, apply_game_config, bootstrap_identity
from .infrastructure import TEMPLATE_INFRASTRUCTURE, missing_infrastructure, read_game_config
from .profiles import ProfileError, vendor_profiles
from .project import DesignError, ProjectMetadata
from .step import InitSettings, InitStep, SettingsError
from .tooling import GhCli, GitCli, Git, GitHub, Repository, ToolError

__all__ = [
    "DesignError",
    "GameConfigError",
    "ProfileError",
    "apply_game_config",
    "bootstrap_identity",
    "vendor_profiles",
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
