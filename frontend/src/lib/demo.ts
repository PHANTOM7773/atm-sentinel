export type DemoLabelSource = {
  case_number?: string;
  title?: string;
  location?: string;
  tags?: string;
  original_filename?: string;
  reference?: string;
  atm_id?: string;
  note?: string;
};

const DEMO_MARKER = /(?:^|[^a-z])(?:demo|sample|synthetic|test[ -]?data)(?:$|[^a-z])/i;

export function hasDemoMarker(...values: Array<string | null | undefined>): boolean {
  return values.some((value) => typeof value === "string" && DEMO_MARKER.test(value));
}

export function isDemoCase(record: DemoLabelSource): boolean {
  return hasDemoMarker(record.case_number, record.title, record.location, record.tags);
}

export function isDemoVideo(record: DemoLabelSource): boolean {
  return hasDemoMarker(record.original_filename, record.tags);
}

export function isDemoTransaction(record: DemoLabelSource): boolean {
  return hasDemoMarker(record.reference, record.atm_id, record.note);
}

export function demoOptionLabel(label: string, demo: boolean): string {
  return demo ? `${label} [demo data]` : label;
}
