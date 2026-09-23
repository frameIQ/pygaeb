"""Per-phase element profiles for the DA XML 3.x procurement writer.

Every exchange phase's XSD restricts the shared GAEB library: X83 (tender)
carries no prices, X84 (bid) has no category labels and no position-type
markers, X86 (contract) requires owner, contractor and totals. The writer
consults these tables so it emits only what the target phase allows, in
schema order, and fills the few required slots it can derive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pygaeb.models.enums import ExchangePhase


@dataclass(frozen=True)
class Slots:
    """Allowed child slots of one container, in ``xs:sequence`` order."""

    order: tuple[str, ...]
    required: frozenset[str] = frozenset()

    def allows(self, slot: str) -> bool:
        return slot in self.order

    def requires(self, slot: str) -> bool:
        return slot in self.required


@dataclass(frozen=True)
class PhaseProfile:
    """What one exchange phase's schema accepts for each procurement container."""

    award: Slots
    award_info: Slots
    prj_info: Slots
    boq_info: Slots
    boq_ctgy: Slots
    item: Slots
    markup_item: Slots
    #: X84 allows only ``CompleteText/DetailTxt``; every other phase the full tree.
    description: Literal["full", "detail_only"] = "full"
    #: X84/X86 party blocks (OWN/CTR/CnstSite) must carry an ``<Address>``.
    party_address_required: bool = False
    #: Children of ``<CTR>`` after ``Address`` (X84's tgCTR has no BidderNo).
    ctr_fields: tuple[str, ...] = ("DPNo", "AwardNo", "AcctsPayNo", "BidderNo")


# Pseudo-slots the emitter expands itself: TypeMarker (Provis/LumpSumItem/…),
# UPComp (UPComp1-6), LblUPComp (LblUPComp1-6), CostApproach / CostType (X52).

_AWARD_INFO_LIB = (
    "BoQID", "Cat", "Cur", "CurLbl", "OpenDate", "OpenTime", "EvalEnd", "SubmLoc",
    "CnstStart", "CnstEnd", "ContrNo", "ContrDate", "AcceptType", "WarrDur", "WarrUnit",
)
_PRJ_INFO_LIB = (
    "NamePrj", "PrjID", "LblPrj", "Descrip", "Cur", "CurLbl",
    "BidCommPerm", "AlterBidPerm", "UPFracDig", "CtlgAssign",
)
_BOQ_INFO_LIB = (
    "Name", "LblBoQ", "Date", "OutlCompl", "BoQBkdn", "NoUPComps", "LblUPComp",
    "LblTime", "CtlgAssign", "Totals",
)
_BOQ_INFO_REQUIRED = frozenset({"Name", "LblBoQ", "OutlCompl", "BoQBkdn"})
_ITEM_LIB = (
    "TypeMarker", "UPBkdn", "CONo", "COStatus", "QtyTBD", "Qty", "QtySplit", "QU", "CtlgAssign",
    "UP", "UPComp", "DiscountPcnt", "IT", "VAT", "Description", "CostApproach",
)
_MARKUP_LIB = (
    "MarkupType", "MarkupSubQty", "ITMarkup", "Markup", "DiscountPcnt", "IT",
    "Description", "CtlgAssign",
)

LIB = PhaseProfile(
    award=Slots(("DP", "AwardInfo", "OWN", "CTR", "CnstSite", "BoQ")),
    award_info=Slots(_AWARD_INFO_LIB),
    prj_info=Slots(_PRJ_INFO_LIB),
    boq_info=Slots(_BOQ_INFO_LIB, _BOQ_INFO_REQUIRED),
    boq_ctgy=Slots(("LblTx", "CtlgAssign", "BoQBody", "Totals"), frozenset({"LblTx"})),
    item=Slots(_ITEM_LIB),
    markup_item=Slots(_MARKUP_LIB, frozenset({"MarkupType", "Description"})),
)

X83 = PhaseProfile(
    award=Slots(("DP", "AwardInfo", "OWN", "CnstSite", "BoQ")),
    award_info=Slots(_AWARD_INFO_LIB),
    prj_info=Slots(_PRJ_INFO_LIB),
    boq_info=Slots(tuple(s for s in _BOQ_INFO_LIB if s != "Totals"), _BOQ_INFO_REQUIRED),
    boq_ctgy=Slots(("LblTx", "CtlgAssign", "BoQBody"), frozenset({"LblTx"})),
    item=Slots(
        ("TypeMarker", "UPBkdn", "CONo", "COStatus", "QtyTBD", "Qty", "QtySplit", "QU",
         "CtlgAssign", "VAT", "Description"),
        frozenset({"QU"}),
    ),
    markup_item=Slots(
        ("MarkupType", "MarkupSubQty", "Description", "CtlgAssign"),
        frozenset({"MarkupType", "Description"}),
    ),
)

X84 = PhaseProfile(
    award=Slots(("DP", "AwardInfo", "CTR", "BoQ"), frozenset({"CTR", "BoQ"})),
    award_info=Slots(("BoQID", "Cur", "CurLbl")),
    prj_info=Slots(("NamePrj", "PrjID", "LblPrj"), frozenset({"NamePrj"})),
    boq_info=Slots(("Name", "BoQBkdn", "Totals"), frozenset({"Name", "BoQBkdn"})),
    boq_ctgy=Slots(("BoQBody", "Totals"), frozenset({"Totals"})),
    item=Slots(("Qty", "UP", "UPComp", "DiscountPcnt", "IT", "VAT", "Description")),
    markup_item=Slots(("ITMarkup", "Markup", "DiscountPcnt", "IT", "Description")),
    description="detail_only",
    party_address_required=True,
    ctr_fields=("DPNo", "AwardNo", "AcctsPayNo"),
)

X86 = PhaseProfile(
    award=Slots(("DP", "AwardInfo", "OWN", "CTR", "CnstSite", "BoQ"), frozenset({"OWN", "CTR"})),
    award_info=Slots((
        "Cur", "CurLbl", "CnstStart", "CnstEnd", "ContrNo", "ContrDate", "AcceptType",
        "WarrDur", "WarrUnit",
    )),
    prj_info=Slots(_PRJ_INFO_LIB),
    boq_info=Slots(_BOQ_INFO_LIB, _BOQ_INFO_REQUIRED),
    boq_ctgy=Slots(("LblTx", "CtlgAssign", "BoQBody", "Totals"), frozenset({"LblTx", "Totals"})),
    item=Slots(_ITEM_LIB),
    markup_item=Slots(
        _MARKUP_LIB, frozenset({"MarkupType", "Description", "ITMarkup", "Markup"}),
    ),
    party_address_required=True,
)

#: Fallback for phases without a dedicated profile (X80, X85, X87-X89, Z-phases,
#: X52 …): the library shape plus the X52-only calculation elements.
GENERIC = PhaseProfile(
    award=LIB.award,
    award_info=LIB.award_info,
    prj_info=LIB.prj_info,
    boq_info=Slots((*_BOQ_INFO_LIB, "CostType"), _BOQ_INFO_REQUIRED),
    boq_ctgy=LIB.boq_ctgy,
    item=LIB.item,
    markup_item=LIB.markup_item,
)

PROFILES: dict[ExchangePhase, PhaseProfile] = {
    ExchangePhase.X81: LIB,
    ExchangePhase.X82: LIB,
    ExchangePhase.X83: X83,
    ExchangePhase.X84: X84,
    ExchangePhase.X86: X86,
}


def profile_for(phase: ExchangePhase) -> PhaseProfile:
    """Return the profile for *phase* (D-phases map to their X form)."""
    return PROFILES.get(phase.normalized(), GENERIC)
