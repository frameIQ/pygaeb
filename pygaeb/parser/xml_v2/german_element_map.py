"""Mapping of German DA XML 2.x element names to English DA XML 3.x equivalents."""

from __future__ import annotations

GERMAN_TO_ENGLISH: dict[str, str] = {
    # Root / structure
    "GAEB": "GAEB",
    "GAEBInfo": "GAEBInfo",
    "Vergabe": "Award",
    "VergabeInfo": "AwardInfo",
    "Leistungsverzeichnis": "BoQ",
    "LVInfo": "BoQInfo",
    "LVGliederung": "BoQBkdn",
    "LVBereich": "BoQBody",
    "LVGruppe": "BoQCtgy",
    "Positionsliste": "Itemlist",
    "Position": "Item",

    # Award info fields
    "Projekt": "Prj",
    "ProjektName": "PrjName",
    "Auftraggeber": "OWN",
    "Waehrung": "Cur",
    "VergabeArt": "PrcTyp",
    "Datum": "Dp",

    # BoQ info / breakdown
    "Los": "Lot",
    "OZEbene": "BoQLevel",
    "Teilposition": "Item",
    "Indexposition": "Index",

    # Item fields
    "OZ": "RNoPart",
    "Kurztext": "ShortText",
    "Langtext": "LongText",
    "Menge": "Qty",
    "Mengeneinheit": "QU",
    "Einheitspreis": "UP",
    "Gesamtbetrag": "IT",
    "Positionsart": "ItemTag",
    "Teilmengen": "QtySplit",

    # Item types
    "Normalposition": "NormalItem",
    "Pauschalposition": "LumpSumItem",
    "Alternativposition": "AlternativeItem",
    "Bedarfsposition": "ContingencyItem",
    "Textposition": "TextItem",
    "Zuschlagsposition": "SurchargeItem",
    "Nachtragsposition": "SupplementItem",

    # Text / richtext
    "Beschreibung": "Description",
    "Volltext": "CompleteText",
    "Kurzfassung": "OutlineText",
    "Textblock": "Textblock",

    # GAEBInfo fields
    "Version": "Version",
    "Programmsystem": "ProgSystem",
    "ProgrammVersion": "ProgSystemVersion",

    # Misc
    "Bezeichnung": "LblTx",
    "Bemerkung": "Remark",
    "Anlage": "Attachment",
    "Dateiname": "Filename",
    "MimeTyp": "MimeType",
    "Daten": "Data",
    "Aufmassnummer": "CONo",
    "Name": "Name",
}

ENGLISH_TO_GERMAN: dict[str, str] = {v: k for k, v in GERMAN_TO_ENGLISH.items()}
# Resolve ambiguity: "Item" maps to both "Position" and "Teilposition".
# In BoQ context (element tags), the correct German name is "Position".
ENGLISH_TO_GERMAN["Item"] = "Position"
