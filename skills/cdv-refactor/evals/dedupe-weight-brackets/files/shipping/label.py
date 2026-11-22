"""Cost of printing and buying the carrier label, charged to us by the carrier."""

HANDLING_FEE = 1.25


def label_cost(weight_kg):
    if weight_kg <= 0:
        raise ValueError("weight must be positive")

    # weight bracket
    if weight_kg <= 1:
        price = 5.0
    elif weight_kg <= 5:
        price = 9.5
    elif weight_kg <= 10:
        price = 14.0
    else:
        price = 20.0

    return round(price + HANDLING_FEE, 2)
