from statistics import mean

MIN_HISTORY_FOR_BASELINE = 3
HISTORY_WINDOW = 30


def evaluate(
    history_prices: list[float],
    current_price: float,
    discount_threshold_pct: float,
    max_price: float | None,
) -> tuple[bool, str]:
    """Decide whether current_price counts as a deal for this route.

    Returns (is_deal, reason). `history_prices` should NOT include current_price.
    """
    if max_price is not None and current_price <= max_price:
        return True, f"hedef fiyat olan {max_price} altında"

    if len(history_prices) < MIN_HISTORY_FOR_BASELINE:
        return False, "henüz yeterli fiyat geçmişi yok, referans oluşturuluyor"

    window = history_prices[-HISTORY_WINDOW:]
    baseline = mean(window)
    drop_pct = (baseline - current_price) / baseline * 100

    if drop_pct >= discount_threshold_pct:
        return True, f"ortalama fiyat {baseline:.0f} iken %{drop_pct:.0f} indirim"

    if current_price < min(window):
        return True, f"şu ana kadar görülen en düşük fiyat (önceki en düşük: {min(window):.0f})"

    return False, "fırsat sayılacak seviyede değil"
