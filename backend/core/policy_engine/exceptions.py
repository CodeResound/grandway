class PolicyEngineError(Exception):
    pass


class PolicyApplicationNotFoundError(PolicyEngineError):
    pass


class PolicyModelNotFoundError(PolicyEngineError):
    pass


class PolicyEndpointNotFoundError(PolicyEngineError):
    pass


class PolicyCategoryNotFoundError(PolicyEngineError):
    pass


class PolicyDuplicateKeyError(PolicyEngineError):
    pass


class PolicyCircularDependencyError(PolicyEngineError):
    pass


class PolicyLifecycleIncompleteError(PolicyEngineError):
    pass


class PolicyInvalidPermissionKeyError(PolicyEngineError):
    pass


class PolicyInvalidVersionError(PolicyEngineError):
    pass


class PolicyImmutabilityError(PolicyEngineError):
    pass


class PolicyIdentityConflictError(PolicyEngineError):
    pass


class PolicyRegistryConfigError(PolicyEngineError):
    pass


class PolicyDependencyNotFoundError(PolicyEngineError):
    pass


class PolicyVersionConflictError(PolicyEngineError):
    pass
