"""Tests for the MAC connections advertised by Livebox client devices."""

from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.livebox.const import DOMAIN


@pytest.mark.parametrize(
    "platforms",
    [
        (Platform.DEVICE_TRACKER,),
        (Platform.SWITCH,),
        (Platform.DEVICE_TRACKER, Platform.SWITCH),
    ],
    ids=["tracker-only", "switch-only", "tracker-and-switch"],
)
@pytest.mark.parametrize(
    "device_key",
    ["AA:BB:CC:DD:EE:FF", "aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF"],
)
async def test_client_mac_connection(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    AIOSysbus: MagicMock,
    platforms: tuple[Platform, ...],
    device_key: str,
) -> None:
    """Client entities share a device with a normalized MAC connection."""
    AIOSysbus.__devices["status"].append(
        {
            "Key": device_key,
            "Name": "MAC test client",
            "PhysAddress": "AA:BB:CC:DD:EE:FF",
            "IPAddress": "192.0.2.10",
            "Active": True,
            "Tags": "wifi edev mac physical",
        }
    )
    device_registry = dr.async_get(hass)
    other_entry = MockConfigEntry(domain="synology_dsm", unique_id="test-nas")
    other_entry.add_to_hass(hass)
    other_device = device_registry.async_get_or_create(
        config_entry_id=other_entry.entry_id,
        identifiers={("synology_dsm", "test-nas")},
        connections={(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")},
    )

    with patch("custom_components.livebox.PLATFORMS", list(platforms)):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = config_entry.runtime_data
    client = device_registry.async_get_device_by_identifier(
        (DOMAIN, device_key), config_entry.entry_id
    )
    gateway = device_registry.async_get_device_by_identifier(
        (DOMAIN, cast(str, coordinator.unique_id)), config_entry.entry_id
    )
    assert client is not None
    assert gateway is not None
    assert client.identifiers == {(DOMAIN, device_key)}
    assert client.connections == {(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")}
    assert client.via_device_id == gateway.id
    assert not gateway.connections
    # Matching MACs allow cross-integration linking without merging the devices.
    assert client.id != other_device.id
    assert client.connections == other_device.connections
    assert other_device.identifiers == {("synology_dsm", "test-nas")}

    entity_registry = er.async_get(hass)
    for platform in platforms:
        unique_id = (
            device_key
            if platform == Platform.DEVICE_TRACKER
            else f"{coordinator.unique_id}_{device_key}_wan_access"
        )
        entity_id = entity_registry.async_get_entity_id(platform, DOMAIN, unique_id)
        assert entity_id is not None
        entity = entity_registry.async_get(entity_id)
        assert entity is not None
        assert entity.device_id == client.id
        assert hass.states.get(entity_id) is not None


@pytest.mark.parametrize(
    "device_key",
    [
        "987654321098765",
        "**REDACTED**",
        "AA:BB:CC:DD:EE:GG",
        "AA:BB:CC:DD:EE",
        "AA:BB:CC:DD:EE:FF-extra",
        "AA:BB:CC:DD:EE:FF\n",
    ],
)
async def test_non_mac_client_has_no_connection(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    AIOSysbus: MagicMock,
    device_key: str,
) -> None:
    """Serial numbers, redacted keys and malformed MACs are not connections."""
    AIOSysbus.__devices["status"].append(
        {
            "Key": device_key,
            "Name": "Non-MAC test client",
            "PhysAddress": "AA:BB:CC:DD:EE:FF",
            "Active": True,
            "Tags": "wifi edev mac physical",
        }
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    client = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, device_key), config_entry.entry_id
    )
    assert client is not None
    assert client.identifiers == {(DOMAIN, device_key)}
    assert not client.connections


@pytest.mark.usefixtures("AIOSysbus")
@pytest.mark.parametrize(
    "api_overlay", ["issue_191_repeater_topology_sanitized.json"], indirect=True
)
async def test_mac_connections_preserve_repeater_topology(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> None:
    """Repeaters and their clients retain their parent links and MACs."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    gateway = device_registry.async_get_device_by_identifier(
        (DOMAIN, cast(str, config_entry.runtime_data.unique_id)), config_entry.entry_id
    )
    repeater = device_registry.async_get_device_by_identifier(
        (DOMAIN, "CC:CC:CC:CC:CC:01"), config_entry.entry_id
    )
    client = device_registry.async_get_device_by_identifier(
        (DOMAIN, "DD:DD:DD:DD:DD:01"), config_entry.entry_id
    )
    assert gateway is not None
    assert repeater is not None
    assert client is not None
    assert not gateway.connections
    assert repeater.connections == {(dr.CONNECTION_NETWORK_MAC, "cc:cc:cc:cc:cc:01")}
    assert client.connections == {(dr.CONNECTION_NETWORK_MAC, "dd:dd:dd:dd:dd:01")}
    assert repeater.via_device_id == gateway.id
    assert client.via_device_id == repeater.id
