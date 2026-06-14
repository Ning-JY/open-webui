<script lang="ts">
	import { getContext, onDestroy, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { mobile, showArchivedChats, showSidebar, user } from '$lib/stores';
	import {
		createDriveFolder,
		deleteDriveNodes,
		downloadDriveNodeBlob,
		getDriveNodes,
		moveDriveNodes,
		previewDriveNodeBlob,
		saveSharedDriveNodesToPersonal,
		shareDriveNodes,
		uploadDriveFiles,
		type DriveNode,
		type DriveSpace
	} from '$lib/apis/drive';

	import UserMenu from '$lib/components/layout/Sidebar/UserMenu.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Sidebar from '$lib/components/icons/Sidebar.svelte';
	import Folder from '$lib/components/icons/Folder.svelte';
	import Document from '$lib/components/icons/Document.svelte';
	import CloudArrowUp from '$lib/components/icons/CloudArrowUp.svelte';
	import NewFolderAlt from '$lib/components/icons/NewFolderAlt.svelte';
	import Download from '$lib/components/icons/Download.svelte';
	import Eye from '$lib/components/icons/Eye.svelte';
	import Share from '$lib/components/icons/Share.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Search from '$lib/components/icons/Search.svelte';

	const i18n = getContext<any>('i18n');

	type SortBy = 'name' | 'size' | 'updated_at';
	type SortOrder = 'asc' | 'desc';
	type ViewMode = 'list' | 'grid';

	let space: DriveSpace = 'personal';
	let items: DriveNode[] = [];
	let breadcrumbs: { id: string | null; name: string }[] = [{ id: null, name: '根目录' }];
	let selectedIds = new Set<string>();
	let loading = false;
	let uploading = false;
	let draggedOver = false;
	let dragCounter = 0;
	let sortBy: SortBy = 'name';
	let sortOrder: SortOrder = 'asc';
	let viewMode: ViewMode = 'list';
	let searchQuery = '';
	let fileInput: HTMLInputElement;
	let folderInput: HTMLInputElement;

	let movingIds: string[] = [];
	let movingFromSpace: DriveSpace | null = null;
	let previewUrl: string | null = null;
	let previewNode: DriveNode | null = null;
	let previewType: 'image' | 'pdf' | 'text' | 'office' | 'other' = 'other';
	let previewText = '';
	let previewHtml = '';

	$: currentParentId = breadcrumbs[breadcrumbs.length - 1]?.id ?? null;
	$: filteredItems = items.filter((item) => {
		const keyword = searchQuery.trim().toLowerCase();
		return !keyword || item.name.toLowerCase().includes(keyword);
	});
	$: selectedItems = items.filter((item) => selectedIds.has(item.id));
	$: canWrite = space === 'personal' || $user?.role === 'admin';
	$: isAdmin = $user?.role === 'admin';
	$: allSelected =
		filteredItems.length > 0 && filteredItems.every((item) => selectedIds.has(item.id));

	const sortItems = (nodes: DriveNode[]) => {
		const sorted = [...nodes];
		sorted.sort((a, b) => {
			if (a.node_type !== b.node_type && sortBy === 'name') {
				return a.node_type === 'folder' ? -1 : 1;
			}

			let result = 0;
			if (sortBy === 'name') {
				result = a.name.localeCompare(b.name);
			} else if (sortBy === 'size') {
				result = (a.size ?? 0) - (b.size ?? 0);
			} else {
				result = a.updated_at - b.updated_at;
			}

			return sortOrder === 'asc' ? result : -result;
		});
		return sorted;
	};

	const loadItems = async (parentId = currentParentId) => {
		loading = true;
		selectedIds = new Set();
		try {
			const res = await getDriveNodes(localStorage.token, space, parentId);
			items = sortItems(res.items ?? []);
		} catch (error) {
			toast.error(`${error}`);
		}
		loading = false;
	};

	const refreshItems = async () => {
		await loadItems();
	};

	const setSort = async (nextSortBy: SortBy) => {
		if (sortBy === nextSortBy) {
			sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
		} else {
			sortBy = nextSortBy;
			sortOrder = 'asc';
		}
		items = sortItems(items);
	};

	const switchSpace = async (nextSpace: DriveSpace) => {
		space = nextSpace;
		breadcrumbs = [{ id: null, name: '根目录' }];
		selectedIds = new Set();
		searchQuery = '';
		movingIds = [];
		movingFromSpace = null;
		await loadItems(null);
	};

	const openFolder = async (node: DriveNode) => {
		if (node.node_type !== 'folder') {
			return;
		}
		if (currentParentId === node.id) {
			return;
		}
		breadcrumbs = [...breadcrumbs, { id: node.id, name: node.name }];
		await loadItems(node.id);
	};

	const goToBreadcrumb = async (index: number) => {
		const nextBreadcrumbs = breadcrumbs.slice(0, index + 1);
		breadcrumbs = nextBreadcrumbs;
		await loadItems(nextBreadcrumbs[nextBreadcrumbs.length - 1]?.id ?? null);
	};

	const toggleSelected = (id: string) => {
		const next = new Set(selectedIds);
		if (next.has(id)) {
			next.delete(id);
		} else {
			next.add(id);
		}
		selectedIds = next;
	};

	const toggleAll = () => {
		if (allSelected) {
			const visibleIds = new Set(filteredItems.map((item) => item.id));
			selectedIds = new Set([...selectedIds].filter((id) => !visibleIds.has(id)));
		} else {
			selectedIds = new Set([...selectedIds, ...filteredItems.map((item) => item.id)]);
		}
	};

	const formatSize = (size?: number | null) => {
		if (!size) {
			return '-';
		}
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		let value = size;
		let unit = 0;
		while (value >= 1024 && unit < units.length - 1) {
			value = value / 1024;
			unit += 1;
		}
		return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
	};

	const formatDate = (timestamp: number) => {
		return new Date(timestamp * 1000).toLocaleString();
	};

	const createFolder = async () => {
		if (!canWrite) {
			return;
		}
		const name = window.prompt($i18n.t('文件夹名称'));
		if (!name?.trim()) {
			return;
		}
		try {
			await createDriveFolder(localStorage.token, space, currentParentId, name.trim());
			await loadItems();
			toast.success($i18n.t('文件夹创建成功'));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const upload = async (files: File[], relativePaths: string[]) => {
		if (!canWrite || files.length === 0) {
			return;
		}
		uploading = true;
		try {
			await uploadDriveFiles(localStorage.token, space, currentParentId, files, relativePaths);
			await loadItems();
			toast.success($i18n.t('上传完成'));
		} catch (error) {
			toast.error(`${error}`);
		}
		uploading = false;
	};

	const handleFileInput = async (event: Event) => {
		const input = event.target as HTMLInputElement;
		const files = Array.from(input.files ?? []);
		await upload(
			files,
			files.map((file: any) => file.webkitRelativePath || file.name)
		);
		input.value = '';
	};

	const readEntry = async (entry: any, prefix = ''): Promise<{ file: File; path: string }[]> => {
		if (entry.isFile) {
			return await new Promise((resolve) => {
				entry.file((file: File) => resolve([{ file, path: `${prefix}${file.name}` }]));
			});
		}

		if (entry.isDirectory) {
			const reader = entry.createReader();
			const entries: any[] = [];
			while (true) {
				const batch = await new Promise<any[]>((resolve) => reader.readEntries(resolve));
				if (batch.length === 0) {
					break;
				}
				entries.push(...batch);
			}
			const nested = await Promise.all(
				entries.map((item) => readEntry(item, `${prefix}${entry.name}/`))
			);
			return nested.flat();
		}

		return [];
	};

	const handleDragEnter = (event: DragEvent) => {
		event.preventDefault();
		dragCounter += 1;
		draggedOver = true;
	};

	const handleDragOver = (event: DragEvent) => {
		event.preventDefault();
	};

	const handleDragLeave = (event: DragEvent) => {
		event.preventDefault();
		dragCounter -= 1;
		if (dragCounter <= 0) {
			dragCounter = 0;
			draggedOver = false;
		}
	};

	const handleDrop = async (event: DragEvent) => {
		event.preventDefault();
		dragCounter = 0;
		draggedOver = false;
		if (!canWrite) {
			return;
		}

		const entries = Array.from(event.dataTransfer?.items ?? [])
			.map((item: any) => item.webkitGetAsEntry?.())
			.filter(Boolean);

		if (entries.length > 0) {
			const dropped = (await Promise.all(entries.map((entry) => readEntry(entry)))).flat();
			await upload(
				dropped.map((item) => item.file),
				dropped.map((item) => item.path)
			);
			return;
		}

		const files = Array.from(event.dataTransfer?.files ?? []);
		await upload(
			files,
			files.map((file) => file.name)
		);
	};

	const downloadBlob = (blob: Blob, name: string) => {
		const url = URL.createObjectURL(blob);
		const anchor = document.createElement('a');
		anchor.href = url;
		anchor.download = name;
		anchor.click();
		URL.revokeObjectURL(url);
	};

	const downloadSelected = async () => {
		for (const item of selectedItems) {
			const blob = await downloadDriveNodeBlob(localStorage.token, item.id);
			downloadBlob(blob, item.node_type === 'folder' ? `${item.name}.zip` : item.name);
		}
	};

	const deleteSelected = async () => {
		if (!canWrite || selectedIds.size === 0) {
			return;
		}
		if (!window.confirm($i18n.t('确定要删除选中的文件吗？'))) {
			return;
		}
		try {
			await deleteDriveNodes(localStorage.token, Array.from(selectedIds));
			await loadItems();
			toast.success($i18n.t('删除成功'));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const startMove = () => {
		if (!canWrite || selectedIds.size === 0) {
			return;
		}
		movingIds = Array.from(selectedIds);
		movingFromSpace = space;
		selectedIds = new Set();
		toast.info($i18n.t('请选择目标文件夹'));
	};

	const finishMove = async () => {
		if (!canWrite || movingIds.length === 0 || movingFromSpace !== space) {
			return;
		}
		try {
			await moveDriveNodes(localStorage.token, movingIds, currentParentId);
			movingIds = [];
			movingFromSpace = null;
			await loadItems();
			toast.success($i18n.t('移动成功'));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const shareSelected = async () => {
		if (!isAdmin || selectedIds.size === 0) {
			return;
		}
		try {
			await shareDriveNodes(localStorage.token, Array.from(selectedIds), null);
			selectedIds = new Set();
			toast.success($i18n.t('已分享到共享空间'));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const saveToPersonal = async () => {
		if (space !== 'shared' || selectedIds.size === 0) {
			return;
		}
		try {
			await saveSharedDriveNodesToPersonal(localStorage.token, Array.from(selectedIds), null);
			selectedIds = new Set();
			toast.success($i18n.t('已转存到个人空间'));
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const preview = async (node: DriveNode) => {
		if (node.node_type !== 'file') {
			await openFolder(node);
			return;
		}

		if (previewUrl) {
			URL.revokeObjectURL(previewUrl);
		}
		previewText = '';
		previewHtml = '';
		previewNode = node;
		previewType = 'other';

		try {
			const blob = await previewDriveNodeBlob(localStorage.token, node.id);
			previewUrl = URL.createObjectURL(blob);
			const type = node.mime_type ?? blob.type ?? '';
			if (type.startsWith('image/')) {
				previewType = 'image';
			} else if (type === 'application/pdf') {
				previewType = 'pdf';
			} else if (
				type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ||
				type === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' ||
				/\.(docx|xlsx)$/i.test(node.name)
			) {
				previewType = 'office';
				const buffer = await blob.arrayBuffer();
				if (/\.docx$/i.test(node.name)) {
					const mammoth = await import('mammoth/mammoth.browser');
					const result = await mammoth.convertToHtml({ arrayBuffer: buffer });
					previewHtml = result.value;
				} else if (/\.xlsx$/i.test(node.name)) {
					const xlsx = await import('xlsx');
					const workbook = xlsx.read(buffer, { type: 'array' });
					const firstSheetName = workbook.SheetNames[0];
					previewHtml = firstSheetName
						? xlsx.utils.sheet_to_html(workbook.Sheets[firstSheetName])
						: `<div>${$i18n.t('空表格')}</div>`;
				}
			} else if (type.startsWith('text/') || /\.(md|txt|json|csv|log|xml|html|css|js|ts)$/i.test(node.name)) {
				previewType = 'text';
				previewText = await blob.text();
			}
		} catch (error) {
			toast.error(`${error}`);
			previewNode = null;
		}
	};

	const previewSelected = async () => {
		if (selectedItems.length === 1) {
			await preview(selectedItems[0]);
		}
	};

	const closePreview = () => {
		if (previewUrl) {
			URL.revokeObjectURL(previewUrl);
		}
		previewUrl = null;
		previewNode = null;
		previewText = '';
		previewHtml = '';
	};

	const downloadPreview = async () => {
		if (!previewNode) {
			return;
		}
		const blob = await downloadDriveNodeBlob(localStorage.token, previewNode.id);
		downloadBlob(blob, previewNode.name);
	};

	onMount(() => {
		folderInput?.setAttribute('webkitdirectory', '');
		folderInput?.setAttribute('directory', '');
		loadItems();
	});
	onDestroy(closePreview);
</script>

<svelte:head>
	<title>{$i18n.t('文件管理')}</title>
</svelte:head>

<input bind:this={fileInput} class="hidden" type="file" multiple on:change={handleFileInput} />
<input bind:this={folderInput} class="hidden" type="file" multiple on:change={handleFileInput} />

{#if $showArchivedChats}
	<div class="fixed top-0 bottom-0 left-0 right-0 z-50">
		<!-- keep layout store compatible with Sidebar state -->
	</div>
{/if}

<div
	class="h-screen max-h-[100dvh] flex flex-col transition-width duration-200 ease-in-out {$showSidebar
		? 'md:max-w-[calc(100%-var(--sidebar-width))]'
		: 'md:max-w-[calc(100%-49px)]'} w-full max-w-full"
>
	<div class="px-2.5 py-2 flex items-center border-b border-gray-100 dark:border-gray-850">
		<div class="flex items-center min-w-0 w-full">
			<div class="{$showSidebar ? 'md:hidden' : ''} mr-1 self-start flex flex-none items-center">
				<Tooltip content={$i18n.t('侧边栏')}>
					<button
						id="sidebar-toggle-button"
						class="cursor-pointer px-2 py-2 flex rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						on:click={() => {
							showSidebar.set(!$showSidebar);
						}}
					>
						<Sidebar />
					</button>
				</Tooltip>
			</div>

			<div class="ml-2 py-0.5 self-center flex items-center justify-between w-full">
				<div class="text-sm font-medium">{$i18n.t('文件管理')}</div>
				{#if $mobile}
					<UserMenu
						role={$user?.role}
						profile={true}
						showActiveUsers={false}
						on:show={(e) => {
							if (e.detail === 'archived-chat') {
								showArchivedChats.set(true);
							}
						}}
					/>
				{/if}
			</div>
		</div>
	</div>

	<div class="flex-1 min-h-0 px-4 py-3">
		<div class="h-full flex flex-col gap-3">
			<div class="flex flex-wrap items-center justify-between gap-2">
				<div class="flex items-center rounded-lg bg-gray-100 dark:bg-gray-900 p-1 text-sm">
					<button
						class="px-3 py-1.5 rounded-md transition {space === 'personal'
							? 'bg-white dark:bg-gray-800 shadow-sm'
							: 'text-gray-600 dark:text-gray-300'}"
						on:click={() => switchSpace('personal')}
					>
						{$i18n.t('个人空间')}
					</button>
					<button
						class="px-3 py-1.5 rounded-md transition {space === 'shared'
							? 'bg-white dark:bg-gray-800 shadow-sm'
							: 'text-gray-600 dark:text-gray-300'}"
						on:click={() => switchSpace('shared')}
					>
						{$i18n.t('共享空间')}
					</button>
				</div>

				<div
					class="flex min-w-56 flex-1 max-w-md items-center gap-2 rounded-lg border border-gray-100 dark:border-gray-850 px-3 py-1.5 text-sm"
				>
					<Search className="size-4 text-gray-500" />
					<input
						class="w-full bg-transparent outline-hidden"
						bind:value={searchQuery}
						placeholder={$i18n.t('搜索文件或文件夹')}
					/>
				</div>

				<div class="flex flex-wrap items-center gap-1.5">
					<button class="text-btn" on:click={refreshItems}>{$i18n.t('刷新')}</button>
					<div class="flex rounded-lg bg-gray-100 dark:bg-gray-900 p-1 text-sm">
						<button
							class="px-2.5 py-1 rounded-md {viewMode === 'list' ? 'bg-white dark:bg-gray-800 shadow-sm' : ''}"
							on:click={() => (viewMode = 'list')}
						>
							{$i18n.t('列表')}
						</button>
						<button
							class="px-2.5 py-1 rounded-md {viewMode === 'grid' ? 'bg-white dark:bg-gray-800 shadow-sm' : ''}"
							on:click={() => (viewMode = 'grid')}
						>
							{$i18n.t('网格')}
						</button>
					</div>

					{#if canWrite}
						<Tooltip content={$i18n.t('上传文件')}>
							<button class="icon-btn" on:click={() => fileInput.click()} disabled={uploading}>
								<CloudArrowUp className="size-4" />
							</button>
						</Tooltip>
						<Tooltip content={$i18n.t('上传文件夹')}>
							<button class="icon-btn" on:click={() => folderInput.click()} disabled={uploading}>
								<Folder className="size-4" />
							</button>
						</Tooltip>
						<Tooltip content={$i18n.t('新建文件夹')}>
							<button class="icon-btn" on:click={createFolder}>
								<NewFolderAlt className="size-4" />
							</button>
						</Tooltip>
					{/if}

					<Tooltip content={$i18n.t('预览')}>
						<button
							class="icon-btn"
							disabled={selectedItems.length !== 1}
							on:click={previewSelected}
						>
							<Eye className="size-4" />
						</button>
					</Tooltip>
					<Tooltip content={$i18n.t('下载')}>
						<button class="icon-btn" disabled={selectedIds.size === 0} on:click={downloadSelected}>
							<Download className="size-4" />
						</button>
					</Tooltip>

					{#if canWrite}
						<button class="text-btn" disabled={selectedIds.size === 0} on:click={startMove}>
							{$i18n.t('移动')}
						</button>
						<button class="text-btn danger" disabled={selectedIds.size === 0} on:click={deleteSelected}>
							{$i18n.t('删除')}
						</button>
					{/if}

					{#if isAdmin && space === 'personal'}
						<Tooltip content={$i18n.t('分享到共享空间')}>
							<button class="icon-btn" disabled={selectedIds.size === 0} on:click={shareSelected}>
								<Share className="size-4" />
							</button>
						</Tooltip>
					{/if}

					{#if space === 'shared'}
						<button class="text-btn" disabled={selectedIds.size === 0} on:click={saveToPersonal}>
							{$i18n.t('转存到个人空间')}
						</button>
					{/if}
				</div>
			</div>

			<div class="flex items-center justify-between gap-2 text-sm">
				<div class="flex items-center gap-1 min-w-0 overflow-x-auto scrollbar-hidden">
					{#each breadcrumbs as crumb, index}
						<button
							class="px-2 py-1 rounded-md hover:bg-gray-100 dark:hover:bg-gray-900 text-gray-700 dark:text-gray-200 whitespace-nowrap"
							on:click={() => goToBreadcrumb(index)}
						>
							{index === 0 ? (space === 'personal' ? $i18n.t('个人空间') : $i18n.t('共享空间')) : crumb.name}
						</button>
						{#if index < breadcrumbs.length - 1}
							<span class="text-gray-400">/</span>
						{/if}
					{/each}
				</div>

				{#if movingIds.length > 0}
					<div class="flex items-center gap-1.5">
						<button
							class="text-btn"
							disabled={movingFromSpace !== space}
							on:click={finishMove}
						>
							{$i18n.t('移动到此处')}
						</button>
						<button
							class="icon-btn"
							on:click={() => {
								movingIds = [];
								movingFromSpace = null;
							}}
						>
							<XMark className="size-4" />
						</button>
					</div>
				{/if}
			</div>

			<div
				class="relative flex-1 overflow-hidden rounded-lg border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950"
				role="region"
				aria-label={$i18n.t('文件管理')}
				class:ring-2={draggedOver}
				class:ring-blue-500={draggedOver}
				on:dragenter={handleDragEnter}
				on:dragover={handleDragOver}
				on:dragleave={handleDragLeave}
				on:drop={handleDrop}
			>
				{#if draggedOver}
					<div
						class="absolute inset-0 z-10 flex items-center justify-center bg-white/80 dark:bg-gray-950/80 text-sm font-medium"
					>
						{$i18n.t('拖放文件到此处上传')}
					</div>
				{/if}

				{#if viewMode === 'list'}
					<div class="grid grid-cols-[40px_minmax(180px,1fr)_120px_180px_120px] px-3 py-2 border-b border-gray-100 dark:border-gray-850 text-xs text-gray-500">
						<label class="flex items-center">
							<input type="checkbox" checked={allSelected} on:change={toggleAll} />
						</label>
						<button class="flex items-center gap-1 text-left" on:click={() => setSort('name')}>
							{$i18n.t('名称')}{#if sortBy === 'name'}<span>{sortOrder === 'asc' ? '↑' : '↓'}</span>{/if}
						</button>
						<button class="flex items-center gap-1 text-left" on:click={() => setSort('size')}>
							{$i18n.t('大小')}{#if sortBy === 'size'}<span>{sortOrder === 'asc' ? '↑' : '↓'}</span>{/if}
						</button>
						<button class="flex items-center gap-1 text-left" on:click={() => setSort('updated_at')}>
							{$i18n.t('更新时间')}{#if sortBy === 'updated_at'}<span>{sortOrder === 'asc' ? '↑' : '↓'}</span>{/if}
						</button>
						<div class="text-right pr-2">{$i18n.t('操作')}</div>
					</div>
				{/if}

				<div class="h-[calc(100%-2.5rem)] overflow-auto">
					{#if loading}
						<div class="h-full flex items-center justify-center text-sm text-gray-500">
							{$i18n.t('加载中...')}
						</div>
					{:else if filteredItems.length === 0}
						<div class="h-full flex flex-col items-center justify-center gap-2 text-sm text-gray-500">
							<Folder className="size-8 text-gray-300 dark:text-gray-700" />
							<div>{searchQuery.trim() ? $i18n.t('没有匹配的文件') : $i18n.t('暂无文件')}</div>
						</div>
					{:else if viewMode === 'grid'}
						<div class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3 p-3">
							{#each filteredItems as item (item.id)}
								<button
									class="min-h-28 rounded-lg border border-gray-100 dark:border-gray-850 p-3 text-left hover:bg-gray-50 dark:hover:bg-gray-900 transition {selectedIds.has(item.id) ? 'ring-2 ring-blue-500' : ''}"
									on:click={() => toggleSelected(item.id)}
									on:dblclick={() => preview(item)}
								>
									<div class="flex items-center justify-between gap-2">
										{#if item.node_type === 'folder'}
											<Folder className="size-7 text-blue-500 shrink-0" />
										{:else}
											<Document className="size-7 text-gray-500 shrink-0" />
										{/if}
										<input
											type="checkbox"
											checked={selectedIds.has(item.id)}
											on:click|stopPropagation
											on:change={() => toggleSelected(item.id)}
										/>
									</div>
									<div class="mt-3 text-sm font-medium truncate">{item.name}</div>
									<div class="mt-1 text-xs text-gray-500 truncate">
										{item.node_type === 'folder' ? $i18n.t('文件夹') : formatSize(item.size)}
									</div>
								</button>
							{/each}
						</div>
					{:else}
						{#each filteredItems as item (item.id)}
							<div
								class="grid grid-cols-[40px_minmax(180px,1fr)_120px_180px_120px] items-center px-3 py-2 border-b border-gray-50 dark:border-gray-900 hover:bg-gray-50 dark:hover:bg-gray-900/60 text-sm"
							>
								<label class="flex items-center">
									<input
										type="checkbox"
										checked={selectedIds.has(item.id)}
										on:change={() => toggleSelected(item.id)}
									/>
								</label>
								<button
									class="flex items-center gap-2 min-w-0 text-left"
									on:click={() => {
										if (item.node_type === 'folder') {
											openFolder(item);
										} else {
											preview(item);
										}
									}}
								>
									{#if item.node_type === 'folder'}
										<Folder className="size-4.5 text-blue-500 shrink-0" />
									{:else}
										<Document className="size-4.5 text-gray-500 shrink-0" />
									{/if}
									<span class="truncate">{item.name}</span>
								</button>
								<div class="text-gray-500">{item.node_type === 'folder' ? '-' : formatSize(item.size)}</div>
								<div class="text-gray-500 truncate">{formatDate(item.updated_at)}</div>
								<div class="flex justify-end gap-1">
									<button class="row-btn" on:click={() => preview(item)} aria-label={$i18n.t('预览')}>
										<Eye className="size-3.5" />
									</button>
									<button
										class="row-btn"
										on:click={async () => {
											const blob = await downloadDriveNodeBlob(localStorage.token, item.id);
											downloadBlob(blob, item.node_type === 'folder' ? `${item.name}.zip` : item.name);
										}}
										aria-label={$i18n.t('下载')}
									>
										<Download className="size-3.5" />
									</button>
								</div>
							</div>
						{/each}
					{/if}
				</div>
			</div>
		</div>
	</div>
</div>

{#if previewNode}
	<div class="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
		<div class="w-full max-w-5xl h-[82vh] bg-white dark:bg-gray-950 rounded-lg shadow-xl flex flex-col">
			<div class="flex items-center justify-between gap-2 px-4 py-3 border-b border-gray-100 dark:border-gray-850">
				<div class="font-medium truncate">{previewNode.name}</div>
				<button class="icon-btn" on:click={closePreview}>
					<XMark className="size-4" />
				</button>
			</div>
			<div class="flex-1 min-h-0 overflow-auto p-4">
				{#if previewType === 'image'}
					<img
						src={previewUrl ?? ''}
						alt={previewNode.name}
						class="max-w-full max-h-full mx-auto object-contain"
					/>
				{:else if previewType === 'pdf'}
					<iframe title={previewNode.name} src={previewUrl ?? ''} class="w-full h-full rounded-md"></iframe>
				{:else if previewType === 'text'}
					<pre class="text-sm whitespace-pre-wrap font-mono">{previewText}</pre>
				{:else if previewType === 'office'}
					{#if previewHtml}
						<div class="office-preview text-sm">
							{@html previewHtml}
						</div>
					{:else}
						<div class="h-full flex flex-col items-center justify-center gap-3 text-sm text-gray-500">
							<Document className="size-10 text-gray-300 dark:text-gray-700" />
							<div>{$i18n.t('无法生成预览，请下载后查看')}</div>
							<button class="text-btn" on:click={downloadPreview}>{$i18n.t('下载')}</button>
						</div>
					{/if}
				{:else}
					<div class="h-full flex flex-col items-center justify-center gap-3 text-sm text-gray-500">
						<Document className="size-10 text-gray-300 dark:text-gray-700" />
						<div>{$i18n.t('此文件类型不支持在线预览')}</div>
						<button class="text-btn" on:click={downloadPreview}>{$i18n.t('下载')}</button>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	.icon-btn {
		display: inline-flex;
		height: 2rem;
		width: 2rem;
		align-items: center;
		justify-content: center;
		border-radius: 0.5rem;
		color: rgb(55 65 81);
		transition: background-color 150ms ease;
	}

	.icon-btn:hover:not(:disabled),
	.row-btn:hover {
		background: rgb(243 244 246);
	}

	.icon-btn:disabled,
	.text-btn:disabled {
		cursor: not-allowed;
		opacity: 0.45;
	}

	.text-btn {
		display: inline-flex;
		min-height: 2rem;
		align-items: center;
		border-radius: 0.5rem;
		padding: 0 0.75rem;
		font-size: 0.875rem;
		color: rgb(55 65 81);
		background: rgb(243 244 246);
		transition: background-color 150ms ease;
		white-space: nowrap;
	}

	.text-btn:hover:not(:disabled) {
		background: rgb(229 231 235);
	}

	.text-btn.danger {
		color: rgb(185 28 28);
	}

	.row-btn {
		display: inline-flex;
		height: 1.75rem;
		width: 1.75rem;
		align-items: center;
		justify-content: center;
		border-radius: 0.5rem;
		color: rgb(75 85 99);
	}

	:global(.dark) .icon-btn,
	:global(.dark) .row-btn {
		color: rgb(209 213 219);
	}

	:global(.dark) .icon-btn:hover:not(:disabled),
	:global(.dark) .row-btn:hover,
	:global(.dark) .text-btn {
		background: rgb(31 41 55);
	}

	:global(.dark) .text-btn:hover:not(:disabled) {
		background: rgb(55 65 81);
	}

	.office-preview :global(table) {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.875rem;
	}

	.office-preview :global(td),
	.office-preview :global(th) {
		border: 1px solid rgb(229 231 235);
		padding: 0.375rem 0.5rem;
		vertical-align: top;
	}

	.office-preview :global(p) {
		margin: 0 0 0.75rem;
	}

	:global(.dark) .office-preview :global(td),
	:global(.dark) .office-preview :global(th) {
		border-color: rgb(55 65 81);
	}
</style>
