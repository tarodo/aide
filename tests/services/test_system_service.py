import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core import errors
from backend.core.exceptions import AppException
from backend.models import CredentialRef, System, SystemFlavor
from backend.schemas.system import SystemCreate, SystemUpdate
from backend.services.system import SystemService


class _MockRepository:
    def __init__(self) -> None:
        self.get_by_code: AsyncMock = AsyncMock()
        self.get: AsyncMock = AsyncMock()


class _MockSystemFlavors:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()


class _MockCredentialRefs:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()


class _MockUnitOfWork:
    def __init__(self) -> None:
        self.session = MagicMock()
        self.system_flavors = _MockSystemFlavors()
        self.credential_refs = _MockCredentialRefs()

    async def __aenter__(self) -> "_MockUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


@pytest.fixture
def mock_uow() -> _MockUnitOfWork:
    """Fixture for a mocked UnitOfWork."""
    return _MockUnitOfWork()


@pytest.fixture
def system_service() -> SystemService:
    """Fixture for a SystemService instance."""
    return SystemService()


@pytest.fixture
def db_system_flavor() -> SystemFlavor:
    return SystemFlavor(id=uuid.uuid4(), code="FLAVOR", name="Flavor")


@pytest.fixture
def db_credential_ref() -> CredentialRef:
    return CredentialRef(id=uuid.uuid4(), provider="vault", path="/secret")


@pytest.fixture
def system_create_schema(
    db_system_flavor: SystemFlavor, db_credential_ref: CredentialRef
) -> SystemCreate:
    return SystemCreate(
        code="SYS1",
        name="System 1",
        flavor_id=db_system_flavor.id,
        credential_ref_id=db_credential_ref.id,
    )


@pytest.fixture
def db_system(system_create_schema: SystemCreate) -> System:
    return System(
        id=uuid.uuid4(),
        code=system_create_schema.code,
        name=system_create_schema.name,
        flavor_id=system_create_schema.flavor_id,
        credential_ref_id=system_create_schema.credential_ref_id,
    )


@pytest.mark.asyncio
class TestSystemServicePreCreate:
    async def test_pre_create_duplicate_code(
        self,
        system_service: SystemService,
        mock_uow: _MockUnitOfWork,
        system_create_schema: SystemCreate,
        db_system: System,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_by_code.return_value = db_system

        with patch.object(system_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await system_service._pre_create(
                    uow=mock_uow, obj_in=system_create_schema, creator_id=None
                )
        assert exc_info.value.error_code == errors.SYSTEM_ALREADY_EXISTS

    async def test_pre_create_flavor_not_found(
        self,
        system_service: SystemService,
        mock_uow: _MockUnitOfWork,
        system_create_schema: SystemCreate,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_by_code.return_value = None
        mock_uow.system_flavors.get.return_value = None

        with patch.object(system_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await system_service._pre_create(
                    uow=mock_uow, obj_in=system_create_schema, creator_id=None
                )
        assert exc_info.value.error_code == errors.SYSTEM_FLAVOR_NOT_FOUND

    async def test_pre_create_credential_ref_not_found(
        self,
        system_service: SystemService,
        mock_uow: _MockUnitOfWork,
        system_create_schema: SystemCreate,
        db_system_flavor: SystemFlavor,
    ):
        mock_repo = _MockRepository()
        mock_repo.get_by_code.return_value = None
        mock_uow.system_flavors.get.return_value = db_system_flavor
        mock_uow.credential_refs.get.return_value = None

        with patch.object(system_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await system_service._pre_create(
                    uow=mock_uow, obj_in=system_create_schema, creator_id=None
                )
        assert exc_info.value.error_code == errors.CREDENTIAL_REF_NOT_FOUND


@pytest.mark.asyncio
class TestSystemServicePreUpdate:
    async def test_pre_update_duplicate_code(
        self,
        system_service: SystemService,
        mock_uow: _MockUnitOfWork,
        db_system: System,
    ):
        update_schema = SystemUpdate(code="NEW_CODE")
        mock_repo = _MockRepository()
        mock_repo.get_by_code.return_value = System(id=uuid.uuid4(), code="NEW_CODE")

        with patch.object(system_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await system_service._pre_update(
                    uow=mock_uow,
                    db_obj=db_system,
                    obj_in=update_schema,
                    updater_id=None,
                )
        assert exc_info.value.error_code == errors.SYSTEM_ALREADY_EXISTS

    async def test_pre_update_flavor_not_found(
        self,
        system_service: SystemService,
        mock_uow: _MockUnitOfWork,
        db_system: System,
    ):
        update_schema = SystemUpdate(flavor_id=uuid.uuid4())
        mock_repo = _MockRepository()
        mock_uow.system_flavors.get.return_value = None

        with patch.object(system_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await system_service._pre_update(
                    uow=mock_uow,
                    db_obj=db_system,
                    obj_in=update_schema,
                    updater_id=None,
                )
        assert exc_info.value.error_code == errors.SYSTEM_FLAVOR_NOT_FOUND

    async def test_pre_update_credential_ref_not_found(
        self,
        system_service: SystemService,
        mock_uow: _MockUnitOfWork,
        db_system: System,
    ):
        update_schema = SystemUpdate(credential_ref_id=uuid.uuid4())
        mock_repo = _MockRepository()
        mock_uow.credential_refs.get.return_value = None

        with patch.object(system_service, "_get_repository", return_value=mock_repo):
            with pytest.raises(AppException) as exc_info:
                await system_service._pre_update(
                    uow=mock_uow,
                    db_obj=db_system,
                    obj_in=update_schema,
                    updater_id=None,
                )
        assert exc_info.value.error_code == errors.CREDENTIAL_REF_NOT_FOUND
