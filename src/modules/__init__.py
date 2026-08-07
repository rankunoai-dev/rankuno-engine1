"""Domain modules.

Each subpackage owns one business domain and contains only `BaseTool`
subclasses plus the Pydantic models describing that domain. Cross-cutting
concerns belong in `src.core`; API access belongs in `src.integrations`.

Dependency direction is one-way and enforced by review:

    modules --> integrations --> core

No domain logic is implemented yet. These namespaces exist so the first feature
request lands in a predetermined place rather than inventing structure under
deadline.
"""
