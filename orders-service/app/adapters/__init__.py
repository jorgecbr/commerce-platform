"""Inbound and outbound adapters.

Everything that talks to the outside world lives here: HTTP, the database,
Redis, Kafka. Adapters implement the ``Protocol`` ports declared in
``app.application.ports`` and never contain business rules.
"""
