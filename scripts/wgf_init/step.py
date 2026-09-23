"""The `init` step: game-design -> project metadata -> repository from the template ->
local project -> scaffold-record.

The one step in the new-game workflow with an outside side effect that must not happen
twice. Its idempotency rests on a marker written into the repository's own description when
it is created, `wgf-init:<run_id>:<step_id>`: once per run, not once per visit, so a retry,
a crash, a resume or a `--from init` re-entry finds the repository it made and records
`reused` instead of creating another. The marker lives on the repository rather than in
run state because the crash that matters is the one between `gh repo create` returning and
the engine persisting the result.

What it does not do, on purpose:

- write game.config.yaml. That file comes from `tech_plan.repo_params`, reviewed at G3, and
  the tech plan is not an input of this step. The template's bootstrap workflow sets the
  game's identity from the repository name; the platform list stays at the template default
  until the plan writes it. Deriving it from the design here would be the "writing
  game.config.yaml by hand" failure mode, and pushing to a repository whose bootstrap
  workflow is about to push to it too would race it.
- recreate anything the template ships: CI, SDKs, build and test configuration. It checks
  they arrived (infrastructure.py) and refuses the project if they did not.
- adopt a repository or a directory it did not make, unless the installation says so.
"""

import datetime
import os
import time

from wgflib import paths
from wgflib.hashing import content_hash
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep

from .infrastructure import (
    GAME_CONFIG,
    InfrastructureError,
    missing_infrastructure,
    read_game_config,
)
from .project import REPO_NAME, DesignError, ProjectMetadata
from .tooling import GhCli, GitCli, ToolError

__all__ = ["InitStep", "InitSettings", "SettingsError", "SCHEMA_VERSION"]

SCHEMA_VERSION = "1.0.0"
ROLE = "release"  # core/roles/roles.yaml: release owns title:scaffolding
VISIBILITIES = ("private", "internal", "public")


class SettingsError(ValueError):
    """factory.init in workspace/config/factory.yaml is missing or wrong."""


class InitSettings:
    """`factory.init` in workspace/config/factory.yaml."""

    def __init__(self, owner, template, visibility="private", projects_dir="..",
                 adopt_existing=False, populate_timeout_seconds=60):
        self.owner = owner
        self.template = template
        self.visibility = visibility
        self.projects_dir = projects_dir
        self.adopt_existing = adopt_existing
        self.populate_timeout_seconds = populate_timeout_seconds

    @classmethod
    def from_config(cls, config):
        section = (config or {}).get("init") or {}
        owner = section.get("owner")
        template = section.get("template")
        if not isinstance(owner, str) or not REPO_NAME.match(owner or ""):
            raise SettingsError("set factory.init.owner: the account or organization that "
                                "will own game repositories")
        if not isinstance(template, str) or template.count("/") != 1:
            raise SettingsError("set factory.init.template to the template repository as "
                                "owner/name, e.g. my-org/web-game-template")
        visibility = section.get("visibility", "private")
        if visibility not in VISIBILITIES:
            raise SettingsError(f"factory.init.visibility {visibility!r} is not one of "
                                f"{', '.join(VISIBILITIES)}")
        adopt = section.get("adopt_existing", False)
        if not isinstance(adopt, bool):
            raise SettingsError("factory.init.adopt_existing must be true or false")
        timeout = section.get("populate_timeout_seconds", 60)
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout < 0:
            raise SettingsError("factory.init.populate_timeout_seconds must be a number >= 0")
        return cls(owner, template, visibility, section.get("projects_dir", ".."), adopt,
                   timeout)

    def local_path(self, repo_name):
        base = self.projects_dir
        if not os.path.isabs(base):
            base = os.path.join(paths.ROOT, base)
        return os.path.normpath(os.path.join(base, repo_name))


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Refused(Exception):
    """Ends the execution with a prepared StepResult."""

    def __init__(self, result):
        super().__init__(result.error)
        self.result = result


