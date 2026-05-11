# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import sys
from pathlib import Path

# Add server source to path so `from config import settings` works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "observal-server"))
