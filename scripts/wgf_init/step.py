"""The `init` step: game-design + tech-plan -> project metadata -> repository from the
template -> local project -> game.config.yaml from the plan -> scaffold-record.

The one step in the new-game workflow with an outside side effect that must not happen
twice. Its idempotency rests on a marker, `wgf-init:<run_id>:<step_id>`: once per run, not
once per visit, so a retry, a crash, a resume or a `--from init` re-entry finds the project
it made and records `reused` instead of creating another. The marker lives with the project
rather than in run state because the crash that matters is the one between creating it and
the engine persisting the result:

    source github   in the repository description, written at `gh repo create`
    source local    in the project's own git config (`wgf.init-marker`) and the trailer of
                    its initial commit

Configuration. When the run holds a tech-plan, init writes its `repo_params.game_config`
into game.config.yaml - engine, platforms, monetization - vendors the pinned profiles into
config/platforms/, and makes one LOCAL commit carrying the marker as a trailer. It never
pushes: pushing is outward-facing, and on GitHub the template's bootstrap workflow is pushing
to the same fresh repository (docs/init-module.md, "The bootstrap race"). A re-run finds the
file already matching the plan and records the commit it made before.

Identity. game.id and game.name are set from the repository name with exactly the
derivation web-game-template's bootstrap.yml uses (gameconfig.bootstrap_identity), for
either source. On GitHub bootstrap.yml writes the same lines in its own remote commit, so
the two changes are identical and a later `pull --rebase` drops one; if bootstrap never runs
- it cannot, without the organization's bot credentials - the project still has its own
identity instead of the template's placeholder.

What it does not do, on purpose:

- recreate anything the template ships: CI, SDKs, build and test configuration. It checks
  they arrived (infrastructure.py) and refuses the project if they did not.
- adopt a repository or a directory it did not make, unless the installation says so.
"""

import datetime
import os
import time

from wgflib import paths
from wgflib import template as template_pin
from wgflib.hashing import content_hash
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep

from .gameconfig import GameConfigError, apply_game_config, bootstrap_identity
from .infrastructure import (
    GAME_CONFIG,
    InfrastructureError,
    missing_infrastructure,
    read_game_config,
)
from .profiles import ProfileError, vendor_profiles
from .project import REPO_NAME, DesignError, ProjectMetadata
from .tooling import (KEY_TRAILER, PLAN_TRAILER, TEMPLATE_TRAILER, GhCli, GitCli, Repository,
                      ToolError)

__all__ = ["InitStep", "InitSettings", "SettingsError", "SCHEMA_VERSION", "BOOTSTRAP"]

SCHEMA_VERSION = "1.1.0"
ROLE = "release"  # core/roles/roles.yaml: release owns title:scaffolding
VISIBILITIES = ("private", "internal", "public")
SOURCES = ("github", "local")
BOOTSTRAP = ".github/workflows/bootstrap.yml"
DEFAULT_AUTHOR = {"name": "wgf-init", "email": "wgf-init@users.noreply.invalid"}


class SettingsError(ValueError):
    """factory.init in workspace/config/factory.yaml is missing or wrong."""


