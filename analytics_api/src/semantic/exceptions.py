"""Exceptions for the Semantic Layer."""


class SemanticLayerError(Exception):
    """Base exception for semantic layer errors."""


class AttributeNotFoundError(SemanticLayerError):
    """Raised when a canonical attribute mapping is missing for a given source."""


class EntityNotFoundError(SemanticLayerError):
    """Raised when a requested canonical entity is not registered."""


class SourceNotFoundError(SemanticLayerError):
    """Raised when an attribute has no mapping for the requested source table."""


class MetricNotFoundError(SemanticLayerError):
    """Raised when a requested metric is not in the registry."""


class RelationshipNotFoundError(SemanticLayerError):
    """Raised when a requested relationship name is not registered."""


class NoJoinPathError(SemanticLayerError):
    """Raised when no join path exists between two requested sources."""


class SQLInjectionGuardError(SemanticLayerError):
    """Raised when an unrecognized or unsafe identifier is detected."""
