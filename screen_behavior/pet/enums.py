from enum import StrEnum


class BaseMood(StrEnum):
    HAPPY = "happy"
    EXCITED = "excited"
    NEUTRAL = "neutral"
    LONELY = "lonely"
    TIRED = "tired"
    ANNOYED = "annoyed"
    HUNGRY = "hungry"
    SURPRISED = "surprised"
    MAD = "mad"


class SpecialMood(StrEnum):
    CUTE = "cute"
    JEALOUS = "jealous"
    AFFECTIONATE = "affectionate"


class Behavior(StrEnum):
    IDLE = "idle"
    WAVE = "wave"
    DANCE = "dance"
    STRETCH = "stretch"
    LOOK_AROUND = "look_around"
    SIT_DOWN = "sit_down"
    SLEEP = "sleep"
    WALK_AROUND_CORNER = "walk_around_corner"
    ASK_FOR_ATTENTION = "ask_for_attention"
    FOLLOW_MOUSE_WITH_EYES = "follow_mouse_with_eyes"
    SEND_KISS = "send_kiss"
    PLAY_DEAD = "play_dead"
    STUDY_WITH_USER = "study_with_user"
    WATCH_SCREEN = "watch_screen"
