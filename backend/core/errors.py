"""
A central registry of all application-specific error codes.

This module defines unique, machine-readable error codes that can be used
throughout the application for consistent error handling and reporting.
Each error code is associated with a default HTTP status code and a
user-facing detail message.
"""

from collections import defaultdict
from typing import Any, Dict, Tuple, Type

from fastapi import status
from pydantic import BaseModel

# Error code constants
UNAUTHORIZED = "UNAUTHORIZED"
FORBIDDEN = "FORBIDDEN"
USER_NOT_FOUND = "USER_NOT_FOUND"
INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
USER_ALREADY_EXISTS = "USER_ALREADY_EXISTS"
SYSTEM_KIND_NOT_FOUND = "SYSTEM_KIND_NOT_FOUND"
SYSTEM_KIND_ALREADY_EXISTS = "SYSTEM_KIND_ALREADY_EXISTS"
SYSTEM_FLAVOR_NOT_FOUND = "SYSTEM_FLAVOR_NOT_FOUND"
SYSTEM_FLAVOR_ALREADY_EXISTS = "SYSTEM_FLAVOR_ALREADY_EXISTS"
DATA_TYPE_NOT_FOUND = "DATA_TYPE_NOT_FOUND"
DATA_TYPE_ALREADY_EXISTS = "DATA_TYPE_ALREADY_EXISTS"
CREDENTIAL_REF_NOT_FOUND = "CREDENTIAL_REF_NOT_FOUND"
CREDENTIAL_REF_ALREADY_EXISTS = "CREDENTIAL_REF_ALREADY_EXISTS"
SYSTEM_NOT_FOUND = "SYSTEM_NOT_FOUND"
SYSTEM_ALREADY_EXISTS = "SYSTEM_ALREADY_EXISTS"
DATASET_NOT_FOUND = "DATASET_NOT_FOUND"
DATASET_ALREADY_EXISTS = "DATASET_ALREADY_EXISTS"
INVALID_DATASET_KIND = "INVALID_DATASET_KIND"
DATASET_KIND_MISMATCH = "DATASET_KIND_MISMATCH"
DATASET_LINK_NOT_FOUND = "DATASET_LINK_NOT_FOUND"
DATASET_LINK_ALREADY_EXISTS = "DATASET_LINK_ALREADY_EXISTS"
DATASET_LINK_SELF_REFERENCE = "DATASET_LINK_SELF_REFERENCE"
DATASET_LINK_LAYER_ORDER = "DATASET_LINK_LAYER_ORDER"
DATASET_LINK_LAYER_MISSING = "DATASET_LINK_LAYER_MISSING"
DATASET_HAS_ACTIVE_LINKS = "DATASET_HAS_ACTIVE_LINKS"
CAST_RULE_NOT_FOUND = "CAST_RULE_NOT_FOUND"
CAST_RULE_ALREADY_EXISTS = "CAST_RULE_ALREADY_EXISTS"
FIELD_NOT_FOUND = "FIELD_NOT_FOUND"
FIELD_ALREADY_EXISTS = "FIELD_ALREADY_EXISTS"
FIELD_LINK_NOT_FOUND = "FIELD_LINK_NOT_FOUND"
FIELD_LINK_ALREADY_EXISTS = "FIELD_LINK_ALREADY_EXISTS"
FIELD_LINK_SOURCE_DATASET_MISMATCH = "FIELD_LINK_SOURCE_DATASET_MISMATCH"
FIELD_LINK_TARGET_DATASET_MISMATCH = "FIELD_LINK_TARGET_DATASET_MISMATCH"
FIELD_LINK_TARGET_OCCUPIED = "FIELD_LINK_TARGET_OCCUPIED"
FIELD_NON_TECH_REQUIRES_SOURCE = "FIELD_NON_TECH_REQUIRES_SOURCE"
SCHEMA_DATASET_MISMATCH = "SCHEMA_DATASET_MISMATCH"
FIELD_ORIGIN_CONFLICT = "FIELD_ORIGIN_CONFLICT"
FIELD_BINDING_MISSING = "FIELD_BINDING_MISSING"
DATASET_SCHEMA_IN_USE = "DATASET_SCHEMA_IN_USE"
DATASET_SCHEMA_NOT_FOUND = "DATASET_SCHEMA_NOT_FOUND"
DATASET_SCHEMA_ALREADY_EXISTS = "DATASET_SCHEMA_ALREADY_EXISTS"
FIELD_BINDING_NOT_FOUND = "FIELD_BINDING_NOT_FOUND"
FIELD_BINDING_FIELD_ID_ALREADY_EXISTS = "FIELD_BINDING_FIELD_ID_ALREADY_EXISTS"
FIELD_BINDING_POSITION_ALREADY_EXISTS = "FIELD_BINDING_POSITION_ALREADY_EXISTS"
TYPE_INSTANCE_NOT_FOUND = "TYPE_INSTANCE_NOT_FOUND"
TYPE_INSTANCE_SLOT_ALREADY_EXISTS = "TYPE_INSTANCE_SLOT_ALREADY_EXISTS"
TYPE_INSTANCE_SLOT_REQUIRED = "TYPE_INSTANCE_SLOT_REQUIRED"
TYPE_INSTANCE_SLOT_FORBIDDEN = "TYPE_INSTANCE_SLOT_FORBIDDEN"
TYPE_INSTANCE_PARENT_NOT_FOUND = "TYPE_INSTANCE_PARENT_NOT_FOUND"
TYPE_INSTANCE_PARAMS_INVALID = "TYPE_INSTANCE_PARAMS_INVALID"
FIELD_PARENT_NOT_FOUND = "FIELD_PARENT_NOT_FOUND"
FIELD_PARENT_DATASET_MISMATCH = "FIELD_PARENT_DATASET_MISMATCH"
FIELD_CIRCULAR_REFERENCE = "FIELD_CIRCULAR_REFERENCE"
REFRESH_TOKEN_INVALID = "REFRESH_TOKEN_INVALID"
REFRESH_TOKEN_EXPIRED = "REFRESH_TOKEN_EXPIRED"
REFRESH_TOKEN_REVOKED = "REFRESH_TOKEN_REVOKED"
ENTITY_NOT_DELETED = "ENTITY_NOT_DELETED"
HAS_DEPENDENT_ENTITIES = "HAS_DEPENDENT_ENTITIES"
VERSION_CONFLICT = "VERSION_CONFLICT"
CRAWL_RUN_NOT_FOUND = "CRAWL_RUN_NOT_FOUND"
FIELD_CLASSIFICATION_NOT_FOUND = "FIELD_CLASSIFICATION_NOT_FOUND"
TECH_FIELD_TEMPLATE_NOT_FOUND = "TECH_FIELD_TEMPLATE_NOT_FOUND"
TECH_FIELD_TEMPLATE_ALREADY_EXISTS = "TECH_FIELD_TEMPLATE_ALREADY_EXISTS"
TECH_FIELD_TEMPLATE_LAYER_MISMATCH = "TECH_FIELD_TEMPLATE_LAYER_MISMATCH"
TECH_FIELD_TEMPLATE_FIELD_NOT_FOUND = "TECH_FIELD_TEMPLATE_FIELD_NOT_FOUND"
TECH_FIELD_TEMPLATE_FIELD_ALREADY_EXISTS = "TECH_FIELD_TEMPLATE_FIELD_ALREADY_EXISTS"
TECH_TYPE_CODE_NOT_RESOLVABLE = "TECH_TYPE_CODE_NOT_RESOLVABLE"
LAKE_SYNC_NO_SOURCE_SCHEMA = "LAKE_SYNC_NO_SOURCE_SCHEMA"
LAKE_SYNC_TARGET_FLAVOR_MISMATCH = "LAKE_SYNC_TARGET_FLAVOR_MISMATCH"
LAKE_SYNC_UNKNOWN_OVERRIDE_FIELD = "LAKE_SYNC_UNKNOWN_OVERRIDE_FIELD"
LAKE_SYNC_AMBIGUOUS_CAST = "LAKE_SYNC_AMBIGUOUS_CAST"
ENGINE_NOT_FOUND = "ENGINE_NOT_FOUND"
ENGINE_IN_USE = "ENGINE_IN_USE"
ENGINE_INCOMPATIBLE_LINK = "ENGINE_INCOMPATIBLE_LINK"
ENGINE_NOT_ATTACHED = "ENGINE_NOT_ATTACHED"
ENGINE_NOT_RENDERABLE = "ENGINE_NOT_RENDERABLE"
ENGINE_KIND_IMMUTABLE = "ENGINE_KIND_IMMUTABLE"
ENGINE_VERSION_INVALID = "ENGINE_VERSION_INVALID"
ENGINE_CODE_ALREADY_EXISTS = "ENGINE_CODE_ALREADY_EXISTS"

