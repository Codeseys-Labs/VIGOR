---
name: cad-parametric
description: Parametric CAD IR for OpenSCAD generation (bracket plates with mounting holes and ribs).
---

# cad-parametric

Parametric CAD IR for OpenSCAD generation (bracket plates with mounting holes and ribs).

## IR contract

This adapter consumes the `cad_parametric.v1` intermediate representation, modeled by `CadParametricIRV1`.

### JSON Schema

```json
{
  "$defs": {
    "CadConstraints": {
      "additionalProperties": false,
      "properties": {
        "manufacturing": {
          "default": "fdm",
          "enum": [
            "fdm",
            "sla",
            "cnc",
            "unknown"
          ],
          "title": "Manufacturing",
          "type": "string"
        },
        "maxBboxMm": {
          "items": {
            "type": "number"
          },
          "maxItems": 3,
          "minItems": 3,
          "title": "Maxbboxmm",
          "type": "array"
        },
        "minWallThicknessMm": {
          "default": 3.0,
          "exclusiveMinimum": 0,
          "title": "Minwallthicknessmm",
          "type": "number"
        }
      },
      "title": "CadConstraints",
      "type": "object"
    },
    "CadFeature": {
      "additionalProperties": false,
      "properties": {
        "count": {
          "anyOf": [
            {
              "minimum": 0,
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Count"
        },
        "type": {
          "enum": [
            "base_plate",
            "mounting_holes",
            "ribs"
          ],
          "title": "Type",
          "type": "string"
        }
      },
      "required": [
        "type"
      ],
      "title": "CadFeature",
      "type": "object"
    },
    "CadParameters": {
      "additionalProperties": false,
      "properties": {
        "heightMm": {
          "default": 60.0,
          "exclusiveMinimum": 0,
          "title": "Heightmm",
          "type": "number"
        },
        "holeDiameterMm": {
          "default": 4.5,
          "exclusiveMinimum": 0,
          "title": "Holediametermm",
          "type": "number"
        },
        "holeMarginMm": {
          "default": 10.0,
          "minimum": 0,
          "title": "Holemarginmm",
          "type": "number"
        },
        "ribCount": {
          "default": 2,
          "maximum": 8,
          "minimum": 0,
          "title": "Ribcount",
          "type": "integer"
        },
        "ribThicknessMm": {
          "default": 4.0,
          "exclusiveMinimum": 0,
          "title": "Ribthicknessmm",
          "type": "number"
        },
        "thicknessMm": {
          "default": 5.0,
          "exclusiveMinimum": 0,
          "title": "Thicknessmm",
          "type": "number"
        },
        "widthMm": {
          "default": 100.0,
          "exclusiveMinimum": 0,
          "title": "Widthmm",
          "type": "number"
        }
      },
      "title": "CadParameters",
      "type": "object"
    }
  },
  "additionalProperties": false,
  "properties": {
    "constraints": {
      "$ref": "#/$defs/CadConstraints"
    },
    "features": {
      "items": {
        "$ref": "#/$defs/CadFeature"
      },
      "title": "Features",
      "type": "array"
    },
    "intent": {
      "title": "Intent",
      "type": "string"
    },
    "kind": {
      "const": "cad_parametric",
      "default": "cad_parametric",
      "title": "Kind",
      "type": "string"
    },
    "parameters": {
      "$ref": "#/$defs/CadParameters"
    },
    "partType": {
      "const": "bracket_plate",
      "default": "bracket_plate",
      "title": "Parttype",
      "type": "string"
    },
    "schemaVersion": {
      "const": "cad_parametric.v1",
      "default": "cad_parametric.v1",
      "title": "Schemaversion",
      "type": "string"
    },
    "units": {
      "const": "mm",
      "default": "mm",
      "title": "Units",
      "type": "string"
    }
  },
  "required": [
    "intent"
  ],
  "title": "CadParametricIRV1",
  "type": "object"
}
```

## How to use

1. Produce a JSON object that validates against the schema above.
2. Hand it to the adapter's `validate_ir` then `compile`; the deterministic output is what the VIGOR loop reviews and exports.
3. Patches must round-trip: `apply_patch` must produce IR that still validates.
