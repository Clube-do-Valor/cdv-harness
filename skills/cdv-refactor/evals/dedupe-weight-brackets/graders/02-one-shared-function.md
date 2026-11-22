---
type: llm
focus: trace
weight: 1
---

`shipping/brackets.py` defines the shared bracket function; `quote.py` and `label.py` call it and keep no bracket price literals (5.0, 9.5, 14.0, 20.0) of their own.
