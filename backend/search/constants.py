"""The searchable-type catalogue and stable constants for the search app.

This app owns no table, so nothing here is a model choice field. What it does
own is the **catalogue of searchable types** — and that catalogue is the whole
design of this app expressed as data rather than as code.

Every fact that differs between one searchable type and the next lives in a
``SearchableType`` row: which app owns it, which permission opens a result,
where the "see all" link goes, and — the detail most likely to be got wrong —
*which query parameter that owning app's list endpoint actually reads*. Seven
apps call it ``search``; ``institutions`` calls it ``q``. Hardcoding one of
those two would produce a "see all" link that silently returns the unfiltered
list, which looks like a search bug rather than a broken link.

Keeping this declarative buys three things:

* ``GET /api/v1/search/types/`` serves the catalogue straight from here, so the
  frontend builds its filter chips from the server rather than from a hardcoded
  list that goes stale the moment a tenth type is added.
* ``search/registry.py`` derives its forward policy dependencies from the same
  rows, so a type can never be searchable without the policy engine knowing
  which permission a user needs to open its results.
* The selectors iterate it, so adding a type is one row plus one resolver entry
  rather than an edit in five files.

Nothing here imports another app. The catalogue names apps as strings; the
actual selector functions are bound in ``search/selectors.py``, which is what
keeps this module import-cheap and free of circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class SearchableTypeKey:
    """Stable ``entity_type`` values, as returned in every hit.

    These are API vocabulary and are relied on by clients to route a result to
    the right screen. Changing one is a breaking change (§22/§29).
    """

    LEAD = "lead"
    APPLICANT = "applicant"
    CLIENT = "client"
    DOCUMENT = "document"
    UPLOADED_FILE = "uploaded_file"
    INSTITUTION = "institution"
    PROGRAM = "program"
    DOCUMENT_TEMPLATE = "document_template"
    SIGNATORY = "signatory"


class SearchGroup:
    """How the results panel stacks its sections (``concepts/search.txt``).

    People first, then the work attached to them, then the reference catalogues.
    The order is a product decision about what someone at the counter is most
    likely to be looking for, so it belongs on the server with the catalogue
    rather than in each client that renders it.
    """

    PEOPLE = "people"
    WORK = "work"
    REFERENCE = "reference"


@dataclass(frozen=True)
class SearchableType:
    """One record type the global box can find.

    ``list_path`` + ``list_search_param`` together build the "see all" link, and
    they are stored rather than derived because the two differ across apps in a
    way no rule predicts.

    ``detail_path`` is a template with a single ``{id}`` placeholder. It is the
    API path of the record, not a frontend route: this app cannot know the
    client's routing table, and inventing one would be a guess baked into the
    contract.
    """

    key: str
    label: str
    group: str
    app_label: str
    #: Permission needed to open one result — the owning app's retrieve endpoint.
    detail_permission_key: str
    #: Permission needed to follow "see all" — the owning app's list endpoint.
    list_permission_key: str
    list_path: str
    #: The query parameter the owning list endpoint reads. ``search`` everywhere
    #: except the catalogue, which reads ``q``.
    list_search_param: str
    detail_path: str
    #: The fields a query is matched against, for the catalogue endpoint. These
    #: are the *owning selector's* fields, restated for a client's benefit; the
    #: selector remains the authority.
    matched_fields: tuple[str, ...] = field(default_factory=tuple)


#: The nine searchable types, in the order the results panel renders them.
#:
#: **Why these nine and not more.** A type earns a place here only if it has a
#: name of its own that a person could plausibly type. Journeys, offers, and
#: checklists have none — they are identified by the applicant they belong to
#: and are reached from that applicant's record, so searching them separately
#: would return rows a user cannot recognise (``concepts/search.txt`` —
#: "Constraints").
SEARCHABLE_TYPES: tuple[SearchableType, ...] = (
    SearchableType(
        key=SearchableTypeKey.APPLICANT,
        label="Applicants",
        group=SearchGroup.PEOPLE,
        app_label="applicants",
        detail_permission_key="applicants.applicant.read",
        list_permission_key="applicants.applicant.list",
        list_path="/api/v1/applicants/",
        list_search_param="search",
        detail_path="/api/v1/applicants/{id}/",
        matched_fields=("full_name", "email", "contact_number", "passport_number"),
    ),
    SearchableType(
        key=SearchableTypeKey.LEAD,
        label="Leads",
        group=SearchGroup.PEOPLE,
        app_label="leads",
        detail_permission_key="leads.lead.read",
        list_permission_key="leads.lead.list",
        list_path="/api/v1/leads/",
        list_search_param="search",
        detail_path="/api/v1/leads/{id}/",
        matched_fields=("full_name", "email", "contact_number"),
    ),
    SearchableType(
        key=SearchableTypeKey.CLIENT,
        label="Clients",
        group=SearchGroup.PEOPLE,
        app_label="clients",
        detail_permission_key="clients.client.read",
        list_permission_key="clients.client.list",
        list_path="/api/v1/clients/",
        list_search_param="search",
        detail_path="/api/v1/clients/{id}/",
        matched_fields=("name", "spokesperson_name"),
    ),
    SearchableType(
        key=SearchableTypeKey.DOCUMENT,
        label="Documents",
        group=SearchGroup.WORK,
        app_label="documents",
        detail_permission_key="documents.document.read",
        list_permission_key="documents.document.list",
        list_path="/api/v1/documents/",
        list_search_param="search",
        detail_path="/api/v1/documents/{id}/",
        matched_fields=("label",),
    ),
    SearchableType(
        key=SearchableTypeKey.UPLOADED_FILE,
        label="Files",
        group=SearchGroup.WORK,
        app_label="uploaded_files",
        detail_permission_key="uploaded_files.file.read",
        list_permission_key="uploaded_files.file.list",
        list_path="/api/v1/files/",
        list_search_param="search",
        detail_path="/api/v1/files/{id}/",
        matched_fields=("original_filename",),
    ),
    SearchableType(
        key=SearchableTypeKey.INSTITUTION,
        label="Institutions",
        group=SearchGroup.REFERENCE,
        app_label="institutions",
        detail_permission_key="institutions.institution.read",
        list_permission_key="institutions.institution.list",
        list_path="/api/v1/catalogue/institutions/",
        list_search_param="q",
        detail_path="/api/v1/catalogue/institutions/{id}/",
        matched_fields=("name", "common_name"),
    ),
    SearchableType(
        key=SearchableTypeKey.PROGRAM,
        label="Programs",
        group=SearchGroup.REFERENCE,
        app_label="institutions",
        detail_permission_key="institutions.program.read",
        list_permission_key="institutions.program.list",
        list_path="/api/v1/catalogue/programs/",
        list_search_param="q",
        detail_path="/api/v1/catalogue/programs/{id}/",
        matched_fields=("title",),
    ),
    SearchableType(
        key=SearchableTypeKey.DOCUMENT_TEMPLATE,
        label="Document templates",
        group=SearchGroup.REFERENCE,
        app_label="document_templates",
        detail_permission_key="document_templates.template.read",
        list_permission_key="document_templates.template.list",
        list_path="/api/v1/document-templates/templates/",
        list_search_param="search",
        detail_path="/api/v1/document-templates/templates/{id}/",
        matched_fields=("label", "key"),
    ),
    SearchableType(
        key=SearchableTypeKey.SIGNATORY,
        label="Signatories",
        group=SearchGroup.REFERENCE,
        app_label="document_templates",
        detail_permission_key="document_templates.signatory.read",
        list_permission_key="document_templates.signatory.list",
        list_path="/api/v1/document-templates/signatories/",
        list_search_param="search",
        detail_path="/api/v1/document-templates/signatories/{id}/",
        matched_fields=("name",),
    ),
)

#: Catalogue by key, for O(1) lookup when validating ``?types=``.
SEARCHABLE_TYPES_BY_KEY: dict[str, SearchableType] = {entry.key: entry for entry in SEARCHABLE_TYPES}

#: Every valid ``?types=`` value, in catalogue order.
SEARCHABLE_TYPE_KEYS: tuple[str, ...] = tuple(entry.key for entry in SEARCHABLE_TYPES)

#: Shortest query this app will run.
#:
#: One character matches a large fraction of every table through ``icontains``,
#: which turns a stray keystroke into nine full scans returning nothing a person
#: could use. Two is the point at which the query is plausibly intentional.
#: Enforced in the serializer, so the refusal is a documented 400 rather than a
#: slow, useless 200.
MIN_QUERY_LENGTH: int = 2

#: Longest query accepted. Matches the ``max_length=150`` the catalogue filters
#: already impose, so this app cannot forward a value another app would reject.
MAX_QUERY_LENGTH: int = 150

#: Hits returned per type before a caller must follow ``list_url``.
#:
#: Five is a results-panel section, not a list view. The bucket's ``total`` is
#: always the real count, so the number a user reads is never the length of this
#: slice (``concepts/search.txt`` — "Results panel").
DEFAULT_LIMIT_PER_TYPE: int = 5

#: Upper bound on the caller-supplied ``limit_per_type``.
#:
#: This is the cap that stops search being an export surface. Nine types at
#: twenty rows is a large but bounded response; without a ceiling, a caller
#: could page the whole database through a box that applies no filters
#: (``concepts/search.txt`` — "Constraints").
MAX_LIMIT_PER_TYPE: int = 20


#: Throttle scope for the query endpoint. The rate is set in settings, next to
#: the authenticate scopes; see ``search/throttling.py`` for why this endpoint
#: gets a bucket of its own rather than sharing the project-wide ``user`` rate.
THROTTLE_SCOPE_SEARCH: str = "search_query"


class ErrorCode:
    """Stable error codes, `APP_RESOURCE_REASON` per §7.

    Only one, deliberately. Bad input — a one-character query, an unknown
    ``types`` key — returns the project-wide ``VALIDATION_ERROR`` from
    ``core.exceptions.global_exception_handler``, with the offending field named
    in ``error.details``, exactly as every other app in the project does. An
    app-specific ``SEARCH_QUERY_INVALID`` would read as more precise and would
    in fact be worse: a client that already branches on ``VALIDATION_ERROR``
    everywhere would need a special case for this one endpoint, and
    ``error.details`` already carries the specificity.
    """

    ACTOR_FORBIDDEN = "SEARCH_ACTOR_FORBIDDEN"
