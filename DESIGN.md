# Customer Tracker — Design System

> **Source:** Stitch project `customertrackerbloomberg` (Terminal Prime)
> **Device:** Desktop · **Color Mode:** Dark Only · **Last Synced:** 2026-06-08

---

## Brand & Style Philosophy

This design system is built for **high-stakes, high-density financial environments** where information velocity and precision are paramount. The brand personality is unapologetically utilitarian, authoritative, and technical. It targets institutional traders and quantitative analysts who require maximum data visibility with zero visual distraction.

The style is a modern evolution of **Brutalism** mixed with **Retro-Futuristic** terminal aesthetics. It rejects modern UI trends like soft shadows, rounded corners, and generous whitespace in favor of a rigid 1px grid, high-contrast signals, and raw functionality. The emotional response is one of **total control and professional intensity**.

---

## Color Palette

### Core Colors

| Role            | Hex       | Usage                                                    |
|-----------------|-----------|----------------------------------------------------------|
| **Background**  | `#181309` | Primary canvas — near-black warm tone                    |
| **Surface**     | `#181309` | App background                                           |
| **Surface Dim** | `#181309` | Recessed areas                                           |
| **Surface Bright** | `#3F382C` | Elevated surfaces                                     |
| **On Surface**  | `#ECE1D0` | Primary text on dark backgrounds                         |
| **On Surface Variant** | `#D4C5AB` | Secondary / muted text                            |
| **Outline**     | `#9C8F78` | Borders, dividers                                        |
| **Outline Variant** | `#4F4632` | Subtle borders, separators                           |

### Surface Container Stack (Elevation Tiers)

| Tier                   | Hex       | Description                          |
|------------------------|-----------|--------------------------------------|
| Container Lowest       | `#120E05` | Deepest recessed areas               |
| Container Low          | `#201B11` | Sidebar backgrounds, inset panels    |
| Container (Default)    | `#241F14` | Standard card / panel surface        |
| Container High         | `#2F291E` | Focused / active cards               |
| Container Highest      | `#3A3428` | Topmost elevation, modals            |

### Signal Colors

| Role                  | Hex       | Usage                                          |
|-----------------------|-----------|-------------------------------------------------|
| **Primary**           | `#FFE4AE` | Primary text, highlights                        |
| **Primary Container** | `#FFC100` | CTAs, badges, active indicators (**Amber**)     |
| **On Primary**        | `#3F2E00` | Text on primary surfaces                        |
| **On Primary Container** | `#6D5100` | Text on amber containers                    |
| **Secondary**         | `#EDFFE1` | Live data, positive states                      |
| **Secondary Container** | `#28FF1D` | Active feeds, success (**Neon Green**)        |
| **On Secondary**      | `#013A00` | Text on green surfaces                          |
| **Tertiary**          | `#34FFFF` | Interactive elements, links (**Cyan**)          |
| **Tertiary Container** | `#00E1E1` | Command-line indicators                        |
| **On Tertiary**       | `#003737` | Text on cyan surfaces                           |
| **Error**             | `#FFB4AB` | Alerts, negative values                         |
| **Error Container**   | `#93000A` | Critical error backgrounds                      |
| **Surface Tint**      | `#FABD00` | Tint overlay for active states                  |

### Custom Override Colors

| Name       | Hex       | Purpose                              |
|------------|-----------|--------------------------------------|
| Primary    | `#FFC100` | Amber — structural labels, CTAs      |
| Secondary  | `#00FF00` | Neon Green — live data, positive     |
| Tertiary   | `#00FFFF` | Cyan — commands, links, interactive  |

### Functional Color Rules

- **Background:** Solid `#000000` / `#181309` for maximum contrast
- **Primary / Labels:** Amber `#FFC100` for all structural text, field labels
- **Active Data:** Neon Green `#00FF00` for live feeds, positive yields
- **Warning / Alert:** Red `#FF0000` for negative movement, system alerts
- **Commands / Links:** Cyan `#00FFFF` for interactive elements, shortcuts
- **Borders:** Dark Grey `#333333` defines the grid without competing with data

---

## Typography

### Font Stack

| Purpose           | Font Family        | Notes                                 |
|-------------------|--------------------|---------------------------------------|
| **Headlines**     | Archivo Narrow     | Condensed, authoritative, uppercase   |
| **Body / Data**   | JetBrains Mono     | Monospaced, decimal-aligned columns   |
| **Labels**        | JetBrains Mono     | Caps-lock utility labels              |

### Type Scale

| Token            | Font            | Size  | Weight | Line Height | Letter Spacing |
|------------------|-----------------|-------|--------|-------------|----------------|
| `display-lg`     | Archivo Narrow  | 20px  | 700    | 24px        | 0.02em         |
| `headline-md`    | Archivo Narrow  | 14px  | 600    | 18px        | —              |
| `data-mono`      | JetBrains Mono  | 12px  | 500    | 14px        | -0.01em        |
| `data-mono-sm`   | JetBrains Mono  | 10px  | 400    | 12px        | —              |
| `label-caps`     | JetBrains Mono  | 11px  | 700    | 12px        | —              |
| `command-inline`  | JetBrains Mono | 12px  | 700    | 14px        | —              |

