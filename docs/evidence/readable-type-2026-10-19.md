# Typography readability follow-up (#111)

Replaced the redesigned consumer UI's 9–12px copy with shared rem-based sizes:
18px-equivalent body text, 17px controls/rating rows, 16px secondary content and
15px minimum metadata. Matchup names remain 24px on desktop and mobile. Increased
line spacing and control heights, enlarged checkboxes, and allowed controls,
metadata and section headings to wrap rather than shrinking text to fit.

Validation: TypeScript/Vite production build passed. Actual Chrome inspection
covered desktop, 390px mobile and 320px narrow mobile. DOM page width matched
viewport width at both mobile sizes. Explicit rating disclosure was exercised:
rating rows rendered at 17px and expanded provenance at 15px; long references
wrapped without overflow at 320px. Mode switching cleared the disclosure after
inspection. No application behavior, data or scoring contracts changed. Temporary
viewport overrides were reset. Final hosted CI is linked in PR #112.

[Desktop](readable-type-desktop-2026-10-19.png) ·
[Mobile](readable-type-mobile-2026-10-19.png)
