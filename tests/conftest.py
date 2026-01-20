"""Configuration for pytest."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blitzortung.const import DOMAIN


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test Location",
            "latitude": 50.0,
            "longitude": 10.0,
        },
        unique_id="50.0-10.0",
    )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: bool) -> None:
    """Enable custom integrations."""
