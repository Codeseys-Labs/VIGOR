---
name: manim-scene
description: Manim scene IR carrying scene title, scene class name, Python source, optional duration.
---

# manim-scene

Manim scene IR carrying scene title, scene class name, Python source, optional duration.

## IR contract

This adapter consumes the `manim_scene.v1` intermediate representation, modeled by `ManimSceneIRV1`.

### JSON Schema

```json
{
  "additionalProperties": false,
  "properties": {
    "durationS": {
      "anyOf": [
        {
          "exclusiveMinimum": 0,
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Durations"
    },
    "kind": {
      "const": "manim_scene",
      "default": "manim_scene",
      "title": "Kind",
      "type": "string"
    },
    "prompt": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Prompt"
    },
    "pythonCode": {
      "title": "Pythoncode",
      "type": "string"
    },
    "sceneName": {
      "default": "VigorScene",
      "pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
      "title": "Scenename",
      "type": "string"
    },
    "schemaVersion": {
      "const": "manim_scene.v1",
      "default": "manim_scene.v1",
      "title": "Schemaversion",
      "type": "string"
    },
    "title": {
      "title": "Title",
      "type": "string"
    }
  },
  "required": [
    "title",
    "pythonCode"
  ],
  "title": "ManimSceneIRV1",
  "type": "object"
}
```

## How to use

1. Produce a JSON object that validates against the schema above.
2. Hand it to the adapter's `validate_ir` then `compile`; the deterministic output is what the VIGOR loop reviews and exports.
3. Patches must round-trip: `apply_patch` must produce IR that still validates.
