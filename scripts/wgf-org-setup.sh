#!/usr/bin/env bash
# Create or update the organization secrets and variables the game pipelines use.
#
# Idempotent: run it as often as you like. It is also the living inventory of what the
# organization is supposed to hold — if something is here and not in the org, or in the org
# and not here, one of the two is wrong.
#
# Three things worth knowing before running it:
#
#   1. Every name is prefixed WGF_ and scoped to selected repositories. Nothing here is
#      visible to the organization's other repositories, and none of their secrets are
#      visible to these.
#
#   2. Values are NOT set here. A secret is created holding the sentinel __UNSET__, which
#      the workflows recognise: they skip the step and say so, rather than failing with
#      something that looks like a credential problem. Set the real value with
#      `gh secret set <NAME> --org <ORG> --body "..."` or through the web UI.
#
#   3. GitHub never returns a secret's value. This script cannot read what is already there,
#      so it will not overwrite a real value with the sentinel — see SET_SENTINELS below.
#
# Usage:
#   bash scripts/wgf-org-setup.sh [--org Cuvara] [--repos a,b,c] [--set-sentinels] [--dry-run]
#
# Requires: gh, authenticated with the admin:org scope.
#   gh auth refresh -h github.com -s admin:org

set -euo pipefail

ORG="Cuvara"
REPOS="web-game-template,web-game-factory"
SET_SENTINELS=false
DRY_RUN=false

while [ $# -gt 0 ]; do
  case "$1" in
    --org) ORG="$2"; shift 2 ;;
    --repos) REPOS="$2"; shift 2 ;;
    --set-sentinels) SET_SENTINELS=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

run() {
  if [ "$DRY_RUN" = true ]; then
    printf '  would run: %s\n' "$*"
  else
    "$@"
  fi
}

# --- secrets -----------------------------------------------------------------------------
#
# name|visibility|what it is for
#
# Every one of these is scoped to selected repositories. Nothing here is readable by the
# organization's other repositories, and none of their secrets are readable by these.
#
# bootstrap.yml is the deliberate exception, and it does not appear below: it authenticates
# as the organization's existing bot app through APP_ID and APP_PRIVATE_KEY, which are
# already organization secrets visible everywhere. It has to be that way round — a repository
# created from the template is on no selected list until bootstrap puts it on one.
SECRETS="
WGF_CF_API_TOKEN|selected|Cloudflare API token for deploying develop builds to Pages.
WGF_POKI_AUTH_JSON|selected|Contents of ~/.config/poki/auth.json, captured once locally. Poki's CLI login is a browser flow.
WGF_YANDEX_CONSOLE_SESSION|selected|Reserved. Yandex publishes no upload API; submission is manual.
WGF_CRAZYGAMES_TOKEN|selected|Reserved. CrazyGames publishes no upload API; submission is manual.
WGF_GAMEVUI_TOKEN|selected|Reserved. GameVui publishes no upload API; submission is manual.
"

# --- variables ---------------------------------------------------------------------------
#
# Not secrets. An app id and a game id are identifiers, not credentials, and storing them as
# secrets only means nobody can read them back to check them.
#
# name|value|visibility|what it is for
VARIABLES="
WGF_CF_ACCOUNT_ID|__UNSET__|selected|Cloudflare account id.
WGF_CF_PROJECT_PREFIX|wgf|selected|Prefix for the Cloudflare Pages project of each game.
WGF_YANDEX_APP_ID|__UNSET__|selected|Yandex Games draft id for the current title.
WGF_POKI_GAME_ID|__UNSET__|selected|Poki game id (a UUID from developers.poki.com).
WGF_CRAZYGAMES_GAME_ID|__UNSET__|selected|CrazyGames game id.
WGF_GAMEVUI_GAME_ID|__UNSET__|selected|GameVui game id.
"

echo "organization : $ORG"
echo "repositories : $REPOS"
echo "sentinels    : $([ "$SET_SENTINELS" = true ] && echo 'will be written' || echo 'only for names that do not exist yet')"
echo

existing_secrets=$(gh api "orgs/$ORG/actions/secrets" --paginate --jq '.secrets[].name' 2>/dev/null || true)
existing_variables=$(gh api "orgs/$ORG/actions/variables" --paginate --jq '.variables[].name' 2>/dev/null || true)

