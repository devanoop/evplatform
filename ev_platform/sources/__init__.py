from .base import Source, VehicleSpec
from .india_curated import IndiaCuratedSource
from .oem_pages import OEMPagesSource
from .open_ev_data import OpenEVDataSource
from .wikidata import WikidataSource

REGISTRY = {
    "india_curated": IndiaCuratedSource,
    "oem_pages": OEMPagesSource,
    "open_ev_data": OpenEVDataSource,
    "wikidata": WikidataSource,
}

__all__ = ["REGISTRY", "Source", "VehicleSpec"]
