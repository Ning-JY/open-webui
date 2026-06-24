<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		getFileSpaceFilesGrouped,
		getFileSpaceStats,
		deleteFileSpaceFile,
		syncOpenClawArtifacts,
		type FileSpaceGroup,
		type FileSpaceStats,
		type FileSpaceEntry
	} from '$lib/apis/file-space';

	import { mobile, showSidebar, showArchivedChats, user } from '$lib/stores';

	import Sidebar from '$lib/components/icons/Sidebar.svelte';
	import UserMenu from '$lib/components/layout/Sidebar/UserMenu.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

	const i18n = getContext<any>('i18n');

	let groups: FileSpaceGroup[] = [];
	let stats: FileSpaceStats = { types: {}, total_count: 0, total_size: 0 };
	let loading = true;

	let activeType = 'all';
	let searchQuery = '';
	let searchDebounce: ReturnType<typeof setTimeout>;

	let selectedFileId: string | null = null;
	let showDeleteDialog = false;

	let previewFile: FileSpaceEntry | null = null;
	let syncing = false;

	const syncOpenClaw = async () => {
		syncing = true;
		try {
			const result = await syncOpenClawArtifacts(localStorage.token);
			if ('error' in result) {
				toast.error(result.error);
			} else {
				toast.success($i18n.t(`Synced ${result.synced} files from OpenClaw`));
				await loadGroups();
				await loadStats();
			}
		} catch (e) {
			toast.error(`${e}`);
		}
		syncing = false;
	};

	const FILE_TYPES = [
		{ key: 'all', label: '全部类型', icon: '📁' },
		{ key: 'document', label: '文档', icon: '📄' },
		{ key: 'spreadsheet', label: '表格', icon: '📊' },
		{ key: 'image', label: '图片', icon: '🖼️' },
		{ key: 'code', label: '代码', icon: '💻' },
		{ key: 'ppt', label: 'PPT', icon: '📽️' },
		{ key: 'other', label: '其他', icon: '📎' }
	];

	const formatSize = (bytes: number | null): string => {
		if (!bytes) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB'];
		let value = bytes;
		let unit = 0;
		while (value >= 1024 && unit < units.length - 1) {
			value /= 1024;
			unit++;
		}
		return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
	};

	const formatTimestamp = (ts: number): string => {
		return new Date(ts * 1000).toLocaleString('zh-CN', {
			month: '2-digit',
			day: '2-digit',
			hour: '2-digit',
			minute: '2-digit'
		});
	};

	const loadGroups = async () => {
		loading = true;
		try {
			groups = await getFileSpaceFilesGrouped(localStorage.token, {
				file_type: activeType === 'all' ? undefined : activeType,
				search: searchQuery || undefined
			});
		} catch (e) {
			toast.error(`${e}`);
		}
		loading = false;
	};

	const loadStats = async () => {
		try {
			stats = await getFileSpaceStats(localStorage.token);
		} catch (e) {
			console.error(e);
		}
	};

	const setTypeFilter = (type: string) => {
		activeType = type;
		loadGroups();
	};

	const handleSearch = () => {
		clearTimeout(searchDebounce);
		searchDebounce = setTimeout(() => loadGroups(), 300);
	};

	const deleteHandler = async () => {
		if (!selectedFileId) return;
		try {
			await deleteFileSpaceFile(localStorage.token, selectedFileId);
			toast.success($i18n.t('File deleted'));
			await loadGroups();
			await loadStats();
		} catch (e) {
			toast.error(`${e}`);
		}
		selectedFileId = null;
	};

	const getFileIcon = (fileType: string | null): string => {
		const icons: Record<string, string> = {
			document: '📄',
			spreadsheet: '📊',
			image: '🖼️',
			code: '💻',
			ppt: '📽️',
			other: '📎'
		};
		return icons[fileType ?? 'other'] || '📎';
	};

	const openPreview = (file: FileSpaceEntry) => {
		previewFile = file;
	};

	onMount(() => {
		loadGroups();
		loadStats();
	});