# Repository ids for the selected-visibility list. Resolved once.
selected_ids=""
IFS=',' read -ra _repos <<< "$REPOS"
for repo in "${_repos[@]}"; do
  id=$(gh api "repos/$ORG/$repo" --jq '.id' 2>/dev/null || true)
  if [ -z "$id" ]; then
    echo "warning: $ORG/$repo not found — leaving it out of the selected list" >&2
    continue
  fi
  selected_ids="${selected_ids:+$selected_ids,}$id"
done
[ -n "$selected_ids" ] || { echo "none of --repos resolved; refusing to continue" >&2; exit 1; }

echo "secrets"
printf '%s\n' "$SECRETS" | while IFS='|' read -r name visibility purpose; do
  [ -z "$name" ] && continue

  if printf '%s\n' "$existing_secrets" | grep -qx "$name"; then
    # A secret's value cannot be read back, so `gh secret set` on an existing name would
    # replace a real credential with the sentinel. Only the repository list is reconciled,
    # through the endpoint that touches nothing else.
    if [ "$visibility" = "selected" ]; then
      if [ "$DRY_RUN" = true ]; then
        printf '  would run: gh api -X PUT orgs/%s/actions/secrets/%s/repositories <- [%s]\n' \
          "$ORG" "$name" "$selected_ids"
      else
        printf '{"selected_repository_ids":[%s]}' "$selected_ids" \
          | gh api -X PUT "orgs/$ORG/actions/secrets/$name/repositories" --input -
      fi
      echo "  = $name exists — value untouched, repository list reconciled"
    else
      echo "  = $name exists (visibility $visibility) — value untouched"
    fi
    continue
  fi

  if [ "$visibility" = "selected" ]; then
    run gh secret set "$name" --org "$ORG" --visibility selected --repos "$REPOS" --body "__UNSET__"
  else
    run gh secret set "$name" --org "$ORG" --visibility all --body "__UNSET__"
  fi
  echo "  + $name  ($visibility) — $purpose"
done

echo
echo "variables"
printf '%s\n' "$VARIABLES" | while IFS='|' read -r name value visibility purpose; do
  [ -z "$name" ] && continue

  if printf '%s\n' "$existing_variables" | grep -qx "$name"; then
    # Unlike a secret, a variable's value can be read back — so an existing one is reported
    # rather than reset, and you can see at a glance which are still sentinels.
    current=$(gh api "orgs/$ORG/actions/variables/$name" --jq '.value' 2>/dev/null || echo "")
    echo "  = $name = $current"
    continue
  fi

  if [ "$visibility" = "all" ]; then
    run gh variable set "$name" --org "$ORG" --visibility all --body "$value"
  else
    run gh variable set "$name" --org "$ORG" --visibility selected --repos "$REPOS" --body "$value"
  fi
  echo "  + $name = $value  ($visibility) — $purpose"
done

echo
cat <<'EOF'
Next:

  1. Set the values that are still __UNSET__. Workflows skip the steps that need them and
     say so in the run summary, so it is safe to leave any of them for later. The Cloudflare
     ones can be copied from the organization's existing CLOUDFLARE_* secrets if the same
     account is being used:
       gh secret   set WGF_CF_API_TOKEN  --org <ORG> --body "<token>"
       gh variable set WGF_CF_ACCOUNT_ID --org <ORG> --body "<account id>"

  2. Nothing to do about the bootstrap credential. bootstrap.yml authenticates as the
     organization's existing bot app through APP_ID and APP_PRIVATE_KEY. Confirm that app
     still holds: organization secrets W, organization variables W, and, per repository,
     contents W, actions W, variables W, administration W, metadata R.

  3. Game repositories get their gate environments from bootstrap.yml. Verify after the first
     one is created that `production` and `campaign-spend` exist AND have required reviewers.
     An environment with no reviewers is not a gate, and publish.yml/campaign.yml will refuse
     to run rather than proceed unapproved.

     Required reviewers are unavailable on PRIVATE repositories under a free plan. A private
     game repository on a free organization cannot enforce G6 or G7 this way at all.
EOF
