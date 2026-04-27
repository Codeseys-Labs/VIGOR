# vigor-adapter-photo

VIGOR domain adapter for agentic photo editing.

Scope for v0:

1. `photo_edit_recipe.v1` Pydantic schema (global adjustments only for MVP).
2. A pure-Python preview renderer using Pillow + NumPy. RAW files are optional via the `raw` extra.
3. A deterministic histogram critic that scores clipped highlights, crushed blacks, and contrast.
4. JSON recipe export.
5. XMP sidecar export compatible with Lightroom / Camera Raw `ProcessVersion=11.0`.

Out of scope for v0 (documented in roadmap): semantic masks, Photoshop UXP, GIMP GEGL, LUT export.
