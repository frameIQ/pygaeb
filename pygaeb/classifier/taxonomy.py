"""Three-level classification taxonomy for construction element types."""

from __future__ import annotations

TAXONOMY: dict[str, dict[str, list[str]]] = {
    "Structural": {
        "Wall": [
            "Interior Wall", "Exterior Wall", "Curtain Wall", "Partition Wall", "Retaining Wall"
        ],
        "Floor": ["Ground Floor Slab", "Suspended Floor", "Screed", "Raised Floor"],
        "Roof": ["Flat Roof", "Pitched Roof", "Green Roof", "Roof Structure"],
        "Foundation": ["Strip Foundation", "Pad Foundation", "Pile Foundation", "Raft Foundation"],
        "Column": ["Concrete Column", "Steel Column", "Timber Column"],
        "Beam": ["Concrete Beam", "Steel Beam", "Timber Beam", "Lintel"],
    },
    "Finishes": {
        "Door": ["Single Door", "Double Door", "Fire Door", "Sliding Door", "Revolving Door"],
        "Window": ["Fixed Window", "Opening Window", "Skylight", "Curtain Wall Panel"],
        "Ceiling": ["Suspended Ceiling", "Plasterboard Ceiling", "Acoustic Ceiling"],
        "Cladding": ["External Cladding", "Internal Cladding", "Render", "Natural Stone"],
        "Flooring": ["Tile", "Carpet", "Vinyl", "Wood Flooring", "Epoxy"],
    },
    "Roofing": {
        "Roof Covering": ["Flat Roof Membrane", "Tiles", "Metal Sheets", "Slate"],
        "Insulation": ["Thermal Insulation", "Acoustic Insulation", "Waterproofing"],
        "Drainage": ["Gutter", "Downpipe", "Roof Drain", "Overflow"],
        "Flashing": ["Lead Flashing", "Zinc Flashing", "Aluminium Flashing"],
    },
    "MEP-Mechanical": {
        "Duct": ["Supply Duct", "Extract Duct", "Flexible Duct"],
        "Air Handling Unit": ["AHU", "Rooftop Unit", "Fan Coil Unit"],
        "Fan": ["Centrifugal Fan", "Axial Fan", "Inline Fan"],
        "Diffuser": ["Supply Diffuser", "Return Grille", "Linear Diffuser"],
    },
    "MEP-Electrical": {
        "Cable": ["Power Cable", "Data Cable", "Fibre Optic", "Control Cable"],
        "Panel": ["Distribution Board", "Main Switchboard", "Sub-Panel"],
        "Luminaire": ["Recessed Light", "Surface Light", "Emergency Lighting", "External Light"],
        "Socket": ["Power Socket", "Data Socket", "Floor Box"],
        "Conduit": ["Metal Conduit", "PVC Conduit", "Cable Tray", "Cable Ladder"],
    },
    "MEP-Plumbing": {
        "Pipe": ["Supply Pipe", "Drain Pipe", "Vent Pipe", "Rainwater Pipe"],
        "Valve": ["Gate Valve", "Ball Valve", "Check Valve", "Pressure Reducing Valve"],
        "Pump": ["Circulating Pump", "Booster Pump", "Sump Pump"],
        "Sanitary Fixture": ["WC", "Washbasin", "Shower", "Bath", "Urinal", "Sink"],
    },
    "Sitework": {
        "Excavation": ["Topsoil Strip", "Bulk Excavation", "Trench Excavation"],
        "Paving": ["Asphalt", "Concrete Paving", "Block Paving", "Kerb"],
        "Landscaping": ["Planting", "Turf", "Irrigation", "Tree"],
        "Fence": ["Timber Fence", "Metal Fence", "Security Fence", "Gate"],
    },
    "Preliminaries": {
        "Site Setup": ["Site Hut", "Hoarding", "Temporary Fencing", "Site Signage"],
        "Scaffolding": ["Independent Scaffold", "System Scaffold", "Mobile Tower"],
        "Welfare": ["Welfare Unit", "Toilet", "Canteen", "Drying Room"],
        "Temp Works": ["Tower Crane", "Hoist", "Temporary Propping", "Dewatering"],
    },
    "Other": {
        "Unclassifiable": [],
    },
}

ALL_TRADES = list(TAXONOMY.keys())
ALL_ELEMENT_TYPES = [et for trade in TAXONOMY.values() for et in trade]


def get_subtypes(trade: str, element_type: str) -> list[str]:
    return TAXONOMY.get(trade, {}).get(element_type, [])


def is_valid_trade(trade: str) -> bool:
    return trade in TAXONOMY


def is_valid_element_type(trade: str, element_type: str) -> bool:
    return element_type in TAXONOMY.get(trade, {})