### Typography Rules

- **Headers:** All headers should be UPPERCASE to reinforce the terminal aesthetic
- **Data & Body:** JetBrains Mono ensures perfect column alignment for numerical data
- **Base size:** Strictly 12px, dropping to 10px for labels and secondary metadata
- **Line height:** Kept tight — zero tolerance for "airy" leading to support high density

---

## Spacing & Layout

### Spacing Tokens

| Token            | Value  | Usage                             |
|------------------|--------|-----------------------------------|
| `unit`           | 4px    | Base spacing unit                 |
| `cell-padding-x` | 4px   | Horizontal cell padding           |
| `cell-padding-y` | 2px   | Vertical cell padding             |
| `gutter`         | 0px    | Inter-column gap                  |
| `margin-page`    | 0px    | Page margin                       |
| `border-width`   | 1px    | Structural border width           |
| `spacing-scale`  | 2      | Multiplier                        |

### Layout Rules

- **Density:** Zero-margin philosophy. Containers touch edges, separated by 1px borders only
- **Grid:** Strictly aligned coordinate system. Elements span columns without internal padding unless necessary for legibility
- **Alignment:** All data top-left aligned. Numerical columns decimal-aligned using monospaced spacing
- **Mobile:** Grid stacks vertically but maintains 1px border separation and 10–12px fonts. No scaling up for touch

---

## Elevation & Depth

This design system is **flat**. Depth is conveyed through color and containment, never shadows or blurs.

- **Tonal Layers:** No Z-axis. Overlays/modals use distinct containers with 1px Amber or Cyan border to indicate focus
- **Contrast Outlines:** Active windows / focused inputs → border changes from `#333333` to `#FFC100` (Amber) or `#00FFFF` (Cyan)
- **Backgrounds:** Content areas remain solid dark. No surface-level greys or tints

---

## Shapes

**Border Radius: 0px everywhere.** Sharp corners reinforce precision and technical nature. Applies to buttons, inputs, cards, and selection highlights.

---

## Components

### Data Grids
- 1px solid `#333333` borders
- Header cells: Amber label text
- Row hover: subtle `#1A1A1A` background or 1px Amber outline

### Buttons
- Rectangular, 1px border, 0px radius
- **Default:** Amber text/border on dark bg
- **Active:** Inverted — Amber background, black text
- No gradients

### Input Fields
- 1px Amber border when focused
- Text is Neon Green to indicate "live" / editing state

### Status Chips
- Small rectangular blocks, no rounding
- **UP / BUY:** Neon Green
- **DOWN / SELL:** Red
- **NEUTRAL:** Cyan

### Command Line
- Persistent input bar with Cyan prefix (`>`) and Cyan text
- Mimics terminal prompt for quick navigation and ticker lookups

### Charts
- Line and candle charts: 1px stroke widths
- Grid lines: `#333333` border color

---

## Screen Inventory

| Screen                              | Dimensions    |
|-------------------------------------|---------------|
| Finance Customer Tracking Terminal  | 2560 × 2048   |

---

## CSS Custom Properties (Ready-to-Use)

```css
:root {
  /* Surfaces */
  --bg:                    #181309;
  --surface:               #181309;
  --surface-dim:           #181309;
  --surface-bright:        #3F382C;
  --surface-container-lowest:  #120E05;
  --surface-container-low:     #201B11;
  --surface-container:         #241F14;
  --surface-container-high:    #2F291E;
  --surface-container-highest: #3A3428;

  /* Text */
  --on-surface:            #ECE1D0;
  --on-surface-variant:    #D4C5AB;
  --inverse-surface:       #ECE1D0;
  --inverse-on-surface:    #363024;

  /* Borders */
  --outline:               #9C8F78;
  --outline-variant:       #4F4632;

  /* Primary (Amber) */
  --primary:               #FFE4AE;
  --primary-container:     #FFC100;
  --on-primary:            #3F2E00;
  --on-primary-container:  #6D5100;
  --surface-tint:          #FABD00;

  /* Secondary (Green) */
  --secondary:             #EDFFE1;
  --secondary-container:   #28FF1D;
  --on-secondary:          #013A00;
  --on-secondary-container:#027100;

  /* Tertiary (Cyan) */
  --tertiary:              #34FFFF;
  --tertiary-container:    #00E1E1;
  --on-tertiary:           #003737;
  --on-tertiary-container: #005F5F;

  /* Error */
  --error:                 #FFB4AB;
  --error-container:       #93000A;
  --on-error:              #690005;
  --on-error-container:    #FFDAD6;

  /* Typography */
  --font-headline:         'Archivo Narrow', sans-serif;
  --font-mono:             'JetBrains Mono', monospace;

  /* Spacing */
  --unit:                  4px;
  --cell-pad-x:            4px;
  --cell-pad-y:            2px;
  --border-w:              1px;
}
```

---

## Google Fonts Import

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo+Narrow:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
```
