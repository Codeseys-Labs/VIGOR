# vigor-harness

Minimal Meta-Harness-inspired evaluator for VIGOR.

The package does not mutate code or run a proposer. It evaluates named harness candidates over split manifests whose `taskUris` point to individual JSON `TaskSpec` files. Each task runs through the normal VIGOR `Orchestrator` and `RunArchive`; the evaluator writes an aggregate report suitable for later promotion gates.

It intentionally does **not** load arbitrary untrusted factories by default. Candidate factories must live under a trusted VIGOR module prefix unless the caller passes a trusted evaluator-side allowlist.
