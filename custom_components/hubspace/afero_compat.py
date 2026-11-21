"""Backport of light selects from aioafero 9.4.0 onto older aioafero releases.

Lights such as the Home Decorators Collection Grand Duchess Christmas tree have
no ``brightness`` function, only a ``brightness-presets`` category
(low / medium / high), plus a ``power-off-timer``. aioafero 9.4.0 tracks both
on ``Light`` and accepts ``selects=`` in ``LightController.set_state``. Until
the pinned aioafero includes that, this module adds the same behaviour at
import time. It is a no-op once aioafero already tracks the preset.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import wraps
import logging

from aioafero.v1.controllers.base import NumbersName
from aioafero.v1.controllers.light import LightController
from aioafero.v1.models import features
from aioafero.v1.models.light import LightPut

_LOGGER = logging.getLogger(__name__)

BRIGHTNESS_PRESETS = ("brightness-presets", None)
POWER_OFF_TIMER = ("power-off-timer", None)


@dataclass
class LightSelectsPut(LightPut):
    """``LightPut`` with the ``selects`` field aioafero 9.4.0 adds."""

    selects: dict[tuple[str, str | None], features.SelectFeature] | None = field(
        default_factory=dict, repr=False, init=False
    )


def apply() -> bool:
    """Patch ``LightController`` when aioafero lacks light selects.

    :return: True when the patch was applied, False when it was not needed.
    """
    if BRIGHTNESS_PRESETS in LightController.ITEM_SELECTS:
        return False
    LightController.ITEM_SELECTS = {
        **LightController.ITEM_SELECTS,
        BRIGHTNESS_PRESETS: "Brightness Preset",
    }
    LightController.ITEM_NUMBERS = {
        **LightController.ITEM_NUMBERS,
        POWER_OFF_TIMER: NumbersName(unit="minutes", display_name="Power Off Timer"),
    }

    orig_init = LightController.initialize_elem
    orig_set_state = LightController.set_state

    @wraps(orig_init)
    async def initialize_elem(self, afero_device):
        item = await orig_init(self, afero_device)
        if item.selects is None:
            item.selects = {}
        for state in afero_device.states:
            if select := await self.initialize_select(afero_device.functions, state):
                item.selects[select[0]] = select[1]
        return item

    @wraps(orig_set_state)
    async def set_state(self, device_id, *, selects=None, **kwargs):
        if selects:
            cur_item = self.get_device(device_id)
            update_obj = LightSelectsPut()
            for key, val in selects.items():
                if key in (cur_item.selects or {}):
                    update_obj.selects[key] = replace(
                        cur_item.selects[key], selected=val
                    )
            if update_obj.selects:
                await self.update(device_id, obj_in=update_obj)
        if any(val is not None for val in kwargs.values()):
            await orig_set_state(self, device_id, **kwargs)

    LightController.initialize_elem = initialize_elem
    LightController.set_state = set_state
    _LOGGER.debug("Applied light selects backport to aioafero LightController")
    return True
