"""주문 API fixture의 입력 정규화와 service 위임 경계를 정의합니다."""

from .order_service import OrderRequest, OrderService


def parse_quantity(value: object) -> int:
    """사용자 quantity를 양의 정수로 정규화합니다.

    Args:
        value: 주문 요청에서 읽은 정규화 전 수량입니다.

    Returns:
        예약에 사용할 양의 정수 수량입니다.

    Raises:
        ValueError: Boolean, 정수 변환 불가 값 또는 0 이하 값이면 발생합니다.
    """
    if isinstance(value, bool):
        raise ValueError("quantity must be a positive integer")  # noqa: TRY004 - normalize user input

    try:
        quantity = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("quantity must be a positive integer") from error

    if quantity <= 0:
        raise ValueError("quantity must be a positive integer")
    return quantity


def submit_order(payload: dict[str, object], service: OrderService) -> str:
    """주문 payload를 검증하고 예약 service에 전달합니다.

    Args:
        payload: SKU와 quantity를 포함하는 외부 주문 입력입니다.
        service: 검증된 주문의 예약과 원장 기록을 수행할 service입니다.

    Returns:
        Inventory가 발급한 reservation identifier입니다.

    Raises:
        ValueError: SKU가 비었거나 quantity가 양의 정수로 정규화되지 않으면 발생합니다.
    """
    sku = payload.get("sku")
    if not isinstance(sku, str) or not sku.strip():
        raise ValueError("sku is required")

    request = OrderRequest(
        sku=sku.strip(),
        quantity=parse_quantity(payload.get("quantity")),
    )
    return service.place(request)
