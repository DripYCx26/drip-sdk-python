# Changelog

All notable changes to the Drip Python SDK are documented here.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses semantic versioning.

## [0.2.0]

### Added

- **Payload Mapping Engine.** Server-side translator from your native JSON
  shape into Drip's canonical usage event. New methods (mirrored on both
  `Drip` and `AsyncDrip`):
  - `create_payload_mapping(...)`
  - `list_payload_mappings()`
  - `get_payload_mapping(mapping_id)`
  - `update_payload_mapping(mapping_id, **patch)`
  - `delete_payload_mapping(mapping_id)`
  - `list_payload_mapping_versions(mapping_id)`
  - `dry_run_payload_mapping(mapping_id, payload)`
  - `ingest_via_mapping(source_name, payload)`

  See the "Payload Mappings — Custom Shapes Without Code Changes" section
  in `FULL_SDK.md` for the full walkthrough.

- **`track_usage` `mode` parameter.** Replaces the removed `charge()` /
  `charge_async()` methods:

  | mode | endpoint | semantics |
  | ---- | -------- | --------- |
  | `"sync"` (default) | `POST /usage` | Billing-aware — creates a charge if a pricing plan matches |
  | `"batch"` | `POST /usage/async` | Queued, returns 202 |
  | `"internal"` | `POST /usage/internal` | Visibility-only, never bills |

- **`unit_type` kwarg as alias for `meter`** on `track_usage()`. Matches the
  Node SDK's `unitType` naming so docs translate cleanly between the two.
  `meter` continues to work (no breaking change for existing callers).

### Removed

- `Drip.charge()`, `Drip.charge_async()`, `AsyncDrip.charge()`,
  `AsyncDrip.charge_async()`, plus the `_RunContext.charge` /
  `_AsyncRunContext.charge` helpers (breaking). They were thin wrappers
  around `POST /usage` / `POST /usage/async`. Migration:

  ```python
  # before
  client.charge(customer_id=..., meter="api_call", quantity=1)
  client.charge_async(customer_id=..., meter="api_call", quantity=1)

  # after
  client.track_usage(customer_id=..., meter="api_call", quantity=1)
  client.track_usage(customer_id=..., meter="api_call", quantity=1, mode="batch")
  ```

  `get_charge()` and `list_charges()` are kept for read-only reconciliation.

### Fixed

- **Pydantic drift on `PricingPlan`.** Backend returns plans without
  `currency` and `pricing_model` fields. `list_pricing_plans()` was
  hard-crashing with a `ValidationError`. Now `currency` defaults to
  `"USDC"`, `pricing_model` is optional, and unknown fields are ignored.

- `TrackUsageResult` / `TrackUsageBatchResult` now accept the response
  shapes from all three endpoints (`/usage`, `/usage/async`,
  `/usage/internal`) instead of strictly requiring the visibility shape.

- Internal `wrap_api_call()` and `StreamMeter` now route through
  `track_usage()` instead of the removed `charge()` method.

## [0.1.2] — historical

Previous baseline. See git history.
