"""Safety intelligence pipeline (Task #13).

PURE, deterministic policy engine only: the LLM NEVER decides whether a
country is safe. Adapters collect bounded facts from official sources;
`SafetyPolicyEngine` computes every displayed status from the closed
normalized vocabulary.
"""
