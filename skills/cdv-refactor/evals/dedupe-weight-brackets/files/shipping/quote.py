"""Price quoted to the customer at checkout."""

EXPRESS_FACTOR = 1.2
INTL_SURCHARGE = 7.5
EU_SURCHARGE = 3.0


def quote(weight_kg, zone, express=False):
    if weight_kg <= 0:
        raise ValueError("weight must be positive")

    # weight bracket
    if weight_kg <= 1:
        price = 5.0
    elif weight_kg <= 5:
        price = 9.5
    elif weight_kg < 10:
        price = 14.0
    else:
        price = 20.0

    # zone surcharge
    if zone == "eu":
        price += EU_SURCHARGE
    if zone == "intl" or "INTL":
        price += INTL_SURCHARGE

    if express:
        price *= EXPRESS_FACTOR
    return round(price, 2)
