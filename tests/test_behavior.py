from awareness.models import ScreenContext, WindowInfo
from pet.behavior import BehaviorEngine
from pet.models import PetState


def context(activity: str = "other", idle: float = 0.0) -> ScreenContext:
    return ScreenContext(
        cursor_x=0,
        cursor_y=0,
        idle_seconds=idle,
        foreground=WindowInfo(),
        activity_kind=activity,
    )


def test_low_energy_causes_sleep():
    pet = PetState(energy=10)
    result = BehaviorEngine().decide(pet, context())
    assert result.behavior == "sleep"


def test_coding_context_causes_study():
    pet = PetState()
    result = BehaviorEngine().decide(pet, context("coding"))
    assert result.behavior == "study_with_user"


def test_idle_user_causes_nap():
    pet = PetState()
    result = BehaviorEngine().decide(pet, context("other", idle=600))
    assert result.behavior == "nap"
