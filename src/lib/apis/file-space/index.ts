import { WEBUI_API_BASE_URL } from '$lib/constants';

export type FileSpaceEntry = {
	id: string;
	user_id: string;
	session_id: string | null;
	conversation_id: string | null;
	conversation_title: string | null;
	filename: string;
	file_path: string | null;
	file_size: number | null;
	mime_type: string | null;
	file_type: string | null;
	created_at: number;
};

export type FileSpaceGroup = {
	session_id: string;
	conversation_title: string;
	files: FileSpaceEntry[];
	file_count: number;
};

export type FileSpaceStats = {
	types: Record<string, { count: number; size: number }>;
	total_count: number;
	total_size: number;
};

export const getFileSpaceFiles = async (
	token: string,
	params?: { file_type?: string; session_id?: string; search?: string }
): Promise<FileSpaceEntry[]> => {
	const searchParams = new URLSearchParams();
	if (params?.file_type) searchParams.append('file_type', params.file_type);
	if (params?.session_id) searchParams.append('session_id', params.session_id);
	if (params?.search) searchParams.append('search', params.search);

	const res = await fetch(`${WEBUI_API_BASE_URL}/file-space/files?${searchParams.toString()}`, {
		headers: { Authorization: `Bearer ${token}` }
	})
		.then((r) => r.json())
		.catch(() => ({ files: [] }));
	return res.files ?? [];
};

export const getFileSpaceFilesGrouped = async (
	token: string,
	params?: { file_type?: string; search?: string }
): Promise<FileSpaceGroup[]> => {
	const searchParams = new URLSearchParams();
	if (params?.file_type) searchParams.append('file_type', params.file_type);
	if (params?.search) searchParams.append('search', params.search);

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/file-space/files/grouped?${searchParams.toString()}`,
		{ headers: { Authorization: `Bearer ${token}` } }
	)
		.then((r) => r.json())
		.catch(() => ({ groups: [] }));
	return res.groups ?? [];
};

export const getFileSpaceStats = async (token: string): Promise<FileSpaceStats> => {
	return await fetch(`${WEBUI_API_BASE_URL}/file-space/stats`, {
		headers: { Authorization: `Bearer ${token}` }
	})
		.then((r) => r.json())
		.catch(() => ({ types: {}, total_count: 0, total_size: 0 }));
};

export const trackFileSpaceFile = async (
	token: string,
	data: {
		session_id?: string;
		conversation_id?: string;
		conversation_title?: string;
		filename: string;
		file_path?: string;
		file_size?: number;
		mime_type?: string;
		file_type?: string;
	}
): Promise<FileSpaceEntry> => {
	return await fetch(`${WEBUI_API_BASE_URL}/file-space/files`, {
		method: 'POST',
		headers: {
			Authorization: `Bearer ${token}`,
			'Content-Type': 'application/json'
		},
		body: JSON.stringify(data)
	}).then((r) => r.json());
};

export const deleteFileSpaceFile = async (token: string, id: string): Promise<void> => {
	await fetch(`${WEBUI_API_BASE_URL}/file-space/files/${id}`, {
		method: 'DELETE',
		headers: { Authorization: `Bearer ${token}` }
	});
};

// --- OpenClaw Integration ---

export const syncOpenClawArtifacts = async (token: string): Promise<{ synced: number } | { error: string }> => {
	return await fetch(`${WEBUI_API_BASE_URL}/file-space/openclaw/sync`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${token}` }
	}).then((r) => r.json());
};

export const getOpenClawArtifacts = async (
	token: string,
	sessionKey?: string
): Promise<any[]> => {
	const params = new URLSearchParams();
	if (sessionKey) params.append('session_key', sessionKey);

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/file-space/openclaw/artifacts?${params.toString()}`,
		{ headers: { Authorization: `Bearer ${token}` } }
	)
		.then((r) => r.json())
		.catch(() => []);
	return Array.isArray(res) ? res : res?.artifacts ?? [];
};

export const getOpenClawWorkspace = async (
	token: string,
	agentId?: string
): Promise<any[]> => {
	const params = new URLSearchParams();
	if (agentId) params.append('agent_id', agentId);

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/file-space/openclaw/workspace?${params.toString()}`,
		{ headers: { Authorization: `Bearer ${token}` } }
	)
		.then((r) => r.json())
		.catch(() => []);
	return Array.isArray(res) ? res : res?.files ?? [];
};
