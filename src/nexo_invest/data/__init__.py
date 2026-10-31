"""Adaptadores de datos externos con procedencia verificable.

El único adaptador implementado es SEC EDGAR (fuente oficial, gratuita y pública).
Las pruebas unitarias nunca dependen de Internet: usan fixtures locales guardados
en `tests/fixtures/` con su origen y fecha de consulta documentados.
"""

from nexo_invest.data.sec_edgar import (
    CONCEPT_MAP,
    SecEdgarClient,
    SecEdgarResult,
    analyze_company,
    build_registry_from_companyfacts,
    extract_observations,
)

__all__ = [
    "CONCEPT_MAP",
    "SecEdgarClient",
    "SecEdgarResult",
    "analyze_company",
    "build_registry_from_companyfacts",
    "extract_observations",
]
