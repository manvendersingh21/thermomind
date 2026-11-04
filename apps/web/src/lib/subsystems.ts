export type SchematicPart =
  | "ambient"
  | "intake"
  | "compressor"
  | "combustor"
  | "turbine"
  | "exhaust"
  | "generator";

/** id = clickable object name in the animation scene */
export interface AnimationObject {
  id: string;
  label: string;
}

export interface SubsystemGuide {
  hypothesis_key: string;
  title: string;
  schematic_parts: SchematicPart[];
  animation_objects: AnimationObject[];
  measurements: string[];
  where_to_look: string[];
  engineer_checks: string[];
}

export const REVIEW_SENTENCE = "Review with approved site procedures; this software issues no control actions.";

export const ANIMATION_OBJECTS: AnimationObject[] = [
  { id: "general", label: "Overview" },
  { id: "gas-turbine", label: "Gas turbine" },
  { id: "air-and-gas-supply", label: "Air & gas supply — filter house, intake duct, fuel gas" },
  { id: "exhaust-path-and-heat-transfer", label: "Exhaust path & heat transfer" },
  { id: "steam-generation-and-steam-distribution", label: "Steam generation & distribution" },
  { id: "steam-turbine", label: "Steam turbine" },
  { id: "condenser-and-cooling-circuit", label: "Condenser & cooling circuit" },
  { id: "generators-and-grid-connection", label: "Generators & grid connection" },
  { id: "exhaust-gas-treatment-and-chimney", label: "Exhaust gas treatment & chimney" },
  { id: "water-treatment-and-auxiliary-services", label: "Water treatment & auxiliary services" },
  { id: "facility-infrastructure-and-operations", label: "Facility infrastructure & operations" },
];

const obj = (id: string): AnimationObject => {
  const found = ANIMATION_OBJECTS.find((o) => o.id === id);
  return found ?? { id, label: id };
};

export const SUBSYSTEM_GUIDES: Record<string, SubsystemGuide> = {
  intake_restriction: {
    hypothesis_key: "intake_restriction",
    title: "Air intake and compressor inlet",
    schematic_parts: ["intake", "compressor"],
    animation_objects: [obj("air-and-gas-supply"), obj("gas-turbine")],
    measurements: ["AFDP", "CDP", "TEY", "TIT"],
    where_to_look: [
      "Start at the filter house and inlet duct, where air filter differential pressure (AFDP) is measured across the filter elements.",
      "Then look at the compressor inlet and discharge, where compressor discharge pressure (CDP) would be expected to respond if airflow were restricted.",
      "Compare the AFDP trend with turbine energy yield (TEY) and turbine inlet temperature (TIT) over the same rows to see whether the pattern is corroborated downstream.",
    ],
    engineer_checks: [
      "Inspect the filter house differential pressure trend and the condition and loading history of the filter elements.",
      "Inspect the inlet duct and bellmouth for fouling, debris or icing.",
      "Compare AFDP against ambient humidity and any local dust or pollen events in the same period.",
      "Verify the differential pressure transmitter calibration and the condition of its impulse lines.",
      "Confirm whether the CDP and TEY trends corroborate a flow restriction or only the AFDP signal deviates.",
      REVIEW_SENTENCE,
    ],
  },
  sensor_issue: {
    hypothesis_key: "sensor_issue",
    title: "Implicated transmitter and its signal path",
    schematic_parts: ["compressor"],
    animation_objects: [obj("gas-turbine")],
    measurements: ["CDP", "TIT", "TEY", "AFDP"],
    where_to_look: [
      "Look first at the transmitter and signal path for the measurement that deviates (for example compressor discharge pressure), not at the machine itself.",
      "Check whether related signals such as TIT, TEY and AFDP show a matching real process change; if they do not, a measurement fault becomes more plausible.",
      "Review the tag's history in the data historian for steps, flat-lining or noise changes that a real process would not produce.",
    ],
    engineer_checks: [
      "Cross-check the implicated transmitter against redundant or adjacent sensors.",
      "Review calibration records and the date of the last calibration.",
      "Inspect transmitter and impulse line health for plugging, freezing or leaks.",
      "Verify whether TIT, TEY and AFDP corroborate any real process change in the same window.",
      "Review the data historian compression and deadband settings for the tag.",
      REVIEW_SENTENCE,
    ],
  },
  operating_condition: {
    hypothesis_key: "operating_condition",
    title: "Ambient and load context",
    schematic_parts: ["ambient", "generator", "turbine"],
    animation_objects: [obj("general"), obj("generators-and-grid-connection"), obj("gas-turbine")],
    measurements: ["AT", "AH", "AP", "TEY", "TIT", "TAT"],
    where_to_look: [
      "Look at the ambient conditions (temperature, humidity, pressure) and at the load the unit was dispatched to during the window.",
      "Then look at the turbine and generator side, where TEY, TIT and TAT reflect how much output was being produced.",
      "The deviation may reflect an operating regime rather than a fault, so establish context before looking for a component.",
    ],
    engineer_checks: [
      "Establish the ambient and load-dispatch context for the window.",
      "Identify whether the unit was at part load or base load.",
      "Note the inlet-air conditioning status (evaporative cooler, chiller, anti-icing) as recorded by the site.",
      "Compare with the same ambient band in the reference period.",
      "Confirm that the baseline model's expected TEY is within its training range for these conditions.",
      REVIEW_SENTENCE,
    ],
  },
  unknown: {
    hypothesis_key: "unknown",
    title: "No confident location",
    schematic_parts: [],
    animation_objects: [obj("general")],
    measurements: [],
    where_to_look: [
      "There is no confident plant location to point to for this case.",
      "Verify data quality first, then gather more context before localising anything.",
    ],
    engineer_checks: [
      "Verify data quality first: missing values, flat-lined signals and out-of-range readings.",
      "Gather a longer reference window for comparison.",
      "Collect the maintenance log for the period.",
      "Pull the relevant historian tags with timestamps so events can be aligned.",
      REVIEW_SENTENCE,
    ],
  },
};

export function guideFor(key: string | null | undefined): SubsystemGuide {
  if (key && Object.prototype.hasOwnProperty.call(SUBSYSTEM_GUIDES, key)) return SUBSYSTEM_GUIDES[key];
  return SUBSYSTEM_GUIDES.unknown;
}
