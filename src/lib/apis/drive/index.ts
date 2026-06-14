import { WEBUI_API_BASE_URL } from '$lib/constants';

export type DriveSpace = 'personal' | 'shared';
export type DriveNodeType = 'folder' | 'file';

export type DriveNode = {
	id: string;
	space: DriveSpace;
	owner_id?: string | null;
	parent_id?: string | null;
	name: string;
	node_type: DriveNodeType;
	mime_type?: string | null;
	size?: number | null;
	storage_path?: string | null;
	source_node_id?: string | null;
	created_by: string;
	updated_by: string;
	created_at: number;
	updated_at: number;
};

export type DriveListResponse = {
	items: DriveNode[];
	parent?: DriveNode | null;
};

const request = async (token: string, url: string, options: RequestInit = {}): Promise<Response> => {
	const res = await fetch(url, {
		...options,
		headers: {
			Accept: 'application/json',
			...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
			authorization: `Bearer ${token}`,
			...(options.headers ?? {})
		}
	});

	if (!res.ok) {
		const error = await res.json().catch(() => null);
		console.error(error);
		throw error?.detail ?? error ?? res.statusText;
	}

	return res;
};

export const getDriveNodes = async (
	token: string,
	space: DriveSpace,
	parentId: string | null = null
): Promise<DriveListResponse> => {
	const params = new URLSearchParams({ space });
	if (parentId) {
		params.set('parent_id', parentId);
	}

	const res = await request(token, `${WEBUI_API_BASE_URL}/drive/list?${params.toString()}`, {
		method: 'GET'
	});
	return await res.json();
};

export const createDriveFolder = async (
	token: string,
	space: DriveSpace,
	parentId: string | null,
	name: string
): Promise<DriveNode> => {
	const res = await request(token, `${WEBUI_API_BASE_URL}/drive/folders`, {
		method: 'POST',
		body: JSON.stringify({ space, parent_id: parentId, name })
	});
	return await res.json();
};

export const uploadDriveFiles = async (
	token: string,
	space: DriveSpace,
	parentId: string | null,
	files: File[],
	relativePaths: string[]
): Promise<DriveNode[]> => {
	const formData = new FormData();
	formData.set('space', space);
	if (parentId) {
		formData.set('parent_id', parentId);
	}
	formData.set('relative_paths', JSON.stringify(relativePaths));
	for (const file of files) {
		formData.append('files', file);
	}

	const res = await request(token, `${WEBUI_API_BASE_URL}/drive/upload`, {
		method: 'POST',
		body: formData
	});
	return await res.json();
};

export const moveDriveNodes = async (
	token: string,
	ids: string[],
	targetParentId: string | null
): Promise<boolean> => {
	const res = await request(token, `${WEBUI_API_BASE_URL}/drive/move`, {
		method: 'POST',
		body: JSON.stringify({ ids, target_parent_id: targetParentId })
	});
	return await res.json();
};

export const deleteDriveNodes = async (token: string, ids: string[]): Promise<boolean> => {
	const res = await request(token, `${WEBUI_API_BASE_URL}/drive/delete`, {
		method: 'POST',
		body: JSON.stringify({ ids })
	});
	return await res.json();
};

export const shareDriveNodes = async (
	token: string,
	ids: string[],
	targetParentId: string | null
): Promise<DriveNode[]> => {
	const res = await request(token, `${WEBUI_API_BASE_URL}/drive/share`, {
		method: 'POST',
		body: JSON.stringify({ ids, target_parent_id: targetParentId })
	});
	return await res.json();
};

export const saveSharedDriveNodesToPersonal = async (
	token: string,
	ids: string[],
	targetParentId: string | null
): Promise<DriveNode[]> => {
	const res = await request(token, `${WEBUI_API_BASE_URL}/drive/save-to-personal`, {
		method: 'POST',
		body: JSON.stringify({ ids, target_parent_id: targetParentId })
	});
	return await res.json();
};

export const downloadDriveNodeBlob = async (token: string, id: string): Promise<Blob> => {
	const res = await request(token, `${WEBUI_API_BASE_URL}/drive/${id}/download`, {
		method: 'GET'
	});
	return await res.blob();
};

export const previewDriveNodeBlob = async (token: string, id: string): Promise<Blob> => {
	const res = await request(token, `${WEBUI_API_BASE_URL}/drive/${id}/preview`, {
		method: 'GET'
	});
	return await res.blob();
};
