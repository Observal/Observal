# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

from pydantic import BaseModel


class TelemetryStatusResponse(BaseModel):
    tool_call_events: int
    agent_interaction_events: int
    status: str
