# Models

The unified domain model that all parser tracks produce. Documents are either **procurement** (X80–X89, using `AwardInfo`/`BoQ`/`Item`) or **trade** (X93–X97, using `TradeOrder`/`OrderItem`).

## Document

::: pygaeb.models.document.GAEBDocument
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.document.GAEBInfo
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.document.AwardInfo
    options:
      show_root_heading: true
      members_order: source

## Bill of Quantities

::: pygaeb.models.boq.BoQ
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.boq.Lot
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.boq.BoQBody
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.boq.BoQCtgy
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.boq.BoQBkdn
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.boq.BoQInfo
    options:
      show_root_heading: true
      members_order: source

## Item (Procurement)

::: pygaeb.models.item.Item
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.item.ClassificationResult
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.item.ExtractionResult
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.item.RichText
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.item.QtySplit
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.item.CostEstimate
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.item.Attachment
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.item.ValidationResult
    options:
      show_root_heading: true
      members_order: source

## Trade Order (X93–X97)

::: pygaeb.models.order.TradeOrder
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.order.OrderItem
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.order.OrderInfo
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.order.SupplierInfo
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.order.CustomerInfo
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.order.DeliveryPlaceInfo
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.order.PlannerInfo
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.order.InvoiceInfo
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.models.order.Address
    options:
      show_root_heading: true
      members_order: source

## Enumerations

::: pygaeb.models.enums.DocumentKind
    options:
      show_root_heading: true
      members: true

::: pygaeb.models.enums.SourceVersion
    options:
      show_root_heading: true
      members: true

::: pygaeb.models.enums.ExchangePhase
    options:
      show_root_heading: true
      members: true

::: pygaeb.models.enums.ItemType
    options:
      show_root_heading: true
      members: true

::: pygaeb.models.enums.BkdnType
    options:
      show_root_heading: true
      members: true

::: pygaeb.models.enums.ValidationSeverity
    options:
      show_root_heading: true
      members: true

::: pygaeb.models.enums.ValidationMode
    options:
      show_root_heading: true
      members: true

::: pygaeb.models.enums.ClassificationFlag
    options:
      show_root_heading: true
      members: true

## Document Navigation

::: pygaeb.api.document_api.DocumentAPI
    options:
      show_root_heading: true
      members_order: source
