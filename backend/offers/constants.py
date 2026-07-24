"""Enums, error codes, and audit-action names for the offers app.

``StudyLevel`` and ``FeePeriod`` are not defined here — both are shared
vocabulary living in ``core.constants`` (§2/§3). An offer's snapshot records the
qualification level in the same words the catalogue and the journey use, so
"which offers are for master's programs" stays an equality check.
"""

from django.db import models


class OfferStatus(models.TextChoices):
    """Where an offer stands.

    Seven statuses, not the concept's eight. ``awaiting_response`` is collapsed
    into ``ISSUED``: once an institution has issued an offer the consultancy is
    by definition awaiting a response, and two statuses for one state would
    only drift apart as staff forget to advance the second one.

    ``EXPIRED`` is set by a person, never by the system. Nothing in V1 runs on a
    schedule (the ``notifications`` domain does not exist), so an automatic
    expiry would be a promise the deployment cannot keep. ``response_deadline``
    plus the computed ``is_response_overdue`` is what surfaces a lapsed offer.
    """

    DRAFT = "draft", "Draft"
    ISSUED = "issued", "Issued"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    WITHDRAWN = "withdrawn", "Withdrawn"
    DEFERRED = "deferred", "Deferred"
    EXPIRED = "expired", "Expired"


#: Statuses that end the offer. A terminal offer accepts no further decision;
#: it stays visible forever, because the journey's decision trail is the point.
TERMINAL_STATUSES: tuple[str, ...] = (
    OfferStatus.ACCEPTED,
    OfferStatus.REJECTED,
    OfferStatus.WITHDRAWN,
    OfferStatus.DEFERRED,
    OfferStatus.EXPIRED,
)

#: Statuses an offer may hold when a decision is recorded against it.
DECIDABLE_STATUSES: tuple[str, ...] = (
    OfferStatus.DRAFT,
    OfferStatus.ISSUED,
)


class DecisionOutcome(models.TextChoices):
    """What the decision dialog records.

    A strict subset of ``OfferStatus`` — the five terminal states a person can
    select. Kept as its own enum so the request body cannot ask for ``draft``
    or ``issued``, which are not decisions.
    """

    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    WITHDRAWN = "withdrawn", "Withdrawn"
    DEFERRED = "deferred", "Deferred"
    EXPIRED = "expired", "Expired"


#: Outcomes that make no sense without an explanation. Accepting needs no
#: reason — the acceptance is its own explanation — and expiry is a date having
#: passed, which the deadline already records.
REASON_REQUIRED_OUTCOMES: tuple[str, ...] = (
    DecisionOutcome.REJECTED,
    DecisionOutcome.WITHDRAWN,
)


class OfferType(models.TextChoices):
    """Whether the offer still depends on conditions being met."""

    CONDITIONAL = "conditional", "Conditional"
    UNCONDITIONAL = "unconditional", "Unconditional"


class OfferSource(models.TextChoices):
    """Where the offer's institution and program reference came from.

    The concept requires the New/Edit Offer form to make clear "whether the
    offer was created from the catalogue or entered as a manual historical
    record". This is that fact, stored rather than inferred from whether the
    catalogue FKs happen to be null — a catalogue record can be superseded, but
    how the offer was entered never changes.
    """

    CATALOGUE = "catalogue", "From Catalogue"
    MANUAL = "manual", "Manual Entry"


class ConditionType(models.TextChoices):
    """The kind of requirement attached to a conditional offer.

    Taken from ``concepts/offers.txt`` — "Offer conditions". ``OTHER`` carries
    the institution-specific requirements the list cannot anticipate; the
    ``description`` is required regardless of type, so nothing is lost by
    falling back to it.
    """

    ACADEMIC_RESULT = "academic_result", "Final Academic Results"
    ENGLISH_TEST = "english_test", "English Test Results"
    DOCUMENT_SUBMISSION = "document_submission", "Document Submission"
    DEPOSIT_PAYMENT = "deposit_payment", "Deposit Payment"
    INTERVIEW = "interview", "Interview or Verification"
    IDENTITY_CONFIRMATION = "identity_confirmation", "Passport or Identity Confirmation"
    OTHER = "other", "Other"


