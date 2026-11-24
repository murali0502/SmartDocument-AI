/// <reference types="vite/client" />
export const api = "/api/v1/workspaces/local"

const configuredOrigin: unknown = import.meta.env.VITE_SMARTDOC_API_ORIGIN
export const apiOrigin = typeof configuredOrigin === "string" ? configuredOrigin : ""
let workspaceAuthorization = ""

export function setWorkspacePassword(password: string) {
  workspaceAuthorization = password ? `Basic ${btoa(`smartdoc:${password}`)}` : ""
}

export function apiFetch(path: string, options?: RequestInit) {
  if (!path.startsWith("/api/v1/")) throw new Error("Invalid workspace API path.")
  const headers = new Headers(options?.headers)
  if (apiOrigin && workspaceAuthorization) headers.set("Authorization", workspaceAuthorization)
  return fetch(apiOrigin + path, { ...options, headers, cache: "no-store", redirect: "error" })
}

export async function json<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await apiFetch(url, options)
  if (!response.ok) {
    const problem = await response.json().catch(() => null)
    throw new Error(problem?.detail ?? `Request failed (${response.status}).`)
  }
  return response.json() as Promise<T>
}

export function message(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong."
}
