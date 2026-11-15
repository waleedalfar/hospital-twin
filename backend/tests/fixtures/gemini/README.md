# Recorded Gemini responses (tests only)

Shapes of what the Gemini API returns for the operations agent's structured output. They are used by the tests
through a fake client; production code never reads this folder. `valid_divert.json` is a well-formed,
grounded answer for the summary built in `tests/agent_helpers.py`; the others are the failure modes the
grounding check and the retry must handle.
