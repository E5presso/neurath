"""주문 입력, retry와 ledger 기록 fixture의 관찰 가능한 계약을 검증합니다."""

from .api import parse_quantity, submit_order
from .order_service import (
    IInventoryRepository,
    IOrderLedger,
    OrderRequest,
    OrderService,
    TemporaryInventoryError,
)


class FlakyInventoryRepository(IInventoryRepository):
    """지정한 횟수만큼 일시 실패한 뒤 예약에 성공하는 test double입니다."""

    def __init__(self, failures: int) -> None:
        """성공 전 발생시킬 일시 실패 횟수를 고정합니다.

        Args:
            failures: 예약 성공 전에 발생시킬 일시 실패 횟수입니다.
        """
        self._failures = failures
        self.attempts = 0

    def reserve(self, sku: str, quantity: int) -> str:
        """시도 횟수를 기록하고 설정된 실패를 소진한 뒤 예약합니다.

        Args:
            sku: 예약할 상품의 식별자입니다.
            quantity: 예약할 양의 정수 수량입니다.

        Returns:
            실패가 소진된 뒤 생성한 예약 식별자입니다.

        Raises:
            TemporaryInventoryError: 아직 설정된 일시 실패가 남아 있으면 발생합니다.
        """
        self.attempts += 1
        if self.attempts <= self._failures:
            raise TemporaryInventoryError
        return f"{sku}:{quantity}"


class RecordingOrderLedger(IOrderLedger):
    """기록 요청을 순서대로 보존하는 in-memory test double입니다."""

    def __init__(self) -> None:
        """원장 기록이 없는 초기 상태를 만듭니다."""
        self.entries: list[tuple[str, OrderRequest]] = []

    def record(self, reservation_id: str, request: OrderRequest) -> None:
        """예약 식별자와 주문 입력을 관찰 가능한 목록에 추가합니다.

        Args:
            reservation_id: Inventory가 발급한 예약 식별자입니다.
            request: 예약에 사용된 불변 주문 입력입니다.
        """
        self.entries.append((reservation_id, request))


def test_parse_quantity_rejects_boolean_values() -> None:
    """Boolean quantity가 정수 1로 오인되지 않고 거부되는지 검증합니다.

    Raises:
        AssertionError: Boolean 입력이 ValueError 없이 처리되면 발생합니다.
    """
    try:
        parse_quantity(True)
    except ValueError:
        return
    raise AssertionError("boolean quantity must be rejected")


def test_submit_order_retries_five_times_before_raising() -> None:
    """다섯 번째 일시 실패가 caller에게 전달되는 retry 한계를 검증합니다.

    Raises:
        AssertionError: 다섯 번째 일시 실패가 caller에게 전달되지 않으면 발생합니다.
    """
    inventory = FlakyInventoryRepository(failures=5)
    service = OrderService(inventory, RecordingOrderLedger())

    try:
        submit_order({"sku": "neurath", "quantity": 1}, service)
    except TemporaryInventoryError:
        assert inventory.attempts == 5
        return
    raise AssertionError("fifth temporary failure must be returned to the caller")


def test_submit_order_records_successful_reservation() -> None:
    """재시도 뒤 성공한 예약이 원장에 한 번 기록되는지 검증합니다."""
    inventory = FlakyInventoryRepository(failures=2)
    ledger = RecordingOrderLedger()
    service = OrderService(inventory, ledger)

    reservation_id = submit_order({"sku": "neurath", "quantity": "2"}, service)

    assert reservation_id == "neurath:2"
    assert inventory.attempts == 3
    assert ledger.entries == [(reservation_id, OrderRequest("neurath", 2))]
