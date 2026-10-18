/**
 * Naive UI 主题镜像（styles/tokens.css 是样式侧真源，这里是 Naive 侧镜像）。
 *
 * 改色只需改 tokens.css 与这里各一处；两侧必须同值，否则自绘组件与 Naive 组件会分叉。
 */
import { darkTheme, lightTheme } from 'naive-ui'
import type { GlobalTheme, GlobalThemeOverrides } from 'naive-ui'

export type ThemeMode = 'dark' | 'light'

const FONT_SANS =
  "'Inter','PingFang SC','Microsoft YaHei',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif"
const FONT_MONO = "'Cascadia Code','JetBrains Mono',Consolas,'Courier New',monospace"

export const naiveThemeFor = (mode: ThemeMode): GlobalTheme =>
  mode === 'dark' ? darkTheme : lightTheme

export const overridesFor = (mode: ThemeMode): GlobalThemeOverrides => {
  if (mode === 'light') {
    return {
      common: {
        primaryColor: '#2f6fb5',
        primaryColorHover: '#3a80c9',
        primaryColorPressed: '#275f9d',
        primaryColorSuppl: '#2f6fb5',
        successColor: '#2f8f6d',
        successColorHover: '#3a9f7c',
        successColorPressed: '#26795c',
        successColorSuppl: '#2f8f6d',
        warningColor: '#9c7a17',
        warningColorHover: '#ac8a24',
        warningColorPressed: '#856711',
        warningColorSuppl: '#9c7a17',
        errorColor: '#c25b5b',
        errorColorHover: '#cf6c6c',
        errorColorPressed: '#a94c4c',
        errorColorSuppl: '#c25b5b',
        infoColor: '#2f86a8',
        infoColorHover: '#3d94b6',
        infoColorPressed: '#277495',
        infoColorSuppl: '#2f86a8',
        borderRadius: '8px',
        borderRadiusSmall: '5px',
        fontFamily: FONT_SANS,
        fontFamilyMono: FONT_MONO,
        bodyColor: '#f5f7f9',
        cardColor: '#ffffff',
        modalColor: '#ffffff',
        popoverColor: '#ffffff',
        tableColor: '#ffffff',
        inputColor: '#ffffff',
        actionColor: '#eef1f5',
        borderColor: 'rgba(16,18,22,0.10)',
        dividerColor: 'rgba(16,18,22,0.10)',
        textColorBase: '#191c22',
        textColor1: '#191c22',
        textColor2: '#4a5058',
        textColor3: '#767d87',
        placeholderColor: '#98a0aa',
        hoverColor: 'rgba(16,18,22,0.045)',
      },
      Card: { borderColor: 'rgba(16,18,22,0.10)' },
      Dialog: { color: '#ffffff' },
      Pagination: { itemBorderRadius: '5px' },
      Layout: { color: '#f5f7f9', siderColor: '#ffffff' },
    }
  }
  return {
    common: {
      primaryColor: '#5b9fe0',
      primaryColorHover: '#74b1ea',
      primaryColorPressed: '#4a8bca',
      primaryColorSuppl: '#5b9fe0',
      successColor: '#5fb894',
      successColorHover: '#72c4a2',
      successColorPressed: '#4fa683',
      successColorSuppl: '#5fb894',
      warningColor: '#d8b25c',
      warningColorHover: '#e2bf72',
      warningColorPressed: '#c4a04c',
      warningColorSuppl: '#d8b25c',
      errorColor: '#dd8b8b',
      errorColorHover: '#e59c9c',
      errorColorPressed: '#c87a7a',
      errorColorSuppl: '#dd8b8b',
      infoColor: '#68b6c8',
      infoColorHover: '#7cc3d3',
      infoColorPressed: '#58a5b7',
      infoColorSuppl: '#68b6c8',
      borderRadius: '8px',
      borderRadiusSmall: '5px',
      fontFamily: FONT_SANS,
      fontFamilyMono: FONT_MONO,
      bodyColor: '#131519',
      cardColor: '#1a1d22',
      modalColor: '#1a1d22',
      popoverColor: '#22262c',
      tableColor: '#1a1d22',
      inputColor: 'rgba(255,255,255,0.05)',
      actionColor: 'rgba(255,255,255,0.05)',
      borderColor: 'rgba(255,255,255,0.09)',
      dividerColor: 'rgba(255,255,255,0.09)',
      textColorBase: '#e7e9ec',
      textColor1: '#e7e9ec',
      textColor2: '#a8adb6',
      textColor3: '#767c86',
      placeholderColor: '#5f656e',
      hoverColor: 'rgba(255,255,255,0.05)',
    },
    Card: { borderColor: 'rgba(255,255,255,0.09)' },
    Dialog: { color: '#22262c' },
    Pagination: { itemBorderRadius: '5px' },
    Layout: { color: '#131519', siderColor: '#1a1d22' },
  }
}
