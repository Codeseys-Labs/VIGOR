# vigor-adapter-cad

First-slice CAD adapter for VIGOR.

The adapter intentionally avoids heavy CAD kernel dependencies in default CI. It validates a constrained parametric CAD IR and generates deterministic OpenSCAD `.scad` source for a bracket plate with mounting holes and optional ribs.

Future optional compilers can add OpenSCAD CLI STL export, CadQuery, FreeCAD, and FEM checks.
