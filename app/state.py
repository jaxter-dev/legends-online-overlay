from dataclasses import dataclass, field


@dataclass
class OverlayRowState:
    """
    One visible row in the overlay.
    """

    label: str
    value: str
    color: str = "#d4c5a1"


@dataclass
class OverlayState:
    """
    Full overlay UI state.

    The UI renders only this object.
    """

    title: str
    rows: list[OverlayRowState] = field(default_factory=list)
