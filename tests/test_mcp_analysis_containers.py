# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from observal_shared.mcp_analysis import detect_container_image


def test_dockerfile_repo_gets_local_build_setup(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")

    image, suggested, setup = detect_container_image(tmp_path, "https://github.com/acme/local-mcp")

    assert image == "acme-local-mcp:latest"
    assert suggested is True
    assert setup == ["docker build -t acme-local-mcp:latest -f Dockerfile ."]


def test_compose_build_service_gets_local_image_tag(tmp_path):
    (tmp_path / "compose.yml").write_text(
        """
services:
  server:
    build:
      context: ./server
      dockerfile: Dockerfile.mcp
""".strip(),
        encoding="utf-8",
    )

    image, suggested, setup = detect_container_image(tmp_path, "https://github.com/acme/local-mcp")

    assert image == "acme-local-mcp-server:latest"
    assert suggested is True
    assert setup == ["docker build -t acme-local-mcp-server:latest -f server/Dockerfile.mcp ./server"]


def test_compose_declared_image_needs_no_local_setup(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(
        """
services:
  mcp:
    image: ghcr.io/acme/local-mcp:1.2.3
""".strip(),
        encoding="utf-8",
    )

    image, suggested, setup = detect_container_image(tmp_path, "https://github.com/acme/local-mcp")

    assert image == "ghcr.io/acme/local-mcp:1.2.3"
    assert suggested is False
    assert setup == []
