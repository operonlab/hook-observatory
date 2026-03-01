import type { PaginatedResponse, User, UserDetail } from "@/types";

const BASE = "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
	const res = await fetch(`${BASE}${path}`, {
		credentials: "include",
		headers: { "Content-Type": "application/json" },
		...options,
	});
	if (!res.ok) {
		const body = await res.json().catch(() => ({}));
		throw new Error(
			(body as Record<string, string>).detail ||
				`Request failed: ${res.status}`,
		);
	}
	return res.json();
}

export function listUsers(params: {
	page?: number;
	page_size?: number;
	status_filter?: string;
	search?: string;
}): Promise<PaginatedResponse<User>> {
	const qs = new URLSearchParams();
	if (params.page) qs.set("page", String(params.page));
	if (params.page_size) qs.set("page_size", String(params.page_size));
	if (params.status_filter) qs.set("status_filter", params.status_filter);
	if (params.search) qs.set("search", params.search);
	return request(`/auth/admin/users?${qs.toString()}`);
}

export function getUserDetail(userId: string): Promise<UserDetail> {
	return request(`/auth/admin/users/${userId}`);
}

export function updateUser(
	userId: string,
	data: { display_name?: string; role?: string; status?: string },
): Promise<User> {
	return request(`/auth/admin/users/${userId}`, {
		method: "PATCH",
		body: JSON.stringify(data),
	});
}
