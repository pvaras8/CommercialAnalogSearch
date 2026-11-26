# Enamine catalogue inspection

Inspected source: `Enamine_screening_collection_sdf_202610.zip`.

- ZIP64 archive, 1,362,628,294 bytes compressed.
- One member: `Enamine_screening_collection_202610.sdf`, 13,765,490,214 bytes uncompressed.
- Catalogue version inferred only from the supplied filename: `202610`.
- Records are SDF/mol blocks. The title line is empty; `Catalog_ID` is the Enamine commercial identifier (observed `Z…` identifiers).
- Observed properties: `Catalog_ID`, `heavy_atoms`, `LogS`, `LogP`, `rotating_bonds`, `PSA`, `hb_acceptors`, `hb_donors`, `Collection`, and `link`.
- `link` points to an Enamine Store catalogue URL containing the same identifier.
- `Collection` is catalogue classification (examples observed: `Functional`, `Legacy`), not proof of current stock.

The implementation preserves all source properties in the sidecar SQLite database and never synthesises supplier IDs. Output availability is deliberately labelled `historical_catalog_listing`; no live availability claim is made because the supplied archive has no real-time stock field or API response.

In the validated first 10,000 records there were 10,000 distinct `Catalog_ID` values and 10,000 distinct canonical structures. `Collection` counts were HTS 4,113; Legacy 3,991; Functional 1,497; Advanced 378; Premium 21. Observed ranges were heavy atoms 5–45, LogP −6.635–5.568, and PSA 0–149.6. These are sample observations, not constraints applied by the software.
