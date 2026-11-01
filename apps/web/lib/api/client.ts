import createClient from "openapi-fetch";
import type { paths } from "./schema";

export function createApiClient(baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL) {
  if (!baseUrl) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL must be set before calling the API.");
  }

  return createClient<paths>({ baseUrl });
}

export type ApiClient = ReturnType<typeof createApiClient>;
