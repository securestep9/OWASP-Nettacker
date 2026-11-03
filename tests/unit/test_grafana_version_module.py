"""Detection tests for the grafana_version_scan module.

The engine evaluates a module's ``content`` condition with
``re.findall(compiled_regex, response_content)`` and, because the module's regex
has a single capture group, logs only the captured version string. These tests
load the module's own regex as shipped and exercise it the same way, covering the
JSON key orderings Grafana's /api/health endpoint produces and the responses that
must not match (``hide_version`` enabled and non-Grafana health endpoints).
"""

import os
import re

import pytest
import yaml

MODULE_PATH = os.path.join("nettacker", "modules", "scan", "grafana_version.yaml")


def _content_regex():
    with open(MODULE_PATH, "r", encoding="utf-8") as f:
        module = yaml.safe_load(f)
    step = module["payloads"][0]["steps"][0]
    return step["response"]["conditions"]["content"]["regex"]


@pytest.fixture(scope="module")
def content_regex():
    return re.compile(_content_regex())


@pytest.mark.parametrize(
    "body, expected_version",
    [
        # Old alphabetically sorted JSON (commit, database, version), e.g. 8.x
        ('{"commit":"abc123","database":"ok","version":"8.3.0"}', "8.3.0"),
        # Current struct-ordered JSON (database, version, commit), e.g. 13.x
        ('{"database":"ok","version":"13.0.0","commit":"deadbeef"}', "13.0.0"),
        # Enterprise alphabetically sorted with enterpriseCommit between the keys
        (
            '{"apiserver":"ok","commit":"abc","database":"ok",'
            '"enterpriseCommit":"ent123","version":"10.4.2"}',
            "10.4.2",
        ),
        # Pretty-printed JSON with whitespace
        ('{\n  "commit": "abc",\n  "database": "ok",\n  "version": "9.5.1"\n}', "9.5.1"),
    ],
)
def test_captures_version_only(content_regex, body, expected_version):
    matches = content_regex.findall(body)
    assert matches == [expected_version]


@pytest.mark.parametrize(
    "body",
    [
        # hide_version = true: version omitted from /api/health
        '{"commit":"","database":"ok","version":""}',
        '{"database":"ok"}',
        # Generic non-Grafana health endpoints
        '{"status":"ok","version":"1.2.3"}',
        '{"health":"UP"}',
        # version present but not paired with a preceding database key
        '{"version":"2.0.0","database":"ok"}',
    ],
)
def test_no_false_positive(content_regex, body):
    assert content_regex.findall(body) == []
