"""주문 예약 retry와 ledger side effect의 fixture 계약을 정의합니다."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class TemporaryInventoryError(RuntimeError):
    """Inventory의 일시적인 예약 실패를 나타냅니다."""


@dataclass(frozen=True)
class OrderRequest:
    """Inventory 예약에 필요한 불변 주문 입력을 보존합니다."""

    sku: str
    """예약할 상품의 공백 제거 식별자입니다."""

    quantity: int
    """예약할 상품의 양의 정수 수량입니다."""


class IInventoryRepository(ABC):
    """상품 수량을 예약하는 inventory boundary입니다."""

    @abstractmethod
    def reserve(self, sku: str, quantity: int) -> str:
        """상품 수량을 예약하고 reservation identifier를 반환합니다.

        Args:
            sku: 예약할 상품의 식별자입니다.
            quantity: 예약할 양의 정수 수량입니다.

        Returns:
            성공한 inventory 예약의 식별자입니다.

        Raises:
            NotImplementedError: Concrete inventory adapter가 구현하지 않으면 발생합니다.
        """
        raise NotImplementedError


class IOrderLedger(ABC):
    """성공한 inventory 예약을 주문 원장에 기록하는 boundary입니다."""

    @abstractmethod
    def record(self, reservation_id: str, request: OrderRequest) -> None:
        """예약 식별자와 주문 입력을 원장에 기록합니다.

        Args:
            reservation_id: Inventory가 발급한 예약 식별자입니다.
            request: 예약에 사용된 불변 주문 입력입니다.

        Raises:
            NotImplementedError: Concrete ledger adapter가 구현하지 않으면 발생합니다.
        """
        raise NotImplementedError


class OrderService:
    """일시적인 inventory 실패를 재시도한 뒤 성공한 예약을 기록합니다."""

    MAX_ATTEMPTS = 5
    """임시 inventory 오류를 포함해 허용하는 전체 예약 시도 횟수입니다."""

    def __init__(
        self,
        inventory: IInventoryRepository,
        ledger: IOrderLedger,
    ) -> None:
        """예약과 원장 기록 boundary를 결합합니다.

        Args:
            inventory: 상품 수량 예약을 소유하는 repository입니다.
            ledger: 성공한 예약의 주문 기록을 소유하는 원장입니다.
        """
        self._inventory = inventory
        self._ledger = ledger

    def place(self, request: OrderRequest) -> str:
        """일시적 실패를 재시도하고 성공한 예약을 원장에 기록합니다.

        Args:
            request: Inventory에 전달할 불변 주문 입력입니다.

        Returns:
            원장 기록까지 완료된 reservation identifier입니다.

        Raises:
            TemporaryInventoryError: 마지막 inventory 시도도 일시적으로 실패하면 발생합니다.
            AssertionError: Retry loop가 반환이나 예외 없이 종료되는 불변식 위반 시 발생합니다.
        """
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                reservation_id = self._inventory.reserve(
                    request.sku,
                    request.quantity,
                )
            except TemporaryInventoryError:
                if attempt == self.MAX_ATTEMPTS:
                    raise
                continue

            self._ledger.record(reservation_id, request)
            return reservation_id

        raise AssertionError("retry loop exhausted without returning or raising")