ErrorInfo = Tuple[int, str]


# Mapping of error codes to (HTTP Status Code, Detail Message)
ERROR_MAP = {
    UNAUTHORIZED: (
        status.HTTP_401_UNAUTHORIZED,
        "Unauthorized.",
    ),
    FORBIDDEN: (
        status.HTTP_403_FORBIDDEN,
        "Forbidden.",
    ),
    USER_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested user was not found.",
    ),
    INVALID_CREDENTIALS: (
        status.HTTP_401_UNAUTHORIZED,
        "Incorrect email or password.",
    ),
    USER_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A user with this email already exists.",
    ),
    SYSTEM_KIND_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested system kind was not found.",
    ),
    SYSTEM_KIND_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A system kind with this code already exists.",
    ),
    SYSTEM_FLAVOR_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested system flavor was not found.",
    ),
    SYSTEM_FLAVOR_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A system flavor with this code already exists.",
    ),
    DATA_TYPE_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested data type was not found.",
    ),
    DATA_TYPE_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A data type with this code already exists for the given system flavor.",
    ),
    CREDENTIAL_REF_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested credential reference was not found.",
    ),
    CREDENTIAL_REF_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A credential reference with this provider and path already exists.",
    ),
    SYSTEM_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested system was not found.",
    ),
    SYSTEM_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A system with this code already exists.",
    ),
    DATASET_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested dataset was not found.",
    ),
    DATASET_ALREADY_EXISTS: (
        status.HTTP_409_CONFLICT,
        "A dataset with this system and object name already exists.",
    ),
    INVALID_DATASET_KIND: (
        status.HTTP_400_BAD_REQUEST,
        "The provided dataset kind is invalid.",
    ),
    DATASET_KIND_MISMATCH: (
        status.HTTP_400_BAD_REQUEST,
        "Changing the kind of a dataset is not allowed.",
    ),
    DATASET_LINK_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested dataset link was not found.",
    ),
    DATASET_LINK_ALREADY_EXISTS: (
        status.HTTP_409_CONFLICT,
        "An active dataset link between this source and target already exists.",
    ),
    DATASET_LINK_SELF_REFERENCE: (
        status.HTTP_400_BAD_REQUEST,
        "A dataset cannot link to itself.",
    ),
    DATASET_LINK_LAYER_ORDER: (
        status.HTTP_400_BAD_REQUEST,
        "Target dataset layer must come after source layer.",
    ),
    DATASET_LINK_LAYER_MISSING: (
        status.HTTP_400_BAD_REQUEST,
        "Both source and target datasets must have a layer set.",
    ),
    DATASET_HAS_ACTIVE_LINKS: (
        status.HTTP_409_CONFLICT,
        "Dataset has active lineage links; unlink first.",
    ),
    CAST_RULE_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested cast rule was not found.",
    ),
    CAST_RULE_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A cast rule with this source and target data type already exists.",
    ),
    FIELD_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested field was not found.",
    ),
    FIELD_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A field with this name already exists for the given dataset.",
    ),
    FIELD_LINK_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested field link was not found.",
    ),
    FIELD_LINK_ALREADY_EXISTS: (
        status.HTTP_409_CONFLICT,
        "A field link with this source and target already exists in this dataset link.",
    ),
    FIELD_LINK_SOURCE_DATASET_MISMATCH: (
        status.HTTP_400_BAD_REQUEST,
        "Source field does not belong to the source dataset.",
    ),
    FIELD_LINK_TARGET_DATASET_MISMATCH: (
        status.HTTP_400_BAD_REQUEST,
        "Target field does not belong to the target dataset.",
    ),
    FIELD_LINK_TARGET_OCCUPIED: (
        status.HTTP_409_CONFLICT,
        "Target field already has a source mapping in this dataset link.",
    ),
    FIELD_NON_TECH_REQUIRES_SOURCE: (
        status.HTTP_409_CONFLICT,
        "Non-technical field must have at least one inbound field link.",
    ),
    SCHEMA_DATASET_MISMATCH: (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "The schema does not belong to the specified dataset.",
    ),
    FIELD_ORIGIN_CONFLICT: (
        status.HTTP_409_CONFLICT,
        "Field origin transition is blocked by current FieldLink state.",
    ),
    FIELD_BINDING_MISSING: (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Field has no FieldBinding in the DatasetLink's pinned schema.",
    ),
    DATASET_SCHEMA_IN_USE: (
        status.HTTP_409_CONFLICT,
        "Cannot delete: this dataset schema is pinned by one or more active DatasetLinks.",
    ),
    DATASET_SCHEMA_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested dataset schema was not found.",
    ),
    DATASET_SCHEMA_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A schema with this version already exists for the given dataset.",
    ),
    FIELD_BINDING_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested field binding was not found.",
    ),
    FIELD_BINDING_FIELD_ID_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A binding for this field already exists in the given dataset schema.",
    ),
    FIELD_BINDING_POSITION_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A binding for this position already exists in the given dataset schema.",
    ),
    TYPE_INSTANCE_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested type instance was not found.",
    ),
    TYPE_INSTANCE_SLOT_ALREADY_EXISTS: (
        status.HTTP_400_BAD_REQUEST,
        "A type instance with this slot already exists under the given parent.",
    ),
    TYPE_INSTANCE_SLOT_REQUIRED: (
        status.HTTP_400_BAD_REQUEST,
        "Slot is required when parent_id is set.",
    ),
    TYPE_INSTANCE_SLOT_FORBIDDEN: (
        status.HTTP_400_BAD_REQUEST,
        "Slot must be null for root type instances (parent_id is null).",
    ),
    TYPE_INSTANCE_PARENT_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The specified parent type instance was not found.",
    ),
    TYPE_INSTANCE_PARAMS_INVALID: (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Invalid type instance parameters.",
    ),
    FIELD_PARENT_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The specified parent field was not found.",
    ),
    FIELD_PARENT_DATASET_MISMATCH: (
        status.HTTP_400_BAD_REQUEST,
        "The parent field belongs to a different dataset.",
    ),
    FIELD_CIRCULAR_REFERENCE: (
        status.HTTP_400_BAD_REQUEST,
        "Circular reference detected: a field cannot be its own ancestor.",
    ),
    REFRESH_TOKEN_INVALID: (
        status.HTTP_401_UNAUTHORIZED,
        "Invalid refresh token.",
    ),
    REFRESH_TOKEN_EXPIRED: (
        status.HTTP_401_UNAUTHORIZED,
        "Refresh token has expired.",
    ),
    REFRESH_TOKEN_REVOKED: (
        status.HTTP_401_UNAUTHORIZED,
        "Refresh token has been revoked.",
    ),
    ENTITY_NOT_DELETED: (
        status.HTTP_400_BAD_REQUEST,
        "The entity is not deleted and cannot be restored.",
    ),
    HAS_DEPENDENT_ENTITIES: (
        status.HTTP_409_CONFLICT,
        "Cannot delete: the entity has dependent records. Remove them first.",
    ),
    VERSION_CONFLICT: (
        status.HTTP_409_CONFLICT,
        "The entity has been modified by another user. Please reload and try again.",
    ),
    CRAWL_RUN_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested crawl run was not found.",
    ),
    FIELD_CLASSIFICATION_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested field classification was not found.",
    ),
    TECH_FIELD_TEMPLATE_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested tech-field template was not found.",
    ),
    TECH_FIELD_TEMPLATE_ALREADY_EXISTS: (
        status.HTTP_409_CONFLICT,
        "A tech-field template with this code already exists.",
    ),
    TECH_FIELD_TEMPLATE_LAYER_MISMATCH: (
        status.HTTP_400_BAD_REQUEST,
        "Template layer does not match dataset layer.",
    ),
    TECH_FIELD_TEMPLATE_FIELD_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested template field was not found.",
    ),
    TECH_FIELD_TEMPLATE_FIELD_ALREADY_EXISTS: (
        status.HTTP_409_CONFLICT,
        "A template field with this name already exists in this template.",
    ),
    TECH_TYPE_CODE_NOT_RESOLVABLE: (
        status.HTTP_400_BAD_REQUEST,
        "Cannot resolve abstract type_code to a concrete data type for this dataset flavor.",
    ),
    LAKE_SYNC_NO_SOURCE_SCHEMA: (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Source dataset has no schema with field bindings.",
    ),
    LAKE_SYNC_TARGET_FLAVOR_MISMATCH: (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Target system flavor must be 'iceberg_v2'.",
    ),
    LAKE_SYNC_UNKNOWN_OVERRIDE_FIELD: (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Override references a field that does not exist on the source dataset.",
    ),
    LAKE_SYNC_AMBIGUOUS_CAST: (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Multiple cast rules match for a field; supply an explicit override.",
    ),
    ENGINE_NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "The requested engine was not found.",
    ),
    ENGINE_IN_USE: (
        status.HTTP_409_CONFLICT,
        "Cannot delete engine while a DatasetLink references it.",
    ),
    ENGINE_INCOMPATIBLE_LINK: (
        status.HTTP_409_CONFLICT,
        "Engine is not compatible with this dataset link's source/target kinds.",
    ),
    ENGINE_NOT_ATTACHED: (
        status.HTTP_409_CONFLICT,
        "Dataset link has no engine attached; cannot render SQL.",
    ),
    ENGINE_NOT_RENDERABLE: (
        status.HTTP_409_CONFLICT,
        "Engine role does not support SQL rendering (CDC engines describe envelopes).",
    ),
    ENGINE_KIND_IMMUTABLE: (
        status.HTTP_409_CONFLICT,
        "Engine kind cannot be changed after creation.",
    ),
    ENGINE_VERSION_INVALID: (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Engine version is not in the supported whitelist for this kind.",
    ),
    ENGINE_CODE_ALREADY_EXISTS: (
        status.HTTP_409_CONFLICT,
        "An engine with this code already exists.",
    ),
}


