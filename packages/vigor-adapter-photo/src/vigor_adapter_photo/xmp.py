"""XMP sidecar writer for photo edit recipes.

Produces a minimal but valid XMP packet compatible with Adobe Camera Raw /
Lightroom Classic using `crs:ProcessVersion="11.0"` (PV2012). See research
notes for the exact attribute names.

References:
* https://developer.adobe.com/xmp/docs/xmp-namespaces/crs/
* https://exiv2.org/tags-xmp-crs.html
* https://www.exiftool.org/TagNames/XMP.html
* https://helpx.adobe.com/lightroom-classic/help/create-xmp-acr-files.html
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vigor_core.util import utcnow_iso

if TYPE_CHECKING:
    from vigor_adapter_photo.recipe import PhotoEditRecipeV1


_XMP_HEADER = '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>'
_XMP_FOOTER = '<?xpacket end="w"?>'


def _fmt_exposure(value: float) -> str:
    return f"{value:+.2f}"


def _fmt_int(value: int) -> str:
    return f"{value:+d}" if value != 0 else "0"


def recipe_to_xmp(recipe: PhotoEditRecipeV1) -> str:
    """Return a Lightroom-compatible XMP sidecar string for the given recipe."""

    adj = recipe.global_adjustments
    temperature_kelvin = 5500 + adj.temperature * 25
    attrs = [
        ("xmp:CreatorTool", "VIGOR Photo Adapter 0.1.0"),
        ("xmp:ModifyDate", utcnow_iso()),
        ("crs:Version", "15.0"),
        ("crs:ProcessVersion", "11.0"),
        ("crs:HasSettings", "True"),
        ("crs:WhiteBalance", "Custom"),
        ("crs:Temperature", str(temperature_kelvin)),
        ("crs:Tint", _fmt_int(adj.tint)),
        ("crs:Exposure2012", _fmt_exposure(adj.exposure)),
        ("crs:Contrast2012", _fmt_int(adj.contrast)),
        ("crs:Highlights2012", _fmt_int(adj.highlights)),
        ("crs:Shadows2012", _fmt_int(adj.shadows)),
        ("crs:Whites2012", _fmt_int(adj.whites)),
        ("crs:Blacks2012", _fmt_int(adj.blacks)),
        ("crs:Clarity2012", _fmt_int(adj.clarity)),
        ("crs:Dehaze", _fmt_int(adj.dehaze)),
        ("crs:Vibrance", _fmt_int(adj.vibrance)),
        ("crs:Saturation", _fmt_int(adj.saturation)),
        ("crs:Sharpness", str(max(0, min(150, adj.sharpening)))),
        ("crs:ColorNoiseReduction", str(max(0, min(100, adj.noise_reduction_color)))),
        ("crs:ToneCurveName2012", "Linear"),
    ]
    attr_xml = "\n    ".join(f'{name}="{value}"' for name, value in attrs)
    body = f"""{_XMP_HEADER}
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="VIGOR 0.1.0">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
    {attr_xml}>
   <crs:ToneCurvePV2012>
    <rdf:Seq>
     <rdf:li>0, 0</rdf:li>
     <rdf:li>255, 255</rdf:li>
    </rdf:Seq>
   </crs:ToneCurvePV2012>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
{_XMP_FOOTER}
"""
    return body
