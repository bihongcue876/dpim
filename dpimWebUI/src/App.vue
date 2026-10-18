<template>
  <n-config-provider
    :theme="theme.naiveTheme"
    :locale="zhCN"
    :date-locale="dateZhCN"
    :theme-overrides="theme.themeOverrides"
  >
    <n-dialog-provider>
      <n-message-provider>
        <AppShell />
      </n-message-provider>
    </n-dialog-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
/**
 * 根组件：只负责主题/语言/消息上下文与外壳挂载。
 * 页面、导航、状态全部下沉到 router / stores / components/layout。
 */
import { NConfigProvider, NDialogProvider, NMessageProvider, dateZhCN, zhCN } from 'naive-ui'
import AppShell from '@/components/layout/AppShell.vue'
import { useThemeStore } from '@/stores/theme'

const theme = useThemeStore()
</script>
