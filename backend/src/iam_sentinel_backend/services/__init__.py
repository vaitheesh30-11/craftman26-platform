"""Domain services backing backend phase-01's routers -- routers translate
HTTP <-> Pydantic; services translate Pydantic <-> adapter dicts and own
every access-control decision (`docs/DATA_CONTRACTS.md` scoping rules).
"""

from __future__ import annotations
