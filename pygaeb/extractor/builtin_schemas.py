"""Built-in starter schemas for common construction element types.

These are examples and convenience — users are expected to define their own
schemas tailored to their specific data needs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DoorSpec(BaseModel):
    """Structured specification for door items."""

    door_type: str = Field("", description="single, double, sliding, revolving, folding")
    width_mm: int | None = Field(None, description="Door leaf width in millimetres")
    height_mm: int | None = Field(None, description="Door leaf height in millimetres")
    material: str = Field("", description="Primary material: wood, steel, aluminium, glass")
    fire_rating: str | None = Field(
        None, description="Fire resistance class: T30, T60, T90, EI30, EI60, EI90"
    )
    smoke_tight: bool = Field(False, description="Whether the door is smoke-tight (Rauchdicht)")
    glazing: bool = Field(False, description="Whether the door has glass panels")
    acoustic_rating_db: int | None = Field(
        None, description="Sound insulation rating in dB (Rw value)"
    )
    surface_finish: str = Field(
        "", description="Surface treatment: painted, lacquered, veneer, laminate, powder-coated"
    )
    hardware: str = Field("", description="Lock, handle, closer type if specified")
    frame_material: str = Field(
        "", description="Frame/Zarge material: steel, wood, aluminium"
    )
    din_standard: str | None = Field(None, description="Referenced DIN/EN standard")


class WindowSpec(BaseModel):
    """Structured specification for window items."""

    window_type: str = Field("", description="fixed, casement, tilt-and-turn, sliding, skylight")
    width_mm: int | None = Field(None, description="Window width in millimetres")
    height_mm: int | None = Field(None, description="Window height in millimetres")
    frame_material: str = Field(
        "", description="Frame material: PVC, aluminium, timber, timber-alu"
    )
    glazing_type: str = Field("", description="single, double, triple glazing")
    u_value: float | None = Field(
        None, description="Thermal transmittance Uw in W/(m²·K)"
    )
    sound_insulation_db: int | None = Field(
        None, description="Sound insulation Rw in dB"
    )
    security_class: str | None = Field(None, description="RC class: RC1, RC2, RC3")
    color: str = Field("", description="Frame colour / RAL number")
    din_standard: str | None = Field(None, description="Referenced DIN/EN standard")


class WallSpec(BaseModel):
    """Structured specification for wall items."""

    wall_type: str = Field("", description="interior, exterior, partition, curtain, retaining")
    material: str = Field("", description="Primary material: masonry, concrete, drywall, timber")
    thickness_mm: int | None = Field(None, description="Wall thickness in millimetres")
    fire_rating: str | None = Field(
        None, description="Fire resistance class: F30, F60, F90, REI60"
    )
    acoustic_rating_db: int | None = Field(
        None, description="Sound insulation Rw in dB"
    )
    insulated: bool = Field(False, description="Whether thermal insulation is included")
    load_bearing: bool = Field(
        False, description="Whether the wall is load-bearing (tragend)"
    )
    surface_finish: str = Field(
        "", description="Surface treatment: plaster, render, paint, exposed"
    )
    block_format: str = Field("", description="Masonry block format if applicable: NF, DF, 2DF")
    din_standard: str | None = Field(None, description="Referenced DIN/EN standard")


class PipeSpec(BaseModel):
    """Structured specification for pipe items."""

    pipe_type: str = Field("", description="supply, drain, vent, rainwater, gas, heating")
    material: str = Field(
        "", description="Material: copper, steel, PE, PP, PVC, cast iron, stainless"
    )
    diameter_mm: int | None = Field(None, description="Nominal diameter DN in millimetres")
    wall_thickness_mm: float | None = Field(None, description="Pipe wall thickness in mm")
    pressure_rating_bar: float | None = Field(None, description="Pressure rating PN in bar")
    insulated: bool = Field(False, description="Whether pipe insulation is included")
    insulation_thickness_mm: int | None = Field(None, description="Insulation thickness in mm")
    connection_type: str = Field(
        "",
        description="Connection method: welded, pressed, soldered, push-fit, threaded",
    )
    medium: str = Field(
        "", description="Conveyed medium: cold water, hot water, waste, gas, heating"
    )
    din_standard: str | None = Field(None, description="Referenced DIN/EN standard")
