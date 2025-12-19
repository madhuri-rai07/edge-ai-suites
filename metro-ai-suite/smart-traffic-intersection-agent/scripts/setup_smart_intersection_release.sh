#!/usr/bin/env bash
set -euo pipefail

# Pin and bootstrap a tagged Smart Intersection app (metro-vision-ai-app-recipe)
# without using git submodules. Downloads the tag archive, runs install.sh, and
# optionally starts the stack. Designed to coexist with dev branches for
# smart-traffic-intersection-agent and route-planner.
#
# Usage:
#   export SI_RELEASE_TAG=release-1.2.0   # or v2025.2 etc.
#   ./scripts/setup_smart_intersection_release.sh [--start]
#
# Env (optional):
#   SI_RELEASE_TAG: Tag name to fetch from open-edge-platform/edge-ai-suites (required)
#   SI_BASE_DIR:    Destination base directory (default: .deps/smart-intersection)
#   SI_STACK:       Which compose to start: scenescape|without-scenescape (default: scenescape)
#   HTTP(S)_PROXY, NO_PROXY: Standard proxy variables are propagated to docker compose

if [[ "${SI_RELEASE_TAG:-}" == "" ]]; then
  echo "ERROR: SI_RELEASE_TAG is required (e.g., release-1.2.0 or v2025.2)." >&2
  echo "Tip: If you want to use a branch (e.g., main), set SI_RELEASE_TAG=main and the script will fallback to the branch archive." >&2
  exit 1
fi

SI_BASE_DIR=${SI_BASE_DIR:-"$(pwd)/.deps/smart-intersection"}
SI_STACK=${SI_STACK:-scenescape} # scenescape | without-scenescape
START_STACK=false
if [[ "${1:-}" == "--start" ]]; then START_STACK=true; fi

mkdir -p "${SI_BASE_DIR}"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo "==> Downloading Smart Intersection: ${SI_RELEASE_TAG}"

# Try tag archive first; if not found (HTTP 404), try branch archive
TAG_URL="https://github.com/open-edge-platform/edge-ai-suites/archive/refs/tags/${SI_RELEASE_TAG}.tar.gz"
BRANCH_URL="https://github.com/open-edge-platform/edge-ai-suites/archive/refs/heads/${SI_RELEASE_TAG}.tar.gz"

HTTP_STATUS=$(curl -L -s -w "%{http_code}" -o "$TMPDIR/release.tar.gz" "$TAG_URL")
if [[ "$HTTP_STATUS" != "200" ]]; then
  echo "Tag not found, attempting branch archive... (${SI_RELEASE_TAG})"
  HTTP_STATUS=$(curl -L -s -w "%{http_code}" -o "$TMPDIR/release.tar.gz" "$BRANCH_URL")
  if [[ "$HTTP_STATUS" != "200" ]]; then
    echo "ERROR: Could not download tag or branch archive for '${SI_RELEASE_TAG}'." >&2
    echo "Tried:" >&2
    echo "  $TAG_URL" >&2
    echo "  $BRANCH_URL" >&2
    echo "Ensure SI_RELEASE_TAG matches a valid tag (e.g., release-1.2.0, v2025.2) or branch (e.g., main)." >&2
    exit 22
  fi
fi

echo "==> Extracting..."
tar -xzf "$TMPDIR/release.tar.gz" -C "$TMPDIR"
ROOT_DIR=$(find "$TMPDIR" -maxdepth 1 -type d -name "edge-ai-suites-*" | head -n1)
if [[ -z "$ROOT_DIR" ]]; then
  echo "ERROR: Could not locate extracted root dir" >&2
  exit 1
fi

APP_DIR_REL="metro-ai-suite/metro-vision-ai-app-recipe"
APP_DIR_SRC="${ROOT_DIR}/${APP_DIR_REL}"
if [[ ! -d "$APP_DIR_SRC" ]]; then
  echo "ERROR: ${APP_DIR_REL} not found in the release archive" >&2
  exit 1
