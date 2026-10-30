"""Open houses — the three extension points behind the Open Houses page (docs/05 §4c).

- `sources`  — where open-house slots come from (`OpenHouseSource` + `REGISTRY`)
- `geocode`  — turning the user's home address into coordinates (`Geocoder`)
- `route`    — ordering a day's stops (`TravelEstimator` + `plan_route`)

Each is a small Protocol with one shipped implementation, so a deployment in
another market can swap a piece without touching the pipeline or the API.
"""