</script>

<svelte:head>
	<title>{$i18n.t('文件空间')}</title>
</svelte:head>

{#if $showArchivedChats}
	<div class="fixed top-0 bottom-0 left-0 right-0 z-50" />
{/if}

<div
	class="h-screen max-h-[100dvh] flex flex-col transition-width duration-200 ease-in-out {$showSidebar
		? 'md:max-w-[calc(100%-var(--sidebar-width))]'
		: 'md:max-w-[calc(100%-49px)]'} w-full max-w-full"
>
	<!-- Header -->
	<div class="px-2.5 py-2 flex items-center border-b border-gray-100 dark:border-gray-850">
		<div class="flex items-center min-w-0 w-full">
			<div class="{$showSidebar ? 'md:hidden' : ''} mr-1 self-start flex flex-none items-center">
				<button
					class="cursor-pointer px-2 py-2 flex rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					on:click={() => showSidebar.set(!$showSidebar)}
				>
					<Sidebar />
				</button>
			</div>
			<div class="ml-2 py-0.5 self-center flex items-center justify-between w-full">
				<div class="text-sm font-medium">{$i18n.t('文件空间')}</div>
				{#if $mobile}
					<UserMenu role={$user?.role} profile={true} showActiveUsers={false} />
				{/if}
			</div>
		</div>
	</div>

	<!-- Content -->
	<div class="flex-1 min-h-0 flex overflow-hidden">
		<!-- Left Sidebar -->
		<div class="w-56 shrink-0 border-r border-gray-100 dark:border-gray-850 flex flex-col overflow-y-auto">
			<!-- Storage -->
			<div class="px-4 pt-4 pb-2">
				<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
					{$i18n.t('已使用')} {formatSize(stats.total_size)}
				</div>
				<div class="w-full h-1.5 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
					<div
						class="h-full bg-blue-500 rounded-full transition-all"
						style="width: {Math.min((stats.total_size / (10 * 1024 * 1024 * 1024)) * 100, 100)}%"
					></div>
				</div>
				<div class="text-[10px] text-gray-400 dark:text-gray-500 mt-0.5">
					{formatSize(stats.total_size)} / 10 GB
				</div>
			</div>

			<!-- Type Filters -->
			<div class="px-2 py-2">
				{#each FILE_TYPES as ft}
					<button
						class="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-left transition
							{activeType === ft.key
								? 'bg-gray-100 dark:bg-gray-800 font-medium'
								: 'hover:bg-gray-50 dark:hover:bg-gray-900 text-gray-600 dark:text-gray-300'}"
						on:click={() => setTypeFilter(ft.key)}
					>
						<span>{ft.icon}</span>
						<span class="flex-1">{$i18n.t(ft.label)}</span>
						<span class="text-xs text-gray-400">
							{ft.key === 'all'
								? stats.total_count
								: (stats.types[ft.key]?.count ?? 0)}
						</span>
					</button>
				{/each}
			</div>
		</div>

		<!-- Main Area -->
		<div class="flex-1 min-w-0 flex flex-col">
			<!-- Search Bar -->
			<div class="px-4 py-3 flex items-center gap-2">
				<div
					class="flex-1 flex items-center gap-2 rounded-lg border border-gray-100 dark:border-gray-850 px-3 py-1.5 text-sm"
				>
					<Search className="size-4 text-gray-500" />
					<input
						class="w-full bg-transparent outline-hidden"
						bind:value={searchQuery}
						on:input={handleSearch}
						placeholder={$i18n.t('搜索文件名')}
					/>
					{#if searchQuery}
						<button
							class="p-0.5 rounded-full hover:bg-gray-100 dark:hover:bg-gray-900"
							on:click={() => { searchQuery = ''; loadGroups(); }}
						>
							<XMark className="size-3" />
						</button>
					{/if}
				</div>
				<button
					class="px-3 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 transition disabled:opacity-50"
					on:click={syncOpenClaw}
					disabled={syncing}
				>
					{syncing ? $i18n.t('同步中...') : $i18n.t('从 OpenClaw 同步')}
				</button>
			</div>

			<!-- File Groups -->
			<div class="flex-1 overflow-y-auto px-4 pb-4">
				{#if loading}
					<div class="h-full flex items-center justify-center text-sm text-gray-500">
						{$i18n.t('加载中...')}
					</div>
				{:else if groups.length === 0}
					<div class="h-full flex flex-col items-center justify-center gap-2 text-sm text-gray-500">
						<div class="text-3xl">📂</div>
						<div>{searchQuery ? $i18n.t('没有匹配的文件') : $i18n.t('暂无文件')}</div>
					</div>
				{:else}
					{#each groups as group}
						<div class="mb-4">
							<!-- Group Header -->
							<div
								class="flex items-center justify-between py-2 px-1 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-900 rounded-lg"
							>
								<div class="flex items-center gap-2 min-w-0">
									<span class="text-gray-400">▸</span>
									<span class="text-sm font-medium truncate">
										{group.conversation_title}
									</span>
								</div>
								<span class="text-xs text-gray-400 shrink-0">
									{group.file_count} {$i18n.t('个文件')}
								</span>
							</div>

							<!-- Files in Group -->
							<div class="ml-4">
								{#each group.files as file}
									<div
										class="flex items-center gap-3 py-2 px-3 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-900 cursor-pointer group"
										on:click={() => openPreview(file)}
									>
										<span class="text-lg shrink-0">{getFileIcon(file.file_type)}</span>
										<div class="flex-1 min-w-0">
											<div class="text-sm truncate">{file.filename}</div>
										</div>
										<div class="text-xs text-gray-400 shrink-0 w-20 text-right">
											{formatSize(file.file_size)}
										</div>
										<div class="text-xs text-gray-400 shrink-0 w-28 text-right">
											{formatTimestamp(file.created_at)}
										</div>
										<button
											class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 shrink-0 transition"
											on:click|stopPropagation={() => {
												selectedFileId = file.id;
												showDeleteDialog = true;
											}}
										>
											<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
												<path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14" />
											</svg>
										</button>
									</div>
								{/each}
							</div>
						</div>
					{/each}
				{/if}
			</div>
		</div>
	</div>
</div>

<!-- Delete Confirm Dialog -->
<ConfirmDialog
	bind:show={showDeleteDialog}
	on:confirm={deleteHandler}
/>

<!-- Preview Modal -->
{#if previewFile}
	<div class="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" on:click={() => previewFile = null}>
		<div class="bg-white dark:bg-gray-950 rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] flex flex-col" on:click|stopPropagation>
			<div class="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-850">
				<div class="flex items-center gap-2 min-w-0">
					<span>{getFileIcon(previewFile.file_type)}</span>
					<span class="font-medium truncate">{previewFile.filename}</span>
				</div>
				<button class="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800" on:click={() => previewFile = null}>
					<XMark className="size-5" />
				</button>
			</div>
			<div class="p-4 text-sm text-gray-600 dark:text-gray-300">
				<div class="grid grid-cols-2 gap-3">
					<div>
						<div class="text-xs text-gray-400">{$i18n.t('文件名')}</div>
						<div>{previewFile.filename}</div>
					</div>
					<div>
						<div class="text-xs text-gray-400">{$i18n.t('大小')}</div>
						<div>{formatSize(previewFile.file_size)}</div>
					</div>
					<div>
						<div class="text-xs text-gray-400">{$i18n.t('类型')}</div>
						<div>{previewFile.file_type}</div>
					</div>
					<div>
						<div class="text-xs text-gray-400">{$i18n.t('创建时间')}</div>
						<div>{formatTimestamp(previewFile.created_at)}</div>
					</div>
				</div>
				{#if previewFile.conversation_title}
					<div class="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800">
						<div class="text-xs text-gray-400">{$i18n.t('来源会话')}</div>
						<div>{previewFile.conversation_title}</div>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}
