# SkillForge design system

**Status:** Active for the `apps/web` frontend  
**Surface:** Skill creation workspace (Operate)  
**Direction:** A calm, warm-neutral workspace with restrained clay accents. It borrows the quiet hierarchy the team requested while keeping SkillForge's own name, content, controls, and component styling.

## Principles

- Keep the skill request and its next action at the center of the screen.
- Use familiar navigation and form controls; reserve the accent for primary actions, selection, and focus.
- Support Arabic-first, right-to-left content. Keep paths, code, and generated Markdown left-to-right where they are shown.
- Use semantic color tokens so the same components remain readable in light and dark themes.
- Do not introduce billing, a paid marketplace, or model-selection controls into the V1 shell; those are outside the supplied V1 scope.

## Color tokens

The source of truth is `apps/web/app/globals.css`. Components use semantic CSS variables instead of page-specific color values.

| Role             | Light     | Dark      |
| ---------------- | --------- | --------- |
| Page background  | `#fffefa` | `#1c1b19` |
| Main surface     | `#fffefa` | `#252320` |
| Sidebar surface  | `#f7f6f2` | `#23221f` |
| Hover surface    | `#eeede7` | `#32302b` |
| Selected surface | `#eceae2` | `#39362f` |
| Primary text     | `#292723` | `#f0eee8` |
| Secondary text   | `#646158` | `#d0cabe` |
| Muted text       | `#706c64` | `#b6b0a5` |
| Border           | `#e9e7df` | `#3b3832` |
| Brand accent     | `#a45e43` | `#d99a79` |
| Accent hover     | `#8d4c34` | `#e8ab8c` |
| Accent surface   | `#f7eee8` | `#392a23` |
| Success          | `#55785e` | `#a1c69f` |

Normal supporting text uses at least 4.5:1 contrast on its intended surfaces. In the light theme, `#706c64` reaches 5.18:1 on `#fffefa` and 4.83:1 on `#f7f6f2`; the light primary button's `#fffaf6` text reaches 4.75:1 on `#a45e43`. The dark palette uses lighter text and accent values on its dark surfaces.

## Typography

- **UI:** `Arial, Tahoma, sans-serif`, allowing the browser to use its Arabic-capable system fallback.
- **Display:** `Georgia, "Times New Roman", serif` for the welcome heading and wordmark only.
- **Code:** `SFMono-Regular, Consolas, "Liberation Mono", monospace` for paths and generated files.
- **Scale:** 12px is the minimum supporting label; standard body copy is 14–16px. The home heading is 44px desktop, 40px tablet, 34px mobile, and 32px on the narrowest screens.
- Keep body copy comfortably spaced and use the serif display face sparingly so it remains a detail rather than an interface-wide voice.

## Layout and spacing

- Use a 4px spacing base; common gaps are 8, 12, 16, 20, 24, and 32px.
- Desktop sidebar: 258px; tablet sidebar: 236px; collapsed desktop sidebar: 68px.
- Main workspace fills the remaining width and keeps the welcome content to 632px.
- Breakpoints: 900px for the narrower desktop rail, 800px for stacked suggestion rows, 680px for the right-side mobile drawer, and 380px for narrow-phone spacing.
- On mobile, keep the app shell at `100dvh`, open navigation from the right in RTL, and dim the page behind the drawer.

## Shape, depth, and interaction

- Controls use an 8px radius; compact rows use 8–10px; main panels use 14px.
- Prefer a fine border for separation and one soft, offset shadow for raised surfaces. Avoid decorative gradients and glass effects.
- Icon controls and primary touch actions have at least a 44×44px hit area. Visible keyboard focus uses the semantic ring token.
- Hover, focus, disabled, and selected states use the same tokens in both themes. Respect `prefers-reduced-motion`.
- The theme control follows the system preference until the user chooses a theme, then remembers that choice in local storage.

## Component notes

| Component       | Contract                                                                                                                                        |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Sidebar         | Persistent navigation on desktop, collapsible to icons, right-side drawer on mobile. Includes create, library, and personal-skill destinations. |
| Primary action  | Full-width sidebar button, neutral surface with a clear accent icon; 44px minimum height.                                                       |
| Navigation item | 44px minimum height; accent is not needed for inactive items; selected route uses the selected-surface token and a weight change.               |
| Icon button     | 44×44px hit area, Lucide outline icon, descriptive accessible name, visible focus.                                                              |
| Composer        | White/surface panel with visible boundary, 16px input on mobile, inline focus and disabled/send states.                                         |
| Suggestion row  | Clear text label and helper text; stacks at tablet and mobile widths instead of squeezing labels.                                               |
| Profile summary | Static account identity until FE-07 connects authentication; not a navigation control yet.                                                      |

The shell navigation is wired to the route map proposed in `docs/frontend/FE-02-user-flows.md`; pages will become active as their frontend tasks are implemented. Recent-skill rows are sample content until the user's-skill API is connected.
