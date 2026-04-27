"""First-slice VIGOR CAD adapter."""

from vigor_adapter_cad.adapter import CadOpenScadAdapter
from vigor_adapter_cad.ir import CadConstraints, CadFeature, CadParameters, CadParametricIRV1
from vigor_adapter_cad.openscad import render_openscad
from vigor_adapter_cad.validators import CadValidation, validate_cad

__all__ = [
    "CadConstraints",
    "CadFeature",
    "CadOpenScadAdapter",
    "CadParameters",
    "CadParametricIRV1",
    "CadValidation",
    "render_openscad",
    "validate_cad",
]
__version__ = "0.1.0"
