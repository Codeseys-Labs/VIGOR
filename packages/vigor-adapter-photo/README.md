# vigor-adapter-photo

VIGOR domain adapter for agentic photo editing.

Scope shipped in the deterministic MVP:

1. `photo_edit_recipe.v1` Pydantic schema.
2. Global Lightroom-style tone/color adjustments.
3. Local adjustment metadata with `mask_uri`, `mask_sha256`, `mask_generator`, `feather_px`, and `invert`.
4. Deterministic heuristic masks: `sky_heuristic`, `foreground_gradient`, `subject_radial`, `linear_gradient`, and `radial_gradient`.
5. Lossless 8-bit grayscale PNG mask persistence under candidate artifacts.
6. Preview rendering with Pillow + NumPy, including local mask blending.
7. A deterministic histogram critic that checks highlight clipping, crushed blacks, and contrast.
8. JSON recipe export, Lightroom/Camera Raw XMP export (PV2012 global settings), preview JPEG export, and mask PNG export.

Out of scope for this slice:

1. Semantic segmentation with SAM or similar heavy ML models.
2. Photoshop UXP, GIMP/GEGL, LUT, and PSD export.
3. Lightroom local adjustment/mask XMP round-tripping.
4. VLM aesthetic critic; the runtime/backend reviewer path exists, but provider/model/corpus decisions are external.
