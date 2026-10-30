/** Categorical series colors for multi-line charts.
 *
 * Fixed 8-slot order, validated against this app's white chart surface
 * (#ffffff, light mode): all slots inside the lightness band and above the
 * chroma floor; worst adjacent colour-vision-deficient separation ΔE 9.1
 * (#eda100 vs #1baf7a, protan) against a ≥8 target; worst adjacent
 * normal-vision ΔE 19.6 against a ≥15 floor.
 *
 * Three slots (aqua, yellow, magenta) sit under 3:1 contrast on white, so any
 * chart using them **must** keep a visible legend or an accompanying table so
 * identity is never carried by colour alone. Both Supply charts do.
 *
 * Two rules when consuming this:
 *   1. Assign in fixed order and never cycle — a 9th series is not a generated
 *      hue. Cap the selection instead.
 *   2. Colour follows the entity, not its rank. Bind a slot to a series when it
 *      is added and hold it; deselecting one series must not repaint the rest.
 */
export const SERIES_COLORS = [
  "#2a78d6", // blue
  "#eb6834", // orange
  "#1baf7a", // aqua
  "#eda100", // yellow
  "#e87ba4", // magenta
  "#008300", // green
  "#4a3aa7", // violet
  "#e34948", // red
] as const;

export const MAX_SERIES = SERIES_COLORS.length;
