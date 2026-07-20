from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination
from core.policy_engine.exceptions import (
    PolicyApplicationNotFoundError,
    PolicyEndpointNotFoundError,
)
from core.policy_engine.selectors import (
    get_application_by_key,
    get_endpoint_by_permission_key,
    get_endpoint_changelog,
    get_endpoint_dependencies,
    get_endpoint_versions,
    get_registered_apps,
    get_ui_permission_tree,
)
from core.policy_engine.serializers import (
    PolicyApplicationDetailSerializer,
    PolicyApplicationSerializer,
    PolicyChangeLogSerializer,
    PolicyEndpointVersionSerializer,
)
from core.responses import success_response


def _require_staff(request: Request) -> None:
    if not request.user.is_authenticated:
        from rest_framework.exceptions import NotAuthenticated

        raise NotAuthenticated("Authentication required.")
    if not request.user.is_staff:
        raise PermissionDenied("Staff access required.")


class PolicyApplicationListView(APIView):
    """
    GET /api/v1/policy/apps/
    Returns all active registered policy applications.
    Auth: IsAuthenticated + is_staff
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        _require_staff(request)
        apps = get_registered_apps()
        paginator = StandardPagination()
        page = paginator.paginate_queryset(apps, request)
        if page is not None:
            serializer = PolicyApplicationSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = PolicyApplicationSerializer(apps, many=True)
        return success_response(data=serializer.data, message="Policy applications retrieved.")


class PolicyApplicationDetailView(APIView):
    """
    GET /api/v1/policy/apps/<app_key>/
    Returns app detail with its models and endpoints.
    Auth: IsAuthenticated + is_staff
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, app_key: str) -> Response:
        _require_staff(request)
        try:
            app = get_application_by_key(app_key)
        except PolicyApplicationNotFoundError as exc:
            raise NotFound(f"Application '{app_key}' not found.") from exc
        serializer = PolicyApplicationDetailSerializer(app)
        return success_response(data=serializer.data, message="Policy application retrieved.")


class UIPermissionTreeView(APIView):
    """
    GET /api/v1/policy/permissions/tree/?app=<app_key>
    Returns UI-friendly permission tree grouped by category.
    Auth: IsAuthenticated + is_staff
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        _require_staff(request)
        app_key = request.query_params.get("app")
        include_inactive = request.query_params.get("include_inactive", "").lower() == "true"
        tree = get_ui_permission_tree(app_key=app_key, include_inactive=include_inactive)
        return success_response(data=tree, message="Permission tree retrieved.")


class PolicyEndpointDetailView(APIView):
    """
    GET /api/v1/policy/endpoints/<permission_key>/
    Returns endpoint detail including metadata.
    Auth: IsAuthenticated + is_staff
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, permission_key: str) -> Response:
        _require_staff(request)
        try:
            from core.policy_engine.serializers import PolicyEndpointSerializer

            endpoint = get_endpoint_by_permission_key(permission_key)
            serializer = PolicyEndpointSerializer(endpoint)
            return success_response(data=serializer.data, message="Endpoint retrieved.")
        except PolicyEndpointNotFoundError as exc:
            raise NotFound(f"Endpoint '{permission_key}' not found.") from exc


class EndpointDependencyView(APIView):
    """
    GET /api/v1/policy/endpoints/<permission_key>/dependencies/
    Returns forward and backward dependency info for an endpoint.
    Auth: IsAuthenticated + is_staff
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, permission_key: str) -> Response:
        _require_staff(request)
        try:
            deps = get_endpoint_dependencies(permission_key)
            return success_response(data=deps, message="Endpoint dependencies retrieved.")
        except PolicyEndpointNotFoundError as exc:
            raise NotFound(f"Endpoint '{permission_key}' not found.") from exc


class EndpointVersionListView(APIView):
    """
    GET /api/v1/policy/endpoints/<permission_key>/versions/
    Returns version history for an endpoint.
    Auth: IsAuthenticated + is_staff
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, permission_key: str) -> Response:
        _require_staff(request)
        try:
            versions = get_endpoint_versions(permission_key)
            serializer = PolicyEndpointVersionSerializer(versions, many=True)
            return success_response(data=serializer.data, message="Endpoint versions retrieved.")
        except PolicyEndpointNotFoundError as exc:
            raise NotFound(f"Endpoint '{permission_key}' not found.") from exc


class EndpointChangelogView(APIView):
    """
    GET /api/v1/policy/endpoints/<permission_key>/changelog/
    Returns changelog history for an endpoint.
    Auth: IsAuthenticated + is_staff
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, permission_key: str) -> Response:
        _require_staff(request)
        try:
            changelog = get_endpoint_changelog(permission_key)
            paginator = StandardPagination()
            page = paginator.paginate_queryset(changelog, request)
            if page is not None:
                serializer = PolicyChangeLogSerializer(page, many=True)
                return paginator.get_paginated_response(serializer.data)
            serializer = PolicyChangeLogSerializer(changelog, many=True)
            return success_response(data=serializer.data, message="Endpoint changelog retrieved.")
        except PolicyEndpointNotFoundError as exc:
            raise NotFound(f"Endpoint '{permission_key}' not found.") from exc
