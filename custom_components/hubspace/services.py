"""Register Afero services within Home Assistant."""

import asyncio
from importlib.metadata import version
import json
import logging
from typing import Final

from aiohttp import web_exceptions
from homeassistant.const import CONF_USERNAME
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.service import verify_domain_control
from packaging.version import Version
import voluptuous as vol

from .bridge import HubspaceBridge
from .const import DOMAIN

# @TODO - Deprecate when minimum version is 2025.10
VERIFY_DOMAIN_CONTROL_CHANGE: Final[Version] = Version("2025.10")
CURRENT_VERSION: Final[Version] = Version(version("homeassistant"))

SERVICE_SEND_COMMAND = "send_command"

SERVICE_SEND_COMMAND_FUNC_CLASS: Final[str] = "function_class"
SERVICE_SEND_COMMAND_FUNC_INSTANCE: Final[str] = "function_instance"
SERVICE_SEND_COMMAND_VALUE: Final[str] = "value"
SERVICE_SEND_COMMAND_ACCOUNT: Final[str] = "account"
# Fork-only diagnostic: a signed request to the raw Afero device API, scoped to
# the logged-in account. Never proposed upstream.
SERVICE_AFERO_REQUEST = "afero_request"

LOGGER = logging.getLogger(__name__)


def optional(value):
    """Validate optional string values.

    Args:
        value: Value to validate

    Returns:
        The validated string value or None if value is None

    """
    if value is None:
        return value
    return cv.string(value)


async def send_command(call: ServiceCall) -> None:
    """Send command to Hubspace device(s).

    Sends a specified command with parameters to one or more Hubspace devices.
    Commands are sent through the appropriate bridge based on account.

    Args:
        call: Service call containing command parameters

    """
    states: list[dict] = []
    states.append(
        {
            "value": call.data.get(SERVICE_SEND_COMMAND_VALUE),
            "functionClass": call.data.get(SERVICE_SEND_COMMAND_FUNC_CLASS),
            "functionInstance": call.data.get(SERVICE_SEND_COMMAND_FUNC_INSTANCE),
        }
    )
    entity_reg = er.async_get(call.hass)
    tasks = []
    account = call.data.get("account")
    for entity_name in call.data.get("entity_id", []):
        entity = entity_reg.async_get(entity_name)
        bridge = await find_bridge(call.hass, account)
        if bridge:
            tasks.append(bridge.api.send_service_request(entity.unique_id, states))
        else:
            LOGGER.warning("No bridge using account %s", account)
            return
    await asyncio.gather(*tasks)


async def afero_request(call: ServiceCall) -> ServiceResponse:
    """Send one signed request to the raw Afero API for the logged-in account.

    The path must sit under /v1/accounts/{account}/; "{account}" is replaced
    with the account id. Only GET and POST are allowed.
    """
    bridge = await find_bridge(call.hass, call.data.get(SERVICE_SEND_COMMAND_ACCOUNT))
    if not bridge:
        raise HomeAssistantError("No Hubspace bridge")
    api = bridge.api
    path = call.data["path"].replace("{account}", str(api.account_id))
    if not path.startswith(f"/v1/accounts/{api.account_id}/"):
        raise HomeAssistantError("path must start with /v1/accounts/{account}/")
    kwargs = {}
    if call.data.get("body") is not None:
        kwargs["json"] = call.data["body"]
        kwargs["headers"] = {"content-type": "application/json; charset=utf-8"}
    try:
        res = await api.request(
            call.data.get("method", "GET"), api.generate_api_url(path), **kwargs
        )
    except web_exceptions.HTTPForbidden:
        return {"status": 403, "body": None}
    text = await res.text()
    try:
        body = json.loads(text)
    except ValueError:
        body = text
    return {"status": res.status, "body": body}


def async_register_services(hass: HomeAssistant) -> None:
    """Register services for Hubspace integration.

    Registers the send_command service that allows sending commands to Hubspace devices.
    The service accepts function class, instance, value and optional account parameters.

    Args:
        hass: HomeAssistant instance to register services with

    """
    if CURRENT_VERSION < VERIFY_DOMAIN_CONTROL_CHANGE:
        args = [hass, DOMAIN]
    else:
        args = [DOMAIN]
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_COMMAND):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_COMMAND,
            verify_domain_control(*args)(send_command),
            schema=vol.Schema(
                {
                    vol.Required("entity_id"): cv.entity_ids,
                    vol.Required(SERVICE_SEND_COMMAND_FUNC_CLASS): cv.string,
                    vol.Required(SERVICE_SEND_COMMAND_VALUE): cv.string,
                    vol.Optional(SERVICE_SEND_COMMAND_FUNC_INSTANCE): optional,
                    vol.Optional(SERVICE_SEND_COMMAND_ACCOUNT): optional,
                }
            ),
        )
    if not hass.services.has_service(DOMAIN, SERVICE_AFERO_REQUEST):
        hass.services.async_register(
            DOMAIN,
            SERVICE_AFERO_REQUEST,
            verify_domain_control(*args)(afero_request),
            schema=vol.Schema(
                {
                    vol.Required("path"): cv.string,
                    vol.Optional("method", default="GET"): vol.In(["GET", "POST"]),
                    vol.Optional("body"): vol.Any(list, dict),
                    vol.Optional(SERVICE_SEND_COMMAND_ACCOUNT): optional,
                }
            ),
            supports_response=SupportsResponse.ONLY,
        )


async def find_bridge(hass: HomeAssistant, username: str) -> HubspaceBridge | None:
    """Find the bridge for the given username.

    Args:
        hass: HomeAssistant instance containing bridges
        username: Username to find bridge for

    Returns:
        HubspaceBridge if found, None otherwise

    """
    for bridge in hass.data[DOMAIN].values():
        if username is None:
            return bridge
        if bridge.config_entry.data[CONF_USERNAME] == username:
            return bridge
    return None