def build_error_responses(
    *error_codes: str,
    error_schema: Type[BaseModel] | None = None,
) -> Dict[int | str, Dict[str, Any]]:
    """
    Turn a list of registered error codes into a FastAPI `responses` mapping.

    Args:
        *error_codes: Error codes defined in `ERROR_MAP`.
        error_schema: Optional Pydantic schema to use for the response model.
            Defaults to `backend.schemas.error.ErrorResponse`.

    Returns:
        Dict[int, Dict[str, Any]]: A mapping suitable for FastAPI route
            declarations (status code -> response metadata).
    """

    if not error_codes:
        return {}

    if error_schema is None:
        from backend.schemas.error import ErrorResponse as DefaultErrorResponse

        error_schema = DefaultErrorResponse

    grouped: Dict[int, list[tuple[str, ErrorInfo]]] = defaultdict(list)
    for code in error_codes:
        if code not in ERROR_MAP:
            raise KeyError(
                f"Unknown error code '{code}'. Register it in ERROR_MAP first."
            )
        grouped[ERROR_MAP[code][0]].append((code, ERROR_MAP[code]))

    responses: Dict[int | str, Dict[str, Any]] = {}
    for status_code, items in grouped.items():
        description = (
            items[0][1][1]
            if len(items) == 1
            else " | ".join(f"{code}: {detail}" for code, (_, detail) in items)
        )
        examples = {
            code: {
                "summary": code,
                "value": {
                    "error_code": code,
                    "detail": detail,
                    "request_id": "b5d6f2a0-1234-4abc-9def-0123456789ab",
                },
            }
            for code, (_, detail) in items
        }
        responses[status_code] = {
            "model": error_schema,
            "description": description,
            "content": {
                "application/json": {
                    "examples": examples,
                },
            },
        }

    return responses
