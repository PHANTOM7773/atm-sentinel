import type {
  CvAnalyzeRequest,
  CvAnalyzeResponse,
  CvBestFaceSelectionResponse,
  CvCandidateSearchRequest,
  CvCandidateSearchResponse,
  CvEmbeddingsResponse,
  CvFaceObservationSummary,
  CvHumanReviewDecision,
  CvPage,
  CvPersonAssociationPage,
  CvReviewUpsertRequest,
  CvRunCreateRequest,
  CvRunCreateResponse,
  CvRunSummary,
  CvStatusResponse,
  SessionResponse,
  SessionState,
  SystemStatus,
  TransactionPersonAssociationRecord,
  TransactionPersonAssociationReviewRequest,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export class ApiError extends Error {
  readonly status: number;
  readonly retryAfterSeconds: number | null;

  constructor(message: string, status: number, retryAfterSeconds: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

function retryAfter(header: string | null): number | null {
  if (!header) return null;
  const seconds = Number(header);
  if (Number.isFinite(seconds)) return Math.max(0, Math.floor(seconds));
  const date = Date.parse(header);
  return Number.isNaN(date) ? null : Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, { credentials: "include", ...init });
  } catch (error) {
    throw new Error(`Cannot reach the local API at ${BASE_URL}. Start the backend first. (${String(error)})`);
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* response was not JSON */
    }
    throw new ApiError(detail, response.status, retryAfter(response.headers.get("Retry-After")));
  }
  return (await response.json()) as T;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown = {}) => request<T>(path, jsonInit("POST", body)),
  patch: <T>(path: string, body: unknown) => request<T>(path, jsonInit("PATCH", body)),
  upload: <T>(path: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<T>(path, { method: "POST", body: form });
  },
  url: (path: string) => `${BASE_URL}${path}`,
  download: (path: string) => {
    window.open(`${BASE_URL}${path}`, "_blank", "noopener");
  },
};

export const systemApi = {
  status: () => api.get<SystemStatus>("/api/system/status"),
};

async function protectedSessionActive(): Promise<boolean> {
  try {
    await api.get("/api/cv/status");
    return true;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return false;
    throw error;
  }
}

export const sessionApi = {
  probe: async (): Promise<SessionState> => {
    const protectedAccess = await protectedSessionActive();
    try {
      const response = await api.post<SessionResponse>("/api/session", {});
      return { mode: response.mode === "secured" ? "secured" : "open", protectedAccess };
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        return { mode: "secured", protectedAccess };
      }
      throw error;
    }
  },
  login: (passphrase: string) => api.post<SessionResponse>("/api/session", { passphrase }),
};

export const cvApi = {
  status: () => api.get<CvStatusResponse>("/api/cv/status"),
  analyze: (payload: CvAnalyzeRequest) => api.post<CvAnalyzeResponse>("/api/cv/analyze", payload),
  embeddings: () => api.get<CvEmbeddingsResponse>("/api/cv/embeddings"),
  createRun: (payload: CvRunCreateRequest) => api.post<CvRunCreateResponse>("/api/cv/runs", payload),
  listRuns: (caseId: string, params: { limit?: number; offset?: number } = {}) =>
    api.get<CvPage<CvRunSummary>>(`/api/cv/runs${qs({ case_id: caseId, limit: params.limit, offset: params.offset })}`),
  getRun: (caseId: string, runId: string) =>
    api.get<CvRunSummary>(`/api/cv/runs/${encodeURIComponent(runId)}${qs({ case_id: caseId })}`),
  getObservations: (caseId: string, runId: string, params: { limit?: number; offset?: number } = {}) =>
    api.get<CvPage<CvFaceObservationSummary>>(
      `/api/cv/runs/${encodeURIComponent(runId)}/observations${qs({ case_id: caseId, limit: params.limit, offset: params.offset })}`,
    ),
  listReviews: (caseId: string, runId: string, params: { limit?: number; offset?: number } = {}) =>
    api.get<CvPage<CvHumanReviewDecision>>(
      `/api/cv/runs/${encodeURIComponent(runId)}/reviews${qs({ case_id: caseId, limit: params.limit, offset: params.offset })}`,
    ),
  listPersonAssociations: (
    caseId: string,
    runId: string,
    params: { transactionId?: string; limit?: number; offset?: number } = {},
  ) =>
    api.get<CvPersonAssociationPage>(
      `/api/cv/runs/${encodeURIComponent(runId)}/person-associations${qs({
        case_id: caseId,
        transaction_id: params.transactionId,
        limit: params.limit,
        offset: params.offset,
      })}`,
    ),
  getBestFace: (caseId: string, runId: string, associationId: string) =>
    api.get<CvBestFaceSelectionResponse>(
      `/api/cv/runs/${encodeURIComponent(runId)}/person-associations/${encodeURIComponent(associationId)}/best-face${qs({ case_id: caseId })}`,
    ),
  reviewPersonAssociation: (
    caseId: string,
    associationId: string,
    payload: TransactionPersonAssociationReviewRequest,
  ) =>
    api.post<TransactionPersonAssociationRecord>(
      `/api/cv/person-associations/${encodeURIComponent(associationId)}/review${qs({ case_id: caseId })}`,
      payload,
    ),
  getReview: (caseId: string, runId: string, observationId: string) =>
    api.get<CvHumanReviewDecision>(
      `/api/cv/runs/${encodeURIComponent(runId)}/observations/${encodeURIComponent(observationId)}/review${qs({ case_id: caseId })}`,
    ),
  upsertReview: (caseId: string, runId: string, observationId: string, payload: CvReviewUpsertRequest) =>
    api.post<CvHumanReviewDecision>(
      `/api/cv/runs/${encodeURIComponent(runId)}/observations/${encodeURIComponent(observationId)}/review${qs({ case_id: caseId })}`,
      payload,
    ),
  cropUrl: (caseId: string, runId: string, observationId: string, cropId: string) =>
    `${BASE_URL}/api/cv/runs/${encodeURIComponent(runId)}/observations/${encodeURIComponent(observationId)}/crop${qs({ case_id: caseId, crop_id: cropId })}`,
  searchCandidates: (payload: CvCandidateSearchRequest) =>
    api.post<CvCandidateSearchResponse>("/api/cv/candidates/search", payload),
};

export function qs(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}
