English | [Tiếng Việt](README.vi.md)

# Design tokens

`tokens.json` — the token source of the design system (four appearances `light`, `dark`, `light-hc`, `dark-hc`; colors, typography, spacing, corner radii, shadows, sizes, durations). The format follows the Design System artifact (each family is a list of `{name, value, usage}`; a color may be an alias `{token}`). Generate code from it instead of copying values by hand: Compose `HandLiveTheme` (Android), Asset Catalog Color Sets + `Font` (Apple). On Apple, semantic colors (`label`, `systemBackground`…) always call the system API; the values in the file are only a reference.
