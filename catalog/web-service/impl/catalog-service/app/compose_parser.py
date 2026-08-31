# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
Real docker-compose parsing (flow B1 step 4) — the one piece of the
onboarding pipeline that is NOT mocked, since it's pure local computation
with no external infra dependency.

Extracts, per service: image ref, environment variable keys (settings),
and bind-mounted host paths that look like config/data files the ISV would
need to upload (referenced_files) — heuristically, any `volumes:` entry
whose source path is relative/local (not a named volume, not an absolute
host path already present in the image).
"""
import yaml

SECRET_KEY_HINTS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "PASS")


def looks_like_secret(env_key: str) -> bool:
    upper = env_key.upper()
    return any(hint in upper for hint in SECRET_KEY_HINTS)


def _split_volume_source(vol: str) -> str | None:
    """
    Returns the source (host-side) part of a `src:dst[:mode]` compose
    volume string, splitting on the first ":" that is NOT inside a
    `${VAR:-default}` interpolation block.

    Naive `str.split(":", 1)` breaks on real-world compose files that use
    shell-style defaults like `${APP_DIR:-..}/src/config:/app/config:ro`
    — it would split inside `${APP_DIR:-..}` (at the colon before `-..}`)
    instead of at the real path separator, silently losing every such
    volume. Discovered while onboarding a real app
    (smart-traffic-intersection-agent) through this reference
    implementation.
    """
    depth = 0
    for i, ch in enumerate(vol):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        elif ch == ":" and depth == 0:
            return vol[:i]
    return None


def parse_compose(compose_bytes: bytes) -> dict:
    """
    Returns {"images": [{service_name, image_ref}], "settings": [env_key],
    "referenced_files": [path_in_compose]}.
    Raises ValueError on invalid YAML/schema (-> caller returns 422).
    """
    try:
        doc = yaml.safe_load(compose_bytes)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML: {exc}") from exc

    if not isinstance(doc, dict) or "services" not in doc:
        raise ValueError("compose file must be a mapping with a top-level 'services' key")

    images: list[dict] = []
    settings_seen: dict[str, bool] = {}
    referenced_files: list[str] = []

    for service_name, service in doc["services"].items():
        if not isinstance(service, dict):
            continue
        image_ref = service.get("image")
        if image_ref:
            images.append({"service_name": service_name, "image_ref": image_ref})

        env = service.get("environment")
        if isinstance(env, dict):
            for k in env.keys():
                settings_seen[k] = settings_seen.get(k, False) or looks_like_secret(k)
        elif isinstance(env, list):
            for item in env:
                key = item.split("=", 1)[0] if "=" in item else item
                settings_seen[key] = settings_seen.get(key, False) or looks_like_secret(key)

        for vol in service.get("volumes", []) or []:
            if isinstance(vol, str) and ":" in vol:
                src = _split_volume_source(vol)
                if src and (
                    src.startswith("./")
                    or src.startswith("../")
                    or (not src.startswith("/") and "/" in src)
                ):
                    referenced_files.append(src)

    return {
        "images": images,
        "settings": settings_seen,
        "referenced_files": referenced_files,
    }
