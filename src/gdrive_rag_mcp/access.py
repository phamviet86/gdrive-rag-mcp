from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path


def normalize_scope_value(value: str) -> str:
    """Normalize a Drive folder label into a stable scope identifier."""
    normalized = value.strip().casefold()
    normalized = re.sub(r"^\d{2}[-_. ]+", "", normalized)
    normalized = re.sub(r"[^\w.-]+", "-", normalized, flags=re.UNICODE)
    return normalized.strip("-._")


PARA_ALIASES = {
    "project": "projects",
    "projects": "projects",
    "area": "areas",
    "areas": "areas",
    "resource": "resources",
    "resources": "resources",
    "archive": "archives",
    "archives": "archives",
}


def normalize_para(value: str) -> str:
    normalized = normalize_scope_value(value)
    return PARA_ALIASES.get(normalized, normalized)


def _folder_ids(items: list[str] | tuple[str, ...]) -> frozenset[str]:
    values = frozenset(item.strip() for item in items)
    if not values or "" in values:
        raise ValueError("Access scope lists must contain non-empty values")
    return values


@dataclass(frozen=True, slots=True)
class AccessScope:
    profile_id: str
    allowed_folder_ids: frozenset[str]

    @classmethod
    def create(
        cls,
        profile_id: str,
        allowed_folder_ids: list[str] | tuple[str, ...],
    ) -> AccessScope:
        normalized_profile = normalize_scope_value(profile_id)
        if not normalized_profile:
            raise ValueError("profile_id must not be empty")
        return cls(
            profile_id=normalized_profile,
            allowed_folder_ids=_folder_ids(allowed_folder_ids),
        )


@dataclass(frozen=True, slots=True)
class Principal:
    token_digest: str
    scope: AccessScope


class AccessPolicy:
    def __init__(self, principals: tuple[Principal, ...]) -> None:
        if not principals:
            raise ValueError("Access policy must define at least one principal")
        self.principals = principals

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @classmethod
    def from_single_token(cls, token: str, scope: AccessScope) -> AccessPolicy:
        if len(token) < 32:
            raise ValueError("Bearer tokens must contain at least 32 characters")
        return cls((Principal(cls._digest(token), scope),))

    @classmethod
    def from_file(cls, path: Path) -> AccessPolicy:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_principals = payload.get("principals") if isinstance(payload, dict) else None
        if not isinstance(raw_principals, list):
            raise ValueError("Access policy must contain a principals array")

        def field(item: dict[str, object], name: str, default: list[str]) -> list[str]:
            value = item.get(name, default)
            if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
                raise ValueError(f"{name} must be an array of strings")
            return value

        principals: list[Principal] = []
        seen_tokens: set[str] = set()
        for item in raw_principals:
            if not isinstance(item, dict):
                raise ValueError("Each access-policy principal must be an object")
            token_env = str(item.get("token_env", ""))
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token_env):
                raise ValueError("Each principal must name a valid token_env")
            token = os.getenv(token_env, "")
            if len(token) < 32:
                raise ValueError(f"{token_env} must contain at least 32 characters")

            scope = AccessScope.create(
                profile_id=str(item.get("profile_id", "")),
                allowed_folder_ids=field(item, "allowed_folder_ids", []),
            )
            token_digest = cls._digest(token)
            if token_digest in seen_tokens:
                raise ValueError("Access policy contains a duplicate bearer token")
            seen_tokens.add(token_digest)
            principals.append(Principal(token_digest, scope))
        return cls(tuple(principals))

    def authenticate(self, token: str) -> AccessScope | None:
        candidate = self._digest(token)
        for principal in self.principals:
            if hmac.compare_digest(candidate, principal.token_digest):
                return principal.scope
        return None


_CURRENT_SCOPE: ContextVar[AccessScope | None] = ContextVar("gdrive_rag_scope", default=None)


def set_current_scope(scope: AccessScope) -> Token[AccessScope | None]:
    return _CURRENT_SCOPE.set(scope)


def reset_current_scope(token: Token[AccessScope | None]) -> None:
    _CURRENT_SCOPE.reset(token)


def current_scope(default: AccessScope | None = None) -> AccessScope:
    scope = _CURRENT_SCOPE.get() or default
    if scope is None:
        raise PermissionError("No authenticated document access scope is available")
    return scope
