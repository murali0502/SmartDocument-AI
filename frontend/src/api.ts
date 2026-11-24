export const api = "/api/v1/workspaces/local"

export async function json<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...options, cache: "no-store" })
  if (!response.ok) {
    const problem = await response.json().catch(() => null)
    throw new Error(problem?.detail ?? `Request failed (${response.status}).`)
  }
  return response.json() as Promise<T>
}

export function message(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong."
}
