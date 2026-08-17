"""与摄像头和 YOLO 无关的判定逻辑，可在普通电脑上单独测试。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfirmationState:
    consecutive_frames: int
    confirmed: bool
    just_confirmed: bool


class PersonConfirmer:
    """必须连续多帧看到人才报警，减少单帧误检。"""

    def __init__(self, required_frames: int = 5) -> None:
        if required_frames < 1:
            raise ValueError("required_frames must be >= 1")
        self.required_frames = required_frames
        self._count = 0
        self._was_confirmed = False

    def update(self, has_person: bool) -> ConfirmationState:
        self._count = self._count + 1 if has_person else 0
        confirmed = self._count >= self.required_frames
        just_confirmed = confirmed and not self._was_confirmed
        self._was_confirmed = confirmed
        return ConfirmationState(self._count, confirmed, just_confirmed)

