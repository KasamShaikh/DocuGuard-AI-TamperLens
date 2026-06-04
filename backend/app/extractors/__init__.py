"""Deterministic tamper-detection extractors.

Each extractor returns a normalized score in [0, 1] (higher = more suspicious)
plus human-readable evidence. The LLM consumes this structured evidence only.
"""
