/**
 * Decoration around the hospital: trees, parked cars and the street car. These are scenery, not data: they
 * carry no patient, staff or status information and are the same for every hospital (reference/engine/
 * pulse3d.js). Ambulances and the helicopter are NOT scenery; they come from the live vehicle list.
 */
export const TREES: readonly [number, number][] = [
  [-30, -22], [-34, 4], [-28, 20], [-42, -8], [30, -22], [36, -8], [46, 14], [-12, -26], [4, -28], [18, -25],
  [-24, 40], [0, 42], [26, 40], [-48, 32], [48, 34], [-54, -30], [54, -28], [-60, 6], [60, 0],
]; // prettier-ignore

/** Color, x, z of the cars in the parking lot. */
export const PARKED_CARS: readonly [string, number, number][] = [
  ['#d64545', 29, 3],
  ['#3d6fd6', 33, 3],
  ['#f0b030', 37, 9],
  ['#7a5cc2', 29, 9],
];

export const PARKING_LOT = { x: 33, z: 6, w: 14, d: 12 } as const;
export const SIDEWALK = { z: 15.4, w: 44, d: 2 } as const;
/** The civilian car that drives along the street, slightly in front of the building (z). */
export const STREET_CAR = { z: 26.2, color: '#c9d2e3', speed: 12, span: 180 } as const;
