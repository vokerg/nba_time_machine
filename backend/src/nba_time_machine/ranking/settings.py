"""Shared validated settings and bounded numeric transforms."""
from pydantic import BaseModel, ConfigDict, model_validator


def clamp(value):
    return max(0.0, min(float(value), 1.0))


def ramp(raw, floor, peak):
    return clamp((raw - floor) / (peak - floor))


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    @model_validator(mode="after")
    def ordered(self):
        for name, value in self.model_dump().items():
            if name.endswith("_floor") and name[:-6] + "_peak" in type(self).model_fields:
                if value >= getattr(self, name[:-6] + "_peak"):
                    raise ValueError("floor must be below peak")
        return self

