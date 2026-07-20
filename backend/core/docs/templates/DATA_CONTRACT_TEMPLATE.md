<!-- Copy this file to <app>/docs/DATA_CONTRACT.md and fill in. Delete this comment line. -->

# Data Contract — <App Display Name>

**Owner app:** `<app_name>`
**Version:** <semver>
**Status:** Active | Draft | Deprecated
**Created:** YYYY-MM-DD
**Purpose:** <what this app's data owns, and explicitly what it does NOT own / which other apps own adjacent concerns>

---

## Change History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | YYYY-MM-DD | AI (Claude) | Initial contract |

---

## Deliberate Deviations
<!-- Omit this entire section if no prior concept/prompt doc exists for this app to deviate from. -->

<one-line framing sentence, then bullets — each: what changed, why, what it resolves>

---

## 1. <ModelName>

**Purpose:** <one or two sentences>
**Table:** `<app>_<model>`
**`<field>` choices:** `a`, `b`, `c`
<!-- Mandatory bold callout line, repeated for every field with choices= — in addition to noting it in the Type column below. -->

| Field | Type | Required | Nullable | Generated | Description |
|-------|------|----------|----------|-----------|--------------|
| id | UUID | — | No | Yes | Primary key |
| ... | ... | ... | ... | ... | ... |

**Validation Rules:**
- <bullet per rule>

**Indexes:** <fields, or omit this line entirely if there are none beyond the PK>

**Soft Delete:** <real contract — field name, manager behavior, query implications — or the literal `N/A — <reason>`>
<!-- Mandatory for every model, even when not applicable — this is the one section that always gets an explicit answer rather than silent omission. -->

**Example:**
```json
{ ... }
```

**Cross-App Dependencies:** <omit this line entirely if none>
**Security Notes:** <omit this line entirely if none>

---

## 2. <NextModel>
...

---

## Request/Response Payload Contracts
<!-- Omit this entire section if the app has no non-model payload shapes (e.g. a service's decision-output). -->

### <PayloadName>

**Purpose:** ...
**Shape:**
```json
{ ... }
```
**Produced by:** `<module>.<function>`
**Consumed by:** <which app/endpoint>

---

## Cross-App Dependencies

<which other apps this app's models reference, and which other apps reference this app's models — per CLAUDE.md §4>

---

## Soft Delete

<app-wide summary of the per-model Soft Delete answers above, or `N/A — <reason>` if no model in this app uses it>
