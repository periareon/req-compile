"""The rules of `@package_metadata` for generated repositories."""

load("@package_metadata//licenses/rules:license.bzl", _license = "license")
load("@package_metadata//licenses/rules:license_kind.bzl", _license_kind = "license_kind")
load("@package_metadata//rules:package_metadata.bzl", _package_metadata = "package_metadata")

license = _license
license_kind = _license_kind
package_metadata = _package_metadata
