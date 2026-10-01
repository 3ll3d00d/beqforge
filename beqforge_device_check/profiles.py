"""Device capabilities, kept separate from claims established by a measurement."""

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class Route:
    name: str
    channels: int
    sections: int

    def __post_init__(self) -> None:
        if not self.name or self.channels < 1 or self.sections < 1:
            raise ValueError("a route needs a name, channels and section capacity")


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    id: str
    name: str
    engine: str
    internal_rates: tuple[int, ...]
    coefficient_format: str
    arithmetic: str
    claim_source: str
    routes: tuple[Route, ...]
    coefficient_readback: bool = False

    def __post_init__(self) -> None:
        if not self.id or not self.name or not self.claim_source:
            raise ValueError("profile identity and claim source are required")
        if self.engine not in ("minidsp", "camilladsp", "manual", "simulation"):
            raise ValueError("unsupported engine")
        if self.coefficient_format not in (
            "float32",
            "float64",
            "fixed5.23",
            "unknown",
        ):
            raise ValueError("unsupported coefficient format")
        if not self.internal_rates or any(
            not isinstance(rate, int) or isinstance(rate, bool) or rate < 1000
            for rate in self.internal_rates
        ):
            raise ValueError("internal rates must be explicit positive integer rates")
        if not self.routes or len({route.name for route in self.routes}) != len(
            self.routes
        ):
            raise ValueError("profile needs uniquely named routes")

    def route(self, name: str, channel: int, rate: int) -> Route:
        if rate not in self.internal_rates:
            raise ValueError(f"{self.name} does not support internal rate {rate}")
        for route in self.routes:
            if route.name == name:
                if not 0 <= channel < route.channels:
                    raise ValueError(
                        "route channel is out of range (channels are zero-based)"
                    )
                return route
        raise ValueError(f"unknown route {name}")

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "DeviceProfile":
        fields = dict(value)
        fields["internal_rates"] = tuple(fields["internal_rates"])
        fields["routes"] = tuple(Route(**route) for route in fields["routes"])
        return cls(**fields)


# Rate/slot layout follows ezbeq's Minidsp24HD descriptor. Format/arithmetic are
# stated claims, not a conclusion inferred from coefficient error or a sweep.
PROFILES = {
    "minidsp-2x4hd": DeviceProfile(
        "minidsp-2x4hd",
        "miniDSP 2x4 HD",
        "minidsp",
        (96000,),
        "float32",
        "float32 (stated; recursive implementation unverified)",
        "ezbeq Minidsp24HD: rate/routes; owner: 32-bit floating-point DSP",
        (Route("input", 2, 10), Route("output", 4, 10)),
    ),
    "camilladsp-float64": DeviceProfile(
        "camilladsp-float64",
        "CamillaDSP float64 reference",
        "camilladsp",
        (48000, 96000),
        "float64",
        "float64 (requires verified build)",
        "CamillaDSP documentation: default float64; verify installed build",
        (Route("filter", 1, 100),),
        True,
    ),
    "simulation-float64": DeviceProfile(
        "simulation-float64",
        "Offline float64 control",
        "simulation",
        (48000, 96000),
        "float64",
        "SciPy float64 SOS simulation",
        "Harness implementation; numerical control, no live device",
        (Route("filter", 1, 100),),
        True,
    ),
}


def finite(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number