fi

DEST_DIR="${SI_BASE_DIR}/${SI_RELEASE_TAG}"
rm -rf "$DEST_DIR"
mkdir -p "$DEST_DIR"
cp -a "$APP_DIR_SRC" "$DEST_DIR/"
APP_DIR="${DEST_DIR}/metro-vision-ai-app-recipe"

pushd "$APP_DIR" >/dev/null

# Best-effort: comment out chown lines that can fail without sudo (seen in some variants)
if [[ -f "smart-intersection/install.sh" ]]; then
  sed -i 's/^sudo chown -R \$USER:\$USER chart\/files\/secrets$/# &/' smart-intersection/install.sh || true
  sed -i 's/^sudo chown -R \$USER:\$USER src\/secrets$/# &/' smart-intersection/install.sh || true
fi

echo "==> Running install.sh smart-intersection"
./install.sh smart-intersection

if $START_STACK; then
  # Prefer docker-compose.yml if install.sh prepared it; otherwise use selected stack file.
  COMPOSE_TO_USE=""
  if [[ -f "docker-compose.yml" ]]; then
    COMPOSE_TO_USE="docker-compose.yml"
  else
    case "$SI_STACK" in
      scenescape)
        COMPOSE_TO_USE="compose-scenescape.yml"
        ;;
      without-scenescape)
        COMPOSE_TO_USE="compose-without-scenescape.yml"
        ;;
      *)
        echo "ERROR: Unknown SI_STACK value: $SI_STACK (expected scenescape|without-scenescape)" >&2
        exit 1
        ;;
    esac
  fi

  # If the chosen compose file is missing, try to fetch from the same tag/branch or fallback to workspace copy.
  if [[ ! -f "$COMPOSE_TO_USE" ]]; then
    RAW_BASE="https://raw.githubusercontent.com/open-edge-platform/edge-ai-suites/${SI_RELEASE_TAG}/metro-ai-suite/metro-vision-ai-app-recipe"
    echo "Compose file '$COMPOSE_TO_USE' not found. Attempting to download from $RAW_BASE ..."
    if curl -L -sSf -o "$COMPOSE_TO_USE" "${RAW_BASE}/${COMPOSE_TO_USE}" 2>/dev/null; then
      echo "Downloaded $COMPOSE_TO_USE from ${SI_RELEASE_TAG}."
    else
      # Fallback: copy from local workspace if available
      SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
      WS_RECIPE_DIR="${SCRIPT_DIR}/../../metro-vision-ai-app-recipe"
      if [[ -f "${WS_RECIPE_DIR}/${COMPOSE_TO_USE}" ]]; then
        echo "Falling back to workspace compose at ${WS_RECIPE_DIR}/${COMPOSE_TO_USE}"
        cp "${WS_RECIPE_DIR}/${COMPOSE_TO_USE}" "." || true
      fi
    fi
  fi

  if [[ ! -f "$COMPOSE_TO_USE" ]]; then
    echo "ERROR: Could not locate a compose file to start the stack." >&2
    echo "Checked: docker-compose.yml, $COMPOSE_TO_USE" >&2
    echo "Tried downloading from the '${SI_RELEASE_TAG}' branch/tag and copying from the local workspace." >&2
    echo "You can still manage the app manually at: $APP_DIR" >&2
    exit 1
  fi

  echo "==> Starting Smart Intersection stack using $COMPOSE_TO_USE"
  docker compose -f "$COMPOSE_TO_USE" up -d
  echo "OK. External network should be present for agent overrides: metro-vision-ai-app-recipe_scenescape"
fi

popd >/dev/null

echo "Done. Smart Intersection (tag ${SI_RELEASE_TAG}) is prepared at:"
echo "  $APP_DIR"
echo "Next steps:"
echo "  - Use this path to manage the app with docker compose"
echo "  - Or just rely on the external network it creates for your local demo"
