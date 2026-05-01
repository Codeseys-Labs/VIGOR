---
name: photo-edit-recipe
description: Photo editing recipe IR (global tone/color + heuristic local masks).
---

# photo-edit-recipe

Photo editing recipe IR (global tone/color + heuristic local masks).

## IR contract

This adapter consumes the `photo_edit_recipe.v1` intermediate representation, modeled by `PhotoEditRecipeV1`.

### JSON Schema

```json
{
  "$defs": {
    "PhotoGlobalAdjustments": {
      "additionalProperties": false,
      "properties": {
        "blacks": {
          "default": 0,
          "maximum": 100,
          "minimum": -100,
          "title": "Blacks",
          "type": "integer"
        },
        "clarity": {
          "default": 0,
          "maximum": 100,
          "minimum": -100,
          "title": "Clarity",
          "type": "integer"
        },
        "contrast": {
          "default": 0,
          "maximum": 100,
          "minimum": -100,
          "title": "Contrast",
          "type": "integer"
        },
        "dehaze": {
          "default": 0,
          "maximum": 100,
          "minimum": -100,
          "title": "Dehaze",
          "type": "integer"
        },
        "exposure": {
          "default": 0.0,
          "maximum": 5.0,
          "minimum": -5.0,
          "title": "Exposure",
          "type": "number"
        },
        "highlights": {
          "default": 0,
          "maximum": 100,
          "minimum": -100,
          "title": "Highlights",
          "type": "integer"
        },
        "noiseReductionColor": {
          "default": 0,
          "maximum": 100,
          "minimum": 0,
          "title": "Noisereductioncolor",
          "type": "integer"
        },
        "saturation": {
          "default": 0,
          "maximum": 100,
          "minimum": -100,
          "title": "Saturation",
          "type": "integer"
        },
        "shadows": {
          "default": 0,
          "maximum": 100,
          "minimum": -100,
          "title": "Shadows",
          "type": "integer"
        },
        "sharpening": {
          "default": 0,
          "maximum": 150,
          "minimum": 0,
          "title": "Sharpening",
          "type": "integer"
        },
        "temperature": {
          "default": 0,
          "maximum": 100,
          "minimum": -100,
          "title": "Temperature",
          "type": "integer"
        },
        "tint": {
          "default": 0,
          "maximum": 150,
          "minimum": -150,
          "title": "Tint",
          "type": "integer"
        },
        "vibrance": {
          "default": 0,
          "maximum": 100,
          "minimum": -100,
          "title": "Vibrance",
          "type": "integer"
        },
        "whites": {
          "default": 0,
          "maximum": 100,
          "minimum": -100,
          "title": "Whites",
          "type": "integer"
        }
      },
      "title": "PhotoGlobalAdjustments",
      "type": "object"
    },
    "PhotoLocalAdjustment": {
      "additionalProperties": false,
      "properties": {
        "adjustments": {
          "additionalProperties": true,
          "title": "Adjustments",
          "type": "object"
        },
        "featherPx": {
          "default": 16,
          "maximum": 256,
          "minimum": 0,
          "title": "Featherpx",
          "type": "integer"
        },
        "invert": {
          "default": false,
          "title": "Invert",
          "type": "boolean"
        },
        "maskGenerator": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Maskgenerator"
        },
        "maskSha256": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Masksha256"
        },
        "maskType": {
          "enum": [
            "sky_heuristic",
            "foreground_gradient",
            "subject_radial",
            "linear_gradient",
            "radial_gradient",
            "semantic_or_gradient_mask",
            "object_mask"
          ],
          "title": "Masktype",
          "type": "string"
        },
        "maskUri": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Maskuri"
        },
        "target": {
          "title": "Target",
          "type": "string"
        }
      },
      "required": [
        "target",
        "maskType"
      ],
      "title": "PhotoLocalAdjustment",
      "type": "object"
    }
  },
  "additionalProperties": false,
  "properties": {
    "constraints": {
      "items": {
        "type": "string"
      },
      "title": "Constraints",
      "type": "array"
    },
    "globalAdjustments": {
      "$ref": "#/$defs/PhotoGlobalAdjustments"
    },
    "intent": {
      "title": "Intent",
      "type": "string"
    },
    "kind": {
      "const": "photo_edit_recipe",
      "default": "photo_edit_recipe",
      "title": "Kind",
      "type": "string"
    },
    "localAdjustments": {
      "items": {
        "$ref": "#/$defs/PhotoLocalAdjustment"
      },
      "title": "Localadjustments",
      "type": "array"
    },
    "schemaVersion": {
      "const": "photo_edit_recipe.v1",
      "default": "photo_edit_recipe.v1",
      "title": "Schemaversion",
      "type": "string"
    }
  },
  "required": [
    "intent"
  ],
  "title": "PhotoEditRecipeV1",
  "type": "object"
}
```

## How to use

1. Produce a JSON object that validates against the schema above.
2. Hand it to the adapter's `validate_ir` then `compile`; the deterministic output is what the VIGOR loop reviews and exports.
3. Patches must round-trip: `apply_patch` must produce IR that still validates.
