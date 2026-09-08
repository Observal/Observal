# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

from observal_shared.registry_slug import slugify, validate_slug


def test_slugify_uses_canonical_registry_rules() -> None:
    assert slugify(" Search Tool! ") == "search-tool"
    assert slugify("A" * 80) == "a" * 64
    assert validate_slug("valid_slug-1") == "valid_slug-1"


@pytest.mark.parametrize("value", ["", "!!!", "draft", "resolve"])
def test_slugify_rejects_empty_or_reserved_targets(value: str) -> None:
    with pytest.raises(ValueError):
        slugify(value)