class ConditionStatus(models.TextChoices):
    """Whether a condition still stands in the way.

    ``NOT_APPLICABLE`` is how a condition is retired. There is no delete
    endpoint: the concept requires that "if a condition is added or changed
    later, the previous state should remain traceable in history".
    """

    PENDING = "pending", "Pending"
    SATISFIED = "satisfied", "Satisfied"
    WAIVED = "waived", "Waived"
    NOT_APPLICABLE = "not_applicable", "Not Applicable"


#: Statuses that no longer block the offer from being complete.
RESOLVED_CONDITION_STATUSES: tuple[str, ...] = (
    ConditionStatus.SATISFIED,
    ConditionStatus.WAIVED,
    ConditionStatus.NOT_APPLICABLE,
)

#: Statuses that require the resolver to say why. Waiving an institution's
#: requirement and declaring one inapplicable are both judgement calls someone
#: will need to defend later; satisfying one is a fact.
CONDITION_NOTE_REQUIRED_STATUSES: tuple[str, ...] = (
    ConditionStatus.WAIVED,
    ConditionStatus.NOT_APPLICABLE,
)


class OfferAuditAction:
    """``audit.AuditEvent.action`` names written by this app."""

    OFFER_CREATED = "offer_created"
    OFFER_UPDATED = "offer_updated"
    OFFER_ISSUED = "offer_issued"
    OFFER_DECISION_RECORDED = "offer_decision_recorded"
    CONDITION_CREATED = "offer_condition_created"
    CONDITION_UPDATED = "offer_condition_updated"
    CONDITION_STATUS_CHANGED = "offer_condition_status_changed"


#: ``audit.AuditEvent.app_label`` value for every event this app records.
AUDIT_APP_LABEL = "offers"

#: ``audit.AuditEvent.entity_type`` values.
#:
#: Condition events are recorded against the **offer**, not the condition, so
#: that ``GET /offers/<id>/history/`` returns one continuous trail. A condition
#: has no history screen of its own, and splitting the log would mean the offer
#: history silently omitted the condition work — which is most of what happens
#: to a conditional offer.
AUDIT_ENTITY_OFFER = "offer"


class ErrorCode:
    """`APP_RESOURCE_REASON` error codes for the offers app (§7)."""

    ACTOR_FORBIDDEN = "OFFERS_ACTOR_FORBIDDEN"

    OFFER_NOT_FOUND = "OFFERS_OFFER_NOT_FOUND"
    CONDITION_NOT_FOUND = "OFFERS_CONDITION_NOT_FOUND"
    JOURNEY_NOT_FOUND = "OFFERS_JOURNEY_NOT_FOUND"

    PROGRAM_REFERENCE_REQUIRED = "OFFERS_PROGRAM_REFERENCE_REQUIRED"
    CATALOGUE_REFERENCE_INVALID = "OFFERS_CATALOGUE_REFERENCE_INVALID"
    REFERENCE_IMMUTABLE = "OFFERS_REFERENCE_IMMUTABLE"
    AMOUNT_INCOMPLETE = "OFFERS_AMOUNT_INCOMPLETE"

    OFFER_NOT_ISSUABLE = "OFFERS_OFFER_NOT_ISSUABLE"
    OFFER_NOT_DECIDABLE = "OFFERS_OFFER_NOT_DECIDABLE"
    DECISION_REASON_REQUIRED = "OFFERS_DECISION_REASON_REQUIRED"
    DEFER_INTAKE_REQUIRED = "OFFERS_DEFER_INTAKE_REQUIRED"
    ACCEPTED_OFFER_EXISTS = "OFFERS_ACCEPTED_OFFER_EXISTS"

    CONDITION_NOTE_REQUIRED = "OFFERS_CONDITION_NOTE_REQUIRED"
