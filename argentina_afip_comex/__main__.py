"""Permite correr la CLI con `python -m argentina_afip_comex`.

Alternativa al comando `argentina-afip-query`, útil cuando Windows bloquea el
ejecutable que genera uv.
"""

from argentina_afip_comex.query import main

raise SystemExit(main())
