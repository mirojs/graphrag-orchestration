# Pro Mode Theming Guide (Fluent UI v9)

This guide documents the theming approach for Pro Mode: how colors are chosen, which tokens to use, patterns to follow, and a quick QA checklist for light/dark accessibility.

## overview

- Foundation: Fluent UI v9 tokens and CSS variables (via ThemeProvider/ProModeThemeProvider).
- Goal: No hard-coded hex colors. All surfaces derive from tokens for consistent light/dark rendering and brand overrides.
- Scope covered: Prediction/analysis surfaces, compare modal, schema management (SchemaTab), viewer overlays (Enhanced/Advanced), and shared selection/scroll styles.

## tokens you should use

Prefer Fluent alias tokens and semantic palettes. Commonly used in this project:

- Neutral (structure/containers)
  - Background: `--colorNeutralBackground1/2/3/4/5`, `--colorNeutralBackground1Selected`
  - Foreground: `--colorNeutralForeground1/2/3`, `--colorNeutralForegroundOnBrand`
  - Stroke: `--colorNeutralStroke1/2/3`

- Brand (primary actions)
  - Background: `--colorBrandBackground`
  - Stroke: `--colorBrandStroke1`
  - Foreground (on brand): `--colorNeutralForegroundOnBrand`

- Semantic palettes (status/accents)
  - Blue (informative): `--colorPaletteBlueForeground2`, `--colorPaletteBlueBackground1/2`, `--colorPaletteBlueBorder1/2`
  - Red (error): `--colorPaletteRedForeground1/2`, `--colorPaletteRedBackground1`, `--colorPaletteRedBorder1`
  - Green (success): `--colorPaletteGreenForeground2`, `--colorPaletteGreenBackground1/2`, `--colorPaletteGreenBorder1`
  - Yellow (warning): `--colorPaletteYellowForeground2`, `--colorPaletteYellowBackground1`, `--colorPaletteYellowBorder1`
  - Orange (accent): `--colorPaletteOrangeBorder2`

- Overlay
  - Overlay backdrop: `--colorOverlay`

Notes:
- Use blue tokens for links/icons and light accents, not large body surfaces.
- Prefer neutral backgrounds; add a thin brand/semantic border or small badge for emphasis.

## patterns to follow

- No hex literals. Use tokens or CSS variables. If translucency is needed:
  - Use `color-mix` with tokens, for example:
    - `background: color-mix(in oklab, var(--colorPaletteYellowBackground1) 40%, transparent)`
  - For canvas rendering (where CSS vars aren’t directly usable), resolve colors via computed styles in code.

- Tables and dense data
  - Base rows on neutral backgrounds; hover with `--colorNeutralBackground3`, selection with `--colorNeutralBackground1Selected`.
  - Use badges (outline or tint) for severity, not heavy solid fills.

- Banners and info panels
  - Info (blue): neutral background (`--colorNeutralBackground2`), thin blue border, title/icon in blue, body text neutral.
  - Error/Warning/Success: use the palette’s Background/Foreground/Border tokens accordingly.

- Buttons and actions
  - Primary: `--colorBrandBackground` with `--colorNeutralForegroundOnBrand`, stroke `--colorBrandStroke1`.
  - Subtle/outline variants rely on neutral tokens.

- Focus and hover states
  - Ensure focus rings meet ≥3:1 contrast against surroundings (use Fluent’s default focus styles where possible).
  - Links should add an underline on hover to avoid color-only cues.

- Color-blind safety
  - Don’t rely only on red/green. Pair color with icons or short labels (✓, !, ×).

## component-specific guidance

- SchemaTab
  - Inline edit “active” backgrounds use `--colorPaletteBlueBackground1`.
  - Error panels use red palette tokens; info panels use neutral + blue border.
  - “ACTIVE” label uses `--colorPaletteGreenForeground2`.

- FileComparisonModal and selection styles
  - Removed all hex fallbacks; rely entirely on tokens in `promode-selection-styles.css`.
  - Selection counters and reference/input rows use blue/green palettes for subtle accents.

- Viewers (Enhanced/Advanced)
  - EnhancedDocumentViewer status chip uses brand tokens (bg/fg/stroke) to remain legible in both themes.
  - AdvancedDocumentViewer text highlight overlays use `color-mix` with palette tokens for translucent fills and semantic borders.

## accessibility and QA checklist

Run this 10-minute sweep after UI changes:

- Contrast
  - Body text: ≥4.5:1; UI elements and focus indicators: ≥3:1.
  - Verify in both light and dark themes.

- Interaction cues
  - Hover states visible on neutral backgrounds.
  - Focus rings clearly visible (keyboard navigation).
  - Links distinguishable from plain text without relying solely on color.

- Data-dense screens
  - Tables readable with minimal chroma; badges/borders provide emphasis without visual noise.

- Overlays and highlights
  - Highlights translucent enough to read content underneath; lower `color-mix` percentage if distracting.

- Color-blind safety
  - States include icons or labels (not only color).

## brand customization

To adapt for enterprise branding:
- Keep semantic palettes intact (error/warn/success). Adjust brand ramp (primary hue) if needed.
- Provide a single “brand hue” config (seed) and derive mapping to Fluent brand tokens to avoid one-off color overrides.
- Validate contrast after switching brand hue, especially on primary buttons and links.

## file inventory (recent updates)

- Schema and analysis surfaces
  - `code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/SchemaTab.tsx` (all hard-coded hex replaced, AI dialogs and banners themed)
  - `code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/promode-selection-styles.css` (hex fallbacks removed; pure tokens)

- Viewers
  - `code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/EnhancedDocumentViewer.tsx` (brand-based status chip)
  - `code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/AdvancedDocumentViewer.tsx` (token-based highlight fill/border)

- Compare modal
  - `code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/FileComparisonModal.css` – prior tokenization applied (verify light/dark QA as needed)

## do and don’t

- Do
  - Use Fluent tokens and CSS variables everywhere
  - Keep surfaces neutral; use small accents for emphasis
  - Use badges/borders instead of large solid fills

- Don’t
  - Hard-code hex colors
  - Use strong chroma for large panels or dense tables
  - Convey meaning using color alone

## troubleshooting

- Too little contrast in dark mode? Move from Background1 → Background2/3 and/or pick a stronger Foreground token.
- Highlights overpowering content? Lower the `color-mix` percentage or use a lighter background token.
- Inconsistent focus/hover? Ensure components inherit Fluent defaults; avoid custom overrides unless necessary.
