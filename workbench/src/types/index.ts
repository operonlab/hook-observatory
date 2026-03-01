// --- Auth types ---

export interface User {
	id: string;
	email: string;
	display_name: string;
	avatar_url: string | null;
	role: string;
	status: string;
	created_at: string;
}

export interface OAuthAccount {
	id: string;
	provider: string;
	provider_id: string;
	email: string | null;
	name: string | null;
	avatar_url: string | null;
	created_at: string;
}

export interface UserDetail extends User {
	oauth_accounts: OAuthAccount[];
}

// --- App shell types ---

export interface AppInfo {
	id: string;
	name: string;
	description: string;
	icon: string;
	path: string;
	color: string;
	status: "available" | "coming-soon";
}

// --- Shared base types (mirrors core/src/shared/schemas.py) ---

export interface BaseEntity {
	id: string;
	space_id: string;
	created_by: string | null;
	created_at: string;
	updated_at: string;
}

export interface PaginatedResponse<T> {
	items: T[];
	total: number;
	page: number;
	page_size: number;
}

export interface ErrorResponse {
	detail: string;
	code: string;
	module: string | null;
}

// --- Memvault API types (P1 contract — shared between worktrees) ---

export interface MemoryBlock extends BaseEntity {
	content: string;
	block_type: "knowledge" | "skill" | "attitude" | "general";
	tags: string[];
	source_session: string | null;
	confidence: number;
}

export interface MemoryBlockCreate {
	content: string;
	block_type: "knowledge" | "skill" | "attitude" | "general";
	tags?: string[];
	source_session?: string;
}

export interface MemoryBlockUpdate {
	content?: string;
	block_type?: "knowledge" | "skill" | "attitude" | "general";
	tags?: string[];
	confidence?: number;
}

export interface KASProfile {
	id: string;
	space_id: string;
	knowledge_score: number;
	attitude_score: number;
	skill_score: number;
	updated_at: string;
}

export interface SemanticSearchResult {
	block: MemoryBlock;
	score: number;
}
