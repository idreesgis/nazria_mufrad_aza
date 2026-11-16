"""Nazria Mufrad Aza knowledge-base pipeline.

Turns the OCR export of "کلیات تحقیقات صابر ملتانی" (2 volumes) into a cleaned,
structured knowledge base and a rule-based Hakeem <-> Patient conversation
dataset, and loads it into PostgreSQL.

Stages:  parse -> normalize/clean -> structure -> entities -> dialogues -> db
"""

PIPELINE_VERSION = "1.0.0"
