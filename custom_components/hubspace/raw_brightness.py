"""Fork-only: full 1-100 brightness for preset-only lights.

The Afero semantics layer maps attribute 2 to ``brightness-presets``
(33 / 66 / 100) and reports any other value as unknown. The device's own
profile describes attribute 2 as a 1-100 slider, so these helpers write and
read it on the raw Afero API instead.
"""

from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)

ATTR_BRIGHTNESS = 2


def _device_path(api, device_id: str) -> str:
    return f"v1/accounts/{api.account_id}/devices/{device_id}"


async def write_brightness(api, device_id: str, pct: int) -> None:
    """Write attribute 2 (1-100) straight to the device."""
    pct = max(1, min(100, int(pct)))
    await api.request(
        "POST",
        api.generate_api_url(_device_path(api, device_id) + "/requests"),
        json=[
            {"type": "attribute_write", "attrId": ATTR_BRIGHTNESS, "value": str(pct)}
        ],
        headers={"content-type": "application/json; charset=utf-8"},
    )


async def read_brightness(api, device_id: str) -> int | None:
    """Read attribute 2 from the device; None when it cannot be read."""
    try:
        res = await api.request(
            "GET",
            api.generate_api_url(_device_path(api, device_id)),
            params={"expansions": "attributes"},
        )
        body = await res.json()
        for attr in body.get("attributes", []):
            if attr.get("id") == ATTR_BRIGHTNESS and attr.get("value") not in (
                None,
                "",
            ):
                return max(1, min(100, int(attr["value"])))
    except Exception:  # noqa: BLE001 - a failed read must not break the entity
        LOGGER.debug("Raw brightness read failed for %s", device_id, exc_info=True)
    return None
