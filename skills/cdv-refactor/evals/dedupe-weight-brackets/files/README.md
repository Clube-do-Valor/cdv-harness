# parcel-rates

- `shipping/quote.py` - `quote(weight_kg, zone, express=False)`: what the customer pays. Zones: `domestic`, `eu`, `intl`.
- `shipping/label.py` - `label_cost(weight_kg)`: what the carrier charges us for the label.

Run the tests with `python3 -m unittest discover -s tests`.
