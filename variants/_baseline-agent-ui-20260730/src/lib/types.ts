export type ToolStatus =
  | "ok"
  | "insufficient_evidence"
  | "invalid_request"
  | "source_error";

export interface ToolResponse<T> {
  status: ToolStatus;
  schemaVersion: string;
  sourceHashes: Record<string, string>;
  methodNote: string;
  payload: T;
}

export interface PoetCatalogRow {
  poet: string;
  dynasty: string;
  dynastyCounts: Record<string, number>;
  workCount: number;
  routeStatus: "available" | "insufficient_evidence";
  sceneCount: number;
  mappedSceneCount: number;
}

export interface PoetCatalog {
  poetCount: number;
  routeAvailableCount: number;
  insufficientEvidenceCount: number;
  poets: PoetCatalogRow[];
}

export interface PoetryScene {
  index: number;
  id: string;
  poet: string;
  poet_key: string;
  color: string;
  dynasty: string;
  year: number;
  year_start: number;
  year_end: number;
  year_label: string;
  year_precision: string;
  year_precision_display: string;
  sequence: string;
  place_historical: string;
  place_modern: string;
  province: string;
  lon: number | null;
  lat: number | null;
  map_eligible: boolean;
  event: string;
  poem_title: string;
  source_poem_id: string;
  poem_lines: string[];
  poem_chars: number;
  source_grade: string;
  source_status: string;
  review_state: string;
  source_name: string;
  source_url: string;
  source_note: string;
  confidence: number;
  emotion_label: string;
  emotion_evidence: string;
  valence: number;
  intensity: number;
  relation_grade: string;
  read_seconds: number;
  scene_image?: string;
}

export interface RouteSegment {
  from_id: string;
  to_id: string;
  coords: [[number, number], [number, number]];
  kind: "chronology" | "visual_transition";
  certainty: "strict" | "not_asserted";
  historical_claim?: boolean;
  gap_reason?: "adjacent_locatable_scene_gap";
  transport_mode: "boat" | "horse" | "carriage" | "walk" | "journey";
  transport_label: string;
  transport_basis: string;
  transport_certainty: "documented" | "unspecified";
}

export interface RoutePayload {
  poet: string;
  poetKey?: string;
  dynasty: string;
  color?: string;
  corpusWorkCount: number;
  sceneCount: number;
  mappedSceneCount: number;
  precisionCounts?: Record<string, number>;
  scenes: PoetryScene[];
  routeSegments: RouteSegment[];
  visualTransitions: RouteSegment[];
  unresolved?: Array<Record<string, unknown>>;
  missingFacts?: string[];
}

export interface ScenePayload extends Omit<RoutePayload, "routeSegments" | "visualTransitions"> {
  mode: "manual_step" | "autoplay" | "scene_playback";
  autoplay?: boolean;
  manualStepDefault?: boolean;
  pauseAtEachScene?: boolean;
  startSceneId?: string | null;
  startIndex?: number;
  controls?: string[];
}

export interface ImageryRate {
  rawHits: number;
  ratePer10k: number;
  chineseCharDenominator: number;
  poemRecords: number;
  poemsWithHit: number;
}

export interface ImageryEvidence {
  dynasty: string;
  poet: string;
  title: string;
  sentence: string;
  matchStart?: number;
  matchEnd?: number;
}

export interface ImageryComparisonRow {
  word: string;
  category: string;
  higherIn: string;
  deltaSongMinusTang: number;
  absoluteDelta: number;
  tang: ImageryRate;
  song: ImageryRate;
  corpusEvidence: ImageryEvidence[];
  chapterStats?: Record<string, unknown> | null;
  chapterEvidence?: ImageryEvidence[];
}

export interface ImageryPayload {
  selectionRule: string;
  requestedLimit: number;
  terms: string[];
  allowedTermCount: number;
  normalization?: string;
  dynastyAggregates?: Record<string, unknown>;
  comparisons: ImageryComparisonRow[];
  chapter?: Record<string, unknown> | null;
  availableChapters?: Array<{
    id: string;
    title: string;
    startYear: number;
    endYear: number;
  }>;
}

export type WorkbenchMode = "route" | "scenes" | "imagery";
export type WorkbenchPayload = RoutePayload | ScenePayload | ImageryPayload;
