# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
Unit tests for compose_parser.py, in particular the ${VAR:-default}
volume-splitting bug found while onboarding a real app
(smart-traffic-intersection-agent) through this reference implementation.
"""
from app.compose_parser import parse_compose


def test_volume_with_shell_style_default_is_split_correctly():
    compose = b"""
services:
  svc:
    image: my-image:1.0
    volumes:
      - ${APP_DIR:-..}/src/config:/app/config:ro
      - ./relative/data:/data
      - named-volume:/var/lib/data
"""
    result = parse_compose(compose)
    assert "${APP_DIR:-..}/src/config" in result["referenced_files"]
    assert "./relative/data" in result["referenced_files"]
    # named (non-path) volumes must NOT be treated as referenced files
    assert not any("named-volume" in f for f in result["referenced_files"])


def test_multiple_nested_default_braces_in_same_volume_line():
    compose = b"""
services:
  svc:
    image: my-image:1.0
    volumes:
      - ${OVMS_CONFIG_DIR:-.ovms}/models:/models:ro
"""
    result = parse_compose(compose)
    assert result["referenced_files"] == ["${OVMS_CONFIG_DIR:-.ovms}/models"]


def test_environment_dict_and_list_forms_both_extract_keys():
    compose = b"""
services:
  a:
    image: img:1
    environment:
      HF_TOKEN: ""
      LOG_LEVEL: info
  b:
    image: img:2
    environment:
      - METRICS_PORT=9090
      - API_KEY=changeme
"""
    result = parse_compose(compose)
    assert result["settings"]["HF_TOKEN"] is True  # secret-like key name
    assert result["settings"]["LOG_LEVEL"] is False
    assert result["settings"]["METRICS_PORT"] is False
    assert result["settings"]["API_KEY"] is True


def test_invalid_yaml_raises_value_error():
    import pytest

    with pytest.raises(ValueError):
        parse_compose(b"not: [valid: yaml: at: all")


def test_missing_services_key_raises_value_error():
    import pytest

    with pytest.raises(ValueError):
        parse_compose(b"version: '3'\n")