class InitSettings:
    """`factory.init` in workspace/config/factory.yaml."""

    def __init__(self, owner, template, visibility="private", projects_dir="..",
                 adopt_existing=False, populate_timeout_seconds=60, source="github",
                 template_path=None, template_ref=None, commit_author=None):
        self.owner = owner
        self.template = template
        self.visibility = visibility
        self.projects_dir = projects_dir
        self.adopt_existing = adopt_existing
        self.populate_timeout_seconds = populate_timeout_seconds
        self.source = source
        self.template_path = template_path
        self.template_ref = template_ref
        self.commit_author = commit_author or dict(DEFAULT_AUTHOR)

    @classmethod
    def from_config(cls, config):
        section = (config or {}).get("init") or {}
        source = section.get("source", "github")
        if source not in SOURCES:
            raise SettingsError(f"factory.init.source {source!r} is not one of "
                                f"{', '.join(SOURCES)}")
        owner = section.get("owner")
        template = section.get("template")
        template_path = section.get("template_path")
        if source == "github":
            if (not isinstance(owner, str) or not REPO_NAME.fullmatch(owner)
                    or owner in (".", "..")):
                raise SettingsError("set factory.init.owner: the account or organization that "
                                    "will own game repositories")
            if not isinstance(template, str) or template.count("/") != 1:
                raise SettingsError("set factory.init.template to the template repository as "
                                    "owner/name, e.g. my-org/web-game-template")
        else:
            if template_path is not None and (not isinstance(template_path, str)
                                              or not template_path):
                raise SettingsError("factory.init.template_path must be a local git checkout "
                                    "of the template, or left out to use a checkout of the "
                                    "pinned revision")
            if owner is not None and (not isinstance(owner, str)
                                      or not REPO_NAME.fullmatch(owner)
                                      or owner in (".", "..")):
                raise SettingsError("factory.init.owner must be a plain name")
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
        ref = section.get("template_ref")
        if ref is not None and (not isinstance(ref, str) or not ref):
            raise SettingsError("factory.init.template_ref must be a git ref or commit")
        author = section.get("commit_author")
        if author is not None and not (isinstance(author, dict) and set(author) <= {"name", "email"}
                                       and all(isinstance(v, str) for v in author.values())):
            raise SettingsError("factory.init.commit_author takes name and email")
        return cls(owner, template, visibility, section.get("projects_dir", ".."), adopt,
                   timeout, source, template_path, ref, author)

    def local_path(self, repo_name):
        base = self.projects_dir
        if not os.path.isabs(base):
            base = os.path.join(paths.ROOT, base)
        return os.path.normpath(os.path.join(base, repo_name))

    def template_dir(self):
        """The local template checkout; None means "a checkout of the pinned revision"."""
        path = self.template_path
        if path is None:
            return None
        if not os.path.isabs(path):
            path = os.path.join(paths.ROOT, path)
        return os.path.normpath(path)


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Refused(Exception):
    """Ends the execution with a prepared StepResult."""

    def __init__(self, result):
        super().__init__(result.error)
        self.result = result


