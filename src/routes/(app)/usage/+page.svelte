<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { mobile, showSidebar, user } from '$lib/stores';

	const i18n = getContext<any>('i18n');

	let stats = [];
	let loading = true;
	let totalInputTokens = 0;
	let totalOutputTokens = 0;
	let totalTokens = 0;
	let totalChats = 0;

	const fetchUsageStats = async () => {
		loading = true;
		try {
			// Fetch chat stats
			const res = await fetch(`${WEBUI_API_BASE_URL}/chats/stats/usage`, {
				headers: {
					Authorization: `Bearer ${localStorage.token}`
				}
			});

			if (res.ok) {
				const data = await res.json();
				stats = (data.stats || data.items || []).map((item: any) => ({
					id: item.id || '',
					title: item.title || item.id || 'Chat',
					models: item.models || item.history_models || {},
					message_count: item.message_count || item.history_message_count || 0,
					average_response_time: item.average_response_time || 0,
					updated_at: item.updated_at || item.created_at || 0,
					input_tokens: 0,
					output_tokens: 0,
					total_tokens: 0
				}));
			}

			// Fetch token usage
			const tokenRes = await fetch(`${WEBUI_API_BASE_URL}/chats/stats/token-usage`, {
				headers: {
					Authorization: `Bearer ${localStorage.token}`
				}
			});

			if (tokenRes.ok) {
				const tokenData = await tokenRes.json();
				totalInputTokens = tokenData.input_tokens || 0;
				totalOutputTokens = tokenData.output_tokens || 0;
				totalTokens = tokenData.total_tokens || 0;
			}
			
			totalChats = stats.length;
		} catch (error) {
			console.error('Failed to fetch usage stats:', error);
		}
		loading = false;
	};

	const calculateTotals = () => {
		totalInputTokens = 0;
		totalOutputTokens = 0;
		totalTokens = 0;
		totalChats = stats.length;

		stats.forEach((stat) => {
			totalInputTokens += stat.input_tokens || 0;
			totalOutputTokens += stat.output_tokens || 0;
			totalTokens += stat.total_tokens || 0;
		});
	};

	const formatNumber = (num: number) => {
		if (num >= 1000000) {
			return (num / 1000000).toFixed(1) + 'M';
		} else if (num >= 1000) {
			return (num / 1000).toFixed(1) + 'K';
		}
		return num.toString();
	};

	const formatDate = (timestamp: number) => {
		if (!timestamp) return '-';
		return new Date(timestamp * 1000).toLocaleDateString('zh-CN');
	};

	onMount(() => {
		fetchUsageStats();
	});
</script>

<svelte:head>
	<title>{$i18n.t('Usage')} - {$i18n.t('Chat')}</title>
</svelte:head>

<div
	class="h-screen max-h-[100dvh] flex flex-col transition-width duration-200 ease-in-out {$showSidebar
		? 'md:max-w-[calc(100%-var(--sidebar-width))]'
		: 'md:max-w-[calc(100%-49px)]'} w-full max-w-full"
>
	<div class="px-4 py-4 flex items-center border-b border-gray-100 dark:border-gray-850">
		<div class="text-lg font-semibold">{$i18n.t('Token Usage Statistics')}</div>
	</div>

	<div class="flex-1 overflow-auto p-4">
		{#if loading}
			<div class="flex items-center justify-center h-full">
				<div class="text-gray-500">{$i18n.t('Loading...')}</div>
			</div>
		{:else}
			<!-- Summary Cards -->
			<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
				<div class="bg-white dark:bg-gray-900 rounded-lg p-4 border border-gray-100 dark:border-gray-850">
					<div class="text-sm text-gray-500 mb-1">{$i18n.t('Total Chats')}</div>
					<div class="text-2xl font-bold">{totalChats}</div>
				</div>
				<div class="bg-white dark:bg-gray-900 rounded-lg p-4 border border-gray-100 dark:border-gray-850">
					<div class="text-sm text-gray-500 mb-1">{$i18n.t('Input Tokens')}</div>
					<div class="text-2xl font-bold text-blue-600">{formatNumber(totalInputTokens)}</div>
				</div>
				<div class="bg-white dark:bg-gray-900 rounded-lg p-4 border border-gray-100 dark:border-gray-850">
					<div class="text-sm text-gray-500 mb-1">{$i18n.t('Output Tokens')}</div>
					<div class="text-2xl font-bold text-green-600">{formatNumber(totalOutputTokens)}</div>
				</div>
				<div class="bg-white dark:bg-gray-900 rounded-lg p-4 border border-gray-100 dark:border-gray-850">
					<div class="text-sm text-gray-500 mb-1">{$i18n.t('Total Tokens')}</div>
					<div class="text-2xl font-bold text-purple-600">{formatNumber(totalTokens)}</div>
				</div>
			</div>

			<!-- Chat Stats Table -->
			<div class="bg-white dark:bg-gray-900 rounded-lg border border-gray-100 dark:border-gray-850">
				<div class="px-4 py-3 border-b border-gray-100 dark:border-gray-850">
					<div class="font-medium">{$i18n.t('Chat Details')}</div>
				</div>
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-gray-100 dark:border-gray-850 text-gray-500">
								<th class="text-left px-4 py-2">{$i18n.t('Title')}</th>
								<th class="text-left px-4 py-2">{$i18n.t('Model')}</th>
								<th class="text-right px-4 py-2">{$i18n.t('Input')}</th>
								<th class="text-right px-4 py-2">{$i18n.t('Output')}</th>
								<th class="text-right px-4 py-2">{$i18n.t('Total')}</th>
							</tr>
						</thead>
						<tbody>
							{#each stats as stat}
								<tr class="border-b border-gray-50 dark:border-gray-900 hover:bg-gray-50 dark:hover:bg-gray-850">
									<td class="px-4 py-2 max-w-[200px] truncate">{stat.title || '-'}</td>
									<td class="px-4 py-2 text-gray-500">{Object.keys(stat.models || {}).join(', ') || '-'}</td>
									<td class="px-4 py-2 text-right text-gray-500">{stat.message_count || 0}</td>
									<td class="px-4 py-2 text-right text-gray-500">{formatDate(stat.updated_at)}</td>
									<td class="px-4 py-2 text-right font-medium">{formatNumber(stat.total_tokens || 0)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>

				{#if stats.length === 0}
					<div class="px-4 py-8 text-center text-gray-500">
						{$i18n.t('No usage data available')}
					</div>
				{/if}
			</div>

			<!-- Refresh Button -->
			<div class="mt-4 flex justify-end">
				<button
					class="px-4 py-2 bg-gray-100 dark:bg-gray-800 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition"
					on:click={fetchUsageStats}
				>
					{$i18n.t('Refresh')}
				</button>
			</div>
		{/if}
	</div>
</div>
