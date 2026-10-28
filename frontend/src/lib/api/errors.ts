import type { components } from "./schema";

export type ErrorCode = components["schemas"]["ErrorBody"]["code"];
type ErrorDetail = components["schemas"]["ErrorDetail"];
type ErrorResponse = components["schemas"]["ErrorResponse"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: ErrorCode | "NETWORK_ERROR",
    message: string,
    readonly details: ErrorDetail[] = [],
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function toApiError(error: unknown, response: Response): ApiError {
  const body = (error as ErrorResponse | undefined)?.error;
  if (body) return new ApiError(response.status, body.code, body.message, body.details, body.request_id);
  return new ApiError(response.status, "INTERNAL_ERROR", `Request failed with status ${response.status}.`);
}

type FetchResult = { data?: unknown; error?: unknown; response: Response };

/** Await an openapi-fetch call and return its data, or throw an ApiError carrying the contract error envelope. */
export async function unwrap<R extends FetchResult>(call: Promise<R>): Promise<Exclude<R["data"], undefined>> {
  let result: R;
  try {
    result = await call;
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Could not reach the Nativeproof API.");
  }
  if (!result.response.ok || result.error !== undefined) throw toApiError(result.error, result.response);
  return result.data as Exclude<R["data"], undefined>;
}
