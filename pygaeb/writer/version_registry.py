"""Version metadata registry for GAEB DA XML output generation."""

from __future__ import annotations

from dataclasses import dataclass, field

from pygaeb.models.enums import ExchangePhase, SourceVersion


@dataclass(frozen=True)
class VersionMeta:
    """Metadata describing a specific GAEB DA XML version's output requirements."""

    namespace: str
    version_tag: str
    lang: str  # "en" for 3.x, "de" for 2.x
    supports_bim_guid: bool = True
    supports_attachments: bool = True
    supports_change_order: bool = True
    supports_long_text_cdata: bool = True
    unsupported_fields: tuple[str, ...] = field(default_factory=tuple)


VERSION_REGISTRY: dict[SourceVersion, VersionMeta] = {
    SourceVersion.DA_XML_33: VersionMeta(
        namespace="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3",
        version_tag="3.3",
        lang="en",
    ),
    SourceVersion.DA_XML_32: VersionMeta(
        namespace="http://www.gaeb.de/GAEB_DA_XML/DA86/3.2",
        version_tag="3.2",
        lang="en",
        supports_bim_guid=False,
        unsupported_fields=("bim_guid",),
    ),
    SourceVersion.DA_XML_31: VersionMeta(
        namespace="http://www.gaeb.de/GAEB_DA_XML/DA86/3.1",
        version_tag="3.1",
        lang="en",
        supports_bim_guid=False,
        unsupported_fields=("bim_guid",),
    ),
    SourceVersion.DA_XML_30: VersionMeta(
        namespace="http://www.gaeb.de/GAEB_DA_XML/200407",
        version_tag="3.0",
        lang="en",
        supports_bim_guid=False,
        supports_attachments=False,
        supports_change_order=False,
        unsupported_fields=("bim_guid", "attachments", "change_order_number"),
    ),
    SourceVersion.DA_XML_21: VersionMeta(
        namespace="http://www.gaeb.de/GAEB_DA_XML/200407",
        version_tag="2.1",
        lang="de",
        supports_bim_guid=False,
        supports_attachments=False,
        supports_change_order=False,
        unsupported_fields=("bim_guid", "attachments", "change_order_number"),
    ),
    SourceVersion.DA_XML_20: VersionMeta(
        namespace="http://www.gaeb.de/GAEB_DA_XML/200407",
        version_tag="2.0",
        lang="de",
        supports_bim_guid=False,
        supports_attachments=False,
        supports_change_order=False,
        unsupported_fields=("bim_guid", "attachments", "change_order_number"),
    ),
}

WRITABLE_VERSIONS = frozenset(VERSION_REGISTRY.keys())


def trade_namespace(phase: ExchangePhase, version: SourceVersion) -> str:
    """Build the namespace URI for a trade phase document."""
    phase_num = phase.value.lstrip("X")
    ver = version.value
    return f"http://www.gaeb.de/GAEB_DA_XML/DA{phase_num}/{ver}"


def cost_namespace(phase: ExchangePhase, version: SourceVersion) -> str:
    """Build the namespace URI for a cost phase document (X50, X51)."""
    phase_num = phase.value.lstrip("X")
    ver = version.value
    return f"http://www.gaeb.de/GAEB_DA_XML/DA{phase_num}/{ver}"


def qty_namespace(phase: ExchangePhase, version: SourceVersion) -> str:
    """Build the namespace URI for a quantity determination document (X31)."""
    phase_num = phase.value.lstrip("X")
    ver = version.value
    return f"http://www.gaeb.de/GAEB_DA_XML/DA{phase_num}/{ver}"
