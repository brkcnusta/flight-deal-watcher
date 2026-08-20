from fast_flights import FlightQuery, Passengers, create_query, get_flights


def cheapest_for_date(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str | None,
    adults: int = 1,
    currency: str = "USD",
) -> dict | None:
    """Query Google Flights (via fast-flights) for one specific date pair.

    Returns {"price": float, "airlines": list[str], "stops": int} for the
    cheapest listed itinerary, or None if nothing could be fetched.
    """
    flights = [FlightQuery(date=depart_date, from_airport=origin, to_airport=destination)]
    trip = "one-way"
    if return_date:
        flights.append(FlightQuery(date=return_date, from_airport=destination, to_airport=origin))
        trip = "round-trip"

    query = create_query(
        flights=flights,
        trip=trip,
        seat="economy",
        passengers=Passengers(adults=adults, children=0, infants_in_seat=0, infants_on_lap=0),
        currency=currency,
    )

    try:
        result = get_flights(query)
    except Exception:
        return None

    if not result:
        return None

    airline_names = {}
    metadata = getattr(result, "metadata", None)
    if metadata is not None:
        for airline in getattr(metadata, "airlines", []):
            airline_names[airline.code] = airline.name

    best = min(result, key=lambda f: f.price)
    names = [airline_names.get(code, code) for code in best.airlines]
    stops = len(best.flights) - 1 if best.flights else None

    return {
        "price": float(best.price),
        "airlines": names,
        "stops": stops,
    }