class InitStep(WorkflowStep):
    type = "init"

    def __init__(self, definition, github=None, git=None, clock=_utc_now, sleep=time.sleep):
        super().__init__(definition)
        self.github = github or GhCli()
        self.git = git or GitCli()
        self.clock = clock
        self.sleep = sleep

    def execute(self, inputs, context):
        if "game-design" in inputs.missing:
            return StepResult.waiting_for_input("init needs a game-design; run design first")
        design = inputs.load("game-design")
        try:
            project = ProjectMetadata.from_design(design, project_id=context.project_id)
        except DesignError as exc:
            return StepResult.failed(str(exc), retryable=False)
        try:
            settings = InitSettings.from_config(context.config)
        except SettingsError as exc:
            return StepResult.blocked(str(exc))

        try:
            repository, outcome, template_sha = self._repository(project, settings, context)
            local = self._local_project(repository, settings, context)
            game_config = self._verify(local)
        except _Refused as refused:
            return refused.result
        except ToolError as exc:
            return StepResult.failed(str(exc), retryable=exc.retryable)

        record = self._record(project, settings, repository, outcome, template_sha,
                              game_config, local, inputs, context)
        context.logger.info("scaffolded", repository=repository.full_name, outcome=outcome,
                            local_path=local)
        return StepResult.success(
            [ArtifactOutput("scaffold-record", record,
                            metadata={"repository": repository.full_name,
                                      "local_path": local, "outcome": outcome})],
            message=f"{repository.full_name} {outcome}",
        )

    # -- the remote repository ----------------------------------------------------------

    def marker(self, context):
        return f"wgf-init:{context.run_id}:{self.id}"

    def _made_by_this_run(self, repository, context):
        if self.marker(context) in repository.description:
            return True
        return any((ref.metadata or {}).get("repository") == repository.full_name
                   for ref in context.previous_outputs or [] if ref.type == "scaffold-record")

    def _repository(self, project, settings, context):
        full_name = f"{settings.owner}/{project.repo_name}"
        existing = self.github.view(full_name)

        if existing is None:
            template_sha = self.github.head_sha(settings.template)
            context.logger.info("creating repository", repository=full_name,
                                template=settings.template, template_sha=template_sha)
            repository = self.github.create_from_template(
                full_name, settings.template, settings.visibility,
                project.description(self.marker(context)))
            outcome = "created"
        else:
            if not self._made_by_this_run(existing, context) and not settings.adopt_existing:
                raise _Refused(StepResult.blocked(
                    f"{full_name} already exists and was not created by this run. Init "
                    "never takes over a repository on its own: resume the run that created "
                    "it, pick another title id, or set factory.init.adopt_existing: true to "
                    "authorize reusing it."))
            repository, outcome, template_sha = existing, "reused", None

        # Adopting is authorized; adopting something that is not the template's output is
        # not, because then nothing downstream can assume the template's infrastructure.
        if (repository.template or "").lower() != settings.template.lower():
            raise _Refused(StepResult.failed(
                f"{full_name} was generated from {repository.template or 'no template'}, "
                f"not {settings.template}. A game repository must originate from the "
                "template.", retryable=False))

        if not self.github.wait_for_file(full_name, GAME_CONFIG,
                                         settings.populate_timeout_seconds, sleep=self.sleep):
            # GitHub fills a generated repository asynchronously. Transient by nature.
            raise ToolError(f"{full_name} has no {GAME_CONFIG} yet: GitHub is still "
                            "generating it from the template")
        return repository, outcome, template_sha

    # -- the local project --------------------------------------------------------------

    def _local_project(self, repository, settings, context):
        local = settings.local_path(repository.name)
        if not os.path.exists(local) or (os.path.isdir(local) and not os.listdir(local)):
            context.logger.info("cloning", repository=repository.full_name, local_path=local)
            os.makedirs(os.path.dirname(local), exist_ok=True)
            self.github.clone(repository.full_name, local)
            return local

        # Something is already there. Reusing a clone of this same repository changes
        # nothing in it; anything else would mean overwriting a directory we did not make.
        origin = self.git.origin(local) if os.path.isdir(local) else None
        if (origin or "").lower() != repository.full_name.lower():
            raise _Refused(StepResult.blocked(
                f"{local} already exists and is not a clone of {repository.full_name} "
                f"(origin: {origin or 'none'}). Init never overwrites a directory: move it, "
                "or set factory.init.projects_dir elsewhere."))
        if not self.git.has_commits(local):
            # Cloned by an earlier attempt before GitHub had finished generating it.
            self.git.pull(local, repository.default_branch or "main")
        context.logger.info("reusing local project", local_path=local)
        return local

    def _verify(self, local):
        missing = missing_infrastructure(local)
        if missing:
            raise _Refused(StepResult.failed(
                f"{local} lacks template infrastructure: {', '.join(missing)}. This is a "
                "template problem; fix the template, never the game.", retryable=False))
        try:
            return read_game_config(local)
        except InfrastructureError as exc:
            raise _Refused(StepResult.failed(str(exc), retryable=False))

    # -- the artifact -------------------------------------------------------------------

    def _record(self, project, settings, repository, outcome, template_sha, game_config,
                local, inputs, context):
        produced_at = self.clock()
        pinned = []
        ref = inputs.refs["game-design"]
        design = inputs.load("game-design")
        if ref.content_hash and (design.get("provenance") or {}).get("artifact_id"):
            pinned.append({"artifact_id": design["provenance"]["artifact_id"],
                           "artifact_type": "game-design",
                           "content_hash": ref.content_hash})

        repo = {"owner": repository.owner, "name": repository.name}
        if repository.url:
            repo["url"] = repository.url
        if repository.default_branch:
            repo["default_branch"] = repository.default_branch
        if repository.visibility in VISIBILITIES:
            repo["visibility"] = repository.visibility
        template = {"repository": settings.template}
        if template_sha:
            template["commit_sha"] = template_sha

        targets = ", ".join(project.design_platforms) or "none named"
        notes = (
            f"Local project: {paths.display(local)}. {GAME_CONFIG} is as the template "
            "generated it: its platform list is written from tech_plan.repo_params, which "
            f"is not an input of init. Platforms the design targets: {targets}."
        )

        record = {
            "provenance": {
                "artifact_id": f"wgf:scaffold-record:{project.title_id}:"
                               f"{produced_at[:10].replace('-', '')}-"
                               f"{min(context.execution, 99):02d}",
                "artifact_type": "scaffold-record",
                "schema_version": SCHEMA_VERSION,
                "title_id": project.title_id,
                "produced_by": {"role": ROLE, "actor": "automation"},
                "produced_at": produced_at,
                "inputs": pinned,
                "content_hash": "",
                "status": "draft",
            },
            "title_id": project.title_id,
            "repository": repo,
            "template": template,
            "game_config": game_config,
            "outcome": outcome,
            "idempotency_key": self.marker(context),
            "notes": notes,
        }
        record["provenance"]["content_hash"] = content_hash(record)
        return record
