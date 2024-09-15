# Override module repos

This test ensures that a child module may have
its Python requirements hubs overridden by a root module. This is
required to ensure interoperability of imports.

## Overridee
Project with `platformdirs` version 4.2.2

## Overrider
Project with `platformdirs` version 4.2.1

## Test
Ensure that when importing platformdirs as a transitive dep via `overridee` that the
version matches the root module.