class InitStep(WorkflowStep):
    type = "init"
    profiles_dir = None  # seam for tests; a real run vendors from core/reference/platforms

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
        plan = None
        if "tech-plan" in inputs:
            plan = inputs.load("tech-plan")
            problem = self._plan_problem(plan, project) or self._plan_template_problem(plan)
            if problem:
                return StepResult.failed(problem, retryable=False)
        else:
            context.logger.warning("no tech-plan in the run: game.config.yaml stays as the "
                                   "template generated it")

        pin = None
        try:
            pinned, pinned_url = self._pin(settings)
            if settings.source == "local":
                repository, outcome, template_sha, local = self._local_source(
                    project, settings, pinned, context)
            else:
                repository, outcome, generated_sha = self._repository(project, settings,
                                                                      context)
                local = self._local_project(repository, settings, context)
                pin = self._pin_github_project(local, settings, pinned, pinned_url,
                                               generated_sha, context)
                template_sha = pinned
            self._verify(local)
            commit, committed = self._configure(local, plan, inputs, project, settings, context)
            game_config = self._read_config(local)
        except _Refused as refused:
            return refused.result
        except ToolError as exc:
            return StepResult.failed(str(exc), retryable=exc.retryable)

        if commit:
            game_config["commit_sha"] = commit
            game_config["pushed"] = False
        record = self._record(project, settings, repository, outcome, template_sha,
                              game_config, local, plan, commit, committed, inputs, context,
                              pin)
        metadata = {"repository": repository.full_name, "local_path": local,
                    "outcome": outcome, "source": settings.source,
                    "template_commit": template_sha}
        if game_config.get("engine"):
            metadata["engine"] = game_config["engine"]["type"]
        if commit:
            metadata["config_commit"] = commit
        context.logger.info("scaffolded", repository=repository.full_name, outcome=outcome,
                            local_path=local, source=settings.source, config_commit=commit)
        return StepResult.success(
            [ArtifactOutput("scaffold-record", record, metadata=metadata)],
            message=f"{repository.full_name} {outcome}"
                    + (f", game.config.yaml committed locally at {commit[:12]}" if committed
                       else ""),
        )

    # -- the plan -----------------------------------------------------------------------

    @staticmethod
    def _plan_problem(plan, project):
        if not isinstance(plan, dict):
            return "tech-plan is not a JSON object"
        if plan.get("title_id") != project.title_id:
            return (f"tech-plan is for {plan.get('title_id')!r} but the game-design is for "
                    f"{project.title_id!r}")
        game_config = (plan.get("repo_params") or {}).get("game_config")
        if not isinstance(game_config, dict):
            return "tech-plan has no repo_params.game_config to write"
        planned = (game_config.get("engine") or {}).get("type")
        selected = (plan.get("engine") or {}).get("type")
        if planned != selected:
            return (f"tech-plan selects engine {selected!r} but its game_config says "
                    f"{planned!r}; the plan contradicts itself")
        return None

    @staticmethod
    def _plan_template_problem(plan):
        """A plan approved at G3 against one template revision is not built from another."""
        named = (plan.get("repo_params") or {}).get("template_ref")
        try:
            lock = template_pin.load_lock()
            pinned = f"{lock['repository']}@{template_pin.expected_commit(lock)}"
        except template_pin.TemplateError:
            return None  # _pin reports the unusable lock
        if not isinstance(named, str) or named.lower() != pinned.lower():
            return (f"the tech plan was approved against template {named!r}, but the Factory "
                    f"is pinned to {pinned} ({paths.display(template_pin.LOCK)}). Plan again "
                    "against the pinned template.")
        return None

    def marker(self, context):
        return f"wgf-init:{context.run_id}:{self.id}"

    # -- the pinned template revision -------------------------------------------------------

    @staticmethod
    def _pin(settings):
        """(commit, url) of the web-game-template revision this Factory is pinned to
        (workspace/config/template.lock.json). Every project init makes holds exactly that
        tree; there is no "latest"."""
        try:
            lock = template_pin.load_lock()
            commit = template_pin.expected_commit(lock)
        except template_pin.TemplateError as exc:
            raise _Refused(StepResult.blocked(f"the Factory's template pin is unusable: {exc}"))
        if (settings.source == "github"
                and settings.template.lower() != lock["repository"].lower()):
            raise _Refused(StepResult.failed(
                f"factory.init.template is {settings.template}, but the Factory is pinned to "
                f"{lock['repository']}@{commit} ({paths.display(template_pin.LOCK)}). Init "
                "creates games only from the pinned template.", retryable=False))
        return commit, lock["url"]

    def _pin_github_project(self, local, settings, pinned, url, generated_sha, context):
        """Make the clone hold the pinned revision's tree.

        `gh repo create --template` copies the template's default branch as it is when the
        repository is generated. That is the pinned revision only by coincidence, so the
        difference is applied here as one local, keyed commit - or, when there is none,
        nothing is. Either way the project's tree is the pinned revision's, apart from what
        the template's own bootstrap commit changed on top of it."""
        marker = self.marker(context)
        trailer = f"{settings.template}@{pinned}"
        found = self.git.find_commit(local, {KEY_TRAILER: marker, TEMPLATE_TRAILER: trailer})
        if found:
            return {"action": "pinned", "commit": found, "generated_from": generated_sha}
        if self.git.dirty(local):
            # Only this run's own clone gets here (_local_project refused anything else): a
            # crash between applying the pin and committing it. Start the pin over.
            self.git.discard(local)
        message = (f"chore(init): pin web-game-template {pinned}\n\n"
                   f"GitHub generated this repository from {settings.template}'s default "
                   f"branch{f' at {generated_sha}' if generated_sha else ''}. The Factory is "
                   f"pinned to {pinned} ({paths.display(template_pin.LOCK)}); this commit is "
                   "the difference, so the project holds exactly the pinned template. Local "
                   "commit: init never pushes.\n\n"
                   f"{TEMPLATE_TRAILER}: {trailer}\n{KEY_TRAILER}: {marker}\n")
        result = self.git.pin_tree(local, url, pinned, message, author=settings.commit_author)
        context.logger.info("template revision", action=result["action"], pinned=pinned,
                            generated_from=generated_sha, commit=result.get("commit"))
        return dict(result, generated_from=generated_sha)

    # -- the remote repository (source: github) -----------------------------------------

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

    # -- the local project (source: local) ----------------------------------------------

    def _local_source(self, project, settings, pinned, context):
        """A project made from a local template checkout at the pinned revision: no remote,
        no network."""
        template = settings.template_dir()
        if template is None:
            try:
                template = template_pin.checkout(pinned)
            except template_pin.TemplateError as exc:
                raise _Refused(StepResult.blocked(
                    f"no factory.init.template_path, and the pinned web-game-template "
                    f"{pinned} cannot be checked out: {exc}"))
        shown = paths.display(template)
        if not os.path.isdir(template) or self.git.head(template) is None:
            raise _Refused(StepResult.blocked(
                f"factory.init.template_path {shown} is not a git checkout of the template "
                "with at least one commit"))
        local = settings.local_path(project.repo_name)
        repository = Repository(settings.owner or "local", project.repo_name,
                                default_branch="main",
                                visibility=settings.visibility)
        marker = self.marker(context)

        if not os.path.exists(local) or (os.path.isdir(local) and not os.listdir(local)):
            template_sha = self._resolve_pinned(template, shown, settings, pinned)
            if os.path.isdir(local):
                os.rmdir(local)  # empty; replaced atomically below
            context.logger.info("creating local project", local_path=local, template=shown,
                                template_sha=template_sha)
            message = (f"Initial commit\n\nGenerated from {shown} at {template_sha} by the "
                       "Factory's init step (factory.init.source: local). Local only: it has "
                       "no remote and nothing was pushed.\n\n"
                       f"{TEMPLATE_TRAILER}: {shown}@{template_sha}\n{KEY_TRAILER}: {marker}\n")
            self.git.create_from_local(
                template, template_sha, local, message,
                {"wgf.init-marker": marker, "wgf.template": shown,
                 "wgf.template-commit": template_sha},
                author=settings.commit_author)
            return repository, "created", template_sha, local

        found = self.git.get_config(local, "wgf.init-marker") \
            if os.path.isdir(os.path.join(local, ".git")) else None
        mine = found == marker or any(
            (ref.metadata or {}).get("local_path") == local
            for ref in context.previous_outputs or [] if ref.type == "scaffold-record")
        if not mine and not settings.adopt_existing:
            raise _Refused(StepResult.blocked(
                f"{local} already exists and was not created by this run (marker: "
                f"{found or 'none'}). Init never overwrites a directory: resume the run that "
                "created it, move it, or set factory.init.adopt_existing: true."))
        made_from = self.git.get_config(local, "wgf.template") if found else None
        if made_from != shown:
            raise _Refused(StepResult.failed(
                f"{local} was not generated from {shown} (recorded: {made_from or 'nothing'}). "
                "A game project must originate from the template.", retryable=False))
        made_at = self.git.get_config(local, "wgf.template-commit")
        if made_at != pinned:
            raise _Refused(StepResult.failed(
                f"{local} was generated from web-game-template "
                f"{made_at or 'an unrecorded revision'}, but the Factory is pinned to "
                f"{pinned}. A project is never carried across template revisions by init; "
                "make a new one.", retryable=False))
        context.logger.info("reusing local project", local_path=local)
        return repository, "reused", made_at, local

    def _resolve_pinned(self, template, shown, settings, pinned):
        """The pinned commit, which the local checkout must hold. A configured
        template_ref may only name that same commit."""
        if settings.template_ref:
            try:
                named = self.git.resolve(template, settings.template_ref)
            except ToolError as exc:
                raise _Refused(StepResult.failed(str(exc), retryable=False))
            if named != pinned:
                raise _Refused(StepResult.failed(
                    f"factory.init.template_ref {settings.template_ref!r} is {named} in "
                    f"{shown}, but the Factory is pinned to web-game-template {pinned} "
                    f"({paths.display(template_pin.LOCK)}). Remove template_ref, or re-pin "
                    "the Factory deliberately.", retryable=False))
        try:
            return self.git.resolve(template, pinned)
        except ToolError:
            raise _Refused(StepResult.blocked(
                f"factory.init.template_path {shown} does not contain the pinned "
                f"web-game-template commit {pinned}. Fetch it there, or leave template_path "
                "out to use a checkout of the pin."))

    # -- verification and configuration -------------------------------------------------

    def _verify(self, local):
        missing = missing_infrastructure(local)
        if missing:
            raise _Refused(StepResult.failed(
                f"{local} lacks template infrastructure: {', '.join(missing)}. This is a "
                "template problem; fix the template, never the game.", retryable=False))
        self._read_config(local)

    @staticmethod
    def _read_config(local):
        try:
            return read_game_config(local)
        except InfrastructureError as exc:
            raise _Refused(StepResult.failed(str(exc), retryable=False))

    def _configure(self, local, plan, inputs, project, settings, context):
        """Write game.config.yaml from the plan and commit it locally, once per key.
        Returns (commit or None, whether this execution made the commit)."""
        marker = self.marker(context)
        candidates = []
        if plan is not None:
            game_config = plan["repo_params"]["game_config"]
            path = os.path.join(local, GAME_CONFIG)
            with open(path, encoding="utf-8") as handle:
                current = handle.read()
            identity = bootstrap_identity(project.repo_name)
            try:
                desired = apply_game_config(current, game_config, identity)
                candidates += vendor_profiles(local, game_config["platforms"], self.profiles_dir)
            except (GameConfigError, ProfileError) as exc:
                raise _Refused(StepResult.failed(str(exc), retryable=False))
            if desired != current:
                with open(path, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(desired)
            candidates.insert(0, GAME_CONFIG)
        if settings.source == "local" and plan is not None:
            # bootstrap.yml's last act on GitHub is to delete itself; locally nothing runs
            # it, so init does what it would have left behind.
            bootstrap = os.path.join(local, *BOOTSTRAP.split("/"))
            if os.path.exists(bootstrap):
                os.remove(bootstrap)
            candidates.append(BOOTSTRAP)

        # A path that changed - by this execution, or by one that crashed before committing.
        changed = [p for p in candidates if self.git.changed(local, [p])]
        if changed:
            plan_hash = inputs.refs["tech-plan"].content_hash or \
                (plan.get("provenance") or {}).get("content_hash", "")
            engine = plan["repo_params"]["game_config"]["engine"]["type"]
            pins = ", ".join(p["profile"] for p in plan["repo_params"]["game_config"]["platforms"])
            message = (f"chore(scaffold): configure {project.title_id} from its tech plan\n\n"
                       f"engine: {engine}\nplatforms: {pins}\n\n"
                       "Written by the Factory's init step from "
                       "tech_plan.repo_params.game_config. Local commit: init never pushes.\n\n"
                       f"{KEY_TRAILER}: {marker}\n{PLAN_TRAILER}: {plan_hash}\n")
            commit = self.git.commit(local, changed, message, author=settings.commit_author)
            context.logger.info("committed game.config.yaml locally", commit=commit,
                                paths=changed)
            return commit, True
        if plan is None:
            return None, False
        return self.git.find_commit(local, {KEY_TRAILER: marker}), False

    # -- the artifact -------------------------------------------------------------------

    def _record(self, project, settings, repository, outcome, template_sha, game_config,
                local, plan, commit, committed, inputs, context, pin=None):
        produced_at = self.clock()
        pinned = []
        for artifact_type in ("game-design", "tech-plan"):
            if artifact_type not in inputs:
                continue
            ref = inputs.refs[artifact_type]
            content = inputs.load(artifact_type)
            if ref.content_hash and (content.get("provenance") or {}).get("artifact_id"):
                pinned.append({"artifact_id": content["provenance"]["artifact_id"],
                               "artifact_type": artifact_type,
                               "content_hash": ref.content_hash})

        repo = {"owner": repository.owner, "name": repository.name}
        if repository.url:
            repo["url"] = repository.url
        if repository.default_branch:
            repo["default_branch"] = repository.default_branch
        if repository.visibility in VISIBILITIES:
            repo["visibility"] = repository.visibility
        if settings.source == "local":
            template = {"repository": paths.display(settings.template_dir()
                                                    or template_pin.load_lock()["repository"]),
                        "source": "local"}
        else:
            template = {"repository": settings.template, "source": "github"}
        if template_sha:
            template["commit_sha"] = template_sha
        if pin and pin.get("generated_from"):
            template["generated_from_sha"] = pin["generated_from"]
        if pin and pin.get("commit"):
            template["pin_commit"] = pin["commit"]

        engine = (game_config.get("engine") or {}).get("type", "unset")
        pins = ", ".join(p["profile"] for p in game_config["platforms"]) or "none"
        where = paths.display(local)
        if plan is None:
            notes = (f"Local project: {where}. No tech-plan was in the run, so {GAME_CONFIG} is "
                     f"as the template generated it (engine {engine}; platforms {pins}).")
        else:
            notes = (f"Local project: {where}. {GAME_CONFIG} written from "
                     f"tech_plan.repo_params.game_config: engine {engine}; platforms {pins}. ")
            if commit:
                notes += (f"Committed locally as {commit[:12]} "
                          f"({'this execution' if committed else 'an earlier execution'}) and "
                          "not pushed: init never pushes.")
            else:
                notes += "The file already matched the plan; nothing was committed."
            if settings.source == "github":
                notes += (" game.id/name are set as the template's bootstrap workflow derives "
                          "them; on GitHub it writes the same lines and deletes itself in its "
                          "own commit, so pull --rebase before pushing.")
        if settings.source == "local":
            notes += " Source local: no remote, no network, no bootstrap."
        elif pin and pin.get("commit"):
            notes += (f" GitHub generated the repository from another revision of the template; "
                      f"local commit {pin['commit'][:12]} brings it to the pinned "
                      f"{template_sha[:12]}.")

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